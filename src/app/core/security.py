"""Password hashing and JWT access tokens (design decisions D3 and D4).

This module is framework-free: it knows nothing about HTTP or FastAPI. The authentication
dependency (T2.4) turns :class:`InvalidTokenError` into a ``401`` response.

* Passwords are hashed with **argon2** through ``pwdlib`` (D3). Every hash embeds its own random
  salt and parameters, so hashing the same password twice gives two different strings.
* Access tokens are **PyJWT** HMAC tokens (D4) carrying exactly three claims: ``sub`` (the user
  id as a decimal string), ``iat`` and ``exp`` (``iat`` + ``JWT_EXPIRE_MINUTES``, 1 hour by
  default). Decoding accepts only the configured algorithm, so ``alg: none`` and algorithm
  substitution are rejected, and all three claims are required.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import jwt
from argon2.exceptions import InvalidHashError
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import Settings

REQUIRED_CLAIMS: Final[tuple[str, ...]] = ("exp", "iat", "sub")
"""Claims every access token must carry; a token missing any of them is rejected."""

MAX_USER_ID: Final = 2**31 - 1
"""Largest accepted ``sub``: ``users.id`` is a PostgreSQL ``INTEGER`` identity column."""

# ``sub`` must be the canonical decimal form of a positive integer: no sign, no leading zeros,
# no whitespace and no non-ASCII digits (which ``int()`` would otherwise accept).
_SUBJECT_PATTERN: Final = re.compile(r"[1-9][0-9]*")

_argon2_hasher: Final = Argon2Hasher()
_password_hash: Final = PasswordHash((_argon2_hasher,))


class InvalidTokenError(Exception):
    """The access token is unusable: malformed, wrongly signed, expired, or with bad claims.

    This is the only exception :func:`decode_token` raises. The message says what was wrong
    (useful for logs) but should not be shown to API clients.
    """


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """The verified content of an access token."""

    user_id: int
    issued_at: datetime
    expires_at: datetime


# ---------------------------------------------------------------- passwords


def hash_password(password: str) -> str:
    """Return an argon2 hash of ``password`` (salted, so never the same string twice)."""
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return whether ``password`` matches ``password_hash``.

    A stored hash that is not a recognised argon2 hash never matches (returns ``False``).
    """
    try:
        return _password_hash.verify(password, password_hash)
    except UnknownHashError:
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """Return whether ``password_hash`` was made with outdated parameters or another algorithm.

    Callers may re-hash the password after a successful login when this is ``True``.
    """
    if not _argon2_hasher.identify(password_hash):
        return True
    try:
        return _argon2_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# ---------------------------------------------------------------- access tokens


def create_access_token(user_id: int, settings: Settings, *, now: datetime | None = None) -> str:
    """Return a signed access token for ``user_id``.

    ``now`` (timezone-aware) sets the issue time; it defaults to the current time and exists so
    tests can create already-expired tokens.
    """
    if isinstance(user_id, bool) or not 1 <= user_id <= MAX_USER_ID:
        raise ValueError(f"user_id must be an integer between 1 and {MAX_USER_ID}")
    if now is None:
        now = datetime.now(UTC)
    elif now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    issued_at = int(now.timestamp())
    expires_at = issued_at + int(timedelta(minutes=settings.jwt_expire_minutes).total_seconds())
    claims: dict[str, Any] = {"sub": str(user_id), "iat": issued_at, "exp": expires_at}
    return jwt.encode(
        claims, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_token(token: str, settings: Settings) -> TokenPayload:
    """Verify ``token`` and return its payload.

    Raises :class:`InvalidTokenError` if the token is malformed, signed with another key or
    algorithm (including ``alg: none``), expired, issued in the future, or if ``sub``, ``iat`` or
    ``exp`` is missing or invalid.
    """
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": list(REQUIRED_CLAIMS)},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(f"invalid access token: {exc}") from exc

    subject = claims["sub"]  # PyJWT has already checked that it is present and a string.
    if not _SUBJECT_PATTERN.fullmatch(subject) or int(subject) > MAX_USER_ID:
        raise InvalidTokenError("invalid access token: sub is not a valid user id")

    # PyJWT has checked that ``exp`` is in the future and ``iat`` is not, but it also accepts
    # numeric strings and floats there; we only ever issue integers.
    issued_at, expires_at = claims["iat"], claims["exp"]
    if type(issued_at) is not int or type(expires_at) is not int:
        raise InvalidTokenError("invalid access token: iat and exp must be integers")
    try:
        return TokenPayload(
            user_id=int(subject),
            issued_at=datetime.fromtimestamp(issued_at, UTC),
            expires_at=datetime.fromtimestamp(expires_at, UTC),
        )
    except (OverflowError, OSError, ValueError) as exc:  # e.g. an ``exp`` in the year 10**12
        raise InvalidTokenError("invalid access token: iat or exp is out of range") from exc
