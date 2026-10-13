"""The storage backend interface and storage key helpers."""

import re
import uuid
from typing import BinaryIO, Final, Protocol, runtime_checkable

CHUNK_SIZE: Final = 64 * 1024
"""Size of the chunks in which backends copy file contents (never the whole file at once)."""

_KEY_PATTERN: Final = re.compile(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*")


class InvalidStorageKey(ValueError):  # noqa: N818 (reads better at call sites)
    """A storage key is malformed or would escape the storage root (path traversal)."""


def validate_storage_key(key: str) -> str:
    """Return ``key`` if it is a well-formed key, else raise :class:`InvalidStorageKey`.

    Keys are ``/``-separated segments of ASCII letters, digits, ``_`` and ``-``: no ``..``, no
    absolute paths, no backslashes and no empty segments.
    """
    if not _KEY_PATTERN.fullmatch(key):
        raise InvalidStorageKey(f"invalid storage key: {key!r}")
    return key


def new_storage_key(project_id: int) -> str:
    """Generate a fresh, unique key ``<project_id>/<uuid>`` (never based on a user filename)."""
    return f"{int(project_id)}/{uuid.uuid4().hex}"


@runtime_checkable
class StorageBackend(Protocol):
    """Stores file contents under opaque keys (see :func:`new_storage_key`)."""

    def save(self, stream: BinaryIO, key: str) -> None:
        """Store the contents of ``stream`` (read from its current position) under ``key``.

        An existing file under ``key`` is replaced. Data is copied in chunks.
        """
        ...

    def open(self, key: str) -> BinaryIO:
        """Open the file stored under ``key`` for binary reading; raise ``FileNotFoundError``."""
        ...

    def delete(self, key: str) -> None:
        """Delete the file stored under ``key``; a missing file is not an error."""
        ...

    def exists(self, key: str) -> bool:
        """Whether a file is stored under ``key``."""
        ...
