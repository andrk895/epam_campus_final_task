"""Tests for the application factory (``app.main``) and the health check endpoint."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from uvicorn.importer import import_from_string

import app.main as main_module
from app import __version__
from app.core.config import ConfigurationError, Settings, SettingsDep, get_settings
from app.main import API_TITLE, create_app

SETTING_ENV_VARS = {
    "DATABASE_URL",
    "JWT_SECRET",
    "JWT_ALGORITHM",
    "JWT_EXPIRE_MINUTES",
    "STORAGE_BACKEND",
    "STORAGE_DIR",
    "MAX_UPLOAD_SIZE_MB",
    "ALLOWED_CONTENT_TYPES",
}


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Hide the developer's environment and `.env`, and reset the cached settings and app."""
    for name in list(os.environ):
        if name.upper() in SETTING_ENV_VARS:
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    main_module._get_default_app.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
    main_module._get_default_app.cache_clear()


def make_settings(**overrides: object) -> Settings:
    """Settings built only from the arguments (no environment, no `.env`)."""
    values: dict[str, object] = {"jwt_secret": "test-secret", "_env_file": None, **overrides}
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(settings=make_settings())) as test_client:
        yield test_client


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok"}


def test_docs_ui_is_served(client: TestClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "swagger-ui" in response.text
    assert API_TITLE in response.text


def test_openapi_schema_is_served(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == API_TITLE
    assert schema["info"]["version"] == __version__
    assert "get" in schema["paths"]["/health"]
    assert schema["paths"]["/health"]["get"]["tags"] == ["health"]


def test_create_app_fails_clearly_without_jwt_secret() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        create_app()

    assert "JWT_SECRET" in str(exc_info.value)
    assert "required" in str(exc_info.value)


def test_create_app_loads_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "from-environment")

    app = create_app()

    assert isinstance(app.state.settings, Settings)
    assert app.state.settings.jwt_secret.get_secret_value() == "from-environment"


def _add_settings_probe(app: FastAPI) -> None:
    @app.get("/settings-probe")
    def probe(settings: SettingsDep) -> dict[str, int]:
        return {"jwt_expire_minutes": settings.jwt_expire_minutes}


def test_settings_passed_to_create_app_are_injected() -> None:
    # No JWT_SECRET in the environment: a 200 proves get_settings() itself is never called.
    settings = make_settings(jwt_expire_minutes=7)
    app = create_app(settings=settings)
    _add_settings_probe(app)

    with TestClient(app) as client:
        response = client.get("/settings-probe")

    assert app.state.settings is settings
    assert response.status_code == 200
    assert response.json() == {"jwt_expire_minutes": 7}


def test_importing_main_does_not_build_the_app() -> None:
    # The module is already imported (above) with no settings in the environment for this
    # test; the ASGI app is only created when `app.main.app` is accessed.
    assert "app" not in vars(main_module)
    with pytest.raises(AttributeError, match="no attribute 'missing'"):
        _ = main_module.missing


def test_uvicorn_entry_point_fails_at_startup_without_jwt_secret() -> None:
    with pytest.raises(ConfigurationError, match="JWT_SECRET"):
        import_from_string("app.main:app")


def test_uvicorn_entry_point_builds_app_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "x")

    asgi_app = import_from_string("app.main:app")

    assert isinstance(asgi_app, FastAPI)
    assert main_module.app is asgi_app
    with TestClient(asgi_app) as client:
        assert client.get("/health").json() == {"status": "ok"}
