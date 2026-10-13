# Project Management Software (backend): Task List

This document breaks [TASK_SPECIFICATION.md](TASK_SPECIFICATION.md) into ordered, implementable tasks. Each task has a short goal, the work involved, and acceptance criteria ("Done when"). Tasks are grouped into phases. A phase generally depends on the ones before it.

---

## Design decisions (assumptions)

The original specification leaves these points open. Each one has a default chosen below; change any of them before starting work if you prefer something else.

| # | Topic | Default |
|---|-------|---------|
| D1 | Dependency management | **uv** with `pyproject.toml`; **tox** (or `uv run`) for test/lint environments |
| D2 | DB migrations | **Alembic** |
| D3 | Password hashing | **argon2** (via `pwdlib` / `argon2-cffi`) or **bcrypt** |
| D4 | JWT library | **PyJWT**, HS256, `exp` = 1 hour, `sub` = user id |
| D5 | Roles | Two roles per project: `owner` (exactly one, the creator) and `participant` |
| D6 | Participant document rights | Participants can **list, download, upload, and replace** documents. Deleting documents is **owner only**, because the spec says owners "add or remove documents" and participants "view and update" them. |
| D7 | Unauthorized access response | `404 Not Found` when the user has no access to the project or document, so its existence isn't revealed. `403 Forbidden` when the user has access but lacks the permission, e.g. a participant tries to delete the project. |
| D8 | Allowed file types | Images (`png`, `jpg/jpeg`, `gif`, `webp`), `pdf`, `doc`, `docx`. Max size configurable (default 10 MB per file). |
| D9 | Document storage | Pluggable `StorageBackend` interface. `LocalStorage` (required) writes to a configurable directory under generated UUID filenames, never under user-supplied names. `S3Storage` is optional (Phase 9). |
| D10 | Participant removal | The spec says owners can remove participants but defines no endpoint for it, so add `DELETE /projects/{project_id}/participants/{login}` (owner only). |
| D11 | Login identifier | `login` is a unique, case-insensitive username (3–50 chars). Password min. 8 chars. |

---

## Phase 0: Project setup

### T0.1 Repository and tooling skeleton
- Create the `pyproject.toml` (Python ≥ 3.12) with runtime dependencies: `fastapi`, `uvicorn[standard]`, `sqlalchemy>=2`, `psycopg[binary]` (or `asyncpg`), `alembic`, `pydantic>=2`, `pydantic-settings`, `pyjwt`, a password hashing library, and `python-multipart`.
- Dev dependencies: `pytest`, `pytest-cov`, `httpx`, `ruff`, `mypy`, `pre-commit`.
- Suggested layout:
  ```
  src/app/
    main.py            # FastAPI app factory
    core/              # config, security (JWT, hashing), errors
    db/                # engine, session, base, migrations
    models/            # SQLAlchemy models
    schemas/           # Pydantic schemas
    repositories/      # DB access
    services/          # business logic + permission checks
    storage/           # StorageBackend, LocalStorage, (S3Storage)
    api/               # routers: auth, projects, documents, sharing
  tests/
  ```
- Add `.gitignore`, `.env.example`, `README.md` (stub), and `ruff`/`mypy` configuration.
- **Done when:** `uv sync` installs everything, `uv run ruff check .` passes, and `uv run pytest` runs (0 tests is fine).

### T0.2 Configuration
- Use `pydantic-settings` for a `Settings` class: `DATABASE_URL`, `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRE_MINUTES=60`, `STORAGE_BACKEND=local`, `STORAGE_DIR`, `MAX_UPLOAD_SIZE_MB`, `ALLOWED_CONTENT_TYPES`.
- Load from environment / `.env`. Startup fails clearly if `JWT_SECRET` is missing.
- **Done when:** settings are injectable as a FastAPI dependency and can be overridden in tests.

### T0.3 Minimal app and health check
- App factory `create_app()` and a `GET /health` endpoint that returns `{"status": "ok"}`.
- **Done when:** `uv run uvicorn app.main:app` starts, `/health` returns 200, and `/docs` shows the OpenAPI UI.

---

## Phase 1: Database and data model

