"""Tests for the project endpoints (``/projects``)."""

import uuid
from collections.abc import Callable, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.models import Document, Project, ProjectMember, ProjectRole
from app.services import projects as projects_service

from .conftest import AuthUser

MakeUser = Callable[..., AuthUser]


def create_project(
    client: TestClient, owner: AuthUser, name: str = "Apollo", description: str | None = "Moon"
) -> dict[str, Any]:
    response = client.post(
        "/projects", json={"name": name, "description": description}, headers=owner.headers
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def add_member(session: Session, project_id: int, user: AuthUser) -> None:
    session.add(ProjectMember(project_id=project_id, user_id=user.id, role=ProjectRole.PARTICIPANT))
    session.commit()


def add_document(session: Session, project_id: int, uploader: AuthUser, filename: str) -> Document:
    document = Document(
        project_id=project_id,
        filename=filename,
        content_type="application/pdf",
        size=123,
        storage_key=uuid.uuid4().hex,
        uploaded_by=uploader.id,
    )
    session.add(document)
    session.commit()
    return document


@pytest.fixture
def alice(make_user: MakeUser) -> AuthUser:
    return make_user("alice")


@pytest.fixture
def bob(make_user: MakeUser) -> AuthUser:
    return make_user("bob")


@pytest.fixture
def carol(make_user: MakeUser) -> AuthUser:
    return make_user("carol")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/projects"),
        ("GET", "/projects"),
        ("GET", "/projects/1/info"),
        ("PUT", "/projects/1/info"),
        ("DELETE", "/projects/1"),
    ],
)
def test_endpoints_require_authentication(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path, json={"name": "x"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


# ---------------------------------------------------------------- POST /projects


def test_create_project(client: TestClient, alice: AuthUser, db_session: Session) -> None:
    response = client.post(
        "/projects", json={"name": "  Apollo  ", "description": "Moon"}, headers=alice.headers
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Apollo"
    assert body["description"] == "Moon"
    assert body["owner_id"] == alice.id
    assert body["owner_login"] == "alice"
    assert body["role"] == "owner"
    assert [(p["login"], p["role"]) for p in body["participants"]] == [("alice", "owner")]
    membership = db_session.get(ProjectMember, (body["id"], alice.id))
    assert membership is not None
    assert membership.role is ProjectRole.OWNER


def test_create_project_description_is_optional(client: TestClient, alice: AuthUser) -> None:
    response = client.post("/projects", json={"name": "Apollo"}, headers=alice.headers)

    assert response.status_code == 201
    assert response.json()["description"] is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 201},
        {"name": "ok", "description": "x" * 5001},
        {"name": "ok", "owner_id": 5},
    ],
)
def test_create_project_invalid_input_is_422(
    client: TestClient, alice: AuthUser, body: dict[str, Any]
) -> None:
    assert client.post("/projects", json=body, headers=alice.headers).status_code == 422


def test_create_project_accepts_boundary_lengths(client: TestClient, alice: AuthUser) -> None:
    create_project(client, alice, name="x" * 200, description="y" * 5000)


# ---------------------------------------------------------------- GET /projects


def test_list_shows_own_and_shared_projects_only(
    client: TestClient, alice: AuthUser, bob: AuthUser, carol: AuthUser, db_session: Session
) -> None:
    own = create_project(client, alice, "Own")
    shared = create_project(client, bob, "Shared")
    create_project(client, carol, "Private")
    add_member(db_session, shared["id"], alice)
    add_document(db_session, shared["id"], bob, "plan.pdf")

    response = client.get("/projects", headers=alice.headers)

    assert response.status_code == 200
    items = response.json()
    assert [item["name"] for item in items] == ["Own", "Shared"]
    by_name = {item["name"]: item for item in items}
    assert by_name["Own"]["role"] == "owner"
    assert by_name["Own"]["owner_login"] == "alice"
    assert by_name["Own"]["documents"] == []
    assert by_name["Shared"]["id"] == shared["id"]
    assert by_name["Shared"]["role"] == "participant"
    assert by_name["Shared"]["owner_login"] == "bob"
    [document] = by_name["Shared"]["documents"]
    assert document["filename"] == "plan.pdf"
    assert document["size"] == 123
    assert document["uploaded_by"] == bob.id
    assert "storage_key" not in document
    assert own["id"] != shared["id"]


def test_list_is_empty_for_a_new_user(client: TestClient, alice: AuthUser) -> None:
    response = client.get("/projects", headers=alice.headers)

    assert response.status_code == 200
    assert response.json() == []


def test_list_uses_a_constant_number_of_queries(
    client: TestClient, alice: AuthUser, bob: AuthUser, db_session: Session
) -> None:
    for index in range(5):
        project = create_project(client, bob, f"P{index}")
        add_member(db_session, project["id"], alice)
        add_document(db_session, project["id"], bob, f"doc{index}.pdf")
    engine = db_session.get_bind()
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(args[2])

    event.listen(engine, "before_cursor_execute", count)
    try:
        response = client.get("/projects", headers=alice.headers)
    finally:
        event.remove(engine, "before_cursor_execute", count)

    assert response.status_code == 200
    assert len(response.json()) == 5
    # Current user + projects (with owners) + documents; no per-project queries.
    assert len(statements) <= 4, statements


# ---------------------------------------------------------------- GET /projects/{id}/info


