"""Document storage backends (design decision D9).

Services depend on the :class:`StorageBackend` protocol only. The concrete backend is chosen by
``Settings.storage_backend`` and injected into endpoints with :data:`StorageDep`.
"""

from app.storage.base import InvalidStorageKey, StorageBackend, new_storage_key
from app.storage.dependencies import StorageDep, build_storage, get_storage
from app.storage.local import LocalStorage

__all__ = [
    "InvalidStorageKey",
    "LocalStorage",
    "StorageBackend",
    "StorageDep",
    "build_storage",
    "get_storage",
    "new_storage_key",
]
