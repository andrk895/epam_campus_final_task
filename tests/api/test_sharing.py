"""Tests for the sharing endpoints (T4.1 invite, T4.2 remove participant)."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from .conftest import AuthUser

MakeUser = Callable[..., AuthUser]


@pytest.fixture
def owner(make_user: MakeUser) -> AuthUser:
    return make_user("owner")


@pytest.fixture
def bob(make_user: MakeUser) -> AuthUser:
    return make_user("bob")


@pytest.fixture
def eve(make_user: MakeUser) -> AuthUser:
    return make_user("eve")


@pytest.fixture
def project_id(client: TestClient, owner: AuthUser) -> int:
    response = client.post("/projects", json={"name": "Shared"}, headers=owner.headers)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def invite(client: TestClient, project_id: int, by: AuthUser, login: str) -> tuple[int, dict]:  # type: ignore[type-arg]
    response = client.post(
        f"/projects/{project_id}/invite", params={"user": login}, headers=by.headers
    )
    return response.status_code, response.json()


def visible_project_ids(client: TestClient, user: AuthUser) -> list[int]:
    response = client.get("/projects", headers=user.headers)
    assert response.status_code == 200
    return [item["id"] for item in response.json()]


def test_invite_gives_access(
    client: TestClient, project_id: int, owner: AuthUser, bob: AuthUser
) -> None:
    assert visible_project_ids(client, bob) == []
    status, body = invite(client, project_id, owner, "BOB")
    assert status == 201
    assert body["project_id"] == project_id
    assert body["user_id"] == bob.id
    assert body["login"] == "bob"
    assert body["role"] == "participant"
    assert "added_at" in body
    assert visible_project_ids(client, bob) == [project_id]
    assert client.get(f"/projects/{project_id}/info", headers=bob.headers).status_code == 200


def test_invite_unknown_user(client: TestClient, project_id: int, owner: AuthUser) -> None:
    status, body = invite(client, project_id, owner, "ghost")
    assert status == 404
    assert body["code"] == "USER_NOT_FOUND"


def test_invite_existing_member(
    client: TestClient, project_id: int, owner: AuthUser, bob: AuthUser
) -> None:
    assert invite(client, project_id, owner, "bob")[0] == 201
    status, body = invite(client, project_id, owner, "bob")
    assert status == 409
    assert body["code"] == "ALREADY_MEMBER"


def test_invite_self(client: TestClient, project_id: int, owner: AuthUser) -> None:
    status, body = invite(client, project_id, owner, "owner")
    assert status == 400
    assert body["code"] == "CANNOT_INVITE_SELF"


def test_participant_cannot_invite(
    client: TestClient, project_id: int, owner: AuthUser, bob: AuthUser, eve: AuthUser
) -> None:
    invite(client, project_id, owner, "bob")
    status, body = invite(client, project_id, bob, "eve")
    assert status == 403
    assert body["code"] == "PERMISSION_DENIED"


def test_outsider_and_missing_project_get_404(
    client: TestClient, project_id: int, eve: AuthUser, bob: AuthUser
) -> None:
    assert invite(client, project_id, eve, "bob")[0] == 404
    assert invite(client, 999_999, eve, "bob")[0] == 404


def test_invite_requires_authentication_and_login_param(
    client: TestClient, project_id: int, owner: AuthUser
) -> None:
    assert client.post(f"/projects/{project_id}/invite", params={"user": "x"}).status_code == 401
    response = client.post(f"/projects/{project_id}/invite", headers=owner.headers)
    assert response.status_code == 422


def test_removed_participant_loses_access(
    client: TestClient, project_id: int, owner: AuthUser, bob: AuthUser
) -> None:
    invite(client, project_id, owner, "bob")
    response = client.delete(f"/projects/{project_id}/participants/Bob", headers=owner.headers)
    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/projects/{project_id}/info", headers=bob.headers).status_code == 404
    assert visible_project_ids(client, bob) == []


def test_owner_cannot_be_removed(client: TestClient, project_id: int, owner: AuthUser) -> None:
    response = client.delete(f"/projects/{project_id}/participants/owner", headers=owner.headers)
    assert response.status_code == 400
    assert response.json()["code"] == "CANNOT_REMOVE_OWNER"


def test_remove_non_member_or_unknown_user(
    client: TestClient, project_id: int, owner: AuthUser, bob: AuthUser
) -> None:
    for login in ("bob", "ghost"):
        response = client.delete(
            f"/projects/{project_id}/participants/{login}", headers=owner.headers
        )
        assert response.status_code == 404


def test_only_owner_can_remove(
    client: TestClient, project_id: int, owner: AuthUser, bob: AuthUser, eve: AuthUser
) -> None:
    invite(client, project_id, owner, "bob")
    url = f"/projects/{project_id}/participants/bob"
    assert client.delete(url, headers=bob.headers).status_code == 403
    assert client.delete(url, headers=eve.headers).status_code == 404
    assert client.delete(url).status_code == 401
