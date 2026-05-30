"""
CortexAI API Middleware Stack.
Includes: rate limiting, security headers, and request audit logging.
"""
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from backend.core.logger import get_logger

logger = get_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply rate limiting to API endpoints."""
    
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for non-API routes and health checks
        path = request.url.path
        if not path.startswith("/api/") and not path.startswith("/ws/"):
            return await call_next(request)
        
        if path == "/api/health":
            return await call_next(request)
        
        # Extract user_id from request state if auth middleware set it
        user_id = getattr(request.state, "user_id", None) if hasattr(request, "state") else None
        
        try:
            from backend.core.rate_limiter import check_rate_limit
            await check_rate_limit(request, user_id=user_id)
        except Exception as e:
            if hasattr(e, "status_code") and e.status_code == 429:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Please try again later."},
                    headers=getattr(e, "headers", {}),
                )
            # Don't block on rate limiter errors
            logger.warning("rate_limit_middleware_error", error=str(e))
        
        response = await call_next(request)
        return response


class AuditMiddleware(BaseHTTPMiddleware):
    """Log all API requests for audit trail."""
    
    async def dispatch(self, request: Request, call_next):
        import time
        start = time.time()
        
        response = await call_next(request)
        
        duration_ms = (time.time() - start) * 1000
        
        # Only log API and WebSocket requests
        path = request.url.path
        if path.startswith("/api/") or path.startswith("/ws/"):
            user_id = getattr(request.state, "user_id", None) if hasattr(request, "state") else None
            logger.info(
                "api_request",
                method=request.method,
                path=path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 1),
                user_id=user_id,
                client_ip=request.client.host if request.client else None,
            )
        
        return response
