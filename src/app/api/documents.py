"""Document endpoints (T5.3-T5.7): upload, list, download, replace and delete."""

from collections.abc import Iterator
from typing import Annotated, Any, BinaryIO
from urllib.parse import quote

from fastapi import APIRouter, File, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUserDep, DbSessionDep
from app.core.config import SettingsDep
from app.schemas.errors import ErrorResponse
from app.schemas.projects import DocumentMeta
from app.services.documents import DocumentService, IncomingFile
from app.storage import StorageDep
from app.storage.base import CHUNK_SIZE

router = APIRouter(tags=["documents"])

Responses = dict[int | str, dict[str, Any]]


def _error(description: str) -> dict[str, Any]:
    return {"model": ErrorResponse, "description": description}


_PROJECT_404: Responses = {
    status.HTTP_404_NOT_FOUND: _error("The project doesn't exist or you are not a member of it")
}
_DOCUMENT_404: Responses = {
    status.HTTP_404_NOT_FOUND: _error("The document doesn't exist or you can't access it")
}
_UPLOAD_ERRORS: Responses = {
    status.HTTP_413_CONTENT_TOO_LARGE: _error("A file exceeds the maximum upload size"),
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: _error("A file's type is not allowed"),
}


def _incoming(file: UploadFile) -> IncomingFile:
    return IncomingFile(stream=file.file, filename=file.filename, content_type=file.content_type)


def _content_disposition(filename: str) -> str:
    """``attachment`` with an ASCII fallback name and the exact UTF-8 name (RFC 6266/5987)."""
    fallback = "".join(ch if 0x20 <= ord(ch) < 0x7F and ch not in '"\\' else "_" for ch in filename)
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _iter_file(stream: BinaryIO) -> Iterator[bytes]:
    with stream:
        while chunk := stream.read(CHUNK_SIZE):
            yield chunk


@router.post(
    "/projects/{project_id}/documents",
    status_code=status.HTTP_201_CREATED,
    summary="Upload documents to a project",
    responses={**_PROJECT_404, **_UPLOAD_ERRORS},
)
def upload_documents(
    project_id: int,
    files: Annotated[list[UploadFile], File(description="One or more files.")],
    user: CurrentUserDep,
    session: DbSessionDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> list[DocumentMeta]:
    """Upload one or more files (owner and participants). All files are stored, or none."""
    service = DocumentService(session, storage, settings)
    documents = service.upload(project_id, user, [_incoming(file) for file in files])
    return [DocumentMeta.model_validate(document) for document in documents]


@router.get(
    "/projects/{project_id}/documents",
    summary="List a project's documents",
    responses=_PROJECT_404,
)
def list_documents(
    project_id: int,
    user: CurrentUserDep,
    session: DbSessionDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> list[DocumentMeta]:
    """Metadata of all documents of the project, oldest first."""
    documents = DocumentService(session, storage, settings).list_documents(project_id, user)
    return [DocumentMeta.model_validate(document) for document in documents]


@router.get(
    "/documents/{document_id}",
    summary="Download a document",
    response_class=StreamingResponse,
    responses={
        status.HTTP_200_OK: {"content": {"application/octet-stream": {}}},
        **_DOCUMENT_404,
    },
)
def download_document(
    document_id: int,
    user: CurrentUserDep,
    session: DbSessionDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> StreamingResponse:
    """Stream the document's file as an attachment."""
    document, stream = DocumentService(session, storage, settings).open(document_id, user)
    return StreamingResponse(
        _iter_file(stream),
        media_type=document.content_type,
        headers={
            "Content-Disposition": _content_disposition(document.filename),
            "Content-Length": str(document.size),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put(
    "/documents/{document_id}",
    summary="Replace a document",
    responses={**_DOCUMENT_404, **_UPLOAD_ERRORS},
)
def replace_document(
    document_id: int,
    file: Annotated[UploadFile, File(description="The new file.")],
    user: CurrentUserDep,
    session: DbSessionDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> DocumentMeta:
    """Replace the document's file and metadata (owner and participants)."""
    service = DocumentService(session, storage, settings)
    return DocumentMeta.model_validate(service.replace(document_id, user, _incoming(file)))


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document",
    responses={
        **_DOCUMENT_404,
        status.HTTP_403_FORBIDDEN: _error("Only the project owner can delete documents"),
    },
)
def delete_document(
    document_id: int,
    user: CurrentUserDep,
    session: DbSessionDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> Response:
    """Delete the document and its file (owner only)."""
    DocumentService(session, storage, settings).delete(document_id, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
