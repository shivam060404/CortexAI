"""Authentication routes for CortexAI."""
import secrets

from fastapi import APIRouter, HTTPException, status, Depends, Request
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from sqlalchemy import select
from jose import JWTError

from backend.config import settings
from backend.db.postgres import async_session
from backend.auth.models import User
from backend.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    verify_token,
    TokenResponse,
)
from backend.auth.oauth import (
    get_google_auth_url,
    handle_google_callback,
    get_github_auth_url,
    handle_github_callback,
)
from backend.auth.dependencies import get_current_active_user
from backend.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ─── Request/Response Schemas ───


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str | None
    avatar_url: str | None
    provider: str
    is_active: bool

    class Config:
        from_attributes = True


class OAuthCallbackRequest(BaseModel):
    code: str
    redirect_uri: str


# ─── Endpoints ───


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest):
    """Register a new user with email/password."""
    async with async_session() as db:
        existing = await db.execute(select(User).where(User.email == req.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")

        user = User(
            email=req.email,
            hashed_password=pwd_context.hash(req.password),
            full_name=req.full_name,
            provider="local",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    logger.info("user_registered", email=req.email)
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    """Login with email/password and receive JWT tokens."""
    async with async_session() as db:
        result = await db.execute(select(User).where(User.email == req.email))
        user = result.scalar_one_or_none()

    if not user or not user.hashed_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not pwd_context.verify(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    logger.info("user_login", email=req.email)
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: Request):
    """Refresh access token using a valid refresh token."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Refresh token required")

    token = auth_header.split(" ")[1]
    try:
        payload = verify_token(token)
        if payload.type != "refresh":
            raise HTTPException(status_code=401, detail="Not a refresh token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    return TokenResponse(
        access_token=create_access_token(payload.sub),
        refresh_token=create_refresh_token(payload.sub),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_active_user)):
    """Get the current authenticated user's profile."""
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        avatar_url=current_user.avatar_url,
        provider=current_user.provider,
        is_active=current_user.is_active,
    )


@router.post("/api-key")
async def generate_api_key(current_user: User = Depends(get_current_active_user)):
    """Generate a new API key for the current user."""
    new_key = f"ctx_{secrets.token_hex(24)}"

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == current_user.id))
        user = result.scalar_one()
        user.api_key = new_key
        await db.commit()

    logger.info("api_key_generated", user_id=str(current_user.id))
    return {"api_key": new_key}


# ─── OAuth2 Endpoints ───


@router.get("/google")
async def google_login(redirect_uri: str):
    """Get Google OAuth2 authorization URL."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")
    url = get_google_auth_url(redirect_uri)
    return {"auth_url": url}


@router.post("/google/callback", response_model=TokenResponse)
async def google_callback(req: OAuthCallbackRequest):
    """Handle Google OAuth2 callback."""
    try:
        user, tokens = await handle_google_callback(req.code, req.redirect_uri)
        logger.info("google_oauth_success", email=user.email)
        return tokens
    except Exception as e:
        logger.error("google_oauth_error", error=str(e))
        raise HTTPException(status_code=400, detail=f"Google OAuth failed: {str(e)}")


@router.get("/github")
async def github_login(redirect_uri: str):
    """Get GitHub OAuth2 authorization URL."""
    if not settings.GITHUB_CLIENT_ID:
        raise HTTPException(status_code=501, detail="GitHub OAuth not configured")
    url = get_github_auth_url(redirect_uri)
    return {"auth_url": url}


@router.post("/github/callback", response_model=TokenResponse)
async def github_callback(req: OAuthCallbackRequest):
    """Handle GitHub OAuth2 callback."""
    try:
        user, tokens = await handle_github_callback(req.code, req.redirect_uri)
        logger.info("github_oauth_success", email=user.email)
        return tokens
    except Exception as e:
        logger.error("github_oauth_error", error=str(e))
        raise HTTPException(status_code=400, detail=f"GitHub OAuth failed: {str(e)}")
