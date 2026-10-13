"""Document use cases (tasks T5.3-T5.7): upload, list, download, replace and delete.

The service keeps the database and the storage backend consistent:

* **upload** validates every file first, then stores the files, then inserts the rows in one
  transaction. If anything fails, the transaction is rolled back and every file already stored
  by this call is deleted again (all-or-nothing);
* **replace** stores the new file under a fresh key and updates the row; the old file is deleted
  only after the commit succeeded (if the commit fails, the new file is deleted instead);
* **delete** removes the row first and the file after the commit.

A file that can't be deleted after a successful commit is logged and left behind (an orphan
costs disk space but never breaks consistency); the request still succeeds.

Access is checked with :class:`~app.services.access.ProjectAccess`. A document whose project the
user can't access is reported as :class:`~app.core.errors.DocumentNotFound`, exactly like a
document that doesn't exist (design decision D7).
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import BinaryIO, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import DocumentNotFound, NoFilesUploaded, ProjectNotFound
from app.models import Document, User
from app.services.access import Permission, ProjectAccess
from app.services.uploads import ValidatedUpload, validate_upload_with_settings
from app.storage import StorageBackend, new_storage_key

logger = logging.getLogger(__name__)

_ID_MAX: Final = 2**31 - 1


@dataclass(frozen=True, slots=True)
class IncomingFile:
    """An uploaded file as received by the API: a seekable stream and client-supplied metadata."""

    stream: BinaryIO
    filename: str | None
    content_type: str | None


class DocumentService:
    """Document operations on behalf of a user."""

    def __init__(self, session: Session, storage: StorageBackend, settings: Settings) -> None:
        self._session = session
        self._storage = storage
        self._settings = settings
        self._access = ProjectAccess(session)

    # ------------------------------------------------------------ helpers

    def _validate(self, file: IncomingFile) -> ValidatedUpload:
        return validate_upload_with_settings(
            file.stream,
            filename=file.filename,
            content_type=file.content_type,
            settings=self._settings,
        )

    def _get_document(self, document_id: int, user: User, permission: Permission) -> Document:
        """Load a document the user has ``permission`` on.

        Raises ``DocumentNotFound`` (no such document, or no access to its project) or
        ``PermissionDenied`` (a member whose role lacks ``permission``).
        """
        if not 1 <= document_id <= _ID_MAX:
            raise DocumentNotFound()
        document = self._session.get(Document, document_id)
        if document is None:
            raise DocumentNotFound()
        try:
            self._access.require(document.project_id, user, permission)
        except ProjectNotFound:
            raise DocumentNotFound() from None
        return document

    def _delete_file_quietly(self, key: str) -> None:
        try:
            self._storage.delete(key)
        except Exception:
            logger.exception("Could not delete stored file %s; it is left orphaned", key)

    # ------------------------------------------------------------ use cases

    def upload(self, project_id: int, user: User, files: Sequence[IncomingFile]) -> list[Document]:
        """Store ``files`` as new documents of the project (all-or-nothing)."""
        self._access.require(project_id, user, Permission.UPLOAD_DOC)
        if not files:
            raise NoFilesUploaded()
        validated = [(file, self._validate(file)) for file in files]

        saved_keys: list[str] = []
        try:
            documents = []
            for file, meta in validated:
                key = new_storage_key(project_id)
                self._storage.save(file.stream, key)
                saved_keys.append(key)
                documents.append(
                    Document(
                        project_id=project_id,
                        filename=meta.filename,
                        content_type=meta.content_type,
                        size=meta.size,
                        storage_key=key,
                        uploaded_by=user.id,
                    )
                )
            self._session.add_all(documents)
            self._session.commit()
        except BaseException:
            self._session.rollback()
            for key in saved_keys:
                self._delete_file_quietly(key)
            raise
        return documents

    def list_documents(self, project_id: int, user: User) -> list[Document]:
        """The project's documents, oldest first."""
        self._access.require(project_id, user, Permission.VIEW)
        statement = select(Document).where(Document.project_id == project_id).order_by(Document.id)
        return list(self._session.scalars(statement))

    def open(self, document_id: int, user: User) -> tuple[Document, BinaryIO]:
        """The document and an open stream of its file (the caller closes it)."""
        document = self._get_document(document_id, user, Permission.VIEW)
        try:
            stream = self._storage.open(document.storage_key)
        except FileNotFoundError:
            logger.error(
                "Stored file %s of document %s is missing", document.storage_key, document.id
            )
            raise DocumentNotFound() from None
        return document, stream

    def replace(self, document_id: int, user: User, file: IncomingFile) -> Document:
        """Replace the document's file and metadata; the old file is deleted after commit."""
        document = self._get_document(document_id, user, Permission.REPLACE_DOC)
        meta = self._validate(file)
        old_key = document.storage_key
        new_key = new_storage_key(document.project_id)
        try:
            self._storage.save(file.stream, new_key)
            document.filename = meta.filename
            document.content_type = meta.content_type
            document.size = meta.size
            document.storage_key = new_key
            self._session.commit()
        except BaseException:
            self._session.rollback()
            self._delete_file_quietly(new_key)
            raise
        self._delete_file_quietly(old_key)
        return document

    def delete(self, document_id: int, user: User) -> None:
        """Delete the document's row, then its file."""
        document = self._get_document(document_id, user, Permission.DELETE_DOC)
        key = document.storage_key
        self._session.delete(document)
        self._session.commit()
        self._delete_file_quietly(key)
