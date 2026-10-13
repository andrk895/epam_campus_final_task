"""Shared pytest fixtures.

Environment
    Every test runs without the setting variables of the developer's environment
    (``DATABASE_URL``, ``JWT_SECRET``...) and with the cached settings and default app reset.
    Tests that must not see a ``.env`` file either also use :func:`isolated_env`, which switches
    to an empty working directory.

Settings
    :func:`test_settings` (or :func:`make_settings` for variants) never read the environment
    or ``.env``: they point at the test database and at a per-test storage directory.

Database
    The test database is ``TEST_DATABASE_URL`` (default: local ``pm_test``, see
    :mod:`tests.database`). Once per test session, the model tables are created with
    ``Base.metadata.create_all`` in a fresh, uniquely named schema (:func:`db_engine`), which is
    dropped at the end of the session. Migrations are tested separately.

    Each test runs inside one outer transaction on one connection (:func:`db_connection`) that
    is rolled back after the test. Sessions (the test's :func:`db_session` and every request's
    session) are bound to that connection with ``join_transaction_mode="create_savepoint"``: their
    ``commit()`` only releases a SAVEPOINT and their ``rollback()`` only rolls back to it, so
    application code can commit or roll back as usual and still nothing outlives the test.

    Caveats: rows are visible across sessions only after ``flush()`` (the factories flush);
    PostgreSQL's ``now()`` is the start time of the outer transaction, so all server-side
    timestamps in a test are equal; identity sequences are not rolled back, so never assume
    specific ids.

App and client
    :func:`app` is built with ``create_app(settings=test_settings)``; its ``get_db`` hands every
    request its own session on the test connection. :func:`client` is a started
    ``TestClient`` (lifespan included).
"""

import os
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Final

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db import create_session_factory
from app.main import _get_default_app, create_app
from app.models import Project, User
from tests.database import (
    get_test_database_url,
    temporary_schema,
    unique_schema_name,
    url_with_search_path,
)
from tests.factories import (
    DEFAULT_PROJECT_NAME,
    DUMMY_PASSWORD_HASH,
    ProjectFactory,
    UserFactory,
    make_project,
    make_user,
)

TEST_JWT_SECRET: Final = "test-jwt-secret-not-for-production"

SETTING_ENV_VARS: Final = frozenset(name.upper() for name in Settings.model_fields)
"""Environment variables read by :class:`~app.core.config.Settings` (matched case-insensitively)."""


# ---------------------------------------------------------------- environment


def _reset_cached_settings_and_app() -> None:
    get_settings.cache_clear()
    _get_default_app.cache_clear()


@pytest.fixture(autouse=True)
def _clean_settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Hide the developer's setting variables and reset the cached settings and default app."""
    for name in list(os.environ):
        if name.upper() in SETTING_ENV_VARS:
            monkeypatch.delenv(name)
    _reset_cached_settings_and_app()
    yield
    _reset_cached_settings_and_app()


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Switch to an empty temporary working directory (no ``.env`` is found) and return it."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return cwd


# ---------------------------------------------------------------- settings and storage


@pytest.fixture
def storage_dir(tmp_path: Path) -> Iterator[Path]:
    """An empty document storage directory for this test, removed with its files afterwards."""
    path = tmp_path / "storage"
    path.mkdir()
    yield path
    if path.exists():
        shutil.rmtree(path)


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """URL of the test database (``TEST_DATABASE_URL``, default: local ``pm_test``)."""
    return get_test_database_url()


@pytest.fixture(scope="session")
def test_schema() -> str:
    """Name of this test session's schema in the test database."""
    return unique_schema_name("test")


@pytest.fixture(scope="session")
def test_schema_url(test_database_url: str, test_schema: str) -> str:
    """URL of the test database whose connections work in :func:`test_schema`."""
    return url_with_search_path(test_database_url, test_schema)


@pytest.fixture
def make_settings(test_schema_url: str, storage_dir: Path) -> Callable[..., Settings]:
    """Build test settings with overrides, e.g. ``make_settings(jwt_expire_minutes=5)``.

    Defaults: a fixed JWT secret, the test database (session schema) and :func:`storage_dir`.
    Neither the environment nor ``.env`` is read for these.
    """

    def make(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "jwt_secret": TEST_JWT_SECRET,
            "database_url": test_schema_url,
            "storage_dir": storage_dir,
            "_env_file": None,
            **overrides,
        }
        return Settings(**values)  # type: ignore[arg-type]

    return make


@pytest.fixture
def test_settings(make_settings: Callable[..., Settings]) -> Settings:
    """The settings of the :func:`app` fixture."""
    return make_settings()


# ---------------------------------------------------------------- database


@pytest.fixture(scope="session")
def db_engine(test_database_url: str, test_schema: str) -> Iterator[Engine]:
    """Engine on the test database; the session's schema holds all model tables."""
    with temporary_schema(test_database_url, test_schema) as engine:
        yield engine


@pytest.fixture
def db_connection(db_engine: Engine) -> Iterator[Connection]:
    """The test's connection, in a transaction that is rolled back after the test."""
    with db_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            if transaction.is_active:
                transaction.rollback()


@pytest.fixture
def db_session_factory(db_connection: Connection) -> sessionmaker[Session]:
    """Session factory like the app's, but bound to :func:`db_connection`.

    ``commit()`` / ``rollback()`` of its sessions act on a SAVEPOINT, never on the outer
    transaction, so they are undone when the test ends.
    """
    factory = create_session_factory(db_connection.engine)  # the app's session options
    factory.configure(bind=db_connection, join_transaction_mode="create_savepoint")
    return factory


@pytest.fixture
def db_session(db_session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """The test's own session (for factories and assertions), rolled back after the test.

    Requests use their own sessions on the same transaction: call ``db_session.expire_all()``
    (or query again) to see changes made by a request in objects loaded before it.
    """
    with db_session_factory() as session:
        yield session


# ---------------------------------------------------------------- app and client


@pytest.fixture
def app(test_settings: Settings, db_session_factory: sessionmaker[Session]) -> Iterator[FastAPI]:
    """The application, built with :func:`test_settings`, on the test's database transaction.

    ``get_db`` takes its sessions from ``app.state.session_factory``; replacing that factory
    gives every request its own session on the test connection, while ``get_db`` itself (rollback
    on errors, close after the request) runs unchanged. ``app.dependency_overrides`` is not
    touched: it still pins ``get_settings`` to :func:`test_settings`. Fixtures that add their own
    overrides must remove only their own keys afterwards, never ``clear()`` the mapping.
    """
    application = create_app(settings=test_settings)
    application.state.session_factory = db_session_factory
    yield application
    application.state.engine.dispose()  # the app's own engine; normally never connected


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """A ``TestClient`` for :func:`app`, started as a context manager (runs the lifespan)."""
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------- factories


@pytest.fixture
def create_user(db_session: Session) -> UserFactory:
    """``create_user(login=None, *, password_hash=DUMMY_PASSWORD_HASH) -> User``.

    The default hash is a placeholder that can't be used to log in.
    """

    def create(login: str | None = None, *, password_hash: str = DUMMY_PASSWORD_HASH) -> User:
        return make_user(db_session, login, password_hash=password_hash)

    return create


@pytest.fixture
def create_project(db_session: Session) -> ProjectFactory:
    """``create_project(owner, *, name=..., description=None) -> Project``.

    Creates the project and the owner's ``owner`` membership (``owner_id`` stays consistent).
    """

    def create(
        owner: User, *, name: str = DEFAULT_PROJECT_NAME, description: str | None = None
    ) -> Project:
        return make_project(db_session, owner, name=name, description=description)

    return create
