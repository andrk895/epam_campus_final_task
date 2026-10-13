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


class ConflictError(AppError):
    """The request conflicts with the current state of a resource (``409``)."""

    code = "CONFLICT"
    default_detail = "The request conflicts with the current state of the resource."


class LoginAlreadyExists(ConflictError):  # noqa: N818 (reads better as a domain event)
    """Registration with a login that is already taken, compared case-insensitively (``409``)."""

    code = "LOGIN_ALREADY_EXISTS"
    default_detail = "This login is already taken."


class AuthenticationError(AppError):
    """The request could not be authenticated (``401``)."""

    code = "NOT_AUTHENTICATED"
    default_detail = "Not authenticated."


class InvalidCredentials(AuthenticationError):  # noqa: N818 (reads better as a domain event)
    """Wrong login or password; the detail never says which one (``401``)."""

    code = "INVALID_CREDENTIALS"
    default_detail = "Incorrect login or password."
