import time
from typing import Dict, Tuple
from fastapi import Request, HTTPException
from backend.config import settings

# In-memory token bucket rate limiter
# Dictionary mapping client IP to (tokens, last_refill_timestamp)
_rate_limits: Dict[str, Tuple[float, float]] = {}

def get_client_ip(request: Request) -> str:
    """Extract client IP from request, respecting proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"

def check_rate_limit(request: Request):
    """
    Enforces a token-bucket rate limit based on client IP.
    Throws HTTPException 429 if the limit is exceeded.
    """
    if not settings.RATE_LIMIT_ENABLED:
        return

    client_ip = get_client_ip(request)
    now = time.time()
    
    capacity = settings.RATE_LIMIT_REQUESTS_PER_MINUTE
    refill_rate = capacity / 60.0  # tokens per second
    
    if client_ip in _rate_limits:
        tokens, last_time = _rate_limits[client_ip]
        # Refill tokens based on time passed
        time_passed = now - last_time
        tokens = min(capacity, tokens + time_passed * refill_rate)
    else:
        tokens = capacity
        
    if tokens < 1:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later."
        )
        
    _rate_limits[client_ip] = (tokens - 1, now)
