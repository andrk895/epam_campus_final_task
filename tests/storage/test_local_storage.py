"""Unit tests for the storage abstraction and ``LocalStorage`` (task T5.1), on a temp dir."""

import io
from pathlib import Path

import pytest

from app.core.config import Settings
from app.storage import (
    InvalidStorageKey,
    LocalStorage,
    StorageBackend,
    build_storage,
    new_storage_key,
)
from app.storage.base import CHUNK_SIZE


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "files")


class CountingStream(io.BytesIO):
    """A stream that records the size of every ``read`` call."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.read_sizes: list[int] = []

    def read(self, size: int | None = -1, /) -> bytes:
        self.read_sizes.append(-1 if size is None else size)
        return super().read(size)


def test_local_storage_implements_the_protocol(storage: LocalStorage) -> None:
    assert isinstance(storage, StorageBackend)


def test_new_storage_key_is_project_id_slash_uuid() -> None:
    key = new_storage_key(42)
    project, name = key.split("/")
    assert project == "42"
    assert len(name) == 32
    assert new_storage_key(42) != key


def test_save_open_roundtrip(storage: LocalStorage) -> None:
    key = new_storage_key(1)
    storage.save(io.BytesIO(b"hello world"), key)
    assert storage.exists(key)
    with storage.open(key) as stream:
        assert stream.read() == b"hello world"
    assert (storage.root / key).read_bytes() == b"hello world"


def test_save_reads_from_the_current_position(storage: LocalStorage) -> None:
    stream = io.BytesIO(b"skipdata")
    stream.seek(4)
    storage.save(stream, "1/abc")
    with storage.open("1/abc") as result:
        assert result.read() == b"data"


def test_save_copies_in_chunks(storage: LocalStorage) -> None:
    data = b"x" * (CHUNK_SIZE * 3 + 5)
    stream = CountingStream(data)
    storage.save(stream, "1/big")
    assert all(0 < size <= CHUNK_SIZE for size in stream.read_sizes)
    assert len(stream.read_sizes) >= 4
    assert (storage.root / "1" / "big").read_bytes() == data


def test_save_replaces_an_existing_file(storage: LocalStorage) -> None:
    storage.save(io.BytesIO(b"old"), "1/a")
    storage.save(io.BytesIO(b"new"), "1/a")
    with storage.open("1/a") as stream:
        assert stream.read() == b"new"


def test_failed_save_leaves_no_files(storage: LocalStorage) -> None:
    class Broken(io.BytesIO):
        def read(self, size: int | None = -1, /) -> bytes:
            raise OSError("disk on fire")

    with pytest.raises(OSError, match="disk on fire"):
        storage.save(Broken(b""), "1/a")
    assert not storage.exists("1/a")
    assert list((storage.root / "1").iterdir()) == []


def test_delete_removes_the_file_and_ignores_missing_files(storage: LocalStorage) -> None:
    storage.save(io.BytesIO(b"data"), "1/a")
    storage.delete("1/a")
    assert not storage.exists("1/a")
    storage.delete("1/a")  # no error
    storage.delete("2/never-existed")


def test_open_missing_file_raises(storage: LocalStorage) -> None:
    with pytest.raises(FileNotFoundError):
        storage.open("1/missing")


@pytest.mark.parametrize(
    "key",
    [
        "",
        "../etc/passwd",
        "1/../../x",
        "/etc/passwd",
        "1//a",
        "1/a/",
        "..",
        ".",
        "1\\..\\a",
        "1/a b",
        "1/\x00",
        "1/ä",
    ],
)
def test_malformed_keys_are_rejected(storage: LocalStorage, key: str) -> None:
    for operation in (
        lambda: storage.save(io.BytesIO(b"x"), key),
        lambda: storage.open(key),
        lambda: storage.delete(key),
        lambda: storage.exists(key),
    ):
        with pytest.raises(InvalidStorageKey):
            operation()


def test_symlink_escaping_the_root_is_rejected(storage: LocalStorage, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_bytes(b"secret")
    storage.root.mkdir(parents=True)
    (storage.root / "1").symlink_to(outside)
    with pytest.raises(InvalidStorageKey):
        storage.open("1/secret")


def test_build_storage_uses_settings(tmp_path: Path) -> None:
    values: dict[str, object] = {
        "jwt_secret": "x" * 32,
        "storage_dir": tmp_path / "configured",
        "_env_file": None,
    }
    settings = Settings(**values)  # type: ignore[arg-type]
    backend = build_storage(settings)
    assert isinstance(backend, LocalStorage)
    assert backend.root == (tmp_path / "configured").resolve()
