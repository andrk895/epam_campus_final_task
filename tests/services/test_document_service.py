"""Tests for the document service (tasks T5.3-T5.7) against PostgreSQL and a temp storage."""

import io
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import (
    DocumentNotFound,
    FileTooLarge,
    NoFilesUploaded,
    PermissionDenied,
    ProjectNotFound,
    UnsupportedFileType,
)
from app.models import Document, Project, User
from app.services.documents import DocumentService, IncomingFile
from app.storage import LocalStorage

Samples = dict[str, tuple[str, bytes]]


@pytest.fixture
def users(make_user: Callable[[str], User]) -> dict[str, User]:
    return {name: make_user(name) for name in ("owner", "part", "outsider")}


@pytest.fixture
def project(make_project: Callable[..., Project], users: dict[str, User]) -> Project:
    return make_project(users["owner"], users["part"])


@pytest.fixture
def service(session: Session, storage: LocalStorage, settings: Settings) -> DocumentService:
    return DocumentService(session, storage, settings)


@pytest.fixture
def incoming(samples: Samples) -> Callable[..., IncomingFile]:
    def factory(
        ext: str = "pdf", name: str | None = None, data: bytes | None = None
    ) -> IncomingFile:
        content_type, sample = samples[ext]
        return IncomingFile(
            stream=io.BytesIO(sample if data is None else data),
            filename=name or f"file.{ext}",
            content_type=content_type,
        )

    return factory


def stored_files(storage: LocalStorage) -> list[str]:
    if not storage.root.exists():
        return []
    return sorted(str(p.relative_to(storage.root)) for p in storage.root.rglob("*") if p.is_file())


def document_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Document)) or 0


def test_upload_single_and_multiple(
    service: DocumentService,
    storage: LocalStorage,
    project: Project,
    users: dict[str, User],
    incoming: Callable[..., IncomingFile],
    samples: Samples,
) -> None:
    [one] = service.upload(project.id, users["owner"], [incoming("pdf", "a.pdf")])
    assert (one.filename, one.content_type, one.size) == (
        "a.pdf",
        "application/pdf",
        len(samples["pdf"][1]),
    )
    assert one.uploaded_by == users["owner"].id
    assert one.storage_key.startswith(f"{project.id}/")
    assert storage.exists(one.storage_key)

    many = service.upload(project.id, users["part"], [incoming("png"), incoming("docx")])
    assert [d.content_type for d in many] == [samples["png"][0], samples["docx"][0]]
    assert len(stored_files(storage)) == 3


def test_upload_is_all_or_nothing_on_validation_error(
    service: DocumentService,
    storage: LocalStorage,
    session: Session,
    project: Project,
    users: dict[str, User],
    incoming: Callable[..., IncomingFile],
) -> None:
    bad = IncomingFile(io.BytesIO(b"text"), "a.txt", "text/plain")
    with pytest.raises(UnsupportedFileType):
        service.upload(project.id, users["owner"], [incoming("pdf"), bad])
    assert document_count(session) == 0
    assert stored_files(storage) == []


def test_upload_too_large(
    service: DocumentService,
    project: Project,
    users: dict[str, User],
    incoming: Callable[..., IncomingFile],
    samples: Samples,
) -> None:
    data = samples["pdf"][1] + b"0" * (1024 * 1024)
    with pytest.raises(FileTooLarge):
        service.upload(project.id, users["owner"], [incoming("pdf", data=data)])


