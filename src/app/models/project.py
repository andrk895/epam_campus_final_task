"""The ``Project`` and ``ProjectMember`` models (tables ``projects`` and ``project_members``)."""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Final

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.user import User

PROJECT_NAME_MAX_LENGTH: Final = 255

MEMBERSHIP_PRIMARY_KEY: Final = "pk_project_members"
"""Name of the ``(project_id, user_id)`` primary key: a user is a member of a project once."""

SINGLE_OWNER_INDEX: Final = "uq_project_members_one_owner_per_project"
"""Name of the partial unique index that allows at most one ``owner`` membership per project."""


class ProjectRole(enum.StrEnum):
    """A user's role in a project (design decision D5)."""

    OWNER = "owner"
    PARTICIPANT = "participant"


_ROLE_VALUES_SQL: Final = ", ".join(f"'{role.value}'" for role in ProjectRole)


class Project(Base):
    """A project, owned by the user who created it.

    The owner is recorded twice: as ``owner_id`` and as the project's single ``owner``
    membership. The service that creates a project writes both in one transaction.

    Deleting a project deletes its memberships and document rows, both through the ORM
    (``cascade="all, delete-orphan"``) and in the database (``ON DELETE CASCADE``), so a bulk
    ``DELETE`` that bypasses the ORM cascades as well. Stored files are not touched here; removing
    them is the job of the service that deletes the project.
    """

    __tablename__ = "projects"
    # Return server-generated values (``updated_at`` on UPDATE) with RETURNING after each flush.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(PROJECT_NAME_MAX_LENGTH))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship(back_populates="owned_projects")
    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Document.id",
    )

    def __repr__(self) -> str:
        return f"Project(id={self.id!r}, name={self.name!r}, owner_id={self.owner_id!r})"


class ProjectMember(Base):
    """A user's membership of a project, with their role.

    The primary key ``(project_id, user_id)`` makes each user a member of a project at most
    once, and a partial unique index allows at most one ``owner`` per project. The role is
    stored as a string limited to the :class:`ProjectRole` values by the CHECK constraint
    ``ck_project_members_project_role`` (not a native PostgreSQL enum type, which would need its
    own CREATE/DROP TYPE in migrations). The CHECK is declared explicitly in ``__table_args__``
    rather than via ``Enum(create_constraint=True)``: Alembic autogenerate renders the latter
    twice (once as a table constraint, once inside ``sa.Enum``), which breaks the migration.
    """

    __tablename__ = "project_members"
    __table_args__ = (
        # Named "ck_project_members_project_role" by the naming convention.
        CheckConstraint(f"role IN ({_ROLE_VALUES_SQL})", name="project_role"),
        Index(
            SINGLE_OWNER_INDEX,
            "project_id",
            unique=True,
            postgresql_where=text(f"role = '{ProjectRole.OWNER.value}'"),
        ),
    )

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    # Indexed separately: the primary key index covers lookups by project, not by user
    # ("which projects is this user a member of").
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[ProjectRole] = mapped_column(
        Enum(
            ProjectRole,
            name="project_role",
            native_enum=False,
            create_constraint=False,  # the CHECK is in __table_args__, see the class docstring
            length=20,
            validate_strings=True,
            # Store the values ("owner"), not the member names ("OWNER").
            values_callable=lambda roles: [role.value for role in roles],
        )
    )
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")

    def __repr__(self) -> str:
        return (
            f"ProjectMember(project_id={self.project_id!r}, user_id={self.user_id!r}, "
            f"role={self.role!r})"
        )
