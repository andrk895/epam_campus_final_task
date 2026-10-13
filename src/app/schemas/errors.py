"""Schema of the error responses produced for domain exceptions."""

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Body of an error response: a human-readable detail and a stable machine-readable code."""

    detail: str
    code: str
