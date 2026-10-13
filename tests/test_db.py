"""Tests for the database engine, session factory and ``get_db`` (``app.db``).

These tests talk to a real PostgreSQL database (``TEST_DATABASE_URL``, see ``tests/database.py``)
and, unlike most tests, use the app's own engine and the real ``get_db`` session factory, so
they check real connection pooling and real commits/rollbacks (on probe tables that are
dropped after each test).
"""

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Engine, make_url, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from app.core.config import ConfigurationError, Settings
from app.db import Base, DbSessionDep, create_session_factory
from app.main import create_app


def queue_pool(engine: Engine) -> QueuePool:
    """The engine's connection pool (``create_engine`` uses a ``QueuePool`` for psycopg)."""
    pool = engine.pool
    assert isinstance(pool, QueuePool)
    return pool


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
def probe_app(spy: SessionSpy, test_settings: Settings) -> FastAPI:
    """An app on the test database with probe endpoints that use the real ``get_db``.

    Unlike the shared ``app`` fixture, its sessions come from the app's own engine.
    """
    app = create_app(settings=test_settings)
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
def probe_client(probe_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(probe_app) as test_client:
        yield test_client


@pytest.fixture
def probe_table(db_engine: Engine) -> Iterator[str]:
    """A uniquely named table in the test session's schema, dropped after the test."""
    name = f"t_db_probe_{uuid.uuid4().hex}"
    with db_engine.begin() as connection:
        connection.execute(text(f"CREATE TABLE {name} (value integer NOT NULL)"))
    yield name
    with db_engine.begin() as connection:
        connection.execute(text(f"DROP TABLE {name}"))


def test_session_executes_select_1_against_postgresql(db_engine: Engine) -> None:
    session_factory = create_session_factory(db_engine)

    with session_factory() as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1
        assert session.get_bind().dialect.name == "postgresql"


def test_create_app_builds_engine_from_settings(test_settings: Settings) -> None:
    app = create_app(settings=test_settings)

    engine: Engine = app.state.engine
    assert engine.url.render_as_string(hide_password=False) == test_settings.database_url
    assert engine.dialect.driver == "psycopg"
    assert app.state.session_factory.kw["bind"] is engine
    engine.dispose()


def test_invalid_database_url_fails_clearly_without_leaking_it(
    make_settings: Callable[..., Settings],
) -> None:
    with pytest.raises(ConfigurationError, match="DATABASE_URL") as exc_info:
        create_app(settings=make_settings(database_url="not a url:s3cret"))

    assert "s3cret" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_request_gets_a_session_that_is_closed_afterwards(
    probe_client: TestClient, spy: SessionSpy, probe_app: FastAPI, test_database_url: str
) -> None:
    response = probe_client.get("/db-probe")

    assert response.status_code == 200
    # The session held a pooled connection while the endpoint ran ...
    assert response.json() == {
        "value": 1,
        "database": make_url(test_database_url).database,
        "checked_out": 1,
    }
    # ... and after the request it was closed and its connection returned to the pool.
    [session] = spy.sessions
    assert spy.closed == [session]
    assert spy.rolled_back == []
    assert not session.in_transaction()
    assert queue_pool(probe_app.state.engine).checkedout() == 0


def test_each_request_gets_its_own_session(probe_client: TestClient, spy: SessionSpy) -> None:
    assert probe_client.get("/db-probe").status_code == 200
    assert probe_client.get("/db-probe").status_code == 200

    first, second = spy.sessions
    assert first is not second
    assert spy.closed == [first, second]


def test_failed_request_rolls_back_and_closes_the_session(
    probe_client: TestClient,
    spy: SessionSpy,
    probe_app: FastAPI,
    db_engine: Engine,
    probe_table: str,
) -> None:
    response = probe_client.post(f"/db-probe/{probe_table}/fail")

    assert response.status_code == 409
    [session] = spy.sessions
    assert session in spy.rolled_back
    assert spy.closed == [session]
    assert queue_pool(probe_app.state.engine).checkedout() == 0
    with db_engine.connect() as connection:
        rows = connection.execute(text(f"SELECT count(*) FROM {probe_table}")).scalar_one()  # noqa: S608
    assert rows == 0


def test_engine_is_disposed_on_shutdown(probe_app: FastAPI) -> None:
    engine: Engine = probe_app.state.engine
    with TestClient(probe_app) as client:
        assert client.get("/db-probe").status_code == 200
        pool_while_running = queue_pool(engine)
        assert pool_while_running.checkedin() == 1

    # ``Engine.dispose()`` closes the pooled connections and replaces the pool.
    assert engine.pool is not pool_while_running
    assert pool_while_running.checkedin() == 0


def test_base_metadata_uses_naming_convention() -> None:
    assert Base.metadata.naming_convention["pk"] == "pk_%(table_name)s"
    assert "fk" in Base.metadata.naming_convention