def test_upload_cleans_up_files_when_storing_fails(
    session: Session,
    storage: LocalStorage,
    settings: Settings,
    project: Project,
    users: dict[str, User],
    incoming: Callable[..., IncomingFile],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_save = storage.save
    calls: list[str] = []

    def flaky_save(stream: Any, key: str) -> None:
        calls.append(key)
        if len(calls) == 2:
            raise OSError("disk full")
        original_save(stream, key)

    monkeypatch.setattr(storage, "save", flaky_save)
    service = DocumentService(session, storage, settings)
    with pytest.raises(OSError, match="disk full"):
        service.upload(project.id, users["owner"], [incoming(), incoming(), incoming()])
    assert stored_files(storage) == []
    assert document_count(session) == 0


def test_upload_cleans_up_files_when_commit_fails(
    session: Session,
    storage: LocalStorage,
    service: DocumentService,
    project: Project,
    users: dict[str, User],
    incoming: Callable[..., IncomingFile],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_commit() -> None:
        raise RuntimeError("commit failed")

    monkeypatch.setattr(session, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        service.upload(project.id, users["owner"], [incoming(), incoming("png")])
    assert stored_files(storage) == []


def test_upload_without_files(
    service: DocumentService, project: Project, users: dict[str, User]
) -> None:
    with pytest.raises(NoFilesUploaded):
        service.upload(project.id, users["owner"], [])


def test_outsider_cannot_upload_or_list(
    service: DocumentService,
    project: Project,
    users: dict[str, User],
    incoming: Callable[..., IncomingFile],
) -> None:
    with pytest.raises(ProjectNotFound):
        service.upload(project.id, users["outsider"], [incoming()])
    with pytest.raises(ProjectNotFound):
        service.list_documents(project.id, users["outsider"])


def test_list_documents(
    service: DocumentService,
    project: Project,
    users: dict[str, User],
    incoming: Callable[..., IncomingFile],
    make_project: Callable[..., Project],
) -> None:
    other = make_project(users["owner"], name="Other")
    service.upload(other.id, users["owner"], [incoming("gif")])
    docs = service.upload(project.id, users["owner"], [incoming("pdf", "1.pdf"), incoming("png")])
    listed = service.list_documents(project.id, users["part"])
    assert [d.id for d in listed] == [d.id for d in docs]


def test_open_returns_the_stored_bytes(
    service: DocumentService,
    project: Project,
    users: dict[str, User],
    incoming: Callable[..., IncomingFile],
    samples: Samples,
) -> None:
    [doc] = service.upload(project.id, users["owner"], [incoming("png")])
    document, stream = service.open(doc.id, users["part"])
    with stream:
        assert stream.read() == samples["png"][1]
    assert document.id == doc.id


@pytest.mark.parametrize("document_id", [999_999, 0, -1, 2**40])
def test_open_missing_document(
    service: DocumentService, users: dict[str, User], document_id: int
) -> None:
    with pytest.raises(DocumentNotFound):
        service.open(document_id, users["owner"])


def test_outsider_gets_document_not_found(
    service: DocumentService,
    project: Project,
    users: dict[str, User],
    incoming: Callable[..., IncomingFile],
) -> None:
    [doc] = service.upload(project.id, users["owner"], [incoming()])
    for operation in (
        lambda: service.open(doc.id, users["outsider"]),
        lambda: service.replace(doc.id, users["outsider"], incoming()),
        lambda: service.delete(doc.id, users["outsider"]),
    ):
        with pytest.raises(DocumentNotFound):
            operation()


def test_open_with_missing_file_is_not_found(
    service: DocumentService,
    storage: LocalStorage,
    project: Project,
    users: dict[str, User],
    incoming: Callable[..., IncomingFile],
) -> None:
    [doc] = service.upload(project.id, users["owner"], [incoming()])
    storage.delete(doc.storage_key)
    with pytest.raises(DocumentNotFound):
        service.open(doc.id, users["owner"])


def test_replace_swaps_file_and_metadata(
    service: DocumentService,
    storage: LocalStorage,
    project: Project,
    users: dict[str, User],
    incoming: Callable[..., IncomingFile],
    samples: Samples,
) -> None:
    [doc] = service.upload(project.id, users["owner"], [incoming("pdf", "old.pdf")])
    old_key = doc.storage_key
    replaced = service.replace(doc.id, users["part"], incoming("png", "new.png"))
    assert replaced.id == doc.id
    assert (replaced.filename, replaced.content_type) == ("new.png", "image/png")
    assert replaced.size == len(samples["png"][1])
    assert replaced.storage_key != old_key
    assert not storage.exists(old_key)
    assert stored_files(storage) == [replaced.storage_key]
    _, stream = service.open(doc.id, users["owner"])
    with stream:
        assert stream.read() == samples["png"][1]


def test_replace_with_invalid_file_keeps_the_old_one(
    service: DocumentService,
    storage: LocalStorage,
    project: Project,
    users: dict[str, User],
    incoming: Callable[..., IncomingFile],
) -> None:
    [doc] = service.upload(project.id, users["owner"], [incoming("pdf", "old.pdf")])
    with pytest.raises(UnsupportedFileType):
        service.replace(doc.id, users["owner"], IncomingFile(io.BytesIO(b"x"), "x", None))
    assert stored_files(storage) == [doc.storage_key]
    assert doc.filename == "old.pdf"


def test_replace_cleans_up_new_file_when_commit_fails(
    session: Session,
    service: DocumentService,
    storage: LocalStorage,
    project: Project,
    users: dict[str, User],
    incoming: Callable[..., IncomingFile],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    [doc] = service.upload(project.id, users["owner"], [incoming("pdf")])
    old_key = doc.storage_key

    def failing_commit() -> None:
        raise RuntimeError("commit failed")

    monkeypatch.setattr(session, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        service.replace(doc.id, users["owner"], incoming("png"))
    assert stored_files(storage) == [old_key]


def test_delete_is_owner_only(
    service: DocumentService,
    storage: LocalStorage,
    session: Session,
    project: Project,
    users: dict[str, User],
    incoming: Callable[..., IncomingFile],
) -> None:
    [doc] = service.upload(project.id, users["part"], [incoming()])
    with pytest.raises(PermissionDenied):
        service.delete(doc.id, users["part"])
    service.delete(doc.id, users["owner"])
    assert document_count(session) == 0
    assert stored_files(storage) == []
    with pytest.raises(DocumentNotFound):
        service.open(doc.id, users["owner"])


def test_delete_succeeds_even_if_the_file_cannot_be_removed(
    service: DocumentService,
    storage: LocalStorage,
    session: Session,
    project: Project,
    users: dict[str, User],
    incoming: Callable[..., IncomingFile],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    [doc] = service.upload(project.id, users["owner"], [incoming()])

    def broken_delete(key: str) -> None:
        raise OSError("read-only")

    monkeypatch.setattr(storage, "delete", broken_delete)
    service.delete(doc.id, users["owner"])
    assert document_count(session) == 0
    assert "orphaned" in caplog.text
