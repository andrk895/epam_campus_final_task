"""Registration (``POST /auth``) and login (``POST /login``)."""

from fastapi import APIRouter, status

from app.core.config import SettingsDep
from app.core.security import create_access_token
from app.db import DbSessionDep
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserRead
from app.schemas.errors import ErrorResponse
from app.services import users

router = APIRouter(tags=["auth"])


@router.post(
    "/auth",
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "Login taken"}},
)
def register(body: RegisterRequest, session: DbSessionDep) -> UserRead:
    """Create a user account. Logins are unique case-insensitively."""
    user = users.register_user(session, body.login, body.password)
    return UserRead.model_validate(user)


@router.post(
    "/login",
    summary="Log in and get an access token",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Wrong login or password",
        }
    },
)
def login(body: LoginRequest, session: DbSessionDep, settings: SettingsDep) -> TokenResponse:
    """Exchange a login and password for a bearer access token (valid for one hour)."""
    user = users.authenticate(session, body.login, body.password)
    return TokenResponse(
        access_token=create_access_token(user.id, settings),
        expires_in=settings.jwt_expire_minutes * 60,
    )
