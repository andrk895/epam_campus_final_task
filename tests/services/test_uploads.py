"""Tests for upload validation (task T5.2)."""

import io
import zipfile

import pytest

from app.core.config import DEFAULT_ALLOWED_CONTENT_TYPES
from app.core.errors import FileTooLarge, UnsupportedFileType
from app.services.uploads import (
    DEFAULT_FILENAME,
    ValidatedUpload,
    detect_content_type,
    sanitize_filename,
    validate_upload,
)

Samples = dict[str, tuple[str, bytes]]
MAX = 1024


def check(
    data: bytes,
    content_type: str | None,
    filename: str | None = "f.bin",
    *,
    max_size: int = MAX,
    allowed: tuple[str, ...] = DEFAULT_ALLOWED_CONTENT_TYPES,
) -> ValidatedUpload:
    return validate_upload(
        io.BytesIO(data),
        filename=filename,
        content_type=content_type,
        max_size_bytes=max_size,
        allowed_content_types=allowed,
    )


@pytest.mark.parametrize("ext", ["png", "jpg", "gif", "webp", "pdf", "doc", "docx"])
def test_every_allowed_type_is_detected_and_accepted(samples: Samples, ext: str) -> None:
    content_type, data = samples[ext]
    assert detect_content_type(io.BytesIO(data)) == content_type
    result = check(data, content_type, f"file.{ext}")
    assert result == ValidatedUpload(
        filename=f"file.{ext}", content_type=content_type, size=len(data)
    )


@pytest.mark.parametrize("declared", [None, "", "application/octet-stream"])
def test_generic_declared_type_is_replaced_by_the_detected_one(
    samples: Samples, declared: str | None
) -> None:
    assert check(samples["pdf"][1], declared).content_type == "application/pdf"


def test_declared_type_is_normalised(samples: Samples) -> None:
    assert check(samples["jpg"][1], "IMAGE/JPG; foo=bar").content_type == "image/jpeg"


def test_validation_rewinds_the_stream(samples: Samples) -> None:
    stream = io.BytesIO(samples["png"][1])
    validate_upload(
        stream,
        filename="a.png",
        content_type="image/png",
        max_size_bytes=MAX,
        allowed_content_types=DEFAULT_ALLOWED_CONTENT_TYPES,
    )
    assert stream.tell() == 0


def test_disallowed_declared_type_is_rejected() -> None:
    with pytest.raises(UnsupportedFileType):
        check(b"plain text", "text/plain", "a.txt")


def test_unrecognised_content_is_rejected() -> None:
    with pytest.raises(UnsupportedFileType):
        check(b"#!/bin/sh\necho hi", "application/octet-stream", "a.sh")


def test_empty_file_is_rejected() -> None:
    with pytest.raises(UnsupportedFileType):
        check(b"", None)


def test_content_not_matching_declared_type_is_rejected(samples: Samples) -> None:
    with pytest.raises(UnsupportedFileType, match="do not match"):
        check(samples["pdf"][1], "image/png", "fake.png")


def test_plain_zip_is_not_a_docx() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("evil.exe", "MZ")
    with pytest.raises(UnsupportedFileType):
        check(buffer.getvalue(), None)


def test_detected_type_must_be_in_the_configured_list(samples: Samples) -> None:
    with pytest.raises(UnsupportedFileType):
        check(samples["png"][1], None, allowed=("application/pdf",))


def test_file_at_the_limit_is_accepted_and_one_byte_more_is_rejected(samples: Samples) -> None:
    data = samples["pdf"][1]
    data = data + b"0" * (MAX - len(data))
    assert check(data, "application/pdf").size == MAX
    with pytest.raises(FileTooLarge):
        check(data + b"0", "application/pdf")


def test_size_is_checked_before_the_type() -> None:
    with pytest.raises(FileTooLarge):
        check(b"x" * (MAX + 1), "text/plain")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\cv.docx", "cv.docx"),
        ('a<b>c:d"e|f?g*h.png', "a_b_c_d_e_f_g_h.png"),
        ("bad\x00name\r\n.pdf", "badname.pdf"),
        ("  .hidden.  ", "hidden"),
        ("multiple   spaces.pdf", "multiple spaces.pdf"),
        ("", DEFAULT_FILENAME),
        (None, DEFAULT_FILENAME),
        ("...", DEFAULT_FILENAME),
        ("dir/", DEFAULT_FILENAME),
        ("árvíztűrő.pdf", "árvíztűrő.pdf"),
    ],
)
def test_sanitize_filename(raw: str | None, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_long_filename_is_shortened_keeping_the_extension() -> None:
    name = sanitize_filename("a" * 400 + ".pdf")
    assert len(name) == 255
    assert name.endswith(".pdf")


def test_validated_filename_is_sanitised(samples: Samples) -> None:
    assert check(samples["png"][1], "image/png", "../x/../a.png").filename == "a.png"
