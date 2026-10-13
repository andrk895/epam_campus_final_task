"""Shared FastAPI dependencies of the API layer.

Endpoints that need the authenticated user declare a parameter of type :data:`CurrentUserDep`;
endpoints that need a database session use :data:`DbSessionDep` (re-exported from ``app.db``).
"""

from typing import Annotated, Final

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import SettingsDep
from app.core.security import InvalidTokenError, decode_token
from app.db import DbSessionDep
from app.models import User

__all__ = ["CurrentUserDep", "DbSessionDep", "bearer_scheme", "get_current_user"]

NOT_AUTHENTICATED_DETAIL: Final = "Not authenticated."
INVALID_TOKEN_DETAIL: Final = "Invalid or expired access token."  # noqa: S105

bearer_scheme: Final = HTTPBearer(
    auto_error=False,
    bearerFormat="JWT",
    description="Paste the `access_token` returned by `POST /login`.",
)
"""OpenAPI security scheme: makes the "Authorize" button in ``/docs`` accept a bearer token."""


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    session: DbSessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """Return the user identified by the ``Authorization: Bearer <token>`` header.

    Raises ``401`` (with ``WWW-Authenticate: Bearer``) if the header is missing or not a bearer
    token, if the token is invalid or expired, or if its user no longer exists.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized(NOT_AUTHENTICATED_DETAIL)
    try:
        payload = decode_token(credentials.credentials, settings)
    except InvalidTokenError:
        raise _unauthorized(INVALID_TOKEN_DETAIL) from None
    user = session.get(User, payload.user_id)
    if user is None:
        raise _unauthorized(INVALID_TOKEN_DETAIL)
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
"""Annotated type for endpoint parameters that need the authenticated user."""