### T1.1 Database connection and session management
- SQLAlchemy 2.x engine + session factory, with a `get_db` dependency that yields a session per request.
- **Done when:** the app can connect to a local PostgreSQL instance and the session is closed after each request.

### T1.2 Models
- `User`: `id`, `login` (unique, indexed), `password_hash`, `created_at`.
- `Project`: `id`, `name`, `description`, `owner_id` → User, `created_at`, `updated_at`.
- `ProjectMember`: `project_id`, `user_id`, `role` (`owner` / `participant`), `added_at`. Unique on `(project_id, user_id)`.
- `Document`: `id`, `project_id` → Project, `filename` (original name), `content_type`, `size`, `storage_key`, `uploaded_by` → User, `created_at`, `updated_at`.
- Cascades: deleting a project deletes its members and document rows.
- **Done when:** the models are defined with relationships, constraints, and indexes.

### T1.3 Alembic migrations
- Set up Alembic with an initial migration for all tables.
- **Done when:** `alembic upgrade head` creates the schema on an empty DB and `alembic downgrade base` reverts it.

### T1.4 Test database fixtures
- Pytest fixtures: an isolated test DB (PostgreSQL via Docker / testcontainers, or a dedicated test database), a per-test transaction rollback or truncate, a `TestClient`/`httpx` client, and a temp storage directory.
- Factory helpers: `create_user`, `auth_headers(user)`, `create_project`.
- **Done when:** tests can run in parallel-safe isolation and leave no data or files behind.

---

## Phase 2: Authentication

### T2.1 Password hashing and JWT utilities
- `hash_password`, `verify_password`.
- `create_access_token(user_id)` with a 1-hour `exp` and `iat`. `decode_token` rejects expired, malformed, or wrongly signed tokens.
- **Done when:** unit tests cover a valid token, an expired token (time frozen or a short expiry), a tampered token, and password verification.

### T2.2 `POST /auth`: registration
- Body: `{login, password}`, validated with Pydantic (D11).
- Returns `201` with `{id, login, created_at}`. The password hash is never returned.
- Returns `409` if the login already exists and `422` on validation errors.
- **Done when:** the endpoint and its tests (success, duplicate, invalid input) are in place.

### T2.3 `POST /login`: login
- Body: `{login, password}`. Returns `200` with `{access_token, token_type: "bearer", expires_in: 3600}`.
- Returns `401` with a generic message for a wrong login or password, without revealing which one was wrong.
- **Done when:** the endpoint and its tests are in place, and the token works on a protected endpoint.

### T2.4 `get_current_user` dependency
- Reads the `Authorization: Bearer <token>` header, decodes it, and loads the user.
- Returns `401` (with a `WWW-Authenticate` header) if the header is missing, the token is invalid or expired, or the user no longer exists.
- Configure the OpenAPI security scheme so the "Authorize" button in `/docs` works.
- **Done when:** every business endpoint uses this dependency, and tests confirm `401` without a token or with an expired one.

---

## Phase 3: Project management

### T3.1 Permission/access service
- A central place for access rules, e.g. `ProjectAccess.require(project_id, user, permission)` with these permissions: `VIEW`, `EDIT`, `DELETE_PROJECT`, `MANAGE_MEMBERS`, `UPLOAD_DOC`, `REPLACE_DOC`, `DELETE_DOC`.
- Permission matrix:

  | Permission | Owner | Participant | No access |
  |------------|:-----:|:-----------:|:---------:|
  | View project / list / download docs | ✅ | ✅ | 404 |
  | Edit project info | ✅ | ✅ | 404 |
  | Upload / replace documents | ✅ | ✅ | 404 |
  | Delete documents | ✅ | 403 (D6) | 404 |
  | Invite / remove participants | ✅ | 403 | 404 |
  | Delete project | ✅ | 403 | 404 |

- **Done when:** unit tests cover every cell of the matrix.

### T3.2 `POST /projects`: create a project
- Body: `{name (1–200 chars), description (optional, ≤ 5000 chars)}`.
- Creates the project and an `owner` membership row for the creator in a single transaction.
- Returns `201` with the project details.
- **Done when:** the endpoint and its tests are in place.

