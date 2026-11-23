from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session

_password_hash = PasswordHash.recommended()
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    if len(settings.jwt_secret_key) < 32:
        raise RuntimeError("JWT_SECRET_KEY must contain at least 32 characters")
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.jwt_access_token_minutes)
    return jwt.encode(
        {"sub": user_id, "iss": settings.jwt_issuer, "iat": now, "exp": expires},
        settings.jwt_secret_key,
        algorithm="HS256",
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    settings = get_settings()
    if len(settings.jwt_secret_key) < 32:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    try:
        claims = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
        user_id = str(UUID(claims["sub"]))
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise unauthorized from None
    result = await session.execute(
        text("SELECT id::text AS id, email, created_at FROM users WHERE id = :id AND disabled = false"),
        {"id": user_id},
    )
    user = result.mappings().first()
    if user is None:
        raise unauthorized
    return dict(user)
