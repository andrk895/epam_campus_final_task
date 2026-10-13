"""Tests for the project access rules (``app.services.access``) and their domain exceptions.

The expected permission matrix is written out below independently of the implementation, and
every cell (owner / participant / no access x each permission) is checked twice: against the
pure policy (:func:`is_allowed`) and against :meth:`ProjectAccess.require` on real PostgreSQL.

The database tests use ``TEST_DATABASE_URL`` (by default the local ``pm_test``): the tables are
created with ``Base.metadata.create_all`` in a fresh, uniquely named schema that is dropped when
the module is done. The data is created once per module; the access checks only read it.
"""

import contextlib
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final, Literal

import pytest
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError, PermissionDenied, ProjectNotFound
from app.db import Base, create_session_factory
from app.models import Project, ProjectMember, ProjectRole, User
from app.services.access import (
    ROLE_PERMISSIONS,
    Permission,
    ProjectAccess,
    ProjectGrant,
    is_allowed,
)

TEST_DATABASE_URL: Final = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/pm_test"
)

Outcome = Literal["allowed", "403", "404"]

# The permission matrix of task T3.1 (design decisions D5-D7): permission -> outcome for
# (owner, participant, no access).
EXPECTED_MATRIX: Final[dict[Permission, tuple[Outcome, Outcome, Outcome]]] = {
    Permission.VIEW: ("allowed", "allowed", "404"),
    Permission.EDIT: ("allowed", "allowed", "404"),
    Permission.UPLOAD_DOC: ("allowed", "allowed", "404"),
    Permission.REPLACE_DOC: ("allowed", "allowed", "404"),
    Permission.DELETE_DOC: ("allowed", "403", "404"),
    Permission.MANAGE_MEMBERS: ("allowed", "403", "404"),
    Permission.DELETE_PROJECT: ("allowed", "403", "404"),
}

Actor = Literal["owner", "participant", "outsider"]
ACTOR_COLUMN: Final[dict[Actor, int]] = {"owner": 0, "participant": 1, "outsider": 2}
ACTOR_ROLE: Final[dict[Actor, ProjectRole]] = {
    "owner": ProjectRole.OWNER,
    "participant": ProjectRole.PARTICIPANT,
}

MATRIX_CELLS: Final = [
    pytest.param(actor, permission, outcomes[ACTOR_COLUMN[actor]], id=f"{actor}-{permission}")
    for permission, outcomes in EXPECTED_MATRIX.items()
    for actor in ACTOR_COLUMN
]
ALL_PERMISSIONS: Final = [pytest.param(permission, id=str(permission)) for permission in Permission]


# ---------------------------------------------------------------- pure policy


def test_the_expected_matrix_covers_every_permission() -> None:
    assert set(EXPECTED_MATRIX) == set(Permission)
    assert {permission.name for permission in Permission} == {
        "VIEW",
        "EDIT",
        "DELETE_PROJECT",
        "MANAGE_MEMBERS",
        "UPLOAD_DOC",
        "REPLACE_DOC",
        "DELETE_DOC",
    }


def test_every_role_has_a_policy() -> None:
    assert set(ROLE_PERMISSIONS) == set(ProjectRole)


@pytest.mark.parametrize(
    ("actor", "permission", "expected"),
    [cell for cell in MATRIX_CELLS if cell.values[0] != "outsider"],
)
def test_policy_matrix(actor: Actor, permission: Permission, expected: Outcome) -> None:
    assert is_allowed(ACTOR_ROLE[actor], permission) is (expected == "allowed")


def test_role_permissions_are_read_only() -> None:
    with pytest.raises(TypeError):
        ROLE_PERMISSIONS[ProjectRole.PARTICIPANT] = frozenset(Permission)  # type: ignore[index]
    with pytest.raises(AttributeError):
        ROLE_PERMISSIONS[ProjectRole.PARTICIPANT].add(Permission.DELETE_DOC)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("actor", "permission", "expected"),
    [cell for cell in MATRIX_CELLS if cell.values[0] != "outsider"],
)
def test_grant_allows_follows_the_policy(
    actor: Actor, permission: Permission, expected: Outcome
) -> None:
    grant = ProjectGrant(project=Project(name="Apollo"), role=ACTOR_ROLE[actor])

    assert grant.allows(permission) is (expected == "allowed")


# ---------------------------------------------------------------- domain exceptions


def test_domain_exceptions_have_stable_codes_and_safe_details() -> None:
    not_found = ProjectNotFound()
    denied = PermissionDenied()

    assert isinstance(not_found, NotFoundError)
    assert isinstance(not_found, AppError)
    assert isinstance(denied, AppError)
    assert not isinstance(denied, NotFoundError)
    assert not_found.code == "PROJECT_NOT_FOUND"
    assert denied.code == "PERMISSION_DENIED"
    assert not_found.detail == str(not_found) == "Project not found."
    assert denied.detail == str(denied)


def test_domain_exception_detail_can_be_overridden() -> None:
    error = PermissionDenied("Only the owner can delete documents.")

    assert error.detail == str(error) == "Only the owner can delete documents."
    assert error.code == "PERMISSION_DENIED"


# ---------------------------------------------------------------- require() on PostgreSQL