### T3.3 `GET /projects`: list accessible projects
- Returns every project the user owns or participates in, each including its details, the user's role, the owner login, and its documents (metadata only).
- Avoid N+1 queries by using `selectinload` / joined loading.
- *(Optional)* Pagination (`limit`, `offset`) and sorting.
- **Done when:** tests confirm the user sees their own and shared projects but not other users' projects.

### T3.4 `GET /projects/{project_id}/info`: project details
- Returns the details plus the participant list (logins and roles).
- Returns `404` for a non-member or a nonexistent project.
- **Done when:** the endpoint and its tests are in place.

### T3.5 `PUT /projects/{project_id}/info`: update project details
- Body: `{name, description}`. Owner and participants are allowed. Updates `updated_at`.
- **Done when:** tests cover an owner update, a participant update, and a non-member getting `404`.

### T3.6 `DELETE /projects/{project_id}`: delete a project
- Owner only (a participant gets `403`). Deletes the DB rows (project, members, documents) **and** the stored files.
- If file deletion fails after the DB commit, log it and don't fail the request. Alternatively, delete the files only after a successful commit.
- Returns `204`.
- **Done when:** tests confirm the files are gone from storage and the project no longer appears for any member.

---

## Phase 4: Sharing and access control

### T4.1 `POST /projects/{project_id}/invite?user=<login>`: invite a user
- Owner only. Adds a `participant` membership.
- Returns:
  - `404` if the target user doesn't exist
  - `409` if the user is already a member
  - `400` if the owner invites themselves
- Returns `201` or `200` with the membership info.
- **Done when:** tests confirm the invited user can now see the project in `GET /projects` and access it.

### T4.2 `DELETE /projects/{project_id}/participants/{login}`: remove a participant (D10)
- Owner only. The owner can't be removed. Returns `204`.
- **Done when:** tests confirm the removed user immediately loses access (`404`).

### T4.3 *(Optional)* Extra sharing features
- `GET /projects/{project_id}/participants`.
- A participant leaves a project voluntarily.
- Ownership transfer.
- Invitation acceptance flow: a pending invite that the invitee accepts or declines.

---

## Phase 5: Document management

### T5.1 Storage abstraction and local storage
- `StorageBackend` protocol: `save(stream, key) -> None`, `open(key) -> stream`, `delete(key)`, `exists(key)`.
- `LocalStorage`: writes to `STORAGE_DIR` under `/<project_id>/<uuid>` keys and streams in chunks without reading the whole file into memory. It guards against path traversal.
- Select the backend through settings and a dependency.
- **Done when:** unit tests run against a temp directory.

### T5.2 Upload validation
- Check the content type (and ideally the file signature / magic bytes) against the allowed list (D8).
- Enforce the max file size and return `413` when it's exceeded.
- Sanitize the original filename before storing it as metadata.
- **Done when:** tests confirm that disallowed types get `415` and files that are too large get `413`.

### T5.3 `POST /projects/{project_id}/documents`: upload document(s)
- `multipart/form-data` with one or more `files` fields.
- Owner and participants are allowed.
- Saves the files, then creates the `Document` rows. If anything fails, cleans up the already-saved files (all-or-nothing).
- Returns `201` with the list of created document metadata.
- **Done when:** tests cover single and multiple uploads, a non-member getting `404`, and an invalid file type.

### T5.4 `GET /projects/{project_id}/documents`: list documents
- Returns metadata: `id`, `filename`, `content_type`, `size`, `uploaded_by`, `created_at`, `updated_at`.
- **Done when:** the endpoint and its tests are in place.

### T5.5 `GET /documents/{document_id}`: download a document
- Resolves the document, then its project, then checks the `VIEW` permission.
- Streams the file (`StreamingResponse` / `FileResponse`) with the correct `Content-Type` and `Content-Disposition: attachment; filename="..."`.
- **Done when:** tests confirm the downloaded bytes match the upload and a non-member gets `404`.

### T5.6 `PUT /documents/{document_id}`: replace a document
- Multipart upload of a single new file. The same validation as T5.2 applies.
- Stores the new file, updates the metadata (`filename`, `content_type`, `size`, `updated_at`), and deletes the old file after the commit.
- **Done when:** tests confirm that a download after the replace returns the new content and the old file is removed.

