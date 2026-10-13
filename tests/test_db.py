"""Tests for the database engine, session factory and ``get_db`` (``app.db``).

These tests talk to a real PostgreSQL database: ``TEST_DATABASE_URL`` from the environment,
by default the local ``pm_test`` database.
"""

import os
import uuid
from collections.abc import Iterator
from typing import Final

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from app.core.config import ConfigurationError, Settings
from app.db import Base, DbSessionDep, create_db_engine, create_session_factory
from app.main import create_app

TEST_DATABASE_URL: Final = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/pm_test"
)


def make_settings(**overrides: object) -> Settings:
    """Settings for the test database, built without the environment or `.env`."""
    values: dict[str, object] = {
        "jwt_secret": "test-secret",
        "database_url": TEST_DATABASE_URL,
        "_env_file": None,
        **overrides,
    }
    return Settings(**values)  # type: ignore[arg-type]


def queue_pool(engine: Engine) -> QueuePool:
    """The engine's connection pool (``create_engine`` uses a ``QueuePool`` for psycopg)."""
    pool = engine.pool
    assert isinstance(pool, QueuePool)
    return pool


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_db_engine(make_settings())
    yield engine
    engine.dispose()


class SessionSpy:
    """Records the sessions handed to endpoints and the calls made on them."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.sessions: list[Session] = []
        self.closed: list[Session] = []
        self.rolled_back: list[Session] = []
        original_close = Session.close
        original_rollback = Session.rollback

        def close(session: Session) -> None:
            self.closed.append(session)
            original_close(session)

        def rollback(session: Session) -> None:
            self.rolled_back.append(session)
            original_rollback(session)

        monkeypatch.setattr(Session, "close", close)
        monkeypatch.setattr(Session, "rollback", rollback)


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> SessionSpy:
    return SessionSpy(monkeypatch)


@pytest.fixture
def app(spy: SessionSpy) -> FastAPI:
    """An app on the test database with probe endpoints that use ``DbSessionDep``."""
    app = create_app(settings=make_settings())
    engine: Engine = app.state.engine

    @app.get("/db-probe")
    def db_probe(session: DbSessionDep) -> dict[str, object]:
        spy.sessions.append(session)
        value = session.execute(text("SELECT 1")).scalar_one()
        database = session.execute(text("SELECT current_database()")).scalar_one()
        return {
            "value": value,
            "database": database,
            "checked_out": queue_pool(engine).checkedout(),
        }

    @app.post("/db-probe/{table}/fail")
    def db_probe_fail(table: str, session: DbSessionDep) -> None:
        spy.sessions.append(session)
        # ``table`` is a generated test identifier, never user input.
        session.execute(text(f"INSERT INTO {table} (value) VALUES (1)"))  # noqa: S608
        raise HTTPException(status_code=409, detail="conflict")

    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def probe_table(engine: Engine) -> Iterator[str]:
    """A uniquely named table in the test database, dropped after the test."""
    name = f"t_db_probe_{uuid.uuid4().hex}"
    with engine.begin() as connection:
        connection.execute(text(f"CREATE TABLE {name} (value integer NOT NULL)"))
    yield name
    with engine.begin() as connection:
        connection.execute(text(f"DROP TABLE {name}"))


def test_session_executes_select_1_against_postgresql(engine: Engine) -> None:
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1
        assert session.get_bind().dialect.name == "postgresql"


def test_create_app_builds_engine_from_settings() -> None:
    app = create_app(settings=make_settings())

    engine: Engine = app.state.engine
    assert engine.url.render_as_string(hide_password=False) == TEST_DATABASE_URL
    assert engine.dialect.driver == "psycopg"
    assert app.state.session_factory.kw["bind"] is engine
    engine.dispose()


def test_invalid_database_url_fails_clearly_without_leaking_it() -> None:
    with pytest.raises(ConfigurationError, match="DATABASE_URL") as exc_info:
        create_app(settings=make_settings(database_url="not a url:s3cret"))

    assert "s3cret" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_request_gets_a_session_that_is_closed_afterwards(
    client: TestClient, spy: SessionSpy, app: FastAPI
) -> None:
    response = client.get("/db-probe")

    assert response.status_code == 200
    # The session held a pooled connection while the endpoint ran ...
    assert response.json() == {"value": 1, "database": "pm_test", "checked_out": 1}
    # ... and after the request it was closed and its connection returned to the pool.
    [session] = spy.sessions
    assert spy.closed == [session]
    assert spy.rolled_back == []
    assert not session.in_transaction()
    assert queue_pool(app.state.engine).checkedout() == 0


def test_each_request_gets_its_own_session(client: TestClient, spy: SessionSpy) -> None:
    assert client.get("/db-probe").status_code == 200
    assert client.get("/db-probe").status_code == 200

    first, second = spy.sessions
    assert first is not second
    assert spy.closed == [first, second]


def test_failed_request_rolls_back_and_closes_the_session(
    client: TestClient, spy: SessionSpy, app: FastAPI, engine: Engine, probe_table: str
) -> None:
    response = client.post(f"/db-probe/{probe_table}/fail")

    assert response.status_code == 409
    [session] = spy.sessions
    assert session in spy.rolled_back
    assert spy.closed == [session]
    assert queue_pool(app.state.engine).checkedout() == 0
    with engine.connect() as connection:
        rows = connection.execute(text(f"SELECT count(*) FROM {probe_table}")).scalar_one()  # noqa: S608
    assert rows == 0


def test_engine_is_disposed_on_shutdown(app: FastAPI) -> None:
    engine: Engine = app.state.engine
    with TestClient(app) as client:
        assert client.get("/db-probe").status_code == 200
        pool_while_running = queue_pool(engine)
        assert pool_while_running.checkedin() == 1

    # ``Engine.dispose()`` closes the pooled connections and replaces the pool.
    assert engine.pool is not pool_while_running
    assert pool_while_running.checkedin() == 0


def test_base_metadata_uses_naming_convention() -> None:
    assert Base.metadata.naming_convention["pk"] == "pk_%(table_name)s"
    assert "fk" in Base.metadata.naming_convention
