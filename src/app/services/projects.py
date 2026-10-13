"""Project use cases: create, list, view, update and delete projects.

Every function takes the current user and checks access through
:class:`~app.services.access.ProjectAccess`, so it raises
:class:`~app.core.errors.ProjectNotFound` or :class:`~app.core.errors.PermissionDenied` as
described there.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import case, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import Project, ProjectMember, ProjectRole, User
from app.services.access import Permission, ProjectAccess

logger = logging.getLogger(__name__)

StoredFileRemover = Callable[[Sequence[str]], None]
"""Deletes stored files by storage key; called only after the database commit succeeded."""


@dataclass(frozen=True, slots=True)
class ProjectView:
    """A project with the current user's role (and, if loaded, its members)."""

    project: Project
    role: ProjectRole
    members: Sequence[ProjectMember] = ()


def _load_members(session: Session, project_id: int) -> Sequence[ProjectMember]:
    """The project's members with their users, the owner first, then by date added."""
    owner_first = case((ProjectMember.role == ProjectRole.OWNER, 0), else_=1)
    statement = (
        select(ProjectMember)
        .options(joinedload(ProjectMember.user))
        .where(ProjectMember.project_id == project_id)
        .order_by(owner_first, ProjectMember.added_at, ProjectMember.user_id)
    )
    return session.scalars(statement).all()


def create_project(session: Session, user: User, name: str, description: str | None) -> ProjectView:
    """Create a project owned by ``user`` (project and owner membership in one transaction)."""
    project = Project(name=name, description=description, owner=user)
    project.members.append(ProjectMember(user=user, role=ProjectRole.OWNER))
    session.add(project)
    session.commit()
    return ProjectView(project, ProjectRole.OWNER, _load_members(session, project.id))


def list_projects(session: Session, user: User) -> list[ProjectView]:
    """Every project ``user`` owns or participates in, with owners and documents preloaded."""
    statement = (
        select(Project, ProjectMember.role)
        .join(
            ProjectMember,
            (ProjectMember.project_id == Project.id) & (ProjectMember.user_id == user.id),
        )
        .options(joinedload(Project.owner), selectinload(Project.documents))
        .order_by(Project.id)
    )
    return [ProjectView(project, role) for project, role in session.execute(statement)]


def get_project(session: Session, user: User, project_id: int) -> ProjectView:
    """The project's details and members, if ``user`` may view it."""
    grant = ProjectAccess(session).require(project_id, user, Permission.VIEW)
    return ProjectView(grant.project, grant.role, _load_members(session, project_id))


def update_project(
    session: Session, user: User, project_id: int, name: str, description: str | None
) -> ProjectView:
    """Replace the project's name and description (owner and participants)."""
    grant = ProjectAccess(session).require(project_id, user, Permission.EDIT)
    project = grant.project
    project.name = name
    project.description = description
    session.commit()
    return ProjectView(project, grant.role, _load_members(session, project_id))


def remove_stored_files(storage_keys: Sequence[str]) -> None:
    """Delete the stored files of a deleted project's documents.

    TODO(storage): there is no storage backend on this branch yet (``app.storage`` is being
    built in parallel). Once it exists, delete each key through the configured
    ``StorageBackend`` here (or pass a remover bound to it to :func:`delete_project`). Until
    then the keys are only logged.
    """
    if storage_keys:
        logger.warning(
            "No storage backend configured; %d stored file(s) not deleted: %s",
            len(storage_keys),
            ", ".join(storage_keys),
        )


def delete_project(
    session: Session,
    user: User,
    project_id: int,
    *,
    remove_files: StoredFileRemover = remove_stored_files,
) -> None:
    """Delete the project with its members and documents (owner only), then its stored files.

    The files are removed only after the database commit succeeded. A failure while removing
    them is logged and does not fail the deletion (the rows are already gone).
    """
    grant = ProjectAccess(session).require(project_id, user, Permission.DELETE_PROJECT)
    project = grant.project
    storage_keys = [document.storage_key for document in project.documents]
    session.delete(project)
    session.commit()
    try:
        remove_files(storage_keys)
    except Exception:
        logger.exception("Failed to delete the stored files of deleted project %d", project_id)
