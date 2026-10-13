# Project Management Software (backend)

A FastAPI + PostgreSQL backend for managing projects, sharing them with other users,
and storing project documents. See [TASK_SPECIFICATION.md](TASK_SPECIFICATION.md) for the
requirements and [specification.md](specification.md) for the task breakdown and design decisions.

> This README is a stub; full documentation will be added later.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL (or Docker)

## Quick start

```bash
uv sync                 # create .venv and install runtime + dev dependencies
cp .env.example .env    # then edit the values
```

## Development

```bash
uv run ruff check .         # lint
uv run ruff format .        # format
uv run mypy                 # type check (strict)
uv run pytest               # tests
uv run pytest --cov         # tests with coverage
```

Tests need a running PostgreSQL. They use the database in the `TEST_DATABASE_URL` environment
variable (default `postgresql+psycopg://postgres:postgres@localhost:5432/pm_test`), create their
tables in a temporary schema that is dropped afterwards, and roll back every test's changes
(see `tests/conftest.py`).

## Database migrations

Alembic is configured in `alembic.ini` (repository root); the migrations live in
`src/app/db/migrations/versions/`. The database URL is `DATABASE_URL` from the environment or
`.env` (the same value the app uses); override it with `-x dburl=...`.

```bash
uv run alembic upgrade head      # create / update the schema
uv run alembic downgrade base    # drop everything again
uv run alembic current           # show the applied revision
uv run alembic check             # fail if the models and migrations have drifted apart
uv run alembic revision --autogenerate --rev-id 0002 -m "describe the change"
```

## Layout

```
src/app/
  core/          # config, security (JWT, hashing), errors
  db/            # engine, session, base, migrations
  models/        # SQLAlchemy models
  schemas/       # Pydantic schemas
  repositories/  # DB access
  services/      # business logic + permission checks
  storage/       # StorageBackend, LocalStorage, (S3Storage)
  api/           # routers: auth, projects, documents, sharing
tests/
```
