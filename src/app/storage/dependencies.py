"""Selecting the storage backend from the settings, and the FastAPI dependency."""

from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, SettingsDep
from app.storage.base import StorageBackend
from app.storage.local import LocalStorage


def build_storage(settings: Settings) -> StorageBackend:
    """Create the backend selected by ``settings.storage_backend``."""
    if settings.storage_backend == "local":
        return LocalStorage(settings.storage_dir)
    raise ValueError(f"unknown storage backend: {settings.storage_backend!r}")  # pragma: no cover


def get_storage(settings: SettingsDep) -> StorageBackend:
    """FastAPI dependency returning the configured storage backend.

    Tests can replace it with ``app.dependency_overrides[get_storage]``.
    """
    return build_storage(settings)


StorageDep = Annotated[StorageBackend, Depends(get_storage)]
"""Annotated type for endpoint parameters that need the storage backend."""
