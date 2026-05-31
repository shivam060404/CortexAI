"""
CortexAI API middleware stack.
Includes auth enforcement, rate limiting, security headers, and audit logging.
"""

from __future__ import annotations

import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.auth.dependencies import get_optional_user_from_request
from backend.core.audit import audit_logger
from backend.core.logger import get_logger
from backend.core.rate_limiter import check_rate_limit
from backend.db.tenant import bind_tenant_context, bind_user_tenant_context, reset_tenant_context

logger = get_logger(__name__)

PUBLIC_API_PREFIXES = (
    "/api/auth/",
    "/api/context/pages",
)
PUBLIC_API_PATHS = {"/api/auth", "/health", "/api/health", "/ready", "/live"}


def _is_public_api_path(path: str) -> bool:
    return path in PUBLIC_API_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_API_PREFIXES)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add baseline security headers to all HTTP responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "connect-src 'self' http: https: ws: wss:; "
            "script-src 'self' 'unsafe-inline';"
        )
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    """Authenticate API requests and populate request state."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        request.state.user = None
        request.state.user_id = None
        tenant_token = bind_tenant_context(source="public" if _is_public_api_path(path) else "anonymous")

        try:
            if not path.startswith("/api/") or _is_public_api_path(path):
                return await call_next(request)

            user = await get_optional_user_from_request(request)

            if user is None:
                await audit_logger.log(
                    event_type="auth_failure",
                    details={"path": path, "method": request.method, "reason": "missing_or_invalid_credentials"},
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                )
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required"},
                    headers={"WWW-Authenticate": "Bearer"},
                )

            reset_tenant_context(tenant_token)
            tenant_token = bind_user_tenant_context(user, source="request")
            request.state.user = user
            request.state.user_id = str(user.id)
            return await call_next(request)
        finally:
            reset_tenant_context(tenant_token)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply Redis-backed rate limiting to API requests."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/") or path in {"/health", "/api/health", "/ready", "/live"}:
            return await call_next(request)

        user_id = getattr(request.state, "user_id", None)

        try:
            await check_rate_limit(request, user_id=user_id)
        except Exception as exc:
            if getattr(exc, "status_code", None) == 429:
                await audit_logger.log(
                    event_type="rate_limit_hit",
                    user_id=user_id,
                    details={"path": path, "method": request.method},
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                )
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Please try again later."},
                    headers=getattr(exc, "headers", {}),
                )
            logger.warning("rate_limit_middleware_error", error=str(exc), path=path)

        return await call_next(request)


class AuditMiddleware(BaseHTTPMiddleware):
    """Persist audit records for API traffic."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        start = time.time()

        try:
            response = await call_next(request)
        except Exception:
            await audit_logger.log(
                event_type="api_error",
                user_id=getattr(request.state, "user_id", None),
                details={"method": request.method, "path": path, "status_code": 500},
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
            raise

        if path.startswith("/api/"):
            duration_ms = round((time.time() - start) * 1000, 1)
            await audit_logger.log(
                event_type="api_request",
                user_id=getattr(request.state, "user_id", None),
                details={
                    "method": request.method,
                    "path": path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )

        return response
