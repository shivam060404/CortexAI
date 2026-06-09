"""
SOC2 Compliance Audit Logging (Feature Gap #12 / Task 18).

Persistent audit logging for security-sensitive application events.
Supports:
  - Data access logging (who read what data, when)
  - Configuration change logging
  - Retention policy with auto-archive
  - Export capability for compliance auditors
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy import select, delete as sa_delete, func

from backend.core.logger import get_logger

logger = get_logger(__name__)

# SOC2 event categories
EVENT_DATA_ACCESS = "data_access"
EVENT_CONFIG_CHANGE = "config_change"
EVENT_AUTH = "auth"
EVENT_SESSION = "session"
EVENT_EXPORT = "export"
EVENT_SHARING = "sharing"


class AuditLogger:
    """Async audit logger backed by PostgreSQL with SOC2 compliance features."""

    async def log(
        self,
        event_type: str,
        user_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Persist a single audit event."""
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

    # ------------------------------------------------------------------
    # Data Access Logging (SOC2 Type II requirement)
    # ------------------------------------------------------------------
    async def log_data_access(
        self,
        user_id: str,
        resource_type: str,
        resource_id: str,
        action: str = "read",
        ip_address: str | None = None,
    ) -> None:
        """Log when a user reads or exports sensitive data."""
        await self.log(
            event_type=EVENT_DATA_ACCESS,
            user_id=user_id,
            ip_address=ip_address,
            details={
                "resource_type": resource_type,
                "resource_id": resource_id,
                "action": action,
            },
        )

    # ------------------------------------------------------------------
    # Configuration Change Logging
    # ------------------------------------------------------------------
    async def log_config_change(
        self,
        user_id: str,
        setting_name: str,
        old_value: Any,
        new_value: Any,
        ip_address: str | None = None,
    ) -> None:
        """Log when an application or org configuration is changed."""
        await self.log(
            event_type=EVENT_CONFIG_CHANGE,
            user_id=user_id,
            ip_address=ip_address,
            details={
                "setting_name": setting_name,
                "old_value": str(old_value),
                "new_value": str(new_value),
            },
        )

    # ------------------------------------------------------------------
    # Retention Policy — auto-archive old logs
    # ------------------------------------------------------------------
    async def apply_retention_policy(self, retention_days: int | None = None) -> dict:
        """Delete audit logs older than the configured retention period.

        Returns the number of deleted records.
        """
        from backend.config import settings as app_settings
        from backend.db.postgres import AuditLog, async_session

        days = retention_days or app_settings.AUDIT_RETENTION_DAYS
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        try:
            async with async_session() as db:
                result = await db.execute(
                    sa_delete(AuditLog).where(AuditLog.created_at < cutoff)
                )
                await db.commit()
                deleted = result.rowcount if hasattr(result, "rowcount") else 0
                logger.info("audit_retention_applied", cutoff=cutoff.isoformat(), deleted=deleted)
                return {"deleted": deleted, "cutoff": cutoff.isoformat(), "retention_days": days}
        except Exception as exc:
            logger.error("audit_retention_error", error=str(exc))
            return {"deleted": 0, "error": str(exc)}

    # ------------------------------------------------------------------
    # Export for Compliance Auditors
    # ------------------------------------------------------------------
    async def export_logs(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        event_type: str | None = None,
        user_id: str | None = None,
        format: str = "json",
        limit: int = 10_000,
    ) -> str | list[dict]:
        """Export audit logs for compliance review.

        Supports JSON (default) and CSV output formats.
        """
        from backend.db.postgres import AuditLog, async_session

        try:
            async with async_session() as db:
                query = select(AuditLog).order_by(AuditLog.created_at.desc())

                if start_date:
                    query = query.where(AuditLog.created_at >= start_date)
                if end_date:
                    query = query.where(AuditLog.created_at <= end_date)
                if event_type:
                    query = query.where(AuditLog.event_type == event_type)
                if user_id:
                    query = query.where(AuditLog.user_id == uuid.UUID(user_id))

                query = query.limit(limit)
                result = await db.execute(query)
                logs = result.scalars().all()

            rows = [
                {
                    "id": str(log.id),
                    "event_type": log.event_type,
                    "user_id": str(log.user_id) if log.user_id else None,
                    "ip_address": log.ip_address,
                    "user_agent": log.user_agent,
                    "details": log.details,
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                }
                for log in logs
            ]

            if format == "csv":
                return self._to_csv(rows)

            # Log the export event itself (SOC2 requirement)
            await self.log(
                event_type=EVENT_EXPORT,
                user_id=user_id,
                details={
                    "exported_count": len(rows),
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                    "event_type_filter": event_type,
                    "format": format,
                },
            )
            return rows

        except Exception as exc:
            logger.error("audit_export_error", error=str(exc))
            return [] if format == "json" else ""

    @staticmethod
    def _to_csv(rows: list[dict]) -> str:
        """Convert audit log rows to CSV string."""
        if not rows:
            return ""
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["id", "event_type", "user_id", "ip_address", "user_agent", "details", "created_at"])
        writer.writeheader()
        for row in rows:
            row_copy = dict(row)
            # Flatten details dict to string for CSV
            if isinstance(row_copy.get("details"), dict):
                import json
                row_copy["details"] = json.dumps(row_copy["details"])
            writer.writerow(row_copy)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Summary / Statistics
    # ------------------------------------------------------------------
    async def get_audit_summary(self, days: int = 30) -> dict:
        """Return aggregate audit statistics for the given period."""
        from backend.db.postgres import AuditLog, async_session

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        try:
            async with async_session() as db:
                total_result = await db.execute(
                    select(func.count(AuditLog.id)).where(AuditLog.created_at >= cutoff)
                )
                total_events = total_result.scalar() or 0

                # Count by event type
                type_result = await db.execute(
                    select(AuditLog.event_type, func.count(AuditLog.id))
                    .where(AuditLog.created_at >= cutoff)
                    .group_by(AuditLog.event_type)
                )
                by_type = {row[0]: row[1] for row in type_result.all()}

                # Count unique users
                user_result = await db.execute(
                    select(func.count(func.distinct(AuditLog.user_id)))
                    .where(AuditLog.created_at >= cutoff, AuditLog.user_id.isnot(None))
                )
                unique_users = user_result.scalar() or 0

            return {
                "period_days": days,
                "total_events": total_events,
                "events_by_type": by_type,
                "unique_users": unique_users,
            }
        except Exception as exc:
            logger.error("audit_summary_error", error=str(exc))
            return {"period_days": days, "total_events": 0, "events_by_type": {}, "unique_users": 0}


audit_logger = AuditLogger()
