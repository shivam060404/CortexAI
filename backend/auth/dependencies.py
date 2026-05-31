"""FastAPI authentication dependencies."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader
from jose import JWTError
from sqlalchemy import or_, select

from backend.db.postgres import async_session
from backend.auth.models import User
from backend.auth.api_keys import api_key_matches, hash_api_key
from backend.auth.jwt_handler import verify_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def _resolve_user_from_credentials(
    token: Optional[str],
    api_key: Optional[str],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if api_key:
        async with async_session() as db:
            result = await db.execute(
                select(User).where(
                    or_(
                        User.api_key == api_key,
                        User.api_key == hash_api_key(api_key),
                    )
                )
            )
            candidates = result.scalars().all()
            user = next((candidate for candidate in candidates if api_key_matches(api_key, candidate.api_key)), None)
            if user and user.is_active:
                return user
        raise credentials_exception

    if not token:
        raise credentials_exception

    try:
        payload = verify_token(token)
        if payload.type != "access":
            raise credentials_exception
        user_id = payload.sub
    except JWTError:
        raise credentials_exception

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception
    return user


def _extract_token_from_request(request: Request) -> tuple[Optional[str], Optional[str]]:
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else None
    api_key = request.headers.get("X-API-Key")
    return token, api_key


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    api_key: Optional[str] = Depends(api_key_header),
) -> User:
    """Extract and validate the current user from JWT token or API key."""
    return await _resolve_user_from_credentials(token=token, api_key=api_key)


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """Ensure user is active."""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def get_optional_user(
    token: Optional[str] = Depends(oauth2_scheme),
    api_key: Optional[str] = Depends(api_key_header),
) -> Optional[User]:
    """Get current user if authenticated, None otherwise. No error raised."""
    if not token and not api_key:
        return None
    try:
        return await _resolve_user_from_credentials(token=token, api_key=api_key)
    except HTTPException:
        return None


async def get_optional_user_from_request(request: Request) -> Optional[User]:
    """Resolve a user directly from request headers for middleware."""
    token, api_key = _extract_token_from_request(request)
    try:
        return await _resolve_user_from_credentials(token=token, api_key=api_key)
    except HTTPException:
        return None
