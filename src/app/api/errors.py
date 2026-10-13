"""Mapping of domain exceptions (:mod:`app.core.errors`) to HTTP error responses.

Every :class:`~app.core.errors.AppError` becomes a JSON response ``{"detail": ..., "code": ...}``
with the status code of the most specific matching class in :data:`STATUS_BY_ERROR`.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.core.errors import (
    AppError,
    AuthenticationError,
    ConflictError,
    FileTooLarge,
    NotFoundError,
    PermissionDenied,
    UnsupportedFileType,
)

STATUS_BY_ERROR: Final[Mapping[type[AppError], int]] = MappingProxyType(
    {
        AuthenticationError: status.HTTP_401_UNAUTHORIZED,
        PermissionDenied: status.HTTP_403_FORBIDDEN,
        NotFoundError: status.HTTP_404_NOT_FOUND,
        ConflictError: status.HTTP_409_CONFLICT,
        FileTooLarge: status.HTTP_413_CONTENT_TOO_LARGE,
        UnsupportedFileType: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    }
)


def status_for(error: AppError) -> int:
    """HTTP status for ``error``: the entry of its closest base class, else ``400``."""
    for cls in type(error).__mro__:
        if cls in STATUS_BY_ERROR:
            return STATUS_BY_ERROR[cls]
    return status.HTTP_400_BAD_REQUEST


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render an :class:`AppError` as ``{"detail": ..., "code": ...}``."""
    assert isinstance(exc, AppError)  # noqa: S101 (registered for AppError only)
    status_code = status_for(exc)
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return JSONResponse(
        status_code=status_code,
        content={"detail": exc.detail, "code": exc.code},
        headers=headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Install the domain exception handler on ``app``."""
    app.add_exception_handler(AppError, app_error_handler)
