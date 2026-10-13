"""Schemas for the health check endpoint."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Liveness status of the API process."""

    status: Literal["ok"] = "ok"
