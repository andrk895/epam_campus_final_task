"""Health check endpoint."""

from fastapi import APIRouter

from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness check")
def health() -> HealthResponse:
    """Return ``{"status": "ok"}`` while the process is up and serving requests.

    This is a liveness probe only: it does not check the database or the storage backend.
    """
    return HealthResponse(status="ok")
