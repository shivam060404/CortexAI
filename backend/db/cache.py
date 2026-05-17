"""
Redis caching layer — cache-aside pattern with graceful degradation.
If Redis is unavailable, operations silently bypass cache.
"""

import hashlib
import json
from typing import Any, Optional

from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

_redis_client = None


async def _get_redis():
    """Lazy Redis connection with graceful fallback."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        await _redis_client.ping()
        logger.info("redis_connected", url=settings.REDIS_URL)
        return _redis_client
    except Exception as e:
        logger.warning("redis_unavailable", error=str(e))
        _redis_client = None
        return None


def _hash_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:24]


class CacheManager:
    """Cache-aside manager for search results, embeddings, and session state."""

    # --- Search cache ---
    async def get_search(self, query: str) -> Optional[list[dict]]:
        r = await _get_redis()
        if r is None:
            return None
        try:
            key = f"tavily:{_hash_key(query)}"
            data = await r.get(key)
            if data:
                logger.debug("cache_hit", key=key)
                return json.loads(data)
        except Exception as e:
            logger.warning("cache_get_error", error=str(e))
        return None

    async def set_search(self, query: str, results: list[dict]):
        r = await _get_redis()
        if r is None:
            return
        try:
            key = f"tavily:{_hash_key(query)}"
            await r.setex(key, settings.CACHE_SEARCH_TTL, json.dumps(results, default=str))
            logger.debug("cache_set", key=key, ttl=settings.CACHE_SEARCH_TTL)
        except Exception as e:
            logger.warning("cache_set_error", error=str(e))

    # --- Embedding cache ---
    async def get_embedding(self, text: str) -> Optional[list[float]]:
        r = await _get_redis()
        if r is None:
            return None
        try:
            key = f"embed:{_hash_key(text)}"
            data = await r.get(key)
            if data:
                return json.loads(data)
        except Exception:
            pass
        return None

    async def set_embedding(self, text: str, embedding: list[float]):
        r = await _get_redis()
        if r is None:
            return
        try:
            key = f"embed:{_hash_key(text)}"
            await r.setex(key, settings.CACHE_EMBEDDING_TTL, json.dumps(embedding))
        except Exception:
            pass

    # --- Session state cache ---
    async def get_session_state(self, session_id: str) -> Optional[dict]:
        r = await _get_redis()
        if r is None:
            return None
        try:
            key = f"session:{session_id}:state"
            data = await r.get(key)
            if data:
                return json.loads(data)
        except Exception:
            pass
        return None

    async def set_session_state(self, session_id: str, state: dict, ttl: int = 3600):
        r = await _get_redis()
        if r is None:
            return
        try:
            key = f"session:{session_id}:state"
            await r.setex(key, ttl, json.dumps(state, default=str))
        except Exception:
            pass
