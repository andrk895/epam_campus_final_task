"""Tests for the ORM models (``app.models``) and the constraints they create in PostgreSQL.

Unlike most tests, these don't run inside a rolled-back transaction: they commit for real (so
that, e.g., ``now()`` advances between transactions and ``updated_at`` changes). The tables are
created with ``Base.metadata.create_all`` in a fresh schema of the test database for this module
(see ``tests/database.py``); every test starts with empty tables, and the schema is dropped when
the module is done.
"""

import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Final

import psycopg
import pytest
from sqlalchemy import Engine, delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base, create_session_factory
from app.models import Document, Project, ProjectMember, ProjectRole, User
from app.models.document import STORAGE_KEY_UNIQUE_CONSTRAINT
from app.models.project import MEMBERSHIP_PRIMARY_KEY, SINGLE_OWNER_INDEX
from app.models.user import LOGIN_UNIQUE_INDEX
from tests.database import temporary_schema, unique_schema_name
from tests.factories import ProjectFactory, UserFactory

TABLES: Final = ("users", "projects", "project_members", "documents")


@pytest.fixture(scope="module")
def engine(test_database_url: str) -> Iterator[Engine]:
    """An engine whose connections use a fresh schema holding the model tables."""
    with temporary_schema(test_database_url, unique_schema_name("test_models")) as engine:
        yield engine


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A session like the app's that really commits; all rows are removed after the test.

    Overrides the shared, rolled-back ``db_session`` (also for the ``create_user`` and
    ``create_project`` factories used here).
    """
    with create_session_factory(engine)() as session:
        yield session
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))


def constraint_name(error: IntegrityError) -> str | None:
    """The name of the PostgreSQL constraint or unique index that ``error`` violated."""
    assert isinstance(error.orig, psycopg.Error)
    return error.orig.diag.constraint_name


def add_document(session: Session, project: Project, uploader: User) -> Document:
    document = Document(
        project=project,
        filename="plan.pdf",
        content_type="application/pdf",
        size=1234,
        storage_key=f"{project.id}/{uuid.uuid4()}",
        uploader=uploader,
    )
    session.add(document)
    session.flush()
    return document


def count(session: Session, model: type[Base]) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


# ---------------------------------------------------------------- schema


def test_all_models_are_registered_on_the_metadata() -> None:
    assert set(Base.metadata.tables) == set(TABLES)


def test_schema_has_the_expected_keys_and_indexes(engine: Engine) -> None:
    inspector = inspect(engine)

    users_indexes = {index["name"]: index for index in inspector.get_indexes("users")}
    assert users_indexes[LOGIN_UNIQUE_INDEX]["unique"]
    assert users_indexes[LOGIN_UNIQUE_INDEX]["expressions"] == ["lower(login::text)"]

    # Exactly one CHECK on the role (a duplicate would break the Alembic migration).
    [role_check] = inspector.get_check_constraints("project_members")
    assert role_check["name"] == "ck_project_members_project_role"
    assert "'owner'" in role_check["sqltext"]
    assert "'participant'" in role_check["sqltext"]

    members_pk = inspector.get_pk_constraint("project_members")
    assert members_pk["name"] == MEMBERSHIP_PRIMARY_KEY
    assert members_pk["constrained_columns"] == ["project_id", "user_id"]

    def indexed_columns(table: str) -> set[str]:
        return {
            column
            for index in inspector.get_indexes(table)
            for column in index["column_names"]
            if column is not None
        }

    assert "owner_id" in indexed_columns("projects")
    assert {"user_id", "project_id"} <= indexed_columns("project_members")
    assert {"project_id", "uploaded_by"} <= indexed_columns("documents")
    assert [c["column_names"] for c in inspector.get_unique_constraints("documents")] == [
        ["storage_key"]
    ]

    foreign_keys = {
        (table, fk["constrained_columns"][0]): (fk["referred_table"], fk["options"].get("ondelete"))
        for table in TABLES
        for fk in inspector.get_foreign_keys(table)
    }
    assert foreign_keys == {
        ("projects", "owner_id"): ("users", "RESTRICT"),
        ("project_members", "project_id"): ("projects", "CASCADE"),
        ("project_members", "user_id"): ("users", "CASCADE"),
        ("documents", "project_id"): ("projects", "CASCADE"),
        ("documents", "uploaded_by"): ("users", "RESTRICT"),
    }


# ---------------------------------------------------------------- users


def test_user_gets_an_id_and_a_timezone_aware_created_at(
    db_session: Session,
    create_user: UserFactory,
) -> None:
    user = create_user("alice")
    db_session.commit()

    assert isinstance(user.id, int)
    assert isinstance(user.created_at, datetime)
    assert user.created_at.tzinfo is not None


def test_duplicate_login_is_rejected(create_user: UserFactory) -> None:
    create_user("alice")

    with pytest.raises(IntegrityError) as exc_info:
        create_user("alice")

    assert constraint_name(exc_info.value) == LOGIN_UNIQUE_INDEX


@pytest.mark.parametrize("variant", ["Alice", "ALICE", "aLiCe"])
def test_login_is_unique_case_insensitively(variant: str, create_user: UserFactory) -> None:
    create_user("alice")

    with pytest.raises(IntegrityError) as exc_info:
        create_user(variant)

    assert constraint_name(exc_info.value) == LOGIN_UNIQUE_INDEX


def test_login_case_is_preserved_and_lookups_ignore_case(
    db_session: Session,
    create_user: UserFactory,
) -> None:
    alice = create_user("Alice")
    create_user("bob")
    db_session.commit()

    found = db_session.execute(select(User).where(User.login_matches("aLICE"))).scalar_one()

    assert found is alice
    assert found.login == "Alice"


def test_deleting_a_user_deletes_their_memberships(
    db_session: Session,
    create_user: UserFactory,
    create_project: ProjectFactory,
) -> None:
    owner = create_user("owner")
    participant = create_user("participant")
    project = create_project(owner)
    project.members.append(ProjectMember(user=participant, role=ProjectRole.PARTICIPANT))
    db_session.commit()

    db_session.execute(delete(User).where(User.id == participant.id))  # bypasses the ORM
    db_session.commit()
    db_session.expire_all()

    assert [member.user_id for member in project.members] == [owner.id]


def test_a_user_who_owns_a_project_cannot_be_deleted(
    db_session: Session,
    create_user: UserFactory,
    create_project: ProjectFactory,
) -> None:
    owner = create_user("owner")
    create_project(owner)
    db_session.commit()

    db_session.delete(owner)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()

    assert constraint_name(exc_info.value) == "fk_projects_owner_id_users"


def test_a_user_who_uploaded_a_document_cannot_be_deleted(
    db_session: Session,
    create_user: UserFactory,
    create_project: ProjectFactory,
) -> None:
    owner = create_user("owner")
    uploader = create_user("uploader")
    project = create_project(owner)
    project.members.append(ProjectMember(user=uploader, role=ProjectRole.PARTICIPANT))
    add_document(db_session, project, uploader)
    db_session.commit()

    with pytest.raises(IntegrityError) as exc_info:
        db_session.execute(delete(User).where(User.id == uploader.id))

    assert constraint_name(exc_info.value) == "fk_documents_uploaded_by_users"


# ---------------------------------------------------------------- projects and members


def test_project_relationships_work_both_ways(
    db_session: Session,
    create_user: UserFactory,
    create_project: ProjectFactory,
) -> None:
    owner = create_user("owner")
    participant = create_user("participant")
    project = create_project(owner)
    project.members.append(ProjectMember(user=participant, role=ProjectRole.PARTICIPANT))
    document = add_document(db_session, project, participant)
    db_session.commit()
    db_session.expire_all()

    assert project.owner is owner
    assert owner.owned_projects == [project]
    assert {(m.user.login, m.role) for m in project.members} == {
        ("owner", ProjectRole.OWNER),
        ("participant", ProjectRole.PARTICIPANT),
    }
    assert [m.project for m in participant.memberships] == [project]
    assert project.documents == [document]
    assert document.project is project
    assert document.uploader is participant


def test_project_timestamps_are_set_and_updated_at_changes_on_update(
    db_session: Session,
    create_user: UserFactory,
    create_project: ProjectFactory,
) -> None:
    project = create_project(create_user("owner"))
    db_session.commit()
    created_at, updated_at = project.created_at, project.updated_at
    assert created_at.tzinfo is not None
    assert updated_at == created_at
    assert project.members[0].added_at.tzinfo is not None

    project.name = "Artemis"
    db_session.commit()

    assert project.created_at == created_at
    assert project.updated_at > updated_at


def test_role_is_stored_as_its_value(
    db_session: Session,
    create_user: UserFactory,
    create_project: ProjectFactory,
) -> None:
    create_project(create_user("owner"))
    db_session.commit()

    stored = db_session.execute(text("SELECT role FROM project_members")).scalar_one()

    assert stored == "owner"


def test_unknown_role_is_rejected_by_the_database(
    db_session: Session,
    create_user: UserFactory,
    create_project: ProjectFactory,
) -> None:
    owner = create_user("owner")
    participant = create_user("participant")
    project = create_project(owner)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.execute(
            text(
                "INSERT INTO project_members (project_id, user_id, role) VALUES (:p, :u, 'admin')"
            ),
            {"p": project.id, "u": participant.id},
        )

    assert constraint_name(exc_info.value) == "ck_project_members_project_role"


def test_a_user_can_be_a_member_of_a_project_only_once(
    db_session: Session,
    create_user: UserFactory,
    create_project: ProjectFactory,
) -> None:
    owner = create_user("owner")
    participant = create_user("participant")
    project = create_project(owner)
    db_session.add(ProjectMember(project=project, user=participant, role=ProjectRole.PARTICIPANT))
    db_session.commit()

    # A second row for the same pair, inserted without the ORM's identity map noticing.
    with pytest.raises(IntegrityError) as exc_info:
        db_session.execute(
            text(
                "INSERT INTO project_members (project_id, user_id, role) "
                "VALUES (:p, :u, 'participant')"
            ),
            {"p": project.id, "u": participant.id},
        )

    assert constraint_name(exc_info.value) == MEMBERSHIP_PRIMARY_KEY


def test_a_project_has_at_most_one_owner_membership(
    db_session: Session,
    create_user: UserFactory,
    create_project: ProjectFactory,
) -> None:
    project = create_project(create_user("owner"))
    second = create_user("second")

    project.members.append(ProjectMember(user=second, role=ProjectRole.OWNER))
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    assert constraint_name(exc_info.value) == SINGLE_OWNER_INDEX


def test_deleting_a_project_via_the_orm_deletes_members_and_documents(
    db_session: Session,
    create_user: UserFactory,
    create_project: ProjectFactory,
) -> None:
    owner = create_user("owner")
    participant = create_user("participant")
    project = create_project(owner)
    project.members.append(ProjectMember(user=participant, role=ProjectRole.PARTICIPANT))
    add_document(db_session, project, owner)
    add_document(db_session, project, participant)
    other = create_project(participant, name="Other")
    add_document(db_session, other, participant)
    db_session.commit()

    db_session.delete(project)
    db_session.commit()

    assert db_session.execute(select(Project.name)).scalars().all() == ["Other"]
    assert db_session.execute(select(ProjectMember.project_id)).scalars().all() == [other.id]
    assert db_session.execute(select(Document.project_id)).scalars().all() == [other.id]
    assert count(db_session, User) == 2


def test_deleting_a_project_in_the_database_cascades_to_members_and_documents(
    db_session: Session,
    create_user: UserFactory,
    create_project: ProjectFactory,
) -> None:
    owner = create_user("owner")
    project = create_project(owner)
    add_document(db_session, project, owner)
    db_session.commit()

    db_session.execute(delete(Project).where(Project.id == project.id))  # bypasses the ORM
    db_session.commit()

    assert count(db_session, Project) == 0
    assert count(db_session, ProjectMember) == 0
    assert count(db_session, Document) == 0


# ---------------------------------------------------------------- documents


def test_storage_key_is_unique(
    db_session: Session,
    create_user: UserFactory,
    create_project: ProjectFactory,
) -> None:
    owner = create_user("owner")
    project = create_project(owner)
    document = add_document(db_session, project, owner)

    duplicate = Document(
        project=project,
        filename="other.png",
        content_type="image/png",
        size=1,
        storage_key=document.storage_key,
        uploader=owner,
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    assert constraint_name(exc_info.value) == STORAGE_KEY_UNIQUE_CONSTRAINT


def test_document_size_cannot_be_negative(
    db_session: Session,
    create_user: UserFactory,
    create_project: ProjectFactory,
) -> None:
    owner = create_user("owner")
    document = add_document(db_session, create_project(owner), owner)

    document.size = -1
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    assert constraint_name(exc_info.value) == "ck_documents_size_not_negative"


def test_document_timestamps_are_set_and_updated_at_changes_on_update(
    db_session: Session,
    create_user: UserFactory,
    create_project: ProjectFactory,
) -> None:
    owner = create_user("owner")
    document = add_document(db_session, create_project(owner), owner)
    db_session.commit()
    updated_at = document.updated_at
    assert document.created_at.tzinfo is not None

    document.filename = "plan-v2.pdf"
    db_session.commit()

    assert document.updated_at > updated_at
