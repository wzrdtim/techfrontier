from __future__ import annotations
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.user import TokenData

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


class AuthService:
    @staticmethod
    def hash_password(password: str) -> str:
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        return pwd_context.verify(plain, hashed)

    @staticmethod
    def create_access_token(user_id: int) -> str:
        settings = get_settings()
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.access_token_expire_minutes
        )
        payload = {"sub": str(user_id), "exp": expire}
        return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

    @staticmethod
    def decode_token(token: str) -> TokenData:
        settings = get_settings()
        try:
            payload = jwt.decode(
                token,
                settings.secret_key,
                algorithms=[settings.algorithm],
            )
            user_id = payload.get("sub")
            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token",
                )
            return TokenData(user_id=int(user_id))
        except (JWTError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            ) from exc

    @staticmethod
    def get_by_email(db: Session, email: str) -> User | None:
        return db.execute(select(User).where(User.email == email)).scalar_one_or_none()

    @staticmethod
    def get_by_username(db: Session, username: str) -> User | None:
        return db.execute(
            select(User).where(User.username == username)
        ).scalar_one_or_none()

    @staticmethod
    def get_by_id(db: Session, user_id: int) -> User | None:
        return db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()

    @staticmethod
    def authenticate(db: Session, login: str, password: str) -> User:
        identifier = login.strip()
        user = AuthService.get_by_username(db, identifier)
        if user is None and "@" in identifier:
            user = AuthService.get_by_email(db, identifier.lower())
        if not user or not AuthService.verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Inactive user",
            )
        return user

    @staticmethod
    def ensure_admin_user(db: Session) -> User:
        settings = get_settings()
        user = AuthService.get_by_username(db, settings.admin_username)
        if user is None:
            user = AuthService.get_by_email(db, settings.admin_email)

        if user is None:
            user = User(
                email=settings.admin_email,
                username=settings.admin_username,
                hashed_password=AuthService.hash_password(settings.admin_password),
                is_admin=True,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user

        changed = False
        if not user.is_admin:
            user.is_admin = True
            changed = True
        if user.username != settings.admin_username:
            existing = AuthService.get_by_username(db, settings.admin_username)
            if existing is None or existing.id == user.id:
                user.username = settings.admin_username
                changed = True
        if user.email != settings.admin_email:
            existing_email = AuthService.get_by_email(db, settings.admin_email)
            if existing_email is None or existing_email.id == user.id:
                user.email = settings.admin_email
                changed = True
        # Sync password from .env only when it actually changed.
        if not AuthService.verify_password(settings.admin_password, user.hashed_password):
            user.hashed_password = AuthService.hash_password(settings.admin_password)
            changed = True
        if changed:
            db.commit()
            db.refresh(user)
        return user


def _user_from_token(db: Session, token: str) -> User:
    token_data = AuthService.decode_token(token)
    user = AuthService.get_by_id(db, token_data.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


def get_token_from_request(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str | None:
    settings = get_settings()
    if credentials is not None:
        return credentials.credentials
    return (
        request.cookies.get(settings.auth_cookie_name)
        or request.cookies.get(settings.admin_cookie_name)
    )


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = get_token_from_request(request, credentials)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _user_from_token(db, token)


def get_current_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    user = get_current_user(request, credentials, db)
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


def require_admin_page(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    from app.core.exceptions import AdminLoginRequired

    token = get_token_from_request(request, credentials)
    if token is None:
        raise AdminLoginRequired()
    try:
        user = _user_from_token(db, token)
    except HTTPException as exc:
        raise AdminLoginRequired() from exc
    if not user.is_admin:
        raise AdminLoginRequired()
    return user


def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    token = get_token_from_request(request, credentials)
    if token is None:
        return None
    try:
        return _user_from_token(db, token)
    except HTTPException:
        return None
