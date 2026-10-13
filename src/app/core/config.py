"""Application configuration.

Settings are read from environment variables and, if present, from a ``.env`` file in the
current working directory. Real environment variables take precedence over ``.env``.

Use :func:`get_settings` everywhere (it is cached, so the environment is read once) and inject
it into endpoints with ``Depends(get_settings)`` / :data:`SettingsDep`. Tests can override it via
``app.dependency_overrides[get_settings]`` or reset it with ``get_settings.cache_clear()``.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from fastapi import Depends
from pydantic import Field, PositiveInt, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Design decision D8: images (png, jpg/jpeg, gif, webp), pdf, doc, docx.
DEFAULT_ALLOWED_CONTENT_TYPES: Final[tuple[str, ...]] = (
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)

DEFAULT_DATABASE_URL: Final = "postgresql+psycopg://postgres:postgres@localhost:5432/pm_app"

_BYTES_PER_MB: Final = 1024 * 1024


class ConfigurationError(RuntimeError):
    """Raised when the application settings are missing or invalid."""


class Settings(BaseSettings):
    """Typed application settings (environment variable names are case-insensitive)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    database_url: str = Field(default=DEFAULT_DATABASE_URL, min_length=1)

    # Required: there is deliberately no default, so a missing secret fails at startup.
    jwt_secret: SecretStr
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_expire_minutes: PositiveInt = 60

    # Only the local backend exists for now; "s3" is an optional later addition (D9).
    storage_backend: Literal["local"] = "local"
    storage_dir: Path = Path("./storage")
    max_upload_size_mb: PositiveInt = 10
    allowed_content_types: Annotated[tuple[str, ...], NoDecode] = DEFAULT_ALLOWED_CONTENT_TYPES

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_not_blank(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("JWT_SECRET must not be empty")
        return value

    @field_validator("allowed_content_types", mode="before")
    @classmethod
    def _parse_content_types(cls, value: Any) -> Any:
        """Accept a comma-separated string (``a/b,c/d``) or a JSON array; lowercase and dedupe."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                try:
                    value = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ValueError("ALLOWED_CONTENT_TYPES is not a valid JSON array") from exc
            else:
                value = stripped.split(",")
        if isinstance(value, list | tuple | set | frozenset):
            items = [item.strip().lower() if isinstance(item, str) else item for item in value]
            items = [item for item in items if item != ""]
            if not items:
                raise ValueError("ALLOWED_CONTENT_TYPES must contain at least one content type")
            for item in items:
                if not isinstance(item, str) or "/" not in item:
                    raise ValueError(f"invalid content type in ALLOWED_CONTENT_TYPES: {item!r}")
            # De-duplicate while keeping the configured order.
            return tuple(dict.fromkeys(items))
        return value

    @property
    def max_upload_size_bytes(self) -> int:
        """Maximum accepted upload size in bytes."""
        return self.max_upload_size_mb * _BYTES_PER_MB


def _format_validation_error(error: ValidationError) -> str:
    lines = []
    for item in error.errors():
        name = ".".join(str(part) for part in item["loc"]).upper() or "<settings>"
        if item["type"] == "missing":
            message = "is required but not set (environment variable or .env file)"
        else:
            message = item["msg"]
        lines.append(f"  - {name}: {message}")
    return "Invalid application configuration:\n" + "\n".join(lines)


def load_settings(**overrides: Any) -> Settings:
    """Build :class:`Settings`; validation errors become a readable :class:`ConfigurationError`.

    ``overrides`` are passed to the ``Settings`` constructor (e.g. ``_env_file=None``).
    """
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        # ``from None``: the formatted message is complete, and the original error's
        # traceback could echo raw input values (e.g. secrets) into logs.
        raise ConfigurationError(_format_validation_error(exc)) from None


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (cached). FastAPI dependency."""
    return load_settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]
