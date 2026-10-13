"""Tests for the document endpoints (T5.2-T5.7)."""

import io
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.api.documents import _content_disposition
from app.core.config import Settings

from .conftest import AuthUser

MakeUser = Callable[..., AuthUser]


def _docx() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
    return buffer.getvalue()


PNG: Final = b"\x89PNG\r\n\x1a\n" + b"\x01" * 100
PDF: Final = b"%PDF-1.7\n" + b"%" * 100
DOCX: Final = _docx()
DOCX_TYPE: Final = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def owner(make_user: MakeUser) -> AuthUser:
    return make_user("owner")


@pytest.fixture
def member(make_user: MakeUser) -> AuthUser:
    return make_user("member")


@pytest.fixture
def outsider(make_user: MakeUser) -> AuthUser:
    return make_user("outsider")


@pytest.fixture
def project_id(client: TestClient, owner: AuthUser, member: AuthUser) -> int:
    response = client.post("/projects", json={"name": "Docs"}, headers=owner.headers)
    assert response.status_code == 201, response.text
    project_id = int(response.json()["id"])
    invited = client.post(
        f"/projects/{project_id}/invite", params={"user": member.login}, headers=owner.headers
    )
    assert invited.status_code == 201
    return project_id


@pytest.fixture
def storage_dir(settings: Settings) -> Path:
    return settings.storage_dir


def stored_files(storage_dir: Path) -> list[Path]:
    return [p for p in storage_dir.rglob("*") if p.is_file()] if storage_dir.exists() else []


def upload(
    client: TestClient, project_id: int, user: AuthUser, *files: tuple[str, bytes, str]
) -> Response:
    response: Response = client.post(
        f"/projects/{project_id}/documents",
        files=[("files", file) for file in files],
        headers=user.headers,
    )
    return response


def upload_one(client: TestClient, project_id: int, user: AuthUser) -> dict[str, Any]:
    response = upload(client, project_id, user, ("report.pdf", PDF, "application/pdf"))
    assert response.status_code == 201, response.text
    return response.json()[0]  # type: ignore[no-any-return]


# ---------------------------------------------------------------- upload (T5.2, T5.3)


def test_upload_single(
    client: TestClient, project_id: int, owner: AuthUser, storage_dir: Path
) -> None:
    response = upload(client, project_id, owner, ("report.pdf", PDF, "application/pdf"))
    assert response.status_code == 201
    [doc] = response.json()
    assert doc["filename"] == "report.pdf"
    assert doc["content_type"] == "application/pdf"
    assert doc["size"] == len(PDF)
    assert doc["uploaded_by"] == owner.id
    assert set(doc) == {
        "id",
        "filename",
        "content_type",
        "size",
        "uploaded_by",
        "created_at",
        "updated_at",
    }
    [path] = stored_files(storage_dir)
    assert path.read_bytes() == PDF
    assert path.parent.name == str(project_id)
    assert path.name != "report.pdf"


def test_upload_multiple_by_participant(
    client: TestClient, project_id: int, member: AuthUser, storage_dir: Path
) -> None:
    response = upload(
        client,
        project_id,
        member,
        ("a.png", PNG, "image/png"),
        ("b.docx", DOCX, DOCX_TYPE),
        ("c.pdf", PDF, "application/octet-stream"),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert [d["filename"] for d in body] == ["a.png", "b.docx", "c.pdf"]
    assert [d["content_type"] for d in body] == ["image/png", DOCX_TYPE, "application/pdf"]
    assert len(stored_files(storage_dir)) == 3


def test_upload_sanitises_filename(client: TestClient, project_id: int, owner: AuthUser) -> None:
    response = upload(client, project_id, owner, ("../../etc/x<y>.pdf", PDF, "application/pdf"))
    assert response.status_code == 201
    assert response.json()[0]["filename"] == "x_y_.pdf"


def test_invalid_type_gets_415_and_nothing_is_stored(
    client: TestClient, project_id: int, owner: AuthUser, storage_dir: Path
) -> None:
    response = upload(
        client,
        project_id,
        owner,
        ("ok.pdf", PDF, "application/pdf"),
        ("evil.exe", b"MZ\x90\x00", "application/x-msdownload"),
    )
    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_FILE_TYPE"
    assert stored_files(storage_dir) == []
    listed = client.get(f"/projects/{project_id}/documents", headers=owner.headers)
    assert listed.json() == []


def test_spoofed_type_gets_415(client: TestClient, project_id: int, owner: AuthUser) -> None:
    response = upload(client, project_id, owner, ("fake.png", b"<html>", "image/png"))
    assert response.status_code == 415


def test_too_large_gets_413(
    client: TestClient, project_id: int, owner: AuthUser, storage_dir: Path
) -> None:
    big = PDF + b"0" * (1024 * 1024)  # the test settings allow 1 MB
    response = upload(client, project_id, owner, ("big.pdf", big, "application/pdf"))
    assert response.status_code == 413
    assert response.json()["code"] == "FILE_TOO_LARGE"
    assert stored_files(storage_dir) == []


def test_upload_without_files_is_rejected(
    client: TestClient, project_id: int, owner: AuthUser
) -> None:
    response = client.post(f"/projects/{project_id}/documents", headers=owner.headers)
    assert response.status_code == 422


def test_non_member_upload_gets_404(
    client: TestClient, project_id: int, outsider: AuthUser, storage_dir: Path
) -> None:
    response = upload(client, project_id, outsider, ("a.pdf", PDF, "application/pdf"))
    assert response.status_code == 404
    assert stored_files(storage_dir) == []
    assert upload(client, 999_999, outsider, ("a.pdf", PDF, "application/pdf")).status_code == 404


def test_upload_requires_authentication(client: TestClient, project_id: int) -> None:
    response = client.post(
        f"/projects/{project_id}/documents", files=[("files", ("a.pdf", PDF, "application/pdf"))]
    )
    assert response.status_code == 401


# ---------------------------------------------------------------- list (T5.4)


def test_list_documents(
    client: TestClient, project_id: int, owner: AuthUser, member: AuthUser, outsider: AuthUser
) -> None:
    first = upload_one(client, project_id, owner)
    second = upload_one(client, project_id, member)
    response = client.get(f"/projects/{project_id}/documents", headers=member.headers)
    assert response.status_code == 200
    assert response.json() == [first, second]
    assert (
        client.get(f"/projects/{project_id}/documents", headers=outsider.headers).status_code == 404
    )


def test_uploaded_documents_appear_in_project_list(
    client: TestClient, project_id: int, owner: AuthUser
) -> None:
    doc = upload_one(client, project_id, owner)
    [project] = client.get("/projects", headers=owner.headers).json()
    assert project["documents"] == [doc]


# ---------------------------------------------------------------- download (T5.5)


def test_download_returns_the_uploaded_bytes(
    client: TestClient, project_id: int, owner: AuthUser, member: AuthUser
) -> None:
    doc = upload_one(client, project_id, owner)
    response = client.get(f"/documents/{doc['id']}", headers=member.headers)
    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        "attachment; filename=\"report.pdf\"; filename*=UTF-8''report.pdf"
    )
    assert response.headers["content-length"] == str(len(PDF))


