from __future__ import annotations

import secrets
from typing import Any

from fastapi import HTTPException, Request, status
from starlette.responses import Response

from app.core.config import get_settings

CSRF_HEADER = "X-CSRF-Token"
CSRF_FORM_FIELD = "csrf_token"


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def get_csrf_token(request: Request) -> str | None:
    return request.cookies.get(get_settings().csrf_cookie_name)


def ensure_csrf_token(request: Request) -> str:
    existing = get_csrf_token(request)
    if existing:
        return existing
    return generate_csrf_token()


def set_csrf_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=token,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(get_settings().csrf_cookie_name, path="/")


def tokens_match(expected: str | None, submitted: str | None) -> bool:
    if not expected or not submitted:
        return False
    return secrets.compare_digest(expected, submitted)


async def _submitted_csrf_token(request: Request) -> str | None:
    header = request.headers.get(CSRF_HEADER)
    if header:
        return header.strip() or None

    content_type = request.headers.get("content-type", "")
    if (
        "application/x-www-form-urlencoded" in content_type
        or "multipart/form-data" in content_type
    ):
        form = await request.form()
        value: Any = form.get(CSRF_FORM_FIELD)
        if value is None:
            return None
        if hasattr(value, "filename"):
            return None
        return str(value).strip() or None
    return None


async def require_csrf(request: Request) -> None:
    """Reject state-changing admin requests without a valid double-submit CSRF token."""
    cookie = get_csrf_token(request)
    submitted = await _submitted_csrf_token(request)
    if not tokens_match(cookie, submitted):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing or invalid",
        )
