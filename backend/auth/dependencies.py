"""FastAPI authentication dependencies."""
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader
from jose import JWTError
from sqlalchemy import select

from backend.db.postgres import async_session
from backend.auth.models import User
from backend.auth.jwt_handler import verify_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    api_key: Optional[str] = Depends(api_key_header),
) -> User:
    """Extract and validate the current user from JWT token or API key."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Try API key first
    if api_key:
        async with async_session() as db:
            result = await db.execute(select(User).where(User.api_key == api_key))
            user = result.scalar_one_or_none()
            if user and user.is_active:
                return user
        raise credentials_exception

    # Then try JWT
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
        return await get_current_user(token=token, api_key=api_key)
    except HTTPException:
        return None
