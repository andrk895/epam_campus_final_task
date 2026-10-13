"""Alembic migration environment.

The target metadata is :data:`app.db.Base.metadata`, with every model registered by importing
:mod:`app.models`. The database is chosen as follows (first match wins):

1. a SQLAlchemy ``Connection`` passed in ``config.attributes["connection"]`` (programmatic use,
   e.g. tests that run migrations on their own connection);
2. ``-x dburl=...`` on the ``alembic`` command line;
3. ``sqlalchemy.url`` set on the Alembic ``Config`` (empty in ``alembic.ini``; tests set it
   with ``Config.set_main_option``);
4. ``DATABASE_URL`` from the application settings (environment variables or ``.env``), the
   same value the application itself uses.

Programmatic callers can set ``config.attributes["configure_logger"] = False`` to keep their
own logging configuration (otherwise the ``[loggers]`` section of ``alembic.ini`` is applied).
"""

from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import Connection, create_engine, pool

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.core.config import load_settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# Options shared by online and offline mode (and used by autogenerate).
CONTEXT_OPTIONS: dict[str, Any] = {
    "target_metadata": target_metadata,
    # Detect column type changes (e.g. a String length) and server default changes too.
    "compare_type": True,
    "compare_server_default": True,
}


def get_database_url() -> str:
    """The database URL to migrate (see the module docstring for the order of precedence)."""
    url = context.get_x_argument(as_dictionary=True).get("dburl")
    if url:
        return url
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    return load_settings().database_url


def run_migrations_offline() -> None:
    """Emit the migration SQL to stdout (``alembic upgrade head --sql``) without connecting."""
    context.configure(
        url=get_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **CONTEXT_OPTIONS,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_on(connection: Connection) -> None:
    """Run the migrations on ``connection``, in one transaction."""
    context.configure(connection=connection, **CONTEXT_OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and run the migrations."""
    connection = config.attributes.get("connection")
    if isinstance(connection, Connection):
        run_migrations_on(connection)
        return

    # NullPool: a one-off command needs no connection pool.
    engine = create_engine(get_database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            run_migrations_on(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
