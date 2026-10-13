"""Tests for the ORM models (``app.models``) and the constraints they create in PostgreSQL.

The tables are created with ``Base.metadata.create_all`` in a fresh, uniquely named schema of
the test database (``TEST_DATABASE_URL``, by default the local ``pm_test``). Every test starts
with empty tables, and the schema is dropped when the module is done.
"""

import os
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Final

import psycopg
import pytest
from sqlalchemy import Engine, create_engine, delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base, create_session_factory
from app.models import Document, Project, ProjectMember, ProjectRole, User
from app.models.document import STORAGE_KEY_UNIQUE_CONSTRAINT
from app.models.project import MEMBERSHIP_PRIMARY_KEY, SINGLE_OWNER_INDEX
from app.models.user import LOGIN_UNIQUE_INDEX

TEST_DATABASE_URL: Final = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/pm_test"
)

TABLES: Final = ("users", "projects", "project_members", "documents")


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    """An engine whose connections use a fresh schema holding the model tables."""
    schema = f"test_models_{uuid.uuid4().hex}"
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


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session like the app's; all rows are removed after the test."""
    with create_session_factory(engine)() as session:
        yield session
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))


def constraint_name(error: IntegrityError) -> str | None:
    """The name of the PostgreSQL constraint or unique index that ``error`` violated."""
    assert isinstance(error.orig, psycopg.Error)
    return error.orig.diag.constraint_name


def add_user(session: Session, login: str) -> User:
    user = User(login=login, password_hash="not-a-real-hash")
    session.add(user)
    session.flush()
    return user


def add_project(session: Session, owner: User, name: str = "Apollo") -> Project:
    """A project with its owner membership, as the project service will create it."""
    project = Project(name=name, description="Moon landing", owner=owner)
    project.members.append(ProjectMember(user=owner, role=ProjectRole.OWNER))
    session.add(project)
    session.flush()
    return project


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


def test_user_gets_an_id_and_a_timezone_aware_created_at(session: Session) -> None:
    user = add_user(session, "alice")
    session.commit()

    assert isinstance(user.id, int)
    assert isinstance(user.created_at, datetime)
    assert user.created_at.tzinfo is not None


def test_duplicate_login_is_rejected(session: Session) -> None:
    add_user(session, "alice")

    with pytest.raises(IntegrityError) as exc_info:
        add_user(session, "alice")

    assert constraint_name(exc_info.value) == LOGIN_UNIQUE_INDEX


@pytest.mark.parametrize("variant", ["Alice", "ALICE", "aLiCe"])
def test_login_is_unique_case_insensitively(session: Session, variant: str) -> None:
    add_user(session, "alice")

    with pytest.raises(IntegrityError) as exc_info:
        add_user(session, variant)

    assert constraint_name(exc_info.value) == LOGIN_UNIQUE_INDEX


def test_login_case_is_preserved_and_lookups_ignore_case(session: Session) -> None:
    alice = add_user(session, "Alice")
    add_user(session, "bob")
    session.commit()

    found = session.execute(select(User).where(User.login_matches("aLICE"))).scalar_one()

    assert found is alice
    assert found.login == "Alice"


def test_deleting_a_user_deletes_their_memberships(session: Session) -> None:
    owner = add_user(session, "owner")
    participant = add_user(session, "participant")
    project = add_project(session, owner)
    project.members.append(ProjectMember(user=participant, role=ProjectRole.PARTICIPANT))
    session.commit()

    session.execute(delete(User).where(User.id == participant.id))  # bypasses the ORM
    session.commit()
    session.expire_all()

    assert [member.user_id for member in project.members] == [owner.id]


def test_a_user_who_owns_a_project_cannot_be_deleted(session: Session) -> None:
    owner = add_user(session, "owner")
    add_project(session, owner)
    session.commit()

    session.delete(owner)
    with pytest.raises(IntegrityError) as exc_info:
        session.commit()

    assert constraint_name(exc_info.value) == "fk_projects_owner_id_users"


def test_a_user_who_uploaded_a_document_cannot_be_deleted(session: Session) -> None:
    owner = add_user(session, "owner")
    uploader = add_user(session, "uploader")
    project = add_project(session, owner)
    project.members.append(ProjectMember(user=uploader, role=ProjectRole.PARTICIPANT))
    add_document(session, project, uploader)
    session.commit()

    with pytest.raises(IntegrityError) as exc_info:
        session.execute(delete(User).where(User.id == uploader.id))

    assert constraint_name(exc_info.value) == "fk_documents_uploaded_by_users"


# ---------------------------------------------------------------- projects and members


def test_project_relationships_work_both_ways(session: Session) -> None:
    owner = add_user(session, "owner")
    participant = add_user(session, "participant")
    project = add_project(session, owner)
    project.members.append(ProjectMember(user=participant, role=ProjectRole.PARTICIPANT))
    document = add_document(session, project, participant)
    session.commit()
    session.expire_all()

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


