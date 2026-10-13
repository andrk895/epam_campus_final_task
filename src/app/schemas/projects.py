"""Schemas for projects, their participants and their documents' metadata."""

from datetime import datetime
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import ProjectRole

PROJECT_NAME_MAX_LENGTH: Final = 200
PROJECT_DESCRIPTION_MAX_LENGTH: Final = 5000

ProjectName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=PROJECT_NAME_MAX_LENGTH),
]
ProjectDescription = Annotated[str, StringConstraints(max_length=PROJECT_DESCRIPTION_MAX_LENGTH)]


class ProjectCreate(BaseModel):
    """Body of ``POST /projects``."""

    model_config = ConfigDict(extra="forbid")

    name: ProjectName = Field(description="1-200 characters (surrounding whitespace is removed).")
    description: ProjectDescription | None = Field(default=None, description="Up to 5000 chars.")


class ProjectUpdate(BaseModel):
    """Body of ``PUT /projects/{project_id}/info``: replaces the name and the description.

    Omitting ``description`` (or sending ``null``) clears it.
    """

    model_config = ConfigDict(extra="forbid")

    name: ProjectName = Field(description="1-200 characters (surrounding whitespace is removed).")
    description: ProjectDescription | None = Field(default=None, description="Up to 5000 chars.")


class DocumentMeta(BaseModel):
    """Metadata of a project document (the file itself is downloaded separately)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    content_type: str
    size: int = Field(description="Size in bytes.")
    uploaded_by: int = Field(description="Id of the user who uploaded the current file.")
    created_at: datetime
    updated_at: datetime


class Participant(BaseModel):
    """A member of a project (the owner or a participant)."""

    user_id: int
    login: str
    role: ProjectRole
    added_at: datetime


class ProjectRead(BaseModel):
    """A project's details, with the current user's role in it."""

    id: int
    name: str
    description: str | None
    owner_id: int
    owner_login: str
    role: ProjectRole = Field(description="The current user's role in this project.")
    created_at: datetime
    updated_at: datetime


class ProjectWithDocuments(ProjectRead):
    """An item of ``GET /projects``: the project's details and its documents' metadata."""

    documents: list[DocumentMeta]


class ProjectDetail(ProjectRead):
    """A project's details with its members (``/projects/{project_id}/info``)."""

    participants: list[Participant] = Field(description="All members, the owner first.")
