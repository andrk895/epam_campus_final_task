"""``LocalStorage``: stores files in a directory on the local filesystem."""

import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO

from app.storage.base import CHUNK_SIZE, InvalidStorageKey, validate_storage_key


class LocalStorage:
    """A :class:`~app.storage.base.StorageBackend` rooted at ``root``.

    The key ``<project_id>/<uuid>`` maps to the file ``root/<project_id>/<uuid>``. Keys are
    validated and the resolved path must stay inside ``root``, so a key can never address a file
    outside the storage directory. Files are written to a temporary file first and then renamed,
    so a reader never sees a partially written file.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        validate_storage_key(key)
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise InvalidStorageKey(f"storage key escapes the storage root: {key!r}")
        return path

    def save(self, stream: BinaryIO, key: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".upload-")
        try:
            with os.fdopen(fd, "wb") as target:
                shutil.copyfileobj(stream, target, CHUNK_SIZE)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()
