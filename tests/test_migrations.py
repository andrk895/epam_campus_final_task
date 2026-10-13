"""Tests for the Alembic migrations (``alembic.ini`` and ``src/app/db/migrations``).

Each test gets a brand-new, empty PostgreSQL database (``pm_migr_<random>``), created through
the test server (``TEST_DATABASE_URL``, by default the local ``pm_test``) and dropped again
afterwards. The migrations are run with Alembic's Python API (``alembic.command``), exactly as
``alembic upgrade head`` / ``alembic downgrade base`` would run them.
"""

import io
import os
import uuid
from argparse import Namespace
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, make_url, text

from app.db import Base
from app.models.document import STORAGE_KEY_UNIQUE_CONSTRAINT
from app.models.project import MEMBERSHIP_PRIMARY_KEY, SINGLE_OWNER_INDEX
from app.models.user import LOGIN_UNIQUE_INDEX

TEST_DATABASE_URL: Final = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/pm_test"
)

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
ALEMBIC_INI: Final = REPO_ROOT / "alembic.ini"

TABLES: Final = frozenset({"users", "projects", "project_members", "documents"})
VERSION_TABLE: Final = "alembic_version"

# A URL nothing listens on: using it for real would fail the test.
UNREACHABLE_DATABASE_URL: Final = "postgresql+psycopg://nobody:wrong@localhost:1/does_not_exist"


@pytest.fixture
def database_url() -> Iterator[str]:
    """The URL of a new, empty database, dropped (even if still connected) after the test."""
    name = f"pm_migr_{uuid.uuid4().hex}"
    admin_engine = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(TEST_DATABASE_URL).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin_engine.dispose()


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


