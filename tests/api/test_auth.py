"""Tests for registration (``POST /auth``) and login (``POST /login``)."""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.core.config import Settings
from app.core.security import decode_token, verify_password
from app.models import User

PASSWORD = "s3cret-password"


def register(client: TestClient, login: str = "alice", password: str = PASSWORD) -> dict:  # type: ignore[type-arg]
    response = client.post("/auth", json={"login": login, "password": password})
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------- POST /auth


def test_register_returns_201_with_user(client: TestClient, db_session: Session) -> None:
    response = client.post("/auth", json={"login": "Alice", "password": PASSWORD})

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "login", "created_at"}
    assert body["login"] == "Alice"
    datetime.fromisoformat(body["created_at"])
    user = db_session.scalars(select(User)).one()
    assert user.id == body["id"]
    assert user.password_hash != PASSWORD
    assert verify_password(PASSWORD, user.password_hash)


@pytest.mark.parametrize("second_login", ["alice", "ALICE", "Alice"])
def test_register_duplicate_login_is_409(client: TestClient, second_login: str) -> None:
    register(client, "Alice")

    response = client.post("/auth", json={"login": second_login, "password": PASSWORD})

    assert response.status_code == 409
    assert response.json() == {
        "detail": "This login is already taken.",
        "code": "LOGIN_ALREADY_EXISTS",
    }


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"login": "alice"},
        {"password": PASSWORD},
        {"login": "al", "password": PASSWORD},
        {"login": "a" * 51, "password": PASSWORD},
        {"login": "has space", "password": PASSWORD},
        {"login": "alice", "password": "short"},
        {"login": "alice", "password": "x" * 129},
        {"login": 123, "password": PASSWORD},
        {"login": "alice", "password": PASSWORD, "extra": 1},
    ],
)
def test_register_invalid_input_is_422(client: TestClient, body: dict) -> None:  # type: ignore[type-arg]
    response = client.post("/auth", json=body)

    assert response.status_code == 422


def test_register_accepts_boundary_lengths(client: TestClient) -> None:
    register(client, "abc", "x" * 8)
    register(client, "b" * 50, "y" * 128)


# ---------------------------------------------------------------- POST /login


def test_login_returns_a_working_token(
    app: FastAPI, client: TestClient, settings: Settings
) -> None:
    @app.get("/test-probe/me")
    def me(user: CurrentUserDep) -> dict[str, object]:
        return {"id": user.id}

    user = register(client, "alice")

    response = client.post("/login", json={"login": "alice", "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert decode_token(body["access_token"], settings).user_id == user["id"]
    protected = client.get(
        "/test-probe/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert protected.status_code == 200
    assert protected.json() == {"id": user["id"]}


def test_login_is_case_insensitive(client: TestClient) -> None:
    register(client, "Alice")

    response = client.post("/login", json={"login": "aLICE", "password": PASSWORD})

    assert response.status_code == 200


@pytest.mark.parametrize(("login", "password"), [("alice", "wrong-password"), ("nobody", PASSWORD)])
def test_login_failure_is_generic_401(client: TestClient, login: str, password: str) -> None:
    register(client, "alice")

    response = client.post("/login", json={"login": login, "password": password})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "detail": "Incorrect login or password.",
        "code": "INVALID_CREDENTIALS",
    }


def test_login_missing_fields_is_422(client: TestClient) -> None:
    assert client.post("/login", json={"login": "alice"}).status_code == 422
