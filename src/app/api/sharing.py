"""Sharing endpoints: invite a participant (T4.1) and remove one (T4.2, D10)."""

from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUserDep, DbSessionDep
from app.schemas.errors import ErrorResponse
from app.schemas.sharing import Membership
from app.services.sharing import SharingService

router = APIRouter(prefix="/projects", tags=["sharing"])

_COMMON: dict[int | str, dict[str, Any]] = {
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": "Only the project owner can manage participants",
    },
}


@router.post(
    "/{project_id}/invite",
    status_code=status.HTTP_201_CREATED,
    summary="Invite a user to a project",
    responses={
        **_COMMON,
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "You tried to invite yourself",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The project is not accessible, or no user has this login",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The user is already a member",
        },
    },
)
def invite(
    project_id: int,
    login: Annotated[str, Query(alias="user", description="Login of the user to invite.")],
    user: CurrentUserDep,
    session: DbSessionDep,
) -> Membership:
    """Add a registered user (by login, case-insensitive) as a participant (owner only)."""
    membership = SharingService(session).invite(project_id, user, login)
    return Membership(
        project_id=membership.project_id,
        user_id=membership.user_id,
        login=membership.user.login,
        role=membership.role,
        added_at=membership.added_at,
    )


@router.delete(
    "/{project_id}/participants/{login}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a participant from a project",
    responses={
        **_COMMON,
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The owner can't be removed",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The project is not accessible, or the user is not a member",
        },
    },
)
def remove_participant(
    project_id: int, login: str, user: CurrentUserDep, session: DbSessionDep
) -> Response:
    """Remove a participant; they lose access immediately (owner only)."""
    SharingService(session).remove_participant(project_id, user, login)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
