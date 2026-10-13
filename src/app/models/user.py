"""The ``User`` model (table ``users``)."""

from datetime import datetime
from typing import TYPE_CHECKING, Final

from sqlalchemy import ColumnElement, DateTime, Identity, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.project import Project, ProjectMember

LOGIN_MAX_LENGTH: Final = 50
"""Maximum length of a login (design decision D11: 3-50 characters)."""

LOGIN_UNIQUE_INDEX: Final = "uq_users_login_lower"
"""Name of the unique index that makes logins unique regardless of case."""


class User(Base):
    """A registered user.

    Logins are unique **case-insensitively** (design decision D11). The login is stored as the
    user typed it (its case is preserved for display), and the unique index
    ``uq_users_login_lower`` on ``lower(login)`` makes the database reject ``"Alice"`` when
    ``"alice"`` already exists. The same index serves login lookups, so queries must compare
    lowercased values: use :meth:`login_matches` rather than ``User.login == value``.

    Users are never deleted by the API. At the database level, deleting a user deletes their
    memberships (``ON DELETE CASCADE``) but is refused while they still own a project or are the
    uploader of a document (``ON DELETE RESTRICT``), so no project or document loses its owner or
    uploader.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    login: Mapped[str] = mapped_column(String(LOGIN_MAX_LENGTH))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # passive_deletes="all": the ORM never nulls out ``projects.owner_id`` when a user is
    # deleted; the database's ON DELETE RESTRICT decides.
    owned_projects: Mapped[list["Project"]] = relationship(
        back_populates="owner", passive_deletes="all"
    )
    memberships: Mapped[list["ProjectMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    @classmethod
    def login_matches(cls, login: str) -> ColumnElement[bool]:
        """SQL condition matching this user's login case-insensitively (uses the unique index).

        Example: ``select(User).where(User.login_matches("Alice"))``.
        """
        return func.lower(cls.login) == func.lower(login)

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, login={self.login!r})"


# Defined after the class because the expression needs the mapped ``User.login`` column.
Index(LOGIN_UNIQUE_INDEX, func.lower(User.login), unique=True)
