"""Fixtures for the API tests.

The tests run against real PostgreSQL: ``TEST_DATABASE_URL`` (by default the local ``pm_test``).
The tables are created with ``Base.metadata.create_all`` in a fresh, uniquely named schema
(selected for every connection through the URL's ``options=-csearch_path=...``), which is
dropped at the end of the session. Every table is truncated after each test.
"""

import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Final

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import create_access_token, hash_password
from app.db import Base
from app.main import create_app
from app.models import User

TEST_DATABASE_URL: Final = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/pm_test"
)
TEST_JWT_SECRET: Final = "api-test-secret-that-is-long-enough-for-hs256"
DEFAULT_PASSWORD: Final = "correct horse battery"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """URL of the test database whose connections use a private, freshly created schema."""
    schema = f"test_api_{uuid.uuid4().hex[:12]}"
    admin_engine = create_engine(TEST_DATABASE_URL)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(TEST_DATABASE_URL).update_query_dict({"options": f"-csearch_path={schema}"})
    url_string = url.render_as_string(hide_password=False)
    schema_engine = create_engine(url_string)
    Base.metadata.create_all(schema_engine)
    schema_engine.dispose()
    try:
        yield url_string
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.fixture
def settings(database_url: str) -> Settings:
    values: dict[str, object] = {
        "database_url": database_url,
        "jwt_secret": TEST_JWT_SECRET,
        "_env_file": None,
    }
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    application = create_app(settings=settings)
    yield application
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with application.state.engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    application.state.engine.dispose()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session(app: FastAPI) -> Iterator[Session]:
    """A session on the app's database, for arranging data and checking results."""
    with app.state.session_factory() as session:
        yield session


@dataclass(frozen=True)
class AuthUser:
    """A user created for a test, with a valid access token."""

    id: int
    login: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
def make_user(db_session: Session, settings: Settings) -> Callable[..., AuthUser]:
    """Create a user directly in the database and return it with an access token."""

    def factory(login: str, password: str = DEFAULT_PASSWORD) -> AuthUser:
        user = User(login=login, password_hash=hash_password(password))
        db_session.add(user)
        db_session.commit()
        return AuthUser(id=user.id, login=login, token=create_access_token(user.id, settings))

    return factory
