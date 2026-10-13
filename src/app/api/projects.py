"""Project endpoints: create, list, view, update and delete projects."""

from typing import Any

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUserDep, DbSessionDep
from app.schemas.errors import ErrorResponse
from app.schemas.projects import (
    DocumentMeta,
    Participant,
    ProjectCreate,
    ProjectDetail,
    ProjectUpdate,
    ProjectWithDocuments,
)
from app.services import projects
from app.services.projects import ProjectView
from app.storage import StorageDep

router = APIRouter(prefix="/projects", tags=["projects"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "The project doesn't exist or you are not a member of it",
    }
}
_FORBIDDEN: dict[int | str, dict[str, Any]] = {
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": "Your role in the project doesn't allow this",
    }
}


def _read_fields(view: ProjectView) -> dict[str, object]:
    project = view.project
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "owner_id": project.owner_id,
        "owner_login": project.owner.login,
        "role": view.role,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def _detail(view: ProjectView) -> ProjectDetail:
    participants = [
        Participant(
            user_id=member.user_id,
            login=member.user.login,
            role=member.role,
            added_at=member.added_at,
        )
        for member in view.members
    ]
    return ProjectDetail.model_validate({**_read_fields(view), "participants": participants})


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a project")
def create_project(
    body: ProjectCreate, user: CurrentUserDep, session: DbSessionDep
) -> ProjectDetail:
    """Create a project. The current user becomes its owner."""
    return _detail(projects.create_project(session, user, body.name, body.description))


@router.get("", summary="List my projects")
def list_projects(user: CurrentUserDep, session: DbSessionDep) -> list[ProjectWithDocuments]:
    """Every project you own or participate in, with your role and its documents' metadata."""
    return [
        ProjectWithDocuments.model_validate(
            {
                **_read_fields(view),
                "documents": [DocumentMeta.model_validate(d) for d in view.project.documents],
            }
        )
        for view in projects.list_projects(session, user)
    ]


@router.get("/{project_id}/info", summary="Get project details", responses=_NOT_FOUND)
def get_project_info(project_id: int, user: CurrentUserDep, session: DbSessionDep) -> ProjectDetail:
    """The project's details and its members (owner and participants)."""
    return _detail(projects.get_project(session, user, project_id))


@router.put("/{project_id}/info", summary="Update project details", responses=_NOT_FOUND)
def update_project_info(
    project_id: int, body: ProjectUpdate, user: CurrentUserDep, session: DbSessionDep
) -> ProjectDetail:
    """Replace the project's name and description (owner and participants)."""
    view = projects.update_project(session, user, project_id, body.name, body.description)
    return _detail(view)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project",
    responses={**_NOT_FOUND, **_FORBIDDEN},
)
def delete_project(
    project_id: int, user: CurrentUserDep, session: DbSessionDep, storage: StorageDep
) -> Response:
    """Delete the project with all its documents (owner only)."""
    projects.delete_project(session, user, project_id, storage=storage)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
