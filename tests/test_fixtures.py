"""Tests for the shared test fixtures in ``tests/conftest.py``.

Some tests come in pairs: the first one leaves something behind on purpose (committed rows, a
stored file) and records it in ``_left_behind``; the next one checks that it is gone. The second
test of a pair is skipped if the first one did not run in the same process (e.g. ``-k`` or
pytest-xdist put them apart).
"""

from pathlib import Path
from typing import Final

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, func, make_url, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, SettingsDep
from app.db import DbSessionDep
from app.models import Project, ProjectMember, ProjectRole, User
from tests.factories import (
    DEFAULT_PROJECT_NAME,
    DUMMY_PASSWORD_HASH,
    ProjectFactory,
    UserFactory,
)

COMMITTED_IN_TEST: Final = "committed_in_test"
COMMITTED_IN_REQUEST: Final = "committed_in_request"

_left_behind: dict[str, object] = {}


def users_with_login(session: Session | Connection, login: str) -> int:
    statement = select(func.count()).select_from(User).where(User.login == login)
    return session.execute(statement).scalar_one()


def visible_outside_the_test(db_engine: Engine, login: str) -> int:
    """Count matching users on a separate connection, i.e. only committed data."""
    with db_engine.connect() as connection:
        return users_with_login(connection, login)


def require_previous_test(key: str) -> object:
    if key not in _left_behind:
        pytest.skip("the test that leaves data behind did not run in this process")
    return _left_behind[key]


@pytest.fixture
def probe_routes(app: FastAPI) -> None:
    """Add endpoints that write users through the app's real ``get_db`` session."""

    @app.post("/probe/users/{login}", status_code=201)
    def create_and_commit(login: str, session: DbSessionDep) -> dict[str, int]:
        user = User(login=login, password_hash=DUMMY_PASSWORD_HASH)
        session.add(user)
        session.commit()
        return {"id": user.id}

    @app.post("/probe/users/{login}/fail")
    def create_and_fail(login: str, session: DbSessionDep) -> None:
        session.add(User(login=login, password_hash=DUMMY_PASSWORD_HASH))
        session.flush()
        raise HTTPException(status_code=409, detail="conflict")

    @app.get("/probe/users/{login}")
    def count_users(login: str, session: DbSessionDep) -> dict[str, int]:
        return {"count": users_with_login(session, login)}

    @app.get("/probe/settings")
    def settings_probe(settings: SettingsDep) -> dict[str, str]:
        return {"storage_dir": str(settings.storage_dir), "database_url": settings.database_url}


# ---------------------------------------------------------------- settings and schema


def test_settings_use_the_test_database_and_storage_dir(
    test_settings: Settings, test_database_url: str, test_schema: str, storage_dir: Path
) -> None:
    url = make_url(test_settings.database_url)
    assert url.database == make_url(test_database_url).database
    assert url.query["options"] == f"-csearch_path={test_schema}"
    assert test_settings.storage_dir == storage_dir
    assert test_settings.jwt_secret.get_secret_value()


def test_tables_live_in_the_session_schema(db_session: Session, test_schema: str) -> None:
    assert db_session.execute(text("SELECT current_schema()")).scalar_one() == test_schema
    tables = db_session.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = :schema"),
        {"schema": test_schema},
    )
    assert set(tables.scalars()) == {"users", "projects", "project_members", "documents"}


@pytest.mark.usefixtures("probe_routes")
def test_app_uses_the_test_settings(
    client: TestClient, app: FastAPI, test_settings: Settings
) -> None:
    response = client.get("/probe/settings")

    assert app.state.settings is test_settings
    assert response.json() == {
        "storage_dir": str(test_settings.storage_dir),
        "database_url": test_settings.database_url,
    }


# ---------------------------------------------------------------- database isolation


def test_data_committed_in_a_test_is_rolled_back_afterwards_1(
    db_session: Session, db_engine: Engine, create_user: UserFactory
) -> None:
    create_user(COMMITTED_IN_TEST)
    db_session.commit()

    assert users_with_login(db_session, COMMITTED_IN_TEST) == 1
    # Only a SAVEPOINT was released: the outer transaction is still open.
    assert visible_outside_the_test(db_engine, COMMITTED_IN_TEST) == 0
    _left_behind[COMMITTED_IN_TEST] = True


def test_data_committed_in_a_test_is_rolled_back_afterwards_2(
    db_session: Session, db_engine: Engine
) -> None:
    require_previous_test(COMMITTED_IN_TEST)

    assert users_with_login(db_session, COMMITTED_IN_TEST) == 0
    assert visible_outside_the_test(db_engine, COMMITTED_IN_TEST) == 0


