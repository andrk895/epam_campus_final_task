"""FastAPI application factory and the ASGI entry point.

Run the server with ``uv run uvicorn app.main:app`` (add ``--reload`` for development).

``app.main:app`` is built lazily on first attribute access (see :func:`__getattr__`), so
importing this module (e.g. ``from app.main import create_app`` in tests) never reads the
environment. ASGI servers resolve ``app`` right at startup, so a missing or invalid setting
such as ``JWT_SECRET`` still makes the server fail to start instead of failing on the first
request.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import cache

from fastapi import FastAPI

from app import __version__
from app.api import health
from app.core.config import Settings, get_settings
from app.db.session import create_db_engine, create_session_factory

API_TITLE = "Project Management API"
API_DESCRIPTION = (
    "Backend for a project management tool: users, projects, sharing and project documents."
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Release the app's database connections when the application shuts down."""
    try:
        yield
    finally:
        app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        settings: Settings to use. If omitted, :func:`~app.core.config.get_settings` is called
            eagerly, so invalid configuration raises
            :class:`~app.core.config.ConfigurationError` here, at startup. Tests pass their
            own ``Settings`` to build an app without touching the environment.

    In both cases ``Depends(get_settings)`` / ``SettingsDep`` in this app resolve to the
    settings the app was built with; they are also available as ``app.state.settings``.

    The app gets its own database engine for ``settings.database_url`` (``app.state.engine``,
    no connection is opened until first use) and session factory
    (``app.state.session_factory``, used by :func:`~app.db.session.get_db`). The engine is
    disposed on application shutdown.
    """
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title=API_TITLE, description=API_DESCRIPTION, version=__version__, lifespan=_lifespan
    )
    app.state.settings = settings
    app.state.engine = create_db_engine(settings)
    app.state.session_factory = create_session_factory(app.state.engine)
    # Pin the settings this app was built with, so endpoints using ``SettingsDep`` see the
    # same object (even if ``get_settings``' cache is cleared or a test passed its own).
    app.dependency_overrides[get_settings] = lambda: settings

    app.include_router(health.router)
    return app


@cache
def _get_default_app() -> FastAPI:
    """Build the process-wide app from the environment (cached once it succeeds)."""
    return create_app()


def __getattr__(name: str) -> FastAPI:
    """Lazily provide the module-level ``app`` used by ``uvicorn app.main:app``."""
    if name == "app":
        return _get_default_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
