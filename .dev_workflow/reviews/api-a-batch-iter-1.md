# Review: api-a batch (T2.4, T2.2, T2.3, T3.2–T3.6), iteration 1

Scope: `git diff 37b9205..HEAD` on `wip/api-a`, three commits (8b43d17, 85c8ed6, 7f8f39f). I skipped the seed commit as instructed.

## Verification I ran
- `uv run pytest -q --deselect tests/test_db.py::test_request_gets_a_session_that_is_closed_afterwards` (TEST_DATABASE_URL=pm_test_api_a) → **296 passed**, 1 deselected
- `uv run ruff check .` → All checks passed
- `uv run ruff format --check .` → 59 files already formatted
- `uv run mypy src` → Success, 30 source files
- I started my own uvicorn on port 8011 against a scratch DB `pm_review_api_a`, created with `Base.metadata.create_all` because this branch has no alembic.ini. I did not touch the demo server on 8000 or `pm_app`. Afterwards I stopped the server and dropped the scratch DB. curl smoke results:
  - `POST /auth` Alice → 201 `{id, login, created_at}` (no hash). `alice` → 409 `LOGIN_ALREADY_EXISTS`.
  - `POST /login` with a wrong password → 401 generic `INVALID_CREDENTIALS`. Empty strings → 422. Correct credentials → token that works on `/projects`.
  - `POST /projects` → 201 with participants `[owner]`. `GET /projects` → own project with `documents: []`.
  - Non-member `GET /projects/1/info` → 404. `/projects/-1/info` and `/projects/99999999999999999999999/info` → 404 (no 500 on int64 overflow). DELETE with an overflowing id → 404.
  - `PUT /projects/1/info` → 200 with `updated_at` bumped and description cleared.
  - Participant/non-member DELETE → 404 (bob was not a member here). Owner DELETE → 204, and the list is empty afterwards.
  - Lowercase `bearer` scheme accepted. `Authorization: Bearer` with no token → 401.
  - OpenAPI: `HTTPBearer` scheme (http/bearer/JWT). `security` is set exactly on the 5 project operations, not on `/auth`, `/login` or `/health`.

## T2.4 `get_current_user`
- [x] Reads the Bearer header, decodes, loads the user. `src/app/api/deps.py:38-57`
- [x] 401 + `WWW-Authenticate: Bearer` for missing header, non-bearer scheme, malformed/tampered/expired token, and deleted user. Tested in `tests/api/test_deps.py`, every case asserts the header.
- [x] OpenAPI security scheme configured (`HTTPBearer(auto_error=False, bearerFormat="JWT")`). Tested in `test_openapi_declares_bearer_security_scheme`, confirmed in the live `/openapi.json`.
- [x] Every business endpoint uses it: all five `/projects` handlers take `CurrentUserDep`. `test_endpoints_require_authentication` covers all of them.
- The `AppError` handler also adds `WWW-Authenticate` to every 401 (`src/app/api/errors.py:45`), so login failures are consistent.

## T2.2 `POST /auth`
- [x] D11 validation: login 3–50 chars with charset `[A-Za-z0-9_.-]`, password 8–128, `extra="forbid"`. The charset and the 128 cap go beyond the spec but are documented and reasonable.
- [x] 201 `{id, login, created_at}`, no hash (`UserRead`). The test asserts the exact key set and verifies the stored hash.
- [x] 409 for a duplicate, case-insensitively. It is detected through the DB unique index name (`LOGIN_UNIQUE_INDEX`), so it is race-safe, and other IntegrityErrors are re-raised.
- [x] 422 matrix plus boundary-length acceptance.

## T2.3 `POST /login`
- [x] 200 `{access_token, token_type: "bearer", expires_in: 3600}`. `expires_in` is derived from settings.
- [x] Generic 401 for both a wrong password and an unknown login, with identical bodies. Unknown logins are verified against a dummy hash to equalise timing.
- [x] The test confirms the token works on a protected endpoint and that login is case-insensitive.
- Missing or empty fields give 422 rather than 401. This is acceptable: the spec only mandates 401 for wrong credentials.

