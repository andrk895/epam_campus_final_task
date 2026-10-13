"""Sharing use cases (tasks T4.1, T4.2): invite a participant and remove one.

Both are owner-only (``Permission.MANAGE_MEMBERS``): a non-member gets
:class:`~app.core.errors.ProjectNotFound` (``404``), a participant
:class:`~app.core.errors.PermissionDenied` (``403``).
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import (
    AlreadyMember,
    CannotInviteSelf,
    CannotRemoveOwner,
    NotAMember,
    UserNotFound,
)
from app.models import ProjectMember, ProjectRole, User
from app.models.user import LOGIN_MAX_LENGTH
from app.services.access import Permission, ProjectAccess


class SharingService:
    """Project membership operations on behalf of a user."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._access = ProjectAccess(session)

    def _find_user(self, login: str) -> User:
        if not login or len(login) > LOGIN_MAX_LENGTH:
            raise UserNotFound()
        user = self._session.scalars(select(User).where(User.login_matches(login))).one_or_none()
        if user is None:
            raise UserNotFound()
        return user

    def invite(self, project_id: int, user: User, login: str) -> ProjectMember:
        """Add the user with ``login`` (case-insensitive) as a participant of the project.

        Raises:
            ProjectNotFound / PermissionDenied: see the module docstring.
            UserNotFound: no user has this login.
            CannotInviteSelf: the owner invited themselves.
            AlreadyMember: the user is already a member.
        """
        self._access.require(project_id, user, Permission.MANAGE_MEMBERS)
        invitee = self._find_user(login)
        if invitee.id == user.id:
            raise CannotInviteSelf()
        if self._session.get(ProjectMember, (project_id, invitee.id)) is not None:
            raise AlreadyMember()
        membership = ProjectMember(
            project_id=project_id, user_id=invitee.id, role=ProjectRole.PARTICIPANT
        )
        membership.user = invitee
        self._session.add(membership)
        try:
            self._session.commit()
        except IntegrityError:
            # A concurrent request added the same membership first.
            self._session.rollback()
            raise AlreadyMember() from None
        return membership

    def remove_participant(self, project_id: int, user: User, login: str) -> None:
        """Remove the participant with ``login`` from the project.

        Raises:
            ProjectNotFound / PermissionDenied: see the module docstring.
            UserNotFound: no user has this login.
            NotAMember: the user isn't a member of the project.
            CannotRemoveOwner: the user is the project's owner.
        """
        self._access.require(project_id, user, Permission.MANAGE_MEMBERS)
        target = self._find_user(login)
        membership = self._session.get(ProjectMember, (project_id, target.id))
        if membership is None:
            raise NotAMember()
        if membership.role == ProjectRole.OWNER:
            raise CannotRemoveOwner()
        self._session.delete(membership)
        self._session.commit()
