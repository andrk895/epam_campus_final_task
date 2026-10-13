"""Database engine, session factory and the per-request ``get_db`` dependency.

Every application built by :func:`app.main.create_app` owns its own engine (created from its
``Settings.database_url``) and session factory, stored as ``app.state.engine`` and
``app.state.session_factory``. The engine is disposed when the application shuts down.

Endpoints receive a session with ``Depends(get_db)`` / :data:`DbSessionDep`. Each request gets
its own :class:`~sqlalchemy.orm.Session`, which is rolled back if the request fails and is
always closed (returning its connection to the pool) when the request is finished. Sessions
never commit implicitly: code that writes must call ``session.commit()`` itself.
"""

from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import ConfigurationError, Settings


def create_db_engine(settings: Settings) -> Engine:
    """Create the SQLAlchemy engine for ``settings.database_url``.

    No connection is opened here; the pool connects lazily on first use. A malformed URL or an
    unknown dialect raises :class:`~app.core.config.ConfigurationError`.
    """
    try:
        return create_engine(
            settings.database_url,
            # Transparently replace connections dropped by the server (e.g. after a restart).
            pool_pre_ping=True,
        )
    except ArgumentError:
        # ``from None`` and no URL in the message: the URL may contain a password.
        raise ConfigurationError(
            "Invalid application configuration:\n"
            "  - DATABASE_URL: not a valid SQLAlchemy database URL "
            "(expected e.g. postgresql+psycopg://user:password@host:5432/dbname)"
        ) from None


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create the session factory bound to ``engine``."""
    return sessionmaker(
        bind=engine,
        autoflush=False,
        # Keep loaded attributes usable after commit (e.g. when serialising a response).
        expire_on_commit=False,
    )


def get_db(request: Request) -> Iterator[Session]:
    """Yield one database session per request (FastAPI dependency).

    If the request raises, the session's transaction is rolled back before the exception
    propagates. The session is closed in every case.
    """
    session_factory = cast(sessionmaker[Session], request.app.state.session_factory)
    with session_factory() as session:  # ``with`` closes the session on exit
        try:
            yield session
        except BaseException:
            session.rollback()
            raise


DbSessionDep = Annotated[Session, Depends(get_db)]
"""Annotated type for endpoint parameters that need a database session."""
