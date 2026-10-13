"""Unit tests for application settings (``app.core.config``)."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import (
    DEFAULT_ALLOWED_CONTENT_TYPES,
    ConfigurationError,
    Settings,
    SettingsDep,
    get_settings,
    load_settings,
)

# The setting variables of the developer's environment are removed for every test (see
# conftest.py); `isolated_env` also hides any `.env` file by switching to an empty directory.
pytestmark = pytest.mark.usefixtures("isolated_env")


def test_missing_jwt_secret_fails_clearly() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        load_settings()

    message = str(exc_info.value)
    assert "JWT_SECRET" in message
    assert "required" in message
    assert exc_info.value.__cause__ is None


def test_get_settings_fails_clearly_without_jwt_secret() -> None:
    with pytest.raises(ConfigurationError, match="JWT_SECRET"):
        get_settings()


@pytest.mark.parametrize("secret", ["", "   "])
def test_blank_jwt_secret_is_rejected(monkeypatch: pytest.MonkeyPatch, secret: str) -> None:
    monkeypatch.setenv("JWT_SECRET", secret)

    with pytest.raises(ConfigurationError, match="JWT_SECRET"):
        load_settings()


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret")

    settings = load_settings()

    assert settings.jwt_secret.get_secret_value() == "test-secret"
    assert settings.database_url == "postgresql+psycopg://postgres:postgres@localhost:5432/pm_app"
    assert settings.jwt_algorithm == "HS256"
    assert settings.jwt_expire_minutes == 60
    assert settings.storage_backend == "local"
    assert settings.storage_dir == Path("storage")
    assert settings.max_upload_size_mb == 10
    assert settings.max_upload_size_bytes == 10 * 1024 * 1024
    assert settings.allowed_content_types == DEFAULT_ALLOWED_CONTENT_TYPES


def test_default_content_types_match_d8() -> None:
    assert set(DEFAULT_ALLOWED_CONTENT_TYPES) == {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }


def test_secret_is_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "super-secret-value")

    settings = load_settings()

    assert "super-secret-value" not in repr(settings)
    assert "super-secret-value" not in str(settings)


def test_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/other")
    monkeypatch.setenv("JWT_SECRET", "s3cr3t")
    monkeypatch.setenv("JWT_ALGORITHM", "HS512")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "15")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "docs"))
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "25")

    settings = load_settings()

    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/other"
    assert settings.jwt_algorithm == "HS512"
    assert settings.jwt_expire_minutes == 15
    assert settings.storage_dir == tmp_path / "docs"
    assert settings.max_upload_size_mb == 25
    assert settings.max_upload_size_bytes == 25 * 1024 * 1024


def test_env_var_names_are_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("jwt_secret", "lower-case")

    assert load_settings().jwt_secret.get_secret_value() == "lower-case"


def test_reads_dotenv_file_from_working_directory(isolated_env: Path) -> None:
    (isolated_env / ".env").write_text(
        "JWT_SECRET=from-dotenv\nJWT_EXPIRE_MINUTES=5\nUNRELATED_VARIABLE=ignored\n",
        encoding="utf-8",
    )

    settings = load_settings()

    assert settings.jwt_secret.get_secret_value() == "from-dotenv"
    assert settings.jwt_expire_minutes == 5


def test_environment_takes_precedence_over_dotenv(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (isolated_env / ".env").write_text("JWT_SECRET=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("JWT_SECRET", "from-environment")

    assert load_settings().jwt_secret.get_secret_value() == "from-environment"


def test_dotenv_can_be_disabled(isolated_env: Path) -> None:
    (isolated_env / ".env").write_text("JWT_SECRET=from-dotenv\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="JWT_SECRET"):
        load_settings(_env_file=None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("image/png", ("image/png",)),
        ("image/png,application/pdf", ("image/png", "application/pdf")),
        (" image/png , Application/PDF ,", ("image/png", "application/pdf")),
        ("image/png,image/png,application/pdf", ("image/png", "application/pdf")),
        ('["image/png", "application/pdf"]', ("image/png", "application/pdf")),
    ],
)
def test_allowed_content_types_parsing(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: tuple[str, ...]
) -> None:
    monkeypatch.setenv("JWT_SECRET", "x")
    monkeypatch.setenv("ALLOWED_CONTENT_TYPES", raw)

    assert load_settings().allowed_content_types == expected


def test_allowed_content_types_accepts_python_list() -> None:
    settings = Settings(
        jwt_secret="x",  # type: ignore[arg-type]
        allowed_content_types=["IMAGE/PNG", "application/pdf"],  # type: ignore[arg-type]
        _env_file=None,
    )

    assert settings.allowed_content_types == ("image/png", "application/pdf")


@pytest.mark.parametrize("raw", ["", " , ", "[]", "image/png,notamimetype", "[not json"])
def test_invalid_allowed_content_types_are_rejected(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("JWT_SECRET", "x")
    monkeypatch.setenv("ALLOWED_CONTENT_TYPES", raw)

    with pytest.raises(ConfigurationError, match="ALLOWED_CONTENT_TYPES"):
        load_settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JWT_EXPIRE_MINUTES", "0"),
        ("JWT_EXPIRE_MINUTES", "abc"),
        ("MAX_UPLOAD_SIZE_MB", "-1"),
        ("JWT_ALGORITHM", "none"),
        ("JWT_ALGORITHM", "RS256"),
        ("STORAGE_BACKEND", "ftp"),
    ],
)
def test_invalid_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv("JWT_SECRET", "x")
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationError, match=name):
        load_settings()


def test_settings_are_immutable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "x")
    settings = load_settings()

    with pytest.raises(ValueError, match="frozen"):
        settings.jwt_expire_minutes = 1  # type: ignore[misc]


def test_get_settings_is_cached_and_cache_can_be_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JWT_SECRET", "first")
    first = get_settings()
    monkeypatch.setenv("JWT_SECRET", "second")

    assert get_settings() is first

    get_settings.cache_clear()

    assert get_settings().jwt_secret.get_secret_value() == "second"


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/settings-probe")
    def probe(settings: SettingsDep) -> dict[str, int]:
        return {"jwt_expire_minutes": settings.jwt_expire_minutes}

    return app


def test_settings_are_injectable_as_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "x")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "42")

    with TestClient(_make_app()) as client:
        response = client.get("/settings-probe")

    assert response.status_code == 200
    assert response.json() == {"jwt_expire_minutes": 42}


def test_settings_dependency_can_be_overridden() -> None:
    # No JWT_SECRET in the environment: get_settings() itself would fail, so a 200 proves
    # the override is used instead.
    app = _make_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        jwt_secret="override",  # type: ignore[arg-type]
        jwt_expire_minutes=7,
        _env_file=None,
    )

    with TestClient(app) as client:
        response = client.get("/settings-probe")

    assert response.status_code == 200
    assert response.json() == {"jwt_expire_minutes": 7}
