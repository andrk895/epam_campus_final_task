"""Test database helpers: the test database URL and temporary, uniquely named schemas.

Tests run against a real PostgreSQL database: ``TEST_DATABASE_URL`` from the environment, by
default the local ``pm_test`` database. Tables are never created in its ``public`` schema;
each test session (each pytest-xdist worker, too) creates its own schema with
``Base.metadata.create_all`` and drops it at the end, so concurrent test runs, Alembic tests
and left-overs of an aborted run never see each other's tables.
"""

import os
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

from sqlalchemy import Engine, create_engine, make_url, text

from app.db import Base

DEFAULT_TEST_DATABASE_URL: Final = "postgresql+psycopg://postgres:postgres@localhost:5432/pm_test"

_SCHEMA_NAME: Final = re.compile(r"[a-z_][a-z0-9_]{0,62}")


def get_test_database_url() -> str:
    """The URL of the test database (``TEST_DATABASE_URL``, default: local ``pm_test``)."""
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


def unique_schema_name(prefix: str = "test") -> str:
    """A fresh schema name such as ``test_3f2a...`` (safe to use unquoted in SQL)."""
    name = f"{prefix}_{uuid.uuid4().hex}"
    if not _SCHEMA_NAME.fullmatch(name):
        raise ValueError(f"invalid schema name: {name!r}")
    return name


def url_with_search_path(database_url: str, schema: str) -> str:
    """``database_url`` with its connections' ``search_path`` set to ``schema``.

    Uses libpq's ``options`` connection parameter, so every connection made from the URL (also
    by an engine the application creates itself) works in ``schema``.
    """
    url = make_url(database_url)
    options = f"-csearch_path={schema}"
    existing = url.query.get("options")
    if isinstance(existing, str) and existing:
        options = f"{existing} {options}"
    return url.update_query_dict({"options": options}).render_as_string(hide_password=False)


@contextmanager
def temporary_schema(database_url: str, schema: str) -> Iterator[Engine]:
    """Create ``schema`` holding all model tables; yield an engine that works in it.

    The schema and everything in it is dropped on exit.
    """
    if not _SCHEMA_NAME.fullmatch(schema):
        raise ValueError(f"invalid schema name: {schema!r}")
    admin_engine = create_engine(database_url)
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_engine(url_with_search_path(database_url, schema))
        try:
            Base.metadata.create_all(engine)
            yield engine
        finally:
            engine.dispose()
            with admin_engine.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    finally:
        admin_engine.dispose()