def test_project_timestamps_are_set_and_updated_at_changes_on_update(session: Session) -> None:
    project = add_project(session, add_user(session, "owner"))
    session.commit()
    created_at, updated_at = project.created_at, project.updated_at
    assert created_at.tzinfo is not None
    assert updated_at == created_at
    assert project.members[0].added_at.tzinfo is not None

    project.name = "Artemis"
    session.commit()

    assert project.created_at == created_at
    assert project.updated_at > updated_at


def test_role_is_stored_as_its_value(session: Session) -> None:
    add_project(session, add_user(session, "owner"))
    session.commit()

    stored = session.execute(text("SELECT role FROM project_members")).scalar_one()

    assert stored == "owner"


def test_unknown_role_is_rejected_by_the_database(session: Session) -> None:
    owner = add_user(session, "owner")
    participant = add_user(session, "participant")
    project = add_project(session, owner)

    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text(
                "INSERT INTO project_members (project_id, user_id, role) VALUES (:p, :u, 'admin')"
            ),
            {"p": project.id, "u": participant.id},
        )

    assert constraint_name(exc_info.value) == "ck_project_members_project_role"


def test_a_user_can_be_a_member_of_a_project_only_once(session: Session) -> None:
    owner = add_user(session, "owner")
    participant = add_user(session, "participant")
    project = add_project(session, owner)
    session.add(ProjectMember(project=project, user=participant, role=ProjectRole.PARTICIPANT))
    session.commit()

    # A second row for the same pair, inserted without the ORM's identity map noticing.
    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text(
                "INSERT INTO project_members (project_id, user_id, role) "
                "VALUES (:p, :u, 'participant')"
            ),
            {"p": project.id, "u": participant.id},
        )

    assert constraint_name(exc_info.value) == MEMBERSHIP_PRIMARY_KEY


def test_a_project_has_at_most_one_owner_membership(session: Session) -> None:
    project = add_project(session, add_user(session, "owner"))
    second = add_user(session, "second")

    project.members.append(ProjectMember(user=second, role=ProjectRole.OWNER))
    with pytest.raises(IntegrityError) as exc_info:
        session.flush()

    assert constraint_name(exc_info.value) == SINGLE_OWNER_INDEX


def test_deleting_a_project_via_the_orm_deletes_members_and_documents(session: Session) -> None:
    owner = add_user(session, "owner")
    participant = add_user(session, "participant")
    project = add_project(session, owner)
    project.members.append(ProjectMember(user=participant, role=ProjectRole.PARTICIPANT))
    add_document(session, project, owner)
    add_document(session, project, participant)
    other = add_project(session, participant, name="Other")
    add_document(session, other, participant)
    session.commit()

    session.delete(project)
    session.commit()

    assert session.execute(select(Project.name)).scalars().all() == ["Other"]
    assert session.execute(select(ProjectMember.project_id)).scalars().all() == [other.id]
    assert session.execute(select(Document.project_id)).scalars().all() == [other.id]
    assert count(session, User) == 2


def test_deleting_a_project_in_the_database_cascades_to_members_and_documents(
    session: Session,
) -> None:
    owner = add_user(session, "owner")
    project = add_project(session, owner)
    add_document(session, project, owner)
    session.commit()

    session.execute(delete(Project).where(Project.id == project.id))  # bypasses the ORM
    session.commit()

    assert count(session, Project) == 0
    assert count(session, ProjectMember) == 0
    assert count(session, Document) == 0


# ---------------------------------------------------------------- documents


def test_storage_key_is_unique(session: Session) -> None:
    owner = add_user(session, "owner")
    project = add_project(session, owner)
    document = add_document(session, project, owner)

    duplicate = Document(
        project=project,
        filename="other.png",
        content_type="image/png",
        size=1,
        storage_key=document.storage_key,
        uploader=owner,
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError) as exc_info:
        session.flush()

    assert constraint_name(exc_info.value) == STORAGE_KEY_UNIQUE_CONSTRAINT


def test_document_size_cannot_be_negative(session: Session) -> None:
    owner = add_user(session, "owner")
    document = add_document(session, add_project(session, owner), owner)

    document.size = -1
    with pytest.raises(IntegrityError) as exc_info:
        session.flush()

    assert constraint_name(exc_info.value) == "ck_documents_size_not_negative"


def test_document_timestamps_are_set_and_updated_at_changes_on_update(session: Session) -> None:
    owner = add_user(session, "owner")
    document = add_document(session, add_project(session, owner), owner)
    session.commit()
    updated_at = document.updated_at
    assert document.created_at.tzinfo is not None

    document.filename = "plan-v2.pdf"
    session.commit()

    assert document.updated_at > updated_at
