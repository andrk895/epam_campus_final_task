# Review — api-b batch (T5.1, T5.2, T4.1, T4.2, T5.3–T5.7, T3.6 file deletion) — iteration 1

Scope: `git diff 7f8f39f HEAD` on `wip/api-b` (24 files, +2382/−60).

## Verification I ran
- `TEST_DATABASE_URL=…/pm_test_api_b uv run pytest -q --deselect tests/test_db.py::test_request_gets_a_session_that_is_closed_afterwards` → 417 passed, 1 deselected
- `uv run ruff check .` → All checks passed
- `uv run ruff format --check .` → 75 files already formatted
- `uv run mypy src` → no issues in 39 source files
- Live smoke test: my own uvicorn on port 8077, cwd `/tmp` (no `.env`), scratch DB `pm_review_api_b` built with `Base.metadata.create_all`, `STORAGE_DIR=/tmp/...`, `MAX_UPLOAD_SIZE_MB=1`. Users alice (owner), bob (participant), carol (outsider). Afterwards I stopped the server, dropped the DB and deleted the temp dir. The demo server on :8000 was not touched and still returns `/health` ok.

## T5.1 Storage abstraction and local storage
- [x] `StorageBackend` protocol with save/open/delete/exists (`src/app/storage/base.py`); keys are `<project_id>/<uuid hex>` from `new_storage_key`, never based on the filename. Live: the files on disk were `storage/1/<32-hex>`.
- [x] `LocalStorage` copies with `shutil.copyfileobj` in 64 KiB chunks and writes atomically (mkstemp, then `os.replace`, temp file removed on failure). Path traversal is blocked twice: a strict key regex, then a `resolve()` + `is_relative_to(root)` check, which also catches symlinks.
- [x] Backend chosen through `Settings.storage_backend` and the `get_storage`/`StorageDep` dependency.
- [x] Unit tests run against `tmp_path` (`tests/storage/test_local_storage.py`). They cover the round trip, chunking, failed save, malformed keys, symlink escape and settings selection. The API tests' `settings` fixture points `storage_dir` at `tmp_path`, so tests never write to `./storage`.

## T5.2 Upload validation
- [x] Magic-byte detection for png/jpeg/gif/webp/pdf/doc (OLE)/docx (a zip that must contain `word/document.xml`). A declared type outside the list, or one that disagrees with the detected type, gives 415. A generic or missing declared type is replaced by the detected one, and the stored content type is always the detected one.
- [x] 413 above the limit, with a boundary test (exactly at the limit is accepted, one byte more is rejected). Live: a 1.1 MB PDF got 413.
- [x] Filename sanitising: the last path component only, NFC, control characters (including CR/LF) removed, reserved characters replaced, shortened to the column length with the extension kept. Live: a filename with `../../`, quotes and CRLF was stored as a plain name with no path parts and no newlines.
- [x] Tests for 415 (disallowed, unrecognised, empty, spoofed, plain zip) and 413 at both the service and API level.

## T4.1 Invite
- [x] Owner only. Live: participant 403, outsider 404, unknown user 404, existing member 409, self-invite 400, success 201 with the membership body. The login match is case-insensitive (`?user=BOB` worked). Concurrent duplicate inserts are turned into 409.
- [x] Test `test_invite_gives_access` confirms the invitee sees the project in `GET /projects` and can access it.

## T4.2 Remove participant (D10)
- [x] Owner only (participant 403, outsider 404). Removing the owner gives 400 `CANNOT_REMOVE_OWNER`; removing a non-member gives 404 `PARTICIPANT_NOT_FOUND`; success gives 204.
- [x] `test_removed_participant_loses_access` passes. Live: after removal bob gets 404 on `/projects/1/info` and on `/documents/2`, and his `GET /projects` returns `[]`.

## T5.3 Upload documents
- [x] Multipart with repeated `files` fields. Owner and participant get 201; outsider 404; no files 400.
- [x] All-or-nothing: every file is validated before anything is stored. If a store or the commit fails, the session is rolled back and the saved keys are deleted. The service tests cover both failure points. Live: uploading one valid PDF together with one text file gave 415 and wrote nothing to disk.
- [x] Tests cover single upload, multiple uploads, non-member 404 and invalid type.

## T5.4 List documents
- [x] Returns id, filename, content_type, size, uploaded_by, created_at and updated_at; VIEW permission; tested.

## T5.5 Download
- [x] Resolves the document, then checks VIEW on its project. An outsider and a nonexistent or out-of-range id both get 404 `DOCUMENT_NOT_FOUND` (D7). The file is streamed in chunks and the stream is closed by the generator.
- [x] `Content-Type` is the detected type. `Content-Disposition` is `attachment` with an ASCII fallback (quotes and backslashes replaced) plus RFC 5987 `filename*`, so a filename can't inject a header. `nosniff` is set.
- [x] Live: the downloaded bytes match the upload (`cmp`); outsider 404. Covered by tests.

## T5.6 Replace
- [x] Participant allowed, outsider 404, 415/413 validation. The new file goes under a fresh key; the old file is deleted only after the commit; if the commit fails, the new file is removed. `updated_at` is bumped through `onupdate`.
- [x] Test confirms the download returns the new content and the old file is gone. Live: the storage diff showed the old key replaced by a new one, the downloaded bytes matched the new file, and an invalid replacement left the old file in place.

## T5.7 Delete
- [x] Owner 204, participant 403 `PERMISSION_DENIED`, outsider 404, unauthenticated 401. The row is deleted, then the file after the commit; a failed file delete is logged and the request still returns 204 (tested). `test_delete_permission_matrix` covers the D6 cells.

## T3.6 File-deletion wiring
- [x] `delete_project` now takes the storage backend and deletes each key after the commit. A failure is logged per key and the request still returns 204. Tests use a recording storage and a failing storage and confirm the project's files are gone while another project's file is left alone. Live: deleting the project removed every remaining file (0 left on disk).

## Blocking issues
None.

## Nits (non-blocking)
- `src/app/services/uploads.py`: the size is measured after the whole multipart body has been received, and there is no request-size cap. An oversized upload is fully spooled to disk before it gets 413. This is acceptable for the task, but a body-size limit in front of the app (proxy or middleware) would be worth adding in a hardening phase.
- An OLE signature also matches `.xls`/`.ppt`, so legacy Office files that aren't Word documents are accepted as `application/msword`. This is a known limit of magic-byte detection and acceptable here.
- `NoFilesUploaded` (400) is only reachable from the service. An empty multipart request is rejected by FastAPI with 422 first, which is fine.

## Summary
The storage layer, upload validation, sharing endpoints, all five document endpoints and the T3.6 file-deletion wiring match the specification and design decisions D6–D10. I checked the permission matrix live and in tests: participants can upload and replace but get 403 on delete, and outsiders get 404 everywhere. Files are stored only under `<project_id>/<uuid>`. Traversal is blocked by the key regex plus the resolve-and-containment check, and filename header injection is blocked by sanitising plus the ASCII fallback and RFC 5987 encoding. Uploads are all-or-nothing, and replace and delete remove old files only after the commit. Tests (417), ruff, ruff format and mypy are clean. There are no blocking issues.

VERDICT: APPROVED
