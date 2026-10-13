# Carry-over notes for later tasks (from reviewer nits)
- T1.4: merge the duplicated env-isolation fixtures from tests/test_config.py and tests/test_main.py into a shared tests/conftest.py.
- T1.4: app pins settings via app.dependency_overrides[get_settings]; fixtures must not blindly call dependency_overrides.clear() (re-apply or remove only own keys).
- T6.4/T6.5: src/app/main.py module-level __getattr__ makes mypy accept any name from app.main; consider `if TYPE_CHECKING: app: FastAPI`. Document the lazy app entry point in README.
- T6.x: Starlette TestClient/httpx deprecation warning.
- T1.3: add a test that runs `alembic upgrade head` on an empty DB/schema and `downgrade base` (the create_all-based model tests can't catch migration-only problems like the iteration-1 duplicate CHECK).