## T3.2 `POST /projects`
- [x] name 1–200 (stripped), description optional ≤5000. 422 matrix, including whitespace-only names and the extra `owner_id` field.
- [x] Project and owner membership are created in one commit (`services/projects.py:47-52`). The test checks the membership row.
- [x] 201 with the details.

## T3.3 `GET /projects`
- [x] Own and shared projects only, with role, owner login and document metadata. `storage_key` is not exposed.
- [x] No N+1: `joinedload(owner)` + `selectinload(documents)`. The test asserts ≤4 statements for 5 projects with documents.
- [x] Test confirms own + shared are shown and another user's private project is not.

## T3.4 `GET /projects/{id}/info`
- [x] Details plus participants (login and role, owner first). Tested from both the owner's and the participant's perspective.
- [x] 404 for a non-member, a nonexistent id and a very large id. The body is `PROJECT_NOT_FOUND`, the same in all cases (D7).

## T3.5 `PUT /projects/{id}/info`
- [x] Owner update, participant update, non-member 404 (and the data is left unchanged). `updated_at` is bumped (tested).
- PUT replaces both fields: omitting `description` clears it. This is documented in the schema docstring and is consistent with PUT semantics.

## T3.6 `DELETE /projects/{id}`
- [x] Owner only. Participant → 403 `PERMISSION_DENIED`, non-member or nonexistent → 404 (D7 and the T3.1 matrix). 204 with an empty body.
- [x] DB rows for the project, members and documents are deleted (ORM cascade plus `ON DELETE CASCADE`). The test confirms the project is gone from every member's list and `/info` returns 404 for each.
- [~] Stored files: this is the **accepted known deviation**. `remove_stored_files` only logs a warning (TODO(storage)). The hook itself is correct:
  - Keys are collected before the delete.
  - It is called only after `session.commit()`. The test asserts the row is already gone inside the remover.
  - It gets exactly the project's storage keys (tested).
  - Exceptions are logged with `logger.exception` and the request still returns 204 (tested).
  
  This must be wired to the `StorageBackend` at merge with api-b. Until then the T3.6 Done-when ("files are gone from storage") is only met through the injected fake.

## Blocking issues
None.

## Nits (non-blocking)
- `src/app/services/projects.py:118-122`: there is a TOCTOU window. A document uploaded between reading `project.documents` and the commit would be deleted by the DB cascade, but its file would not be in `storage_keys`, so it would be orphaned. Locking the project row (`with_for_update`) in the access check, or re-collecting keys via `DELETE ... RETURNING`, would close it. This is low priority.
- `src/app/services/projects.py:96-105`: when wiring storage at merge, replace the default remover. The current default silently leaks files in production, though it does log a warning.
- `src/app/services/projects.py:80-83`: a PUT with values identical to the current ones does not bump `updated_at`, because SQLAlchemy emits no UPDATE when nothing changed. This is arguably correct.
- `src/app/services/users.py:15-18`: the dummy hash is computed lazily on the first unknown-login attempt, so that one request costs two hashes. Pre-computing it at import or startup would make the timing fully even. This is cosmetic.
- This branch has no `alembic.ini` or migrations: it is based on `abab90f`, before T1.3. That will resolve on rebase or merge onto main. Make sure the full suite, including the migrations test, is re-run after the merge.

## Summary
All four tasks (T2.4, T2.2, T2.3, T3.2–T3.6) meet their Done-when criteria. The only exception is the stored-file deletion in T3.6, which is the explicitly accepted deviation: its post-commit, failure-tolerant hook is implemented and tested correctly and only needs the storage backend wired in at merge time. Status codes follow D6/D7 and the T3.1 matrix (404 for non-members including out-of-range ids, 403 for a participant deleting). Authentication is applied to every business endpoint and exposed in OpenAPI. The tests are meaningful and cover the named error paths. Tests, ruff, format and mypy are all clean, and a live curl smoke test confirmed the behaviour.

VERDICT: APPROVED
