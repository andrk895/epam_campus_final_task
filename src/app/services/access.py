"""Project access rules: the single place that decides who may do what with a project.

Every project and document endpoint checks access through :class:`ProjectAccess`::

    grant = ProjectAccess(session).require(project_id, current_user, Permission.DELETE_DOC)
    project = grant.project

The rules are the permission matrix of task T3.1 (design decisions D5-D7):

=====================  =====  ===========  =========
Permission             Owner  Participant  No access
=====================  =====  ===========  =========
``VIEW``               yes    yes          404
``EDIT``               yes    yes          404
``UPLOAD_DOC``         yes    yes          404
``REPLACE_DOC``        yes    yes          404
``DELETE_DOC``         yes    403 (D6)     404
``MANAGE_MEMBERS``     yes    403          404
``DELETE_PROJECT``     yes    403          404
=====================  =====  ===========  =========

"No access" covers both a project that doesn't exist and a project the user isn't a member
of; both raise :class:`~app.core.errors.ProjectNotFound`, so the existence of a project is
never revealed (D7). A member whose role lacks the permission gets
:class:`~app.core.errors.PermissionDenied`.
"""

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import PermissionDenied, ProjectNotFound
from app.models import Project, ProjectMember, ProjectRole, User

_ID_MIN: Final = -(2**31)
_ID_MAX: Final = 2**31 - 1
"""Range of PostgreSQL ``integer``, the type of the ``projects.id`` and ``users.id`` columns."""


def _fits_id_column(value: int) -> bool:
    return _ID_MIN <= value <= _ID_MAX


class Permission(enum.StrEnum):
    """An action on a project or its documents that is subject to an access check."""

    VIEW = "view"
    """View the project's details and participants, list and download its documents."""
    EDIT = "edit"
    """Edit the project's name and description."""
    DELETE_PROJECT = "delete_project"
    """Delete the project with all its documents."""
    MANAGE_MEMBERS = "manage_members"
    """Invite participants and remove them."""
    UPLOAD_DOC = "upload_doc"
    """Upload new documents."""
    REPLACE_DOC = "replace_doc"
    """Replace the file of an existing document."""
    DELETE_DOC = "delete_doc"
    """Delete a document."""


ROLE_PERMISSIONS: Final[Mapping[ProjectRole, frozenset[Permission]]] = MappingProxyType(
    {
        ProjectRole.OWNER: frozenset(Permission),
        ProjectRole.PARTICIPANT: frozenset(
            {
                Permission.VIEW,
                Permission.EDIT,
                Permission.UPLOAD_DOC,
                Permission.REPLACE_DOC,
            }
        ),
    }
)
"""The permissions granted by each role (read-only)."""


def is_allowed(role: ProjectRole, permission: Permission) -> bool:
    """Whether a member with ``role`` has ``permission`` (pure policy, no database access)."""
    return permission in ROLE_PERMISSIONS[role]


@dataclass(frozen=True, slots=True)
class ProjectGrant:
    """The result of a successful access check: the project and the user's role in it."""

    project: Project
    role: ProjectRole

    def allows(self, permission: Permission) -> bool:
        """Whether the user's role also has ``permission`` in this project."""
        return is_allowed(self.role, permission)


class ProjectAccess:
    """Checks a user's access to projects, using the given database session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def require(self, project_id: int, user: User | int, permission: Permission) -> ProjectGrant:
        """Return the project and the user's role if the user has ``permission`` in it.

        ``user`` is a :class:`~app.models.User` or a user id. The project and the user's
        membership are loaded in a single query.

        Raises:
            ProjectNotFound: the project doesn't exist or the user isn't a member of it.
            PermissionDenied: the user is a member, but their role lacks ``permission``.
        """
        user_id = user.id if isinstance(user, User) else user
        if not (_fits_id_column(project_id) and _fits_id_column(user_id)):
            # No row can have such an id; PostgreSQL would reject the comparison with
            # "integer out of range" instead of finding nothing.
            raise ProjectNotFound()
        # Inner join on the user's own membership: a project the user isn't a member of
        # yields no row, exactly like a project that doesn't exist.
        statement = (
            select(Project, ProjectMember.role)
            .join(
                ProjectMember,
                (ProjectMember.project_id == Project.id) & (ProjectMember.user_id == user_id),
            )
            .where(Project.id == project_id)
        )
        row = self._session.execute(statement).one_or_none()
        if row is None:
            raise ProjectNotFound()
        project, role = row
        if not is_allowed(role, permission):
            raise PermissionDenied()
        return ProjectGrant(project=project, role=role)
