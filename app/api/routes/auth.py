from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.cookies import clear_auth_cookie, set_auth_cookie
from app.core.database import get_db
from app.models.user import User
from app.schemas.user import Token, UserLogin, UserResponse
from app.services.auth_service import AuthService, get_current_admin

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(data: UserLogin, db: Session = Depends(get_db)) -> JSONResponse:
    """Admin-only API login. Public registration is disabled."""
    user = AuthService.authenticate(db, login=data.login, password=data.password)
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    token = AuthService.create_access_token(user.id)
    payload = Token(access_token=token).model_dump()
    response = JSONResponse(content=payload)
    set_auth_cookie(response, token)
    return response


@router.post("/logout")
def logout() -> JSONResponse:
    response = JSONResponse(content={"ok": True})
    clear_auth_cookie(response)
    return response


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_admin)) -> UserResponse:
    return UserResponse.model_validate(current_user)
