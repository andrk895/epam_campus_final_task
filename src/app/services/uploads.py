"""Upload validation (task T5.2): size limit, content type + file signature, filename sanitising.

:func:`validate_upload` is called for every uploaded file before it is stored:

* files larger than the limit raise :class:`~app.core.errors.FileTooLarge` (``413``);
* the content type is detected from the file's leading bytes (its "magic number"). A file whose
  detected type isn't in the allowed list (design decision D8), or whose declared
  ``Content-Type`` contradicts its contents, raises
  :class:`~app.core.errors.UnsupportedFileType` (``415``). A missing or generic declared type
  (``application/octet-stream``) is replaced by the detected one. The stored type is always the
  detected type, never a client-supplied string;
* the original filename is reduced to a safe display name (:func:`sanitize_filename`).
"""

import os
import re
import unicodedata
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from typing import BinaryIO, Final

from app.core.config import Settings
from app.core.errors import FileTooLarge, UnsupportedFileType
from app.models.document import FILENAME_MAX_LENGTH

PNG: Final = "image/png"
JPEG: Final = "image/jpeg"
GIF: Final = "image/gif"
WEBP: Final = "image/webp"
PDF: Final = "application/pdf"
DOC: Final = "application/msword"
DOCX: Final = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

GENERIC_CONTENT_TYPES: Final = frozenset({"", "application/octet-stream", "binary/octet-stream"})
"""Declared types that say nothing about the file; the detected type is used instead."""

CONTENT_TYPE_ALIASES: Final = {
    "image/jpg": JPEG,
    "image/pjpeg": JPEG,
    "application/x-pdf": PDF,
}

DEFAULT_FILENAME: Final = "file"

_HEADER_SIZE: Final = 16
_OLE_SIGNATURE: Final = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_SIGNATURE: Final = b"PK\x03\x04"
_FORBIDDEN_FILENAME_CHARS: Final = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    """Metadata of an uploaded file that passed validation."""

    filename: str
    content_type: str
    size: int


def normalize_content_type(value: str | None) -> str:
    """Lowercase the media type, drop parameters (``; charset=...``) and resolve aliases."""
    media_type = (value or "").split(";", 1)[0].strip().lower()
    return CONTENT_TYPE_ALIASES.get(media_type, media_type)


def _is_docx(stream: BinaryIO) -> bool:
    try:
        with zipfile.ZipFile(stream) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError, ValueError):
        return False
    return "[Content_Types].xml" in names and "word/document.xml" in names


def detect_content_type(stream: BinaryIO) -> str | None:
    """Detect the type of a supported file from its contents; ``None`` if not recognised.

    The stream must be seekable; it is rewound to the start afterwards.
    """
    stream.seek(0)
    header = stream.read(_HEADER_SIZE)
    detected: str | None = None
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = PNG
    elif header.startswith(b"\xff\xd8\xff"):
        detected = JPEG
    elif header.startswith((b"GIF87a", b"GIF89a")):
        detected = GIF
    elif header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        detected = WEBP
    elif header.startswith(b"%PDF-"):
        detected = PDF
    elif header.startswith(_OLE_SIGNATURE):
        detected = DOC
    elif header.startswith(_ZIP_SIGNATURE):
        stream.seek(0)
        detected = DOCX if _is_docx(stream) else None
    stream.seek(0)
    return detected


def sanitize_filename(filename: str | None) -> str:
    """Return a safe display name for a user-supplied filename.

    Keeps only the last path component (``/`` or ``\\`` separated), normalises Unicode (NFC),
    removes control and reserved characters, trims surrounding spaces and dots, and shortens the
    name to the column length while keeping the extension. Falls back to ``"file"``.
    """
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = unicodedata.normalize("NFC", name)
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = _FORBIDDEN_FILENAME_CHARS.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        return DEFAULT_FILENAME
    if len(name) > FILENAME_MAX_LENGTH:
        stem, ext = os.path.splitext(name)
        if len(ext) > 20:
            ext = ""
        name = stem[: FILENAME_MAX_LENGTH - len(ext)].rstrip(" .") + ext
    return name or DEFAULT_FILENAME


def _stream_size(stream: BinaryIO) -> int:
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size


def validate_upload(
    stream: BinaryIO,
    *,
    filename: str | None,
    content_type: str | None,
    max_size_bytes: int,
    allowed_content_types: Iterable[str],
) -> ValidatedUpload:
    """Validate one uploaded file (seekable ``stream``, rewound to the start afterwards).

    Raises:
        FileTooLarge: the file is larger than ``max_size_bytes``.
        UnsupportedFileType: the detected type isn't allowed, can't be recognised, or
            contradicts the declared ``content_type``.
    """
    safe_name = sanitize_filename(filename)
    size = _stream_size(stream)
    if size > max_size_bytes:
        raise FileTooLarge(
            f"File {safe_name!r} is larger than the maximum of {max_size_bytes} bytes."
        )
    allowed = {normalize_content_type(item) for item in allowed_content_types}
    declared = normalize_content_type(content_type)
    if declared not in GENERIC_CONTENT_TYPES and declared not in allowed:
        raise UnsupportedFileType(f"File type {declared!r} of {safe_name!r} is not allowed.")
    detected = detect_content_type(stream)
    if detected is None or detected not in allowed:
        raise UnsupportedFileType(f"The contents of {safe_name!r} are not an allowed file type.")
    if declared not in GENERIC_CONTENT_TYPES and declared != detected:
        raise UnsupportedFileType(
            f"The contents of {safe_name!r} do not match its declared type {declared!r}."
        )
    return ValidatedUpload(filename=safe_name, content_type=detected, size=size)


def validate_upload_with_settings(
    stream: BinaryIO, *, filename: str | None, content_type: str | None, settings: Settings
) -> ValidatedUpload:
    """:func:`validate_upload` with the limits from ``settings``."""
    return validate_upload(
        stream,
        filename=filename,
        content_type=content_type,
        max_size_bytes=settings.max_upload_size_bytes,
        allowed_content_types=settings.allowed_content_types,
    )
