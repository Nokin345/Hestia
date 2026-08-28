from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_session_token,
    current_authenticated,
    verify_credentials,
)
from app.config import get_settings
from app.db import get_db
from app.schemas.auth import AuthResponse, LoginRequest, LogoutResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)
):
    if not verify_credentials(body.username, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    settings = get_settings()
    token = create_session_token()
    response.set_cookie(
        key=settings.session_cookie,
        value=token,
        max_age=settings.session_max_age,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return AuthResponse(authenticated=True, username=body.username)


@router.post("/logout", response_model=LogoutResponse)
async def logout(response: Response):
    settings = get_settings()
    response.delete_cookie(settings.session_cookie, path="/")
    return LogoutResponse()


@router.get("/me", response_model=AuthResponse)
async def me(request: Request):
    return AuthResponse(
        authenticated=current_authenticated(request),
        username=get_settings().auth_username if current_authenticated(request) else "",
    )
