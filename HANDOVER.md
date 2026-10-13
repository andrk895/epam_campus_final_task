# Handover: Project Management API (FastAPI + PostgreSQL + React UI)

> **For the next Claude Code session:** read this whole file first, then `specification.md`
> (the task list, with binding design decisions D1–D11) and `TASK_SPECIFICATION.md` (the
> original requirements). Continue with the "Remaining work" section below, in order.

Status as of 2026-10-13, `main` at `09248ad` (pushed to `origin/main`).

---

## 1. What this project is

A backend for a project management tool: users register and log in (JWT), create projects,
share them with other users (owner / participant roles), and upload, download, replace and
delete project documents. There is also a React + Vite web UI in `frontend/`.

- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL (psycopg 3), PyJWT,
  pwdlib/argon2, managed with **uv**. Code in `src/app/`, tests in `tests/`.
- Frontend: React 18 + TypeScript + Vite in `frontend/` (see `frontend/README.md`). The Vite dev
  server proxies `/api/*` to the backend on `:8000`, so the backend has no CORS setup.

## 2. What is DONE (all reviewed and merged to `main`)

Phases 0–5 of `specification.md`: **all 15 required endpoints are implemented and tested.**

| Task | Status |
|------|--------|
| T0.1–T0.3 tooling, settings (`pydantic-settings`), app factory, `/health` | done |
| T1.1–T1.4 DB session, models, Alembic migration `0001`, test fixtures/factories | done |
| T2.1–T2.4 hashing + JWT, `POST /auth`, `POST /login`, `get_current_user` | done |
| T3.1–T3.6 permission service, project CRUD (incl. stored-file deletion on project delete) | done |
| T4.1–T4.2 invite, remove participant | done |
| T4.3 optional sharing extras | **skipped on purpose** (optional) |
| T5.1–T5.7 storage abstraction, upload validation (magic bytes, 413/415), document endpoints | done |
| Frontend (login/register, projects list, project page with sharing + documents, backend-progress page) | done, merged from `frontend` branch, `npm run build` passes |

Verified state of `main` right now:
- `uv run pytest --cov` → **443 passed**, coverage **99%**
- `uv run ruff check .` and `uv run ruff format --check .` → clean
- `uv run mypy` (strict, src + tests) → clean
- `cd frontend && npm run build` → succeeds

Some Phase 6 items already exist partly (see below): domain exceptions render as
`{"detail": ..., "code": ...}` (`src/app/core/errors.py`, `src/app/api/errors.py`); endpoints
have summaries and tags.

## 3. Remaining work (in this order)

### Phase 6: Quality, error handling, docs
- **T6.1 Consistent errors — partial.** `AppError` subclasses already map to
  `{"detail", "code"}`. Still missing: a handler for FastAPI's `RequestValidationError` (422)
  and for `HTTPException`/Starlette 404/405 so *every* error uses the same shape (e.g.
  `code: "VALIDATION_ERROR"`, keep the field errors in an extra key). Update tests that assert
  on the default 422 body, and check the frontend's error parsing in `frontend/src/api.ts` still
  works.
- **T6.2 Logging — not started.** Structured logging config + a request-ID middleware
  (`X-Request-ID` in/out). Never log passwords, tokens or file contents. Only
  `services/documents.py` and `services/projects.py` log today.
- **T6.3 Test coverage — mostly done.** Coverage is 99% but:
  - add the **end-to-end scenario test** from the spec (register A and B → A creates project →
    uploads → invites B → B lists/downloads/replaces → B can't delete project → A removes B →
    B loses access → A deletes project → files gone). None exists yet.
  - enforce coverage: add `--cov=app --cov-fail-under=85` (e.g. in `[tool.pytest.ini_options]`
    addopts or in the CI command).
- **T6.4 Static checks — partial.** ruff + mypy strict pass; **`.pre-commit-config.yaml` is
  missing** (ruff, ruff-format, mypy hooks).
- **T6.5 Documentation — not started.** `README.md` is a stub. Needs: overview,
  architecture, local setup with and without Docker, env vars (see `.env.example`), tests,
  migrations, API overview (the 15 endpoints), the permission matrix, how to run the frontend.

### Phase 7: Containerization — not started
- **T7.1** multi-stage `Dockerfile` (uv, python:3.12-slim, non-root user, `HEALTHCHECK` on
  `/health`). Add a `.dockerignore`.
- **T7.2** `docker-compose.yml` with `api` + `postgres`, volumes for DB data and document
  storage (`STORAGE_DIR`), migrations on startup (`alembic upgrade head` in an entrypoint or a
  `migrate` service). Optionally a `frontend` service.
- Note: Docker is **not installed** on the original dev machine; if it isn't available to you
  either, write the files carefully and tell the user they couldn't be built locally.