def make_config(
    database_url: str | None = None, output_buffer: io.StringIO | None = None
) -> Config:
    """The repository's Alembic configuration, optionally pointed at ``database_url``."""
    config = Config(ALEMBIC_INI, output_buffer=output_buffer)
    # Keep pytest's logging setup instead of applying the [loggers] section of alembic.ini.
    config.attributes["configure_logger"] = False
    if database_url is not None:
        # ``set_main_option`` goes through ConfigParser interpolation, so escape "%".
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def head_revision() -> str:
    head = ScriptDirectory.from_config(make_config()).get_current_head()
    assert head is not None
    return head


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def relations(engine: Engine) -> set[tuple[str, str]]:
    """``(name, relkind)`` of every table, index, sequence, view, ... in the public schema."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT c.relname, c.relkind FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public'"
            )
        )
        return {(name, kind) for name, kind in rows}


def index_definitions(engine: Engine) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
        )
        return {row.indexname: row.indexdef for row in rows}


def test_there_is_a_single_head() -> None:
    script = ScriptDirectory.from_config(make_config())

    assert len(script.get_heads()) == 1
    assert head_revision() == "0001"


def test_upgrade_head_creates_the_schema_on_an_empty_database(
    database_url: str, engine: Engine
) -> None:
    assert relations(engine) == set()

    command.upgrade(make_config(database_url), "head")

    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == TABLES | {VERSION_TABLE}
    assert current_revision(engine) == head_revision()

    # Primary keys, unique constraints and foreign keys (with their ON DELETE rules).
    membership_pk = inspector.get_pk_constraint("project_members")
    assert membership_pk["name"] == MEMBERSHIP_PRIMARY_KEY
    assert membership_pk["constrained_columns"] == ["project_id", "user_id"]
    assert [uq["name"] for uq in inspector.get_unique_constraints("documents")] == [
        STORAGE_KEY_UNIQUE_CONSTRAINT
    ]
    foreign_keys = {
        (table, fk["name"], fk["options"].get("ondelete"))
        for table in TABLES
        for fk in inspector.get_foreign_keys(table)
    }
    assert foreign_keys == {
        ("projects", "fk_projects_owner_id_users", "RESTRICT"),
        ("project_members", "fk_project_members_project_id_projects", "CASCADE"),
        ("project_members", "fk_project_members_user_id_users", "CASCADE"),
        ("documents", "fk_documents_project_id_projects", "CASCADE"),
        ("documents", "fk_documents_uploaded_by_users", "RESTRICT"),
    }

    # Each CHECK constraint exists exactly once.
    checks = {
        table: [ck["name"] for ck in inspector.get_check_constraints(table)] for table in TABLES
    }
    assert checks == {
        "users": [],
        "projects": [],
        "project_members": ["ck_project_members_project_role"],
        "documents": ["ck_documents_size_not_negative"],
    }

    # The functional index on lower(login) and the partial single-owner index.
    indexes = index_definitions(engine)
    assert indexes[LOGIN_UNIQUE_INDEX] == (
        f"CREATE UNIQUE INDEX {LOGIN_UNIQUE_INDEX} ON public.users "
        "USING btree (lower((login)::text))"
    )
    assert indexes[SINGLE_OWNER_INDEX] == (
        f"CREATE UNIQUE INDEX {SINGLE_OWNER_INDEX} ON public.project_members "
        "USING btree (project_id) WHERE ((role)::text = 'owner'::text)"
    )
    assert set(indexes) == {
        "alembic_version_pkc",
        "pk_users",
        LOGIN_UNIQUE_INDEX,
        "pk_projects",
        "ix_projects_owner_id",
        MEMBERSHIP_PRIMARY_KEY,
        "ix_project_members_user_id",
        SINGLE_OWNER_INDEX,
        "pk_documents",
        "ix_documents_project_id",
        "ix_documents_uploaded_by",
        STORAGE_KEY_UNIQUE_CONSTRAINT,
    }


def test_migrated_schema_matches_the_models(database_url: str, engine: Engine) -> None:
    command.upgrade(make_config(database_url), "head")

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        )
        diff = compare_metadata(context, Base.metadata)

    assert diff == []


def test_downgrade_base_removes_the_schema(database_url: str, engine: Engine) -> None:
    config = make_config(database_url)
    command.upgrade(config, "head")

    command.downgrade(config, "base")

    # Only Alembic's (now empty) version table is left: no tables, indexes or sequences.
    assert relations(engine) == {(VERSION_TABLE, "r"), ("alembic_version_pkc", "i")}
    assert current_revision(engine) is None


def test_upgrade_works_again_after_downgrade(database_url: str, engine: Engine) -> None:
    config = make_config(database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    command.upgrade(config, "head")

    assert set(inspect(engine).get_table_names()) == TABLES | {VERSION_TABLE}
    assert current_revision(engine) == head_revision()


def test_database_url_defaults_to_the_application_settings(
    database_url: str, engine: Engine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # No URL on the Config and no -x argument: env.py uses DATABASE_URL (as the app does).
    monkeypatch.chdir(tmp_path)  # no .env file here
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("JWT_SECRET", "test-secret")

    command.upgrade(make_config(), "head")

    assert current_revision(engine) == head_revision()


def test_x_dburl_argument_takes_precedence(database_url: str, engine: Engine) -> None:
    config = make_config(UNREACHABLE_DATABASE_URL)
    config.cmd_opts = Namespace(x=[f"dburl={database_url}"])

    command.upgrade(config, "head")

    assert current_revision(engine) == head_revision()


def test_migrations_can_run_on_a_passed_in_connection(engine: Engine) -> None:
    config = make_config(UNREACHABLE_DATABASE_URL)
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        connection.commit()

    assert current_revision(engine) == head_revision()


def test_offline_mode_renders_the_sql() -> None:
    output = io.StringIO()
    # Offline mode never connects, so the URL only selects the dialect.
    config = make_config(UNREACHABLE_DATABASE_URL, output_buffer=output)

    command.upgrade(config, "head", sql=True)

    sql = output.getvalue()
    assert "CREATE TABLE users" in sql
    assert f"CREATE UNIQUE INDEX {LOGIN_UNIQUE_INDEX} ON users (lower(login))" in sql
    assert "WHERE role = 'owner'" in sql
    assert sql.count("CONSTRAINT ck_project_members_project_role CHECK") == 1
    assert sql.count("CONSTRAINT ck_documents_size_not_negative CHECK") == 1
