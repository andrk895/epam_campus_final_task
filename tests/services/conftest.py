"""Fixtures for the service tests: sample files, a PostgreSQL session and a temp storage.

The database is ``TEST_DATABASE_URL`` (by default the local ``pm_test``). The tables are created
in a fresh, uniquely named schema that is dropped at the end of the session; every table is
truncated after each test. Storage lives in a pytest temp directory.
"""

import io
import os
import uuid
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session

from app.db import Base, create_session_factory
from app.models import Project, ProjectMember, ProjectRole, User
from app.storage import LocalStorage

TEST_DATABASE_URL: Final = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/pm_test"
)


def _docx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
    return buffer.getvalue()


SAMPLES: Final[dict[str, tuple[str, bytes]]] = {
    "png": ("image/png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 32),
    "jpg": ("image/jpeg", b"\xff\xd8\xff\xe0" + b"\x00" * 32),
    "gif": ("image/gif", b"GIF89a" + b"\x00" * 32),
    "webp": ("image/webp", b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32),
    "pdf": ("application/pdf", b"%PDF-1.7\n" + b"%" * 32),
    "doc": ("application/msword", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        _docx_bytes(),
    ),
}
"""Minimal files with valid signatures: extension -> (content type, bytes)."""


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    schema = f"test_services_{uuid.uuid4().hex[:12]}"
    admin_engine = create_engine(TEST_DATABASE_URL)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(TEST_DATABASE_URL).update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(url)
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with create_session_factory(engine)() as session:
        yield session
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
def make_user(session: Session) -> Callable[[str], User]:
    def factory(login: str) -> User:
        user = User(login=login, password_hash="not-a-real-hash")
        session.add(user)
        session.commit()
        return user

    return factory


@pytest.fixture
def make_project(session: Session) -> Callable[..., Project]:
    def factory(owner: User, *participants: User, name: str = "Project") -> Project:
        project = Project(name=name, owner_id=owner.id)
        project.members.append(ProjectMember(user_id=owner.id, role=ProjectRole.OWNER))
        for participant in participants:
            project.members.append(
                ProjectMember(user_id=participant.id, role=ProjectRole.PARTICIPANT)
            )
        session.add(project)
        session.commit()
        return project

    return factory


@pytest.fixture
def samples() -> dict[str, tuple[str, bytes]]:
    """See :data:`SAMPLES`."""
    return SAMPLES