@pytest.mark.usefixtures("probe_routes")
def test_a_commit_inside_a_request_is_rolled_back_after_the_test_1(
    client: TestClient, db_session: Session, db_engine: Engine
) -> None:
    response = client.post(f"/probe/users/{COMMITTED_IN_REQUEST}")

    assert response.status_code == 201
    user = db_session.get(User, response.json()["id"])
    assert user is not None
    assert user.login == COMMITTED_IN_REQUEST
    assert visible_outside_the_test(db_engine, COMMITTED_IN_REQUEST) == 0
    _left_behind[COMMITTED_IN_REQUEST] = True


@pytest.mark.usefixtures("probe_routes")
def test_a_commit_inside_a_request_is_rolled_back_after_the_test_2(
    client: TestClient, db_session: Session, db_engine: Engine
) -> None:
    require_previous_test(COMMITTED_IN_REQUEST)

    assert client.get(f"/probe/users/{COMMITTED_IN_REQUEST}").json() == {"count": 0}
    assert users_with_login(db_session, COMMITTED_IN_REQUEST) == 0
    assert visible_outside_the_test(db_engine, COMMITTED_IN_REQUEST) == 0


@pytest.mark.usefixtures("probe_routes")
def test_requests_see_rows_created_by_factories(
    client: TestClient, create_user: UserFactory
) -> None:
    user = create_user()  # flushed, not committed

    assert client.get(f"/probe/users/{user.login}").json() == {"count": 1}


@pytest.mark.usefixtures("probe_routes")
def test_a_failed_request_rolls_back_only_its_own_changes(
    client: TestClient, db_session: Session, create_user: UserFactory
) -> None:
    existing = create_user()

    response = client.post("/probe/users/from_failed_request/fail")

    assert response.status_code == 409
    assert users_with_login(db_session, "from_failed_request") == 0
    # The rollback in get_db went back to the request's own SAVEPOINT, not the test's data.
    assert users_with_login(db_session, existing.login) == 1


@pytest.mark.usefixtures("probe_routes")
def test_request_sessions_are_closed_after_each_request(
    client: TestClient, db_connection: Connection
) -> None:
    assert client.post("/probe/users/closed_session").status_code == 201

    # The request's SAVEPOINT is gone; only the test's outer transaction is still open.
    assert not db_connection.in_nested_transaction()
    assert db_connection.in_transaction()


# ---------------------------------------------------------------- storage


def test_storage_dir_is_cleaned_after_the_test_1(storage_dir: Path) -> None:
    assert storage_dir.is_dir()
    assert list(storage_dir.iterdir()) == []
    stored = storage_dir / "1" / "some-uuid"
    stored.parent.mkdir()
    stored.write_bytes(b"document")
    _left_behind["stored_file"] = stored


def test_storage_dir_is_cleaned_after_the_test_2(storage_dir: Path) -> None:
    previous = require_previous_test("stored_file")

    assert isinstance(previous, Path)
    assert not previous.exists()
    assert list(storage_dir.iterdir()) == []


# ---------------------------------------------------------------- factories


def test_create_user_defaults(create_user: UserFactory, db_session: Session) -> None:
    first = create_user()
    second = create_user()

    assert first.id is not None
    assert first.login != second.login
    assert 3 <= len(first.login) <= 50
    assert first.password_hash == DUMMY_PASSWORD_HASH
    assert db_session.get(User, first.id) is first


def test_create_user_with_login_and_password_hash(create_user: UserFactory) -> None:
    user = create_user(login="alice", password_hash="$argon2id$fake")

    assert user.login == "alice"
    assert user.password_hash == "$argon2id$fake"


def test_create_project_adds_the_owner_membership(
    create_user: UserFactory, create_project: ProjectFactory, db_session: Session
) -> None:
    owner = create_user()

    project = create_project(owner, name="Apollo", description="Moon landing")

    assert (project.name, project.description) == ("Apollo", "Moon landing")
    assert project.owner_id == owner.id
    memberships = db_session.execute(
        select(ProjectMember.user_id, ProjectMember.role).where(
            ProjectMember.project_id == project.id
        )
    ).all()
    assert [tuple(row) for row in memberships] == [(owner.id, ProjectRole.OWNER)]


def test_create_project_defaults(create_user: UserFactory, create_project: ProjectFactory) -> None:
    project = create_project(create_user())

    assert isinstance(project, Project)
    assert project.name == DEFAULT_PROJECT_NAME
    assert project.description is None
