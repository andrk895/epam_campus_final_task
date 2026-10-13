"""Domain exceptions shared by the services.

Services raise these exceptions and never ``HTTPException``: they know nothing about HTTP. The
API layer maps each class to a status code and an error response (task T6.1); the intended
mapping is noted on each class. Every exception has a stable machine-readable ``code`` and a
human-readable ``detail`` that is safe to show to the client.
"""

from typing import ClassVar


class AppError(Exception):
    """Base class of all domain exceptions."""

    code: ClassVar[str] = "APP_ERROR"
    """Stable, machine-readable error code (e.g. ``"PROJECT_NOT_FOUND"``)."""
    default_detail: ClassVar[str] = "Application error."

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail if detail is not None else self.default_detail
        super().__init__(self.detail)


class NotFoundError(AppError):
    """The requested resource doesn't exist or the user can't access it (``404``)."""

    code = "NOT_FOUND"
    default_detail = "Resource not found."


class ProjectNotFound(NotFoundError):  # noqa: N818 (name given by the task list)
    """The project doesn't exist, **or** the user isn't a member of it (``404``, D7).

    Both cases raise the same exception with the same detail, so a response never reveals
    whether a project the user can't access exists.
    """

    code = "PROJECT_NOT_FOUND"
    default_detail = "Project not found."


class PermissionDenied(AppError):  # noqa: N818 (name given by the task list)
    """The user is a member of the project but their role lacks the permission (``403``, D7)."""

    code = "PERMISSION_DENIED"
    default_detail = "You do not have permission to perform this action."


# ---------------------------------------------------------------- sharing and documents
# Each class below carries its intended HTTP status as ``status_code``, so an exception handler
# can map it without a separate table.


class DocumentNotFound(NotFoundError):  # noqa: N818 (name given by the task list)
    """The document doesn't exist, **or** the user can't access its project (``404``, D7)."""

    code = "DOCUMENT_NOT_FOUND"
    default_detail = "Document not found."
    status_code: ClassVar[int] = 404


class UserNotFound(NotFoundError):  # noqa: N818 (name given by the task list)
    """No user has the given login (``404``)."""

    code = "USER_NOT_FOUND"
    default_detail = "User not found."
    status_code: ClassVar[int] = 404


class AlreadyMember(AppError):  # noqa: N818 (name given by the task list)
    """The invited user is already a member of the project (``409``)."""

    code = "ALREADY_MEMBER"
    default_detail = "The user is already a member of this project."
    status_code: ClassVar[int] = 409


class CannotInviteSelf(AppError):  # noqa: N818 (name given by the task list)
    """The owner tried to invite themselves (``400``)."""

    code = "CANNOT_INVITE_SELF"
    default_detail = "You cannot invite yourself."
    status_code: ClassVar[int] = 400


class CannotRemoveOwner(AppError):  # noqa: N818 (name given by the task list)
    """The project owner can't be removed from the project (``400``)."""

    code = "CANNOT_REMOVE_OWNER"
    default_detail = "The project owner cannot be removed."
    status_code: ClassVar[int] = 400


class NotAMember(NotFoundError):  # noqa: N818 (reads better at call sites)
    """The user to remove is not a participant of the project (``404``)."""

    code = "PARTICIPANT_NOT_FOUND"
    default_detail = "The user is not a participant of this project."
    status_code: ClassVar[int] = 404


class FileTooLarge(AppError):  # noqa: N818 (name given by the task list)
    """An uploaded file exceeds the configured maximum size (``413``)."""

    code = "FILE_TOO_LARGE"
    default_detail = "The file is too large."
    status_code: ClassVar[int] = 413


class UnsupportedFileType(AppError):  # noqa: N818 (name given by the task list)
    """An uploaded file's type is not allowed, or its content doesn't match it (``415``)."""

    code = "UNSUPPORTED_FILE_TYPE"
    default_detail = "The file type is not supported."
    status_code: ClassVar[int] = 415


class NoFilesUploaded(AppError):  # noqa: N818 (reads better at call sites)
    """An upload request contained no files (``400``)."""

    code = "NO_FILES"
    default_detail = "No files were uploaded."
    status_code: ClassVar[int] = 400
