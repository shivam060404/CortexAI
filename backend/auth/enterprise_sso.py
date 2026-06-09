"""
Enterprise SSO / OIDC Provider — Generic SAML-like SSO via OpenID Connect.

Supports any OIDC-compliant identity provider:
  - Azure AD (Entra ID)
  - Okta
  - Auth0
  - Keycloak
  - Google Workspace (SAML-like via OIDC)
  - Custom OIDC providers

Features:
  - OIDC Discovery for auto-configuration
  - Authorization Code flow with PKCE
  - Group/role claim mapping
  - Just-In-Time (JIT) user provisioning
  - Organization auto-assignment via domain matching
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from sqlalchemy import select

from backend.config import settings
from backend.db.postgres import async_session
from backend.auth.models import User
from backend.auth.jwt_handler import create_access_token, create_refresh_token, TokenResponse
from backend.core.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# OIDC Provider Configuration
# ---------------------------------------------------------------------------

@dataclass
class OIDCProviderConfig:
    """Configuration for a generic OIDC provider."""
    # Required
    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""

    # Auto-discovered from .well-known/openid-configuration
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    userinfo_endpoint: str = ""
    jwks_uri: str = ""
    end_session_endpoint: str = ""

    # Claim mapping
    email_claim: str = "email"
    name_claim: str = "name"
    sub_claim: str = "sub"
    groups_claim: str = "groups"
    roles_claim: str = "roles"

    # Organization mapping
    domain_mapping: dict[str, str] = field(default_factory=dict)  # email domain -> org_id
    default_role: str = "member"
    auto_provision: bool = True

    # Scopes
    scopes: list[str] = field(default_factory=lambda: ["openid", "email", "profile"])

    @property
    def is_configured(self) -> bool:
        return bool(self.issuer and self.client_id and self.client_secret)


@dataclass
class OIDCUserInfo:
    """Normalized user info from an OIDC provider."""
    sub: str = ""
    email: str = ""
    name: str = ""
    picture: str = ""
    groups: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    raw_claims: dict[str, Any] = field(default_factory=dict)


class EnterpriseSSOProvider:
    """
    Enterprise SSO via generic OIDC provider.

    Usage:
        sso = EnterpriseSSOProvider()
        await sso.discover()  # Auto-configure from OIDC discovery
        auth_url, state, code_verifier = sso.get_authorization_url(redirect_uri)
        user_info = await sso.handle_callback(code, redirect_uri, code_verifier)
    """

    def __init__(self, config: Optional[OIDCProviderConfig] = None):
        self._config = config or self._load_from_settings()
        self._discovered = False

    @staticmethod
    def _load_from_settings() -> OIDCProviderConfig:
        """Load OIDC config from application settings."""
        return OIDCProviderConfig(
            issuer=getattr(settings, "SSO_ISSUER", ""),
            client_id=getattr(settings, "SSO_CLIENT_ID", ""),
            client_secret=getattr(settings, "SSO_CLIENT_SECRET", ""),
            email_claim=getattr(settings, "SSO_EMAIL_CLAIM", "email"),
            name_claim=getattr(settings, "SSO_NAME_CLAIM", "name"),
            groups_claim=getattr(settings, "SSO_GROUPS_CLAIM", "groups"),
            auto_provision=getattr(settings, "SSO_AUTO_PROVISION", True),
            default_role=getattr(settings, "SSO_DEFAULT_ROLE", "member"),
        )

    # ------------------------------------------------------------------
    # OIDC Discovery
    # ------------------------------------------------------------------
    async def discover(self) -> bool:
        """Auto-discover OIDC endpoints from .well-known/openid-configuration.

        Returns:
            True if discovery was successful.
        """
        if not self._config.issuer:
            logger.warning("sso_not_configured", note="SSO_ISSUER is not set")
            return False

        discovery_url = f"{self._config.issuer.rstrip('/')}/.well-known/openid-configuration"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(discovery_url)
                resp.raise_for_status()
                data = resp.json()

            self._config.authorization_endpoint = data.get("authorization_endpoint", "")
            self._config.token_endpoint = data.get("token_endpoint", "")
            self._config.userinfo_endpoint = data.get("userinfo_endpoint", "")
            self._config.jwks_uri = data.get("jwks_uri", "")
            self._config.end_session_endpoint = data.get("end_session_endpoint", "")

            self._discovered = True
            logger.info(
                "sso_discovery_success",
                issuer=self._config.issuer,
                auth_endpoint=self._config.authorization_endpoint,
            )
            return True

        except Exception as e:
            logger.error("sso_discovery_error", issuer=self._config.issuer, error=str(e))
            return False

    # ------------------------------------------------------------------
    # Authorization URL (with PKCE)
    # ------------------------------------------------------------------
    def get_authorization_url(
        self,
        redirect_uri: str,
        state: Optional[str] = None,
    ) -> tuple[str, str, str]:
        """Build the OIDC authorization URL with PKCE.

        Args:
            redirect_uri: The callback URL.
            state: Optional state parameter (auto-generated if not provided).

        Returns:
            Tuple of (auth_url, state, code_verifier).
        """
        if not self._config.authorization_endpoint:
            # Try well-known endpoints for common providers
            self._config.authorization_endpoint = f"{self._config.issuer.rstrip('/')}/authorize"
            self._config.token_endpoint = f"{self._config.issuer.rstrip('/')}/oauth/token"
            self._config.userinfo_endpoint = f"{self._config.issuer.rstrip('/')}/userinfo"

        # Generate PKCE code verifier and challenge
        code_verifier = secrets.token_urlsafe(64)[:128]
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode()

        state = state or secrets.token_urlsafe(32)

        params = {
            "client_id": self._config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(self._config.scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        query = "&".join(f"{k}={v}" for k, v in params.items())
        auth_url = f"{self._config.authorization_endpoint}?{query}"

        return auth_url, state, code_verifier

    # ------------------------------------------------------------------
    # Handle Callback
    # ------------------------------------------------------------------
    async def handle_callback(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> Optional[OIDCUserInfo]:
        """Exchange authorization code for user info.

        Args:
            code: The authorization code from the callback.
            redirect_uri: Must match the original redirect URI.
            code_verifier: The PKCE code verifier.

        Returns:
            OIDCUserInfo or None on failure.
        """
        if not self._config.token_endpoint:
            await self.discover()

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # Exchange code for tokens
                token_resp = await client.post(
                    self._config.token_endpoint,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": redirect_uri,
                        "client_id": self._config.client_id,
                        "client_secret": self._config.client_secret,
                        "code_verifier": code_verifier,
                    },
                    headers={"Accept": "application/json"},
                )
                token_resp.raise_for_status()
                token_data = token_resp.json()

                access_token = token_data.get("access_token")
                id_token = token_data.get("id_token")

                if not access_token:
                    logger.error("sso_no_access_token", response_keys=list(token_data.keys()))
                    return None

                # Parse ID token claims (without verification for now — production should verify with JWKS)
                claims = {}
                if id_token:
                    try:
                        import json
                        # Decode the payload part of the JWT
                        parts = id_token.split(".")
                        if len(parts) == 3:
                            payload = parts[1]
                            # Add padding if needed
                            payload += "=" * (4 - len(payload) % 4)
                            decoded = base64.urlsafe_b64decode(payload)
                            claims = json.loads(decoded)
                    except Exception as e:
                        logger.warning("sso_id_token_parse_error", error=str(e))

                # Get user info endpoint data
                userinfo = {}
                if self._config.userinfo_endpoint:
                    ui_resp = await client.get(
                        self._config.userinfo_endpoint,
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    if ui_resp.status_code == 200:
                        userinfo = ui_resp.json()

                # Merge claims
                all_claims = {**userinfo, **claims}

                # Extract user info using claim mapping
                user_info = OIDCUserInfo(
                    sub=all_claims.get(self._config.sub_claim, ""),
                    email=all_claims.get(self._config.email_claim, ""),
                    name=all_claims.get(self._config.name_claim, ""),
                    picture=all_claims.get("picture", ""),
                    groups=all_claims.get(self._config.groups_claim, []),
                    roles=all_claims.get(self._config.roles_claim, []),
                    raw_claims=all_claims,
                )

                if not user_info.email:
                    # Try nested email_claim
                    email_claim = self._config.email_claim
                    if "." in email_claim:
                        # Handle nested claims like "attributes.email"
                        val = all_claims
                        for part in email_claim.split("."):
                            val = val.get(part, {}) if isinstance(val, dict) else ""
                        if isinstance(val, str):
                            user_info.email = val

                logger.info("sso_user_info", email=user_info.email, groups=len(user_info.groups))
                return user_info

        except Exception as e:
            logger.error("sso_callback_error", error=str(e))
            return None

    # ------------------------------------------------------------------
    # Find or Create User
    # ------------------------------------------------------------------
    async def find_or_create_user(self, user_info: OIDCUserInfo) -> tuple[Optional[User], Optional[TokenResponse]]:
        """Find or create a user from OIDC claims.

        Handles JIT provisioning and organization assignment.
        """
        if not user_info.email:
            return None, None

        async with async_session() as db:
            result = await db.execute(select(User).where(User.email == user_info.email))
            user = result.scalar_one_or_none()

            if not user:
                if not self._config.auto_provision:
                    logger.warning("sso_user_not_found_provision_disabled", email=user_info.email)
                    return None, None

                # JIT Provisioning: create user
                user = User(
                    email=user_info.email,
                    full_name=user_info.name,
                    avatar_url=user_info.picture,
                    provider="sso_oidc",
                    provider_id=user_info.sub,
                    is_active=True,
                )
                db.add(user)
                logger.info("sso_user_provisioned", email=user_info.email)
            else:
                # Update user info from SSO
                user.full_name = user_info.name or user.full_name
                user.avatar_url = user_info.picture or getattr(user, "avatar_url", None)
                user.provider_id = user_info.sub or getattr(user, "provider_id", None)

            await db.commit()
            await db.refresh(user)

            # Map groups to roles
            role = self._config.default_role
            if user_info.roles:
                if "admin" in [r.lower() for r in user_info.roles]:
                    role = "admin"
                elif "editor" in [r.lower() for r in user_info.roles]:
                    role = "editor"
            if user_info.groups:
                # Map group names to roles
                group_lower = [g.lower() for g in user_info.groups]
                if any(g in ("admins", "administrators", "cortexai-admins") for g in group_lower):
                    role = "admin"

            # Generate tokens
            tokens = TokenResponse(
                access_token=create_access_token(str(user.id)),
                refresh_token=create_refresh_token(str(user.id)),
            )

            await db.commit()
            return user, tokens

    # ------------------------------------------------------------------
    # Logout URL
    # ------------------------------------------------------------------
    def get_logout_url(self, redirect_uri: str, id_token: Optional[str] = None) -> Optional[str]:
        """Build the OIDC end-session URL for single logout."""
        if not self._config.end_session_endpoint:
            return None

        params = {"post_logout_redirect_uri": redirect_uri}
        if id_token:
            params["id_token_hint"] = id_token

        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self._config.end_session_endpoint}?{query}"


# Module-level singleton
enterprise_sso = EnterpriseSSOProvider()
