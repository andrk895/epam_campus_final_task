"""User registration and authentication."""

from functools import cache

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import InvalidCredentials, LoginAlreadyExists
from app.core.security import hash_password, verify_password
from app.models import User
from app.models.user import LOGIN_UNIQUE_INDEX


@cache
def _dummy_password_hash() -> str:
    """A hash to verify against when the login is unknown, so both cases take as long."""
    return hash_password("dummy password for timing equalisation")


def get_user_by_login(session: Session, login: str) -> User | None:
    """Return the user whose login matches ``login`` case-insensitively, if any."""
    return session.scalars(select(User).where(User.login_matches(login))).one_or_none()


def register_user(session: Session, login: str, password: str) -> User:
    """Create and commit a new user.

    Raises:
        LoginAlreadyExists: the login is taken (case-insensitively). Detected by the database's
            unique index, so concurrent registrations can't both succeed.
    """
    user = User(login=login, password_hash=hash_password(password))
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if LOGIN_UNIQUE_INDEX in str(exc.orig):
            raise LoginAlreadyExists() from None
        raise
    return user


def authenticate(session: Session, login: str, password: str) -> User:
    """Return the user if ``login`` and ``password`` match.

    Raises:
        InvalidCredentials: unknown login or wrong password (indistinguishable, including in
            timing: a dummy hash is verified for unknown logins).
    """
    user = get_user_by_login(session, login)
    if user is None:
        verify_password(password, _dummy_password_hash())
        raise InvalidCredentials()
    if not verify_password(password, user.password_hash):
        raise InvalidCredentials()
    return user
