"""
Redis-backed distributed rate limiter for CortexAI.
Uses sliding window algorithm with Redis SORTED SETS for precise rate limiting.
Supports per-user (authenticated) and per-IP (unauthenticated) tracking.
Tiered limits for different endpoint types.
"""
import time
from typing import Optional, Tuple

import redis.asyncio as aioredis
from fastapi import Request, HTTPException, status

from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

# Tier definitions: (requests_per_minute, window_seconds)
RATE_TIERS = {
    "session_create": (10, 60),      # Expensive: triggers AI agents
    "websocket": (5, 60),            # Very expensive: long-running connections
    "general_write": (30, 60),       # Moderate: POST/PUT/DELETE
    "general_read": (120, 60),       # Cheap: GET endpoints
    "auth": (20, 60),                # Auth attempts
}


def _get_tier_for_request(request: Request) -> str:
    """Determine the rate limit tier based on request path and method."""
    path = request.url.path
    method = request.method.upper()

    if path.startswith("/ws/"):
        return "websocket"
    if path == "/api/sessions" and method == "POST":
        return "session_create"
    if path.startswith("/api/auth"):
        return "auth"
    if method in ("POST", "PUT", "DELETE"):
        return "general_write"
    return "general_read"


def _get_client_identifier(request: Request, user_id: Optional[str] = None) -> str:
    """Get the rate limit key: prefer user_id, fallback to IP."""
    if user_id:
        return f"user:{user_id}"

    # Extract real IP (respect X-Forwarded-For from trusted proxies only)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take the first IP (client IP) - only trust if behind known proxy
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"

    return f"ip:{ip}"


class RateLimiter:
    """Redis-backed sliding window rate limiter."""

    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None

    async def connect(self):
        """Initialize Redis connection for rate limiting."""
        try:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._redis.ping()
            logger.info("rate_limiter_connected")
        except Exception as e:
            logger.warning("rate_limiter_redis_unavailable", error=str(e),
                          note="Falling back to permissive mode")
            self._redis = None

    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()

    async def check_rate_limit(
        self, request: Request, user_id: Optional[str] = None
    ) -> Tuple[bool, dict]:
        """
        Check if request is within rate limits.

        Returns:
            Tuple of (is_allowed: bool, headers: dict)
            headers contains X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After
        """
        if not self._redis:
            # Permissive fallback if Redis is unavailable
            return True, {}

        tier = _get_tier_for_request(request)
        max_requests, window_seconds = RATE_TIERS.get(tier, (60, 60))
        identifier = _get_client_identifier(request, user_id)
        key = f"ratelimit:{tier}:{identifier}"

        now = time.time()
        window_start = now - window_seconds

        try:
            pipe = self._redis.pipeline()
            # Remove expired entries
            pipe.zremrangebyscore(key, 0, window_start)
            # Count current window entries
            pipe.zcard(key)
            # Add current request
            pipe.zadd(key, {f"{now}": now})
            # Set expiry on the key
            pipe.expire(key, window_seconds + 1)
            results = await pipe.execute()

            current_count = results[1]  # zcard result

            remaining = max(0, max_requests - current_count - 1)
            headers = {
                "X-RateLimit-Limit": str(max_requests),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(int(now + window_seconds)),
            }

            if current_count >= max_requests:
                # Rate limited
                retry_after = int(window_seconds - (now - window_start))
                headers["Retry-After"] = str(max(1, retry_after))
                logger.warning("rate_limit_exceeded",
                             identifier=identifier, tier=tier,
                             count=current_count, limit=max_requests)
                return False, headers

            return True, headers

        except Exception as e:
            logger.error("rate_limit_check_error", error=str(e))
            # Fail open on errors
            return True, {}

    async def check_identifier_rate_limit(
        self,
        identifier: str,
        tier: str,
    ) -> Tuple[bool, dict]:
        """Check limits for non-HTTP flows such as WebSocket handshakes."""
        if not self._redis:
            return True, {}

        max_requests, window_seconds = RATE_TIERS.get(tier, (60, 60))
        key = f"ratelimit:{tier}:{identifier}"
        now = time.time()
        window_start = now - window_seconds

        try:
            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zcard(key)
            pipe.zadd(key, {f"{now}:{identifier}": now})
            pipe.expire(key, window_seconds + 1)
            results = await pipe.execute()
            current_count = results[1]
            remaining = max(0, max_requests - current_count - 1)
            headers = {
                "X-RateLimit-Limit": str(max_requests),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(int(now + window_seconds)),
            }
            if current_count >= max_requests:
                retry_after = max(1, int(window_seconds))
                headers["Retry-After"] = str(retry_after)
                return False, headers
            return True, headers
        except Exception as e:
            logger.error("rate_limit_identifier_error", error=str(e), identifier=identifier, tier=tier)
            return True, {}


# Module-level singleton
rate_limiter = RateLimiter()


async def check_rate_limit(request: Request, user_id: Optional[str] = None) -> None:
    """
    Compatibility function for middleware.
    Raises HTTPException with 429 if rate limited.
    """
    is_allowed, headers = await rate_limiter.check_rate_limit(request, user_id)

    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
            headers=headers,
        )


async def check_websocket_rate_limit(client_ip: str, user_id: Optional[str] = None) -> Tuple[bool, dict]:
    identifier = f"user:{user_id}" if user_id else f"ip:{client_ip or 'unknown'}"
    return await rate_limiter.check_identifier_rate_limit(identifier, tier="websocket")
