"""Authentication routes for CortexAI."""

from fastapi import APIRouter, HTTPException, Depends, Request
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
from backend.auth.api_keys import generate_api_key_pair
from backend.api.schemas import RegisterRequest, LoginRequest, OAuthCallbackRequest, UserResponse
from backend.core.audit import audit_logger
from backend.core.logger import get_logger
from backend.auth.organization import (
    create_organization,
    get_user_organizations,
    add_member,
    list_members,
)
from backend.auth.api_key_manager import (
    create_api_key,
    list_api_keys,
    revoke_api_key,
    delete_api_key,
    rotate_api_key,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


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
    await audit_logger.log("register", user_id=str(user.id), details={"email": req.email})
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
    await audit_logger.log("login", user_id=str(user.id), details={"email": req.email})
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
        organization_id=str(getattr(current_user, "organization_id", None) or current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        avatar_url=current_user.avatar_url,
        provider=current_user.provider,
        role=("admin" if bool(getattr(current_user, "is_admin", False)) else getattr(current_user, "role", "owner")),
        is_active=current_user.is_active,
    )


@router.post("/api-key")
async def generate_api_key(current_user: User = Depends(get_current_active_user)):
    """Generate a new API key for the current user."""
    raw_api_key, stored_api_key = generate_api_key_pair()

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == current_user.id))
        user = result.scalar_one()
        user.api_key = stored_api_key
        await db.commit()

    logger.info("api_key_generated", user_id=str(current_user.id))
    await audit_logger.log("api_key_generated", user_id=str(current_user.id))
    return {"api_key": raw_api_key}


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
        await audit_logger.log("login", user_id=str(user.id), details={"provider": "google", "email": user.email})
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
        await audit_logger.log("login", user_id=str(user.id), details={"provider": "github", "email": user.email})
        return tokens
    except Exception as e:
        logger.error("github_oauth_error", error=str(e))
        raise HTTPException(status_code=400, detail=f"GitHub OAuth failed: {str(e)}")


# ─── Organization Endpoints (Feature Gap #1) ───


@router.post("/organizations")
async def create_org(req: dict, current_user: User = Depends(get_current_active_user)):
    """Create a new organization."""
    name = req.get("name", "").strip()
    plan_type = req.get("plan_type", "free")
    if not name:
        raise HTTPException(status_code=400, detail="Organization name is required")
    try:
        org = await create_organization(name, str(current_user.id), plan_type=plan_type)
        await audit_logger.log("org_create", user_id=str(current_user.id), details={"org_id": org["id"]})
        return {"organization": org}
    except Exception as e:
        logger.error("create_org_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/organizations")
async def list_orgs(current_user: User = Depends(get_current_active_user)):
    """List all organizations the current user belongs to."""
    orgs = await get_user_organizations(str(current_user.id))
    return {"organizations": orgs}


@router.get("/organizations/{org_id}/members")
async def get_org_members(org_id: str, current_user: User = Depends(get_current_active_user)):
    """List members of an organization."""
    try:
        members = await list_members(org_id)
        return {"members": members}
    except Exception as e:
        logger.error("get_org_members_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/organizations/{org_id}/members")
async def add_org_member(org_id: str, req: dict, current_user: User = Depends(get_current_active_user)):
    """Add a member to an organization."""
    user_id = req.get("user_id", "").strip()
    role = req.get("role", "member")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    try:
        result = await add_member(org_id, user_id, role=role, invited_by=str(current_user.id))
        await audit_logger.log("org_member_add", user_id=str(current_user.id),
                               details={"org_id": org_id, "member_id": user_id, "role": role})
        return {"member": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("add_org_member_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ─── API Key Management Endpoints (Feature Gap #2) ───


@router.post("/api-keys")
async def create_key(req: dict, current_user: User = Depends(get_current_active_user)):
    """Create a new API key with optional scopes and rate limits."""
    name = req.get("name", "default")
    scopes = req.get("scopes")
    rate_limit = req.get("rate_limit", 60)
    expires_days = req.get("expires_days", 90)
    result = await create_api_key(
        str(current_user.id), name=name, scopes=scopes,
        rate_limit=rate_limit, expires_days=expires_days,
    )
    await audit_logger.log("api_key_create", user_id=str(current_user.id),
                           details={"key_id": result["id"], "name": name})
    return {"api_key": result}


@router.get("/api-keys")
async def get_api_keys(current_user: User = Depends(get_current_active_user)):
    """List all API keys for the current user."""
    keys = await list_api_keys(str(current_user.id))
    return {"api_keys": keys}


@router.delete("/api-keys/{key_id}")
async def remove_api_key(key_id: str, current_user: User = Depends(get_current_active_user)):
    """Delete an API key."""
    result = await delete_api_key(str(current_user.id), key_id)
    await audit_logger.log("api_key_delete", user_id=str(current_user.id), details={"key_id": key_id})
    return result


@router.post("/api-keys/{key_id}/revoke")
async def revoke_key(key_id: str, current_user: User = Depends(get_current_active_user)):
    """Revoke (deactivate) an API key."""
    result = await revoke_api_key(str(current_user.id), key_id)
    await audit_logger.log("api_key_revoke", user_id=str(current_user.id), details={"key_id": key_id})
    return result


@router.post("/api-keys/{key_id}/rotate")
async def rotate_key(key_id: str, current_user: User = Depends(get_current_active_user)):
    """Rotate an API key: creates a new key and schedules old key expiry."""
    try:
        result = await rotate_api_key(str(current_user.id), key_id)
        await audit_logger.log("api_key_rotate", user_id=str(current_user.id),
                               details={"old_key_id": key_id, "new_key_id": result["new_key"]["id"]})
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
