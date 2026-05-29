import time
from typing import Dict, Tuple
from fastapi import Request, HTTPException
from backend.config import settings
from backend.core.rate_limiter import check_rate_limit

async def rate_limit_middleware(request: Request, call_next):
    """
    Middleware that applies the rate limit check for all API routes.
    """
    if request.url.path.startswith("/api/"):
        check_rate_limit(request)
    return await call_next(request)
