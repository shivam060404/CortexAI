"""OAuth2 handlers for Google and GitHub."""
import httpx
from typing import Tuple

from sqlalchemy import select

from backend.config import settings
from backend.db.postgres import async_session
from backend.auth.models import User
from backend.auth.jwt_handler import create_access_token, create_refresh_token, TokenResponse
from backend.core.logger import get_logger

logger = get_logger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


def get_google_auth_url(redirect_uri: str) -> str:
    """Build Google OAuth2 authorization URL."""
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{GOOGLE_AUTH_URL}?{query}"


async def handle_google_callback(code: str, redirect_uri: str) -> Tuple[User, TokenResponse]:
    """Exchange Google auth code for user info and return/create user with tokens."""
    async with httpx.AsyncClient() as client:
        # Exchange code for token
        token_resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        token_data = token_resp.json()
        access_token = token_data.get("access_token")

        if not access_token:
            raise ValueError("Failed to get Google access token")

        # Get user info
        user_resp = await client.get(
            GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        user_info = user_resp.json()

    email = user_info.get("email")
    if not email:
        raise ValueError("Google account has no email")

    # Find or create user
    async with async_session() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                email=email,
                full_name=user_info.get("name"),
                avatar_url=user_info.get("picture"),
                provider="google",
                provider_id=user_info.get("id"),
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            logger.info("user_created_via_google", email=email)
        else:
            # Update avatar/name if changed
            user.avatar_url = user_info.get("picture") or user.avatar_url
            user.full_name = user_info.get("name") or user.full_name
            await db.commit()

    tokens = TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )
    return user, tokens


def get_github_auth_url(redirect_uri: str) -> str:
    """Build GitHub OAuth2 authorization URL."""
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "read:user user:email",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{GITHUB_AUTH_URL}?{query}"


async def handle_github_callback(code: str, redirect_uri: str) -> Tuple[User, TokenResponse]:
    """Exchange GitHub auth code for user info and return/create user with tokens."""
    async with httpx.AsyncClient() as client:
        # Exchange code for token
        token_resp = await client.post(GITHUB_TOKEN_URL, data={
            "code": code,
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
        }, headers={"Accept": "application/json"})
        token_data = token_resp.json()
        access_token = token_data.get("access_token")

        if not access_token:
            raise ValueError("Failed to get GitHub access token")

        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

        # Get user info
        user_resp = await client.get(GITHUB_USER_URL, headers=headers)
        user_info = user_resp.json()

        # Get primary email
        email_resp = await client.get(GITHUB_EMAILS_URL, headers=headers)
        emails = email_resp.json()
        primary_email = next((e["email"] for e in emails if e.get("primary")), None)

    email = primary_email or user_info.get("email")
    if not email:
        raise ValueError("GitHub account has no email")

    # Find or create user
    async with async_session() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                email=email,
                full_name=user_info.get("name") or user_info.get("login"),
                avatar_url=user_info.get("avatar_url"),
                provider="github",
                provider_id=str(user_info.get("id")),
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            logger.info("user_created_via_github", email=email)
        else:
            user.avatar_url = user_info.get("avatar_url") or user.avatar_url
            user.full_name = user_info.get("name") or user.full_name
            await db.commit()

    tokens = TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )
    return user, tokens
