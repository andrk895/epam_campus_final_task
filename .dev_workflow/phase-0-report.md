# Phase 0 report: Project setup ✅

**Tasks:** T0.1 skeleton (2 iterations), T0.2 configuration (1), T0.3 app + health check (1). All approved by the reviewer.

## Try it in the browser
The server is running with auto-reload at **http://localhost:8000**.

1. Open http://localhost:8000/docs. You'll see the Swagger UI for "Project Management API" v0.1.0.
2. Expand **GET /health** → *Try it out* → *Execute*. The response is `200 {"status": "ok"}`.

At this point the app only has a health check. Registration and login come in Phase 2, projects in Phase 3, and documents in Phase 5.

## What was built
- `pyproject.toml` managed by uv: FastAPI, SQLAlchemy 2, psycopg 3, Alembic, pydantic-settings, PyJWT, pwdlib[argon2]; ruff, strict mypy and pytest are configured.
- `src/app/core/config.py`: typed settings loaded from environment variables and `.env`. A missing `JWT_SECRET` stops the app at startup with a clear error.
- `src/app/main.py`: a `create_app()` factory and the `GET /health` endpoint.

## Checks
- `ruff check` ✅, `ruff format --check` ✅, `mypy` (strict, src + tests) ✅
- `pytest`: **43 passed**. There is one deprecation warning from the installed Starlette/httpx versions.

## Worth knowing
- **No Docker on this machine.** PostgreSQL 16 runs locally on localhost:5432 (see `environment.md`). It's needed from Phase 1 on.
- **The `app` object is created when first used** (a module `__getattr__` in `main.py`). This lets tests import the code without a `.env`, while uvicorn still fails at startup if the config is bad. The reviewer accepted this.
- **Nothing is committed yet.** Approved work is staged with `git add`.