### Phase 8: CI/CD — not started
- **T8.1** `.github/workflows/ci.yml`: on push/PR to `main`; jobs for ruff, mypy, pytest with
  a `postgres:16` service container (set `TEST_DATABASE_URL`, `JWT_SECRET`), coverage report,
  uv cache (`astral-sh/setup-uv`). Optionally also a frontend `npm ci && npm run build` job.
  Blocking PRs on failure is a GitHub branch-protection setting: tell the user to enable it.
- T8.2 / T8.3 are *(advanced)*: only if the user asks.

### Phase 9: AWS — optional, only if the user asks.

### Known nits carried over from reviews (`.dev_workflow/carry-over.md`)
- `src/app/main.py` uses a module-level `__getattr__` for the lazy `app`, so mypy accepts any
  name from `app.main`; consider adding `if TYPE_CHECKING: app: FastAPI`. Document the lazy app
  entry point in the README.
- Starlette `TestClient`/httpx deprecation warning in test output.
- Uploads are measured after the whole multipart body is received; no request-body size cap
  (could add middleware or rely on a proxy).
- Optional: a test that runs `alembic upgrade head` / `downgrade base` against an empty schema
  (check `tests/test_migrations.py` first, it may already cover this).

## 4. Local environment

- **No Docker on the original machine.** PostgreSQL 16 runs via the `pgserver` pip package in
  `~/.local/share/pg-local` (outside the repo):
  - start: `~/.local/share/pg-local/bin/pg_ctl -D ~/.local/share/pg-local/data -l ~/.local/share/pg-local/server.log -o "-p 5432 -k /tmp -c listen_addresses=localhost" -w start`
  - stop: `~/.local/share/pg-local/bin/pg_ctl -D ~/.local/share/pg-local/data stop`
  - On a different machine, use any PostgreSQL 16 (e.g. `docker run -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:16`)
    and create the databases `pm_app` and `pm_test`.
- Connection: `localhost:5432`, user `postgres` / password `postgres`, DBs `pm_app` (dev) and
  `pm_test` (tests, override with `TEST_DATABASE_URL`). Tests create a temporary schema and
  roll back each test.
- uv lives at `~/.local/bin/uv` (may not be on `PATH`).
- `.env` is a copy of `.env.example` (`JWT_SECRET=change-me`): fine for dev, never commit it.

Common commands:
```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload      # http://localhost:8000/docs
uv run pytest --cov
uv run ruff check . && uv run ruff format --check . && uv run mypy
cd frontend && npm install && npm run dev  # http://localhost:5173
```

## 5. How the work was organised (optional to reuse)

- `.claude/agents/` has `orchestrator`, `programmer` and `reviewer` agents. The orchestrator
  (`claude --agent orchestrator`) drives tasks from `specification.md`: programmer implements,
  reviewer writes a verdict to `.dev_workflow/reviews/<TASK>-iter-<N>.md`, loop until
  `VERDICT: APPROVED`, then commit + push per task.
- Progress/state: `.dev_workflow/progress.md`, `.dev_workflow/state.json` (phases 0–5 done,
  T4.3 skipped). If you use the orchestrator, update `state.json` `phases` to include 6–8 so it
  resumes at T6.1. Otherwise, just work task by task and keep `progress.md` updated.
- Conventions: one commit per task, message like `T6.1: <summary>`; run tests, ruff, ruff
  format and mypy before each commit; the user wants verified tasks committed and pushed to
  `origin/main`.
- Leftover git worktrees/branches from parallel work (all already merged; safe to remove once
  the user agrees): `../epam_campus_final_task-frontend` (`frontend`),
  `../epam_campus_final_task-worktrees/api-a` (`wip/api-a`),
  `../epam_campus_final_task-worktrees/api-b` (`wip/api-b`). Don't build on them; work on `main`
  or a fresh branch.

## 6. Code map (where to look)

```
src/app/main.py            create_app(), lazy module-level app, router registration
src/app/core/config.py     Settings (env / .env), get_settings
src/app/core/security.py   hashing, JWT
src/app/core/errors.py     domain exceptions (each has a stable `code`)
src/app/api/errors.py      AppError → HTTP status + {"detail","code"}   ← extend for T6.1
src/app/api/deps.py        get_current_user, DB/settings/storage deps
src/app/api/*.py           routers: auth, projects, sharing, documents, health
src/app/services/          access (permission matrix), projects, sharing, documents, uploads, users
src/app/storage/           StorageBackend protocol, LocalStorage, dependency
src/app/db/migrations/     Alembic (versions/0001_initial_schema.py)
tests/conftest.py, tests/database.py, tests/factories.py   shared fixtures/helpers
tests/api/                 endpoint tests                     ← add the E2E scenario here
```

---

**Suggested first prompt for the next session:**
"Read HANDOVER.md and specification.md. Make sure PostgreSQL is running and the test suite
passes on `main`, then implement the remaining work starting at T6.1, one task at a time,
committing each task after tests, ruff and mypy pass."
