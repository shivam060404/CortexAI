"""
Persistent audit logging for security-sensitive application events.
"""

from __future__ import annotations

from typing import Any

from backend.core.logger import get_logger

logger = get_logger(__name__)


class AuditLogger:
    """Async audit logger backed by PostgreSQL."""

    async def log(
        self,
        event_type: str,
        user_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        try:
            from backend.db.postgres import AuditLog, async_session

            async with async_session() as db:
                record = AuditLog(
                    event_type=event_type,
                    user_id=user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    details=details or {},
                )
                db.add(record)
                await db.commit()
        except Exception as exc:
            logger.warning(
                "audit_log_failed",
                event_type=event_type,
                user_id=user_id,
                error=str(exc),
            )


audit_logger = AuditLogger()
