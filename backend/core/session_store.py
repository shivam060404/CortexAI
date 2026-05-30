"""
Redis-backed session store for CortexAI.
Provides fast access to session data with PostgreSQL as source of truth.
Sessions are cached in Redis with a 7-day TTL and auto-hydrated from DB on cache miss.
"""
import json
from typing import Optional
from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy import select

from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

SESSION_PREFIX = "session:"
USER_SESSIONS_PREFIX = "user_sessions:"
SESSION_TTL = 86400 * 7  # 7 days


class SessionStore:
    """Redis-backed session store with PostgreSQL fallback."""

    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None

    async def connect(self):
        """Initialize Redis connection."""
        try:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._redis.ping()
            logger.info("session_store_connected")
        except Exception as e:
            logger.warning("session_store_redis_unavailable", error=str(e))
            self._redis = None

    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()

    @property
    def is_connected(self) -> bool:
        return self._redis is not None

    async def get(self, session_id: str) -> Optional[dict]:
        """Get session data from Redis, falling back to PostgreSQL."""
        if self._redis:
            try:
                data = await self._redis.get(f"{SESSION_PREFIX}{session_id}")
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.warning("session_store_get_error", session_id=session_id, error=str(e))

        # Fallback: hydrate from PostgreSQL
        session = await self._hydrate_from_db(session_id)
        if session:
            await self.set(session_id, session)
        return session

    async def set(self, session_id: str, data: dict, user_id: Optional[str] = None) -> None:
        """Store session data in Redis with TTL."""
        if not self._redis:
            return

        try:
            serialized = json.dumps(data, default=str)
            await self._redis.setex(f"{SESSION_PREFIX}{session_id}", SESSION_TTL, serialized)

            # Track user -> session mapping
            if user_id:
                await self._redis.sadd(f"{USER_SESSIONS_PREFIX}{user_id}", session_id)
                await self._redis.expire(f"{USER_SESSIONS_PREFIX}{user_id}", SESSION_TTL)
        except Exception as e:
            logger.warning("session_store_set_error", session_id=session_id, error=str(e))

    async def delete(self, session_id: str, user_id: Optional[str] = None) -> None:
        """Remove session from Redis cache."""
        if not self._redis:
            return

        try:
            await self._redis.delete(f"{SESSION_PREFIX}{session_id}")
            if user_id:
                await self._redis.srem(f"{USER_SESSIONS_PREFIX}{user_id}", session_id)
        except Exception as e:
            logger.warning("session_store_delete_error", session_id=session_id, error=str(e))

    async def update(self, session_id: str, updates: dict) -> Optional[dict]:
        """Update specific fields in a cached session."""
        session = await self.get(session_id)
        if session:
            session.update(updates)
            session["updated_at"] = datetime.now(timezone.utc).isoformat()
            await self.set(session_id, session, user_id=session.get("user_id"))
        return session

    async def list_by_user(self, user_id: str) -> list[dict]:
        """List all sessions belonging to a user."""
        sessions = []

        if self._redis:
            try:
                session_ids = await self._redis.smembers(f"{USER_SESSIONS_PREFIX}{user_id}")
                for sid in session_ids:
                    session = await self.get(sid)
                    if session:
                        sessions.append(session)
            except Exception as e:
                logger.warning("session_store_list_error", user_id=user_id, error=str(e))

        # If Redis has nothing, hydrate from DB
        if not sessions:
            sessions = await self._hydrate_user_sessions_from_db(user_id)

        # Sort by created_at descending
        sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
        return sessions

    async def cleanup_expired(self) -> int:
        """Remove expired sessions. Returns count of cleaned sessions."""
        # Redis handles TTL-based expiration automatically
        # This method is for any additional cleanup logic
        return 0

    async def _hydrate_from_db(self, session_id: str) -> Optional[dict]:
        """Load a single session from PostgreSQL."""
        try:
            from backend.db.postgres import async_session as db_session, ResearchSession
            async with db_session() as db:
                result = await db.execute(
                    select(ResearchSession).where(ResearchSession.id == session_id)
                )
                row = result.scalar_one_or_none()
                if row:
                    return {
                        "id": str(row.id),
                        "title": row.title,
                        "user_request": row.user_request,
                        "status": row.status.value if hasattr(row.status, 'value') else str(row.status),
                        "final_report": row.final_report or "",
                        "iterations_used": row.iterations_used or 0,
                        "tokens_used": row.tokens_used or 0,
                        "tool_calls_count": row.tool_calls_count or 0,
                        "user_id": str(row.user_id) if hasattr(row, 'user_id') and row.user_id else None,
                        "created_at": row.created_at.isoformat() if row.created_at else "",
                        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
                    }
        except Exception as e:
            logger.warning("session_hydrate_from_db_failed", session_id=session_id, error=str(e))
        return None

    async def _hydrate_user_sessions_from_db(self, user_id: str) -> list[dict]:
        """Load all sessions for a user from PostgreSQL."""
        sessions = []
        try:
            from backend.db.postgres import async_session as db_session, ResearchSession
            async with db_session() as db:
                result = await db.execute(
                    select(ResearchSession)
                    .where(ResearchSession.user_id == user_id)
                    .order_by(ResearchSession.created_at.desc())
                )
                rows = result.scalars().all()
                for row in rows:
                    session = {
                        "id": str(row.id),
                        "title": row.title,
                        "user_request": row.user_request,
                        "status": row.status.value if hasattr(row.status, 'value') else str(row.status),
                        "final_report": row.final_report or "",
                        "iterations_used": row.iterations_used or 0,
                        "tokens_used": row.tokens_used or 0,
                        "tool_calls_count": row.tool_calls_count or 0,
                        "user_id": str(row.user_id) if hasattr(row, 'user_id') and row.user_id else None,
                        "created_at": row.created_at.isoformat() if row.created_at else "",
                        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
                    }
                    sessions.append(session)
                    # Cache in Redis
                    await self.set(str(row.id), session, user_id=user_id)
        except Exception as e:
            logger.warning("session_hydrate_user_from_db_failed", user_id=user_id, error=str(e))
        return sessions


# Module-level singleton
session_store = SessionStore()