def test_download_non_ascii_filename(client: TestClient, project_id: int, owner: AuthUser) -> None:
    response = upload(client, project_id, owner, ("árvíz 1.pdf", PDF, "application/pdf"))
    doc_id = response.json()[0]["id"]
    download = client.get(f"/documents/{doc_id}", headers=owner.headers)
    assert download.headers["content-disposition"] == (
        "attachment; filename=\"_rv_z 1.pdf\"; filename*=UTF-8''%C3%A1rv%C3%ADz%201.pdf"
    )


def test_download_by_outsider_or_missing_gets_404(
    client: TestClient, project_id: int, owner: AuthUser, outsider: AuthUser
) -> None:
    doc = upload_one(client, project_id, owner)
    response = client.get(f"/documents/{doc['id']}", headers=outsider.headers)
    assert response.status_code == 404
    assert response.json()["code"] == "DOCUMENT_NOT_FOUND"
    assert client.get("/documents/999999", headers=owner.headers).status_code == 404
    assert client.get(f"/documents/{2**40}", headers=owner.headers).status_code == 404
    assert client.get(f"/documents/{doc['id']}").status_code == 401


def test_content_disposition_escapes_quotes_and_backslashes() -> None:
    assert _content_disposition('a "b"\\c.pdf') == (
        "attachment; filename=\"a _b__c.pdf\"; filename*=UTF-8''a%20%22b%22%5Cc.pdf"
    )


# ---------------------------------------------------------------- replace (T5.6)


def test_replace_document(
    client: TestClient, project_id: int, owner: AuthUser, member: AuthUser, storage_dir: Path
) -> None:
    doc = upload_one(client, project_id, owner)
    [old_path] = stored_files(storage_dir)
    response = client.put(
        f"/documents/{doc['id']}",
        files={"file": ("new.png", PNG, "image/png")},
        headers=member.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == doc["id"]
    assert (body["filename"], body["content_type"], body["size"]) == (
        "new.png",
        "image/png",
        len(PNG),
    )
    assert body["updated_at"] >= doc["updated_at"]
    assert not old_path.exists()
    assert len(stored_files(storage_dir)) == 1
    download = client.get(f"/documents/{doc['id']}", headers=owner.headers)
    assert download.content == PNG
    assert download.headers["content-type"] == "image/png"


def test_replace_validation_and_access(
    client: TestClient, project_id: int, owner: AuthUser, outsider: AuthUser
) -> None:
    doc = upload_one(client, project_id, owner)
    url = f"/documents/{doc['id']}"
    bad = client.put(url, files={"file": ("a.txt", b"text", "text/plain")}, headers=owner.headers)
    assert bad.status_code == 415
    big = client.put(
        url,
        files={"file": ("a.pdf", PDF + b"0" * 1024 * 1024, "application/pdf")},
        headers=owner.headers,
    )
    assert big.status_code == 413
    other = client.put(
        url, files={"file": ("a.pdf", PDF, "application/pdf")}, headers=outsider.headers
    )
    assert other.status_code == 404
    assert client.get(url, headers=owner.headers).content == PDF


# ---------------------------------------------------------------- delete (T5.7)


def test_delete_permission_matrix(
    client: TestClient,
    project_id: int,
    owner: AuthUser,
    member: AuthUser,
    outsider: AuthUser,
    storage_dir: Path,
) -> None:
    doc = upload_one(client, project_id, member)
    url = f"/documents/{doc['id']}"
    assert client.delete(url).status_code == 401
    assert client.delete(url, headers=outsider.headers).status_code == 404
    forbidden = client.delete(url, headers=member.headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "PERMISSION_DENIED"
    assert len(stored_files(storage_dir)) == 1

    deleted = client.delete(url, headers=owner.headers)
    assert deleted.status_code == 204
    assert stored_files(storage_dir) == []
    assert client.get(url, headers=owner.headers).status_code == 404
    assert client.delete(url, headers=owner.headers).status_code == 404
    assert client.get(f"/projects/{project_id}/documents", headers=owner.headers).json() == []