### T5.7 `DELETE /documents/{document_id}`: delete a document
- Owner only by default (D6). Removes the DB row and the file. Returns `204`.
- **Done when:** the endpoint and its tests are in place, covering the permission matrix.

---

## Phase 6: Quality, error handling and docs

### T6.1 Consistent error responses
- A single error shape, e.g. `{"detail": "...", "code": "PROJECT_NOT_FOUND"}`, with custom exception classes mapped to HTTP status codes in exception handlers.
- **Done when:** all endpoints return errors in this format.

### T6.2 Logging
- Structured logging with a request ID middleware. Passwords, tokens, and file contents are never logged.

### T6.3 Test coverage
- Integration tests for every endpoint, covering the happy path, authorization (401/403/404), and validation (422/409/413/415).
- An end-to-end scenario test: register A and B → A creates a project → A uploads documents → A invites B → B lists, downloads, and replaces → B can't delete the project → A removes B → B loses access → A deletes the project → its files are gone.
- **Done when:** coverage is ≥ 85% and enforced through `--cov-fail-under`.

### T6.4 Static checks
- `ruff` (lint + format), `mypy` (strict on `src/`), and `pre-commit` hooks.
- **Done when:** all of them pass locally.

### T6.5 Documentation
- README: project overview, architecture, local setup (with and without Docker), environment variables, how to run tests and migrations, API overview, and the permission matrix.
- Clear OpenAPI descriptions, tags, and response models on every endpoint.

---

## Phase 7: Containerization

### T7.1 Dockerfile
- A multi-stage build (uv for dependencies) on a slim Python 3.12 base. The container runs as a non-root user, and the image includes a health check.
- **Done when:** `docker build` succeeds and the container serves `/health`.

### T7.2 docker-compose
- Services: `api` and `postgres`, with a volume for DB data and a volume for document storage.
- Migrations run on startup (an entrypoint or a separate `migrate` service).
- **Done when:** `docker compose up` gives a fully working API on a fresh machine.

---

## Phase 8: CI/CD (GitHub Actions)

### T8.1 CI pipeline
- Triggers on pushes and PRs to `main`.
- Jobs:
  - lint: `ruff`
  - type check: `mypy`
  - tests: `pytest` with a PostgreSQL service container, plus a coverage report
- Caches uv dependencies.
- **Done when:** the pipeline is green on `main` and PRs are blocked when it fails.

### T8.2 Security scanning *(advanced)*
- Dependency audit (`pip-audit`), static analysis (`bandit`), Docker image scan (`trivy`), and optionally CodeQL.

### T8.3 Build and push image *(advanced)*
- Builds the Docker image and pushes it to GHCR or Amazon ECR on merge to `main` or on tags.

---

## Phase 9: Advanced / optional (AWS)

### T9.1 S3 storage backend
- `S3Storage` implementing `StorageBackend` (boto3), selected with `STORAGE_BACKEND=s3`. Tested with `moto` or LocalStack.
- *(Optional)* Pre-signed URLs for downloads.

### T9.2 Deploy to AWS
- ECS Fargate (or EC2) + RDS PostgreSQL + S3, with secrets in AWS Secrets Manager / SSM.
- Infrastructure as code (Terraform / CDK) is optional.

### T9.3 Continuous deployment
- A GitHub Actions job that deploys the new image to ECS after CI passes on `main`.

### T9.4 Lambda document processing
- An S3-triggered Lambda that, for example, resizes uploaded images or creates thumbnails. It stores the results and/or updates the metadata.

### T9.5 Other ideas
- Refresh tokens / logout (token blacklist).
- Document versioning (keep the history on replace).
- Activity / audit log per project.
- Rate limiting on `/login`.
- Search and filter projects and documents.

---

## Suggested milestone order

1. **M1: Foundation:** T0.1 – T1.4
2. **M2: Auth:** T2.1 – T2.4
3. **M3: Projects and sharing:** T3.1 – T4.2
4. **M4: Documents:** T5.1 – T5.7
5. **M5: Production-ready:** T6.x, T7.x, T8.1 (this completes all required functionality)
6. **M6: Advanced:** T8.2+, T9.x
