"""Tests for the sharing service (tasks T4.1, T4.2) against PostgreSQL."""

from collections.abc import Callable

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import (
    AlreadyMember,
    CannotInviteSelf,
    CannotRemoveOwner,
    NotAMember,
    PermissionDenied,
    ProjectNotFound,
    UserNotFound,
)
from app.models import Project, ProjectMember, ProjectRole, User
from app.services.access import Permission, ProjectAccess
from app.services.sharing import SharingService

MakeUser = Callable[[str], User]
MakeProject = Callable[..., Project]


@pytest.fixture
def users(make_user: MakeUser) -> dict[str, User]:
    return {name: make_user(name) for name in ("owner", "bob", "carol", "outsider")}


@pytest.fixture
def project(make_project: MakeProject, users: dict[str, User]) -> Project:
    return make_project(users["owner"], users["carol"])


def roles(session: Session, project: Project) -> dict[int, ProjectRole]:
    rows = session.execute(
        select(ProjectMember.user_id, ProjectMember.role).where(
            ProjectMember.project_id == project.id
        )
    )
    return dict(rows.all())


def test_invite_adds_a_participant(
    session: Session, project: Project, users: dict[str, User]
) -> None:
    membership = SharingService(session).invite(project.id, users["owner"], "bob")
    assert membership.user_id == users["bob"].id
    assert membership.role == ProjectRole.PARTICIPANT
    assert membership.user.login == "bob"
    assert membership.added_at is not None
    assert roles(session, project)[users["bob"].id] == ProjectRole.PARTICIPANT
    # The invited user can now access the project.
    ProjectAccess(session).require(project.id, users["bob"], Permission.VIEW)


def test_invite_login_is_case_insensitive(
    session: Session, project: Project, users: dict[str, User]
) -> None:
    SharingService(session).invite(project.id, users["owner"], "BoB")
    assert users["bob"].id in roles(session, project)


@pytest.mark.parametrize("login", ["nobody", "", "x" * 300])
def test_invite_unknown_user(
    session: Session, project: Project, users: dict[str, User], login: str
) -> None:
    with pytest.raises(UserNotFound):
        SharingService(session).invite(project.id, users["owner"], login)


def test_invite_existing_member(session: Session, project: Project, users: dict[str, User]) -> None:
    with pytest.raises(AlreadyMember):
        SharingService(session).invite(project.id, users["owner"], "carol")


def test_invite_self(session: Session, project: Project, users: dict[str, User]) -> None:
    with pytest.raises(CannotInviteSelf):
        SharingService(session).invite(project.id, users["owner"], "OWNER")


def test_participant_cannot_invite(
    session: Session, project: Project, users: dict[str, User]
) -> None:
    with pytest.raises(PermissionDenied):
        SharingService(session).invite(project.id, users["carol"], "bob")


@pytest.mark.parametrize("project_id", [None, 999_999])
def test_outsider_or_missing_project_cannot_invite(
    session: Session, project: Project, users: dict[str, User], project_id: int | None
) -> None:
    with pytest.raises(ProjectNotFound):
        SharingService(session).invite(project_id or project.id, users["outsider"], "bob")


def test_remove_participant(session: Session, project: Project, users: dict[str, User]) -> None:
    SharingService(session).remove_participant(project.id, users["owner"], "Carol")
    assert users["carol"].id not in roles(session, project)
    with pytest.raises(ProjectNotFound):
        ProjectAccess(session).require(project.id, users["carol"], Permission.VIEW)


def test_owner_cannot_be_removed(
    session: Session, project: Project, users: dict[str, User]
) -> None:
    with pytest.raises(CannotRemoveOwner):
        SharingService(session).remove_participant(project.id, users["owner"], "owner")


def test_remove_non_member(session: Session, project: Project, users: dict[str, User]) -> None:
    with pytest.raises(NotAMember):
        SharingService(session).remove_participant(project.id, users["owner"], "bob")
    with pytest.raises(UserNotFound):
        SharingService(session).remove_participant(project.id, users["owner"], "ghost")


def test_participant_cannot_remove(
    session: Session, project: Project, users: dict[str, User]
) -> None:
    with pytest.raises(PermissionDenied):
        SharingService(session).remove_participant(project.id, users["carol"], "carol")


def test_outsider_cannot_remove(session: Session, project: Project, users: dict[str, User]) -> None:
    with pytest.raises(ProjectNotFound):
        SharingService(session).remove_participant(project.id, users["outsider"], "carol")
