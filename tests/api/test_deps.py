"""Tests for the ``get_current_user`` dependency (``app.api.deps``)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.core.config import Settings
from app.core.security import create_access_token
from app.models import User

from .conftest import AuthUser

PROBE = "/test-probe/me"


@pytest.fixture(autouse=True)
def probe_route(app: FastAPI) -> None:
    @app.get(PROBE)
    def me(user: CurrentUserDep) -> dict[str, object]:
        return {"id": user.id, "login": user.login}


def assert_unauthorized(response: object) -> None:
    assert response.status_code == 401  # type: ignore[attr-defined]
    assert response.headers["www-authenticate"] == "Bearer"  # type: ignore[attr-defined]
    assert "detail" in response.json()  # type: ignore[attr-defined]


def test_valid_token_returns_the_user(
    client: TestClient, make_user: Callable[..., AuthUser]
) -> None:
    alice = make_user("alice")

    response = client.get(PROBE, headers=alice.headers)

    assert response.status_code == 200
    assert response.json() == {"id": alice.id, "login": "alice"}


def test_missing_header_is_401(client: TestClient) -> None:
    assert_unauthorized(client.get(PROBE))


def test_non_bearer_scheme_is_401(client: TestClient) -> None:
    assert_unauthorized(client.get(PROBE, headers={"Authorization": "Basic YWxpY2U6cHc="}))


def test_malformed_token_is_401(client: TestClient) -> None:
    assert_unauthorized(client.get(PROBE, headers={"Authorization": "Bearer not-a-jwt"}))


def test_tampered_token_is_401(client: TestClient, make_user: Callable[..., AuthUser]) -> None:
    alice = make_user("alice")
    tampered = alice.token[:-2] + ("AA" if not alice.token.endswith("AA") else "BB")

    assert_unauthorized(client.get(PROBE, headers={"Authorization": f"Bearer {tampered}"}))


def test_expired_token_is_401(
    client: TestClient, make_user: Callable[..., AuthUser], settings: Settings
) -> None:
    alice = make_user("alice")
    token = create_access_token(alice.id, settings, now=datetime.now(UTC) - timedelta(hours=2))

    assert_unauthorized(client.get(PROBE, headers={"Authorization": f"Bearer {token}"}))


def test_token_of_deleted_user_is_401(
    client: TestClient, make_user: Callable[..., AuthUser], db_session: Session
) -> None:
    alice = make_user("alice")
    db_session.execute(delete(User).where(User.id == alice.id))
    db_session.commit()

    assert_unauthorized(client.get(PROBE, headers=alice.headers))


def test_openapi_declares_bearer_security_scheme(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    schemes = schema["components"]["securitySchemes"]
    assert schemes["HTTPBearer"]["type"] == "http"
    assert schemes["HTTPBearer"]["scheme"] == "bearer"
    assert schema["paths"][PROBE]["get"]["security"] == [{"HTTPBearer": []}]
