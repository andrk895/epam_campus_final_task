"""The ``Document`` model (table ``documents``)."""

from datetime import datetime
from typing import TYPE_CHECKING, Final

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User

FILENAME_MAX_LENGTH: Final = 255
CONTENT_TYPE_MAX_LENGTH: Final = 255
STORAGE_KEY_MAX_LENGTH: Final = 255

STORAGE_KEY_UNIQUE_CONSTRAINT: Final = "uq_documents_storage_key"


class Document(Base):
    """Metadata of a file attached to a project; the bytes live in the storage backend.

    ``filename`` is the original (user-supplied) name, used only for display and downloads.
    The file is stored under ``storage_key``, a generated key that is unique across all
    documents (design decision D9).

    The row is deleted with its project (``ON DELETE CASCADE``). ``uploaded_by`` uses
    ``ON DELETE RESTRICT``: a user who uploaded a document can't be deleted while the
    document exists (the API has no user deletion), so the uploader is always known.
    """

    __tablename__ = "documents"
    __table_args__ = (CheckConstraint("size >= 0", name="size_not_negative"),)
    # Return server-generated values (``updated_at`` on UPDATE) with RETURNING after each flush.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(FILENAME_MAX_LENGTH))
    content_type: Mapped[str] = mapped_column(String(CONTENT_TYPE_MAX_LENGTH))
    size: Mapped[int] = mapped_column(BigInteger)
    """Size of the file in bytes."""
    storage_key: Mapped[str] = mapped_column(String(STORAGE_KEY_MAX_LENGTH), unique=True)
    uploaded_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="documents")
    uploader: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return (
            f"Document(id={self.id!r}, project_id={self.project_id!r}, filename={self.filename!r})"
        )
