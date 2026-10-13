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