def test_info_returns_details_and_participants(
    client: TestClient, alice: AuthUser, bob: AuthUser, db_session: Session
) -> None:
    project = create_project(client, alice)
    add_member(db_session, project["id"], bob)

    for user, role in ((alice, "owner"), (bob, "participant")):
        response = client.get(f"/projects/{project['id']}/info", headers=user.headers)

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Apollo"
        assert body["role"] == role
        assert body["owner_login"] == "alice"
        assert [(p["login"], p["role"]) for p in body["participants"]] == [
            ("alice", "owner"),
            ("bob", "participant"),
        ]


@pytest.mark.parametrize("project_id", ["missing", "999999", str(2**40)])
def test_info_is_404_for_non_member_or_missing_project(
    client: TestClient, alice: AuthUser, bob: AuthUser, project_id: str
) -> None:
    project = create_project(client, alice)
    target = project["id"] if project_id == "missing" else project_id

    response = client.get(f"/projects/{target}/info", headers=bob.headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found.", "code": "PROJECT_NOT_FOUND"}


def test_info_with_non_integer_id_is_422(client: TestClient, alice: AuthUser) -> None:
    assert client.get("/projects/abc/info", headers=alice.headers).status_code == 422


# ---------------------------------------------------------------- PUT /projects/{id}/info


def test_owner_can_update(client: TestClient, alice: AuthUser) -> None:
    project = create_project(client, alice)

    response = client.put(
        f"/projects/{project['id']}/info",
        json={"name": "Artemis", "description": "Back to the Moon"},
        headers=alice.headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Artemis"
    assert body["description"] == "Back to the Moon"
    assert body["updated_at"] > project["updated_at"]
    info = client.get(f"/projects/{project['id']}/info", headers=alice.headers).json()
    assert info["name"] == "Artemis"


def test_participant_can_update(
    client: TestClient, alice: AuthUser, bob: AuthUser, db_session: Session
) -> None:
    project = create_project(client, alice)
    add_member(db_session, project["id"], bob)

    response = client.put(
        f"/projects/{project['id']}/info", json={"name": "By Bob"}, headers=bob.headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "By Bob"
    assert response.json()["description"] is None
    assert response.json()["role"] == "participant"


def test_non_member_update_is_404(client: TestClient, alice: AuthUser, bob: AuthUser) -> None:
    project = create_project(client, alice)

    response = client.put(
        f"/projects/{project['id']}/info", json={"name": "Hijack"}, headers=bob.headers
    )

    assert response.status_code == 404
    info = client.get(f"/projects/{project['id']}/info", headers=alice.headers).json()
    assert info["name"] == "Apollo"


def test_update_invalid_input_is_422(client: TestClient, alice: AuthUser) -> None:
    project = create_project(client, alice)

    response = client.put(
        f"/projects/{project['id']}/info", json={"name": ""}, headers=alice.headers
    )

    assert response.status_code == 422


# ---------------------------------------------------------------- DELETE /projects/{id}


def test_owner_deletes_project_with_members_documents_and_files(
    client: TestClient,
    alice: AuthUser,
    bob: AuthUser,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, alice)
    add_member(db_session, project["id"], bob)
    keys = {add_document(db_session, project["id"], alice, f"{n}.pdf").storage_key for n in "ab"}
    removed: list[str] = []

    def fake_remove(storage_keys: Sequence[str]) -> None:
        # Called after the commit: the rows are already gone.
        with Session(db_session.get_bind()) as check:
            assert check.get(Project, project["id"]) is None
        removed.extend(storage_keys)

    monkeypatch.setattr(
        projects_service.delete_project, "__kwdefaults__", {"remove_files": fake_remove}
    )

    response = client.delete(f"/projects/{project['id']}", headers=alice.headers)

    assert response.status_code == 204
    assert response.content == b""
    assert set(removed) == keys
    db_session.expire_all()
    assert db_session.get(Project, project["id"]) is None
    assert db_session.scalar(select(func.count()).select_from(ProjectMember)) == 0
    assert db_session.scalar(select(func.count()).select_from(Document)) == 0
    for user in (alice, bob):
        assert client.get("/projects", headers=user.headers).json() == []
        info = client.get(f"/projects/{project['id']}/info", headers=user.headers)
        assert info.status_code == 404


def test_file_removal_failure_does_not_fail_the_request(
    client: TestClient, alice: AuthUser, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, alice)
    add_document(db_session, project["id"], alice, "a.pdf")

    def broken_remove(storage_keys: Sequence[str]) -> None:
        raise OSError("disk on fire")

    monkeypatch.setattr(
        projects_service.delete_project, "__kwdefaults__", {"remove_files": broken_remove}
    )

    response = client.delete(f"/projects/{project['id']}", headers=alice.headers)

    assert response.status_code == 204
    db_session.expire_all()
    assert db_session.get(Project, project["id"]) is None


def test_participant_delete_is_403(
    client: TestClient, alice: AuthUser, bob: AuthUser, db_session: Session
) -> None:
    project = create_project(client, alice)
    add_member(db_session, project["id"], bob)

    response = client.delete(f"/projects/{project['id']}", headers=bob.headers)

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"
    assert client.get(f"/projects/{project['id']}/info", headers=alice.headers).status_code == 200


def test_non_member_delete_is_404(client: TestClient, alice: AuthUser, bob: AuthUser) -> None:
    project = create_project(client, alice)

    assert client.delete(f"/projects/{project['id']}", headers=bob.headers).status_code == 404
    assert client.delete("/projects/999999", headers=alice.headers).status_code == 404
    assert client.get(f"/projects/{project['id']}/info", headers=alice.headers).status_code == 200
