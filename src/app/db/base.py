"""Declarative base class shared by all ORM models."""

from typing import Final

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint and index names, so Alembic autogenerate produces stable,
# reviewable migrations (and constraints can be dropped by name in downgrades).
NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for the ORM models in :mod:`app.models`.

    ``Base.metadata`` is the target metadata for Alembic migrations.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
