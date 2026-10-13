"""Factory helpers that insert model rows for tests.

The ``make_*`` functions take the session explicitly. Most tests use the ``create_user`` /
``create_project`` fixtures from ``tests/conftest.py`` instead, which are bound to the test's
``db_session`` (see :class:`UserFactory` and :class:`ProjectFactory` for their signatures).

The factories only ``flush()``: the rows get their ids and are visible to requests made with
the ``client`` fixture (which share the test's database transaction), and they are rolled back
after the test like everything else.
"""

import uuid
from typing import Final, Protocol

from sqlalchemy.orm import Session

from app.models import Project, ProjectMember, ProjectRole, User

DUMMY_PASSWORD_HASH: Final = "not-a-real-password-hash"
"""Default ``password_hash`` of factory users (it can't be used to log in)."""

DEFAULT_PROJECT_NAME: Final = "Test project"


def unique_login(prefix: str = "user") -> str:
    """A login that is unique across tests, e.g. ``user_3f2a9c1b04de`` (within D11's 3-50)."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def make_user(
    session: Session,
    login: str | None = None,
    *,
    password_hash: str = DUMMY_PASSWORD_HASH,
) -> User:
    """Insert a user (a unique login is generated when ``login`` is omitted)."""
    user = User(login=login if login is not None else unique_login(), password_hash=password_hash)
    session.add(user)
    session.flush()
    return user


def make_project(
    session: Session,
    owner: User,
    *,
    name: str = DEFAULT_PROJECT_NAME,
    description: str | None = None,
) -> Project:
    """Insert a project owned by ``owner``, with ``owner``'s ``owner`` membership.

    ``owner_id`` and the single owner membership are written together, as the project service
    does (design decision D5), so they are always consistent.
    """
    project = Project(name=name, description=description, owner=owner)
    project.members.append(ProjectMember(user=owner, role=ProjectRole.OWNER))
    session.add(project)
    session.flush()
    return project


class UserFactory(Protocol):
    """Type of the ``create_user`` fixture."""

    def __call__(self, login: str | None = None, *, password_hash: str = ...) -> User: ...


class ProjectFactory(Protocol):
    """Type of the ``create_project`` fixture."""

    def __call__(
        self, owner: User, *, name: str = ..., description: str | None = ...
    ) -> Project: ...
