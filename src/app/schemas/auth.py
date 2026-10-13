"""Schemas for registration and login (design decision D11)."""

from datetime import datetime
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.user import LOGIN_MAX_LENGTH

LOGIN_MIN_LENGTH: Final = 3
PASSWORD_MIN_LENGTH: Final = 8
PASSWORD_MAX_LENGTH: Final = 128
"""Upper bound on password length, so hashing cost can't be abused with huge inputs."""
LOGIN_PATTERN: Final = r"^[A-Za-z0-9_.\-]+$"
"""Logins are usernames: ASCII letters, digits, ``_``, ``.`` and ``-``."""

Login = Annotated[
    str,
    StringConstraints(
        min_length=LOGIN_MIN_LENGTH, max_length=LOGIN_MAX_LENGTH, pattern=LOGIN_PATTERN
    ),
]
Password = Annotated[
    str, StringConstraints(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
]


class RegisterRequest(BaseModel):
    """Body of ``POST /auth``."""

    model_config = ConfigDict(extra="forbid")

    login: Login = Field(description="3-50 characters: letters, digits, `_`, `.`, `-`.")
    password: Password = Field(description="At least 8 characters.")


class UserRead(BaseModel):
    """A user as returned by the API (never includes the password hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    created_at: datetime


class LoginRequest(BaseModel):
    """Body of ``POST /login``.

    Only loosely validated: any wrong login or password, however malformed, gets the same
    generic ``401``.
    """

    login: Annotated[str, StringConstraints(min_length=1, max_length=LOGIN_MAX_LENGTH * 4)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=PASSWORD_MAX_LENGTH * 4)]


class TokenResponse(BaseModel):
    """An access token for the ``Authorization: Bearer <token>`` header."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 (not a secret)
    expires_in: int = Field(description="Lifetime of the token in seconds.")