@dataclass(frozen=True)
class World:
    """Ids of the rows shared by the database tests."""

    project_id: int
    """Owned by ``owner``, shared with ``participant``."""
    other_project_id: int
    """Owned by ``outsider``; ``owner`` and ``participant`` are not members."""
    missing_project_id: int
    """No project has this id."""
    user_ids: dict[Actor, int]


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    """An engine whose connections use a fresh schema holding the model tables."""
    schema = f"test_access_{uuid.uuid4().hex}"
    admin_engine = create_engine(TEST_DATABASE_URL)
    with admin_engine.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(TEST_DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin_engine.dispose()


def add_project(session: Session, owner: User, name: str) -> Project:
    """A project with its owner membership, as the project service will create it."""
    project = Project(name=name, owner=owner)
    project.members.append(ProjectMember(user=owner, role=ProjectRole.OWNER))
    session.add(project)
    return project


@pytest.fixture(scope="module")
def world(engine: Engine) -> World:
    with create_session_factory(engine)() as session:
        users = {
            actor: User(login=actor, password_hash="not-a-real-hash") for actor in ACTOR_COLUMN
        }
        session.add_all(users.values())
        project = add_project(session, users["owner"], "Apollo")
        project.members.append(
            ProjectMember(user=users["participant"], role=ProjectRole.PARTICIPANT)
        )
        other_project = add_project(session, users["outsider"], "Gemini")
        session.commit()
        return World(
            project_id=project.id,
            other_project_id=other_project.id,
            missing_project_id=max(project.id, other_project.id) + 1000,
            user_ids={actor: user.id for actor, user in users.items()},
        )


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with create_session_factory(engine)() as session:
        yield session


@pytest.fixture
def access(session: Session) -> ProjectAccess:
    return ProjectAccess(session)


@pytest.mark.parametrize(("actor", "permission", "expected"), MATRIX_CELLS)
def test_require_matrix(
    access: ProjectAccess, world: World, actor: Actor, permission: Permission, expected: Outcome
) -> None:
    user_id = world.user_ids[actor]

    if expected == "allowed":
        grant = access.require(world.project_id, user_id, permission)
        assert grant.project.id == world.project_id
        assert grant.project.name == "Apollo"
        assert grant.role is ACTOR_ROLE[actor]
    elif expected == "403":
        with pytest.raises(PermissionDenied):
            access.require(world.project_id, user_id, permission)
    else:
        with pytest.raises(ProjectNotFound):
            access.require(world.project_id, user_id, permission)


@pytest.mark.parametrize("actor", ["owner", "participant", "outsider"])
@pytest.mark.parametrize("permission", ALL_PERMISSIONS)
def test_require_nonexistent_project_is_not_found(
    access: ProjectAccess, world: World, actor: Actor, permission: Permission
) -> None:
    with pytest.raises(ProjectNotFound):
        access.require(world.missing_project_id, world.user_ids[actor], permission)


@pytest.mark.parametrize("permission", ALL_PERMISSIONS)
def test_membership_of_one_project_gives_no_access_to_another(
    access: ProjectAccess, world: World, permission: Permission
) -> None:
    for actor in ("owner", "participant"):
        with pytest.raises(ProjectNotFound):
            access.require(world.other_project_id, world.user_ids[actor], permission)

    grant = access.require(world.other_project_id, world.user_ids["outsider"], permission)
    assert grant.role is ProjectRole.OWNER


def test_no_access_is_indistinguishable_from_a_missing_project(
    access: ProjectAccess, world: World
) -> None:
    outsider_id = world.user_ids["outsider"]
    with pytest.raises(ProjectNotFound) as not_member:
        access.require(world.project_id, outsider_id, Permission.VIEW)
    with pytest.raises(ProjectNotFound) as missing:
        access.require(world.missing_project_id, outsider_id, Permission.VIEW)

    assert type(not_member.value) is type(missing.value)
    assert not_member.value.code == missing.value.code
    assert not_member.value.detail == missing.value.detail
    assert not_member.value.args == missing.value.args


def test_require_accepts_a_user_object(
    session: Session, access: ProjectAccess, world: World
) -> None:
    participant = session.get_one(User, world.user_ids["participant"])

    grant = access.require(world.project_id, participant, Permission.UPLOAD_DOC)

    assert grant.role is ProjectRole.PARTICIPANT
    with pytest.raises(PermissionDenied):
        access.require(world.project_id, participant, Permission.DELETE_DOC)


def test_require_returns_the_session_project(
    session: Session, access: ProjectAccess, world: World
) -> None:
    grant = access.require(world.project_id, world.user_ids["owner"], Permission.EDIT)

    assert grant.project is session.get(Project, world.project_id)


# Ids outside PostgreSQL's ``integer`` range must not make the query fail.
UNUSED_IDS: Final = [0, -1, 2**31 - 1, 2**31, -(2**31) - 1, 2**63, 2**70]


@pytest.mark.parametrize("project_id", UNUSED_IDS)
def test_require_unused_or_out_of_range_project_id_is_not_found(
    access: ProjectAccess, world: World, project_id: int
) -> None:
    with pytest.raises(ProjectNotFound):
        access.require(project_id, world.user_ids["owner"], Permission.VIEW)


@pytest.mark.parametrize("user_id", UNUSED_IDS)
def test_require_unused_or_out_of_range_user_id_is_not_found(
    access: ProjectAccess, world: World, user_id: int
) -> None:
    with pytest.raises(ProjectNotFound):
        access.require(world.project_id, user_id, Permission.VIEW)


@pytest.mark.parametrize(
    ("actor", "permission"),
    [
        ("owner", Permission.DELETE_PROJECT),
        ("participant", Permission.VIEW),
        ("participant", Permission.DELETE_PROJECT),
        ("outsider", Permission.VIEW),
    ],
)
def test_require_uses_a_single_query(
    engine: Engine, access: ProjectAccess, world: World, actor: Actor, permission: Permission
) -> None:
    statements: list[str] = []

    def record(*args: Any) -> None:
        statements.append(args[2])

    event.listen(engine, "before_cursor_execute", record)
    try:
        with contextlib.suppress(ProjectNotFound, PermissionDenied):
            access.require(world.project_id, world.user_ids[actor], permission)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert len(statements) == 1, statements
