"""
Shareable Report Permalinks (Feature Gap #5 / Task 17).

Generate public/private shareable URLs for completed research reports.
Supports expiration, view counting, and access control.
"""

import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, update as sa_update
from backend.db.postgres import async_session, ReportShare, ResearchSession
from backend.db.workspace import WorkspaceManager
from backend.core.logger import get_logger

logger = get_logger(__name__)
_workspace = WorkspaceManager()

# Default share link expiry: 30 days
DEFAULT_SHARE_EXPIRY_DAYS = 30


def _generate_share_token() -> str:
    """Generate a URL-safe share token."""
    return secrets.token_urlsafe(32)


async def create_share_link(
    session_id: str,
    user_id: str,
    is_public: bool = False,
    expires_days: int = DEFAULT_SHARE_EXPIRY_DAYS,
) -> dict:
    """Create a shareable link for a research report."""
    token = _generate_share_token()
    expires_at = None
    if expires_days and expires_days > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

    async with async_session() as db:
        share = ReportShare(
            session_id=uuid.UUID(session_id),
            share_token=token,
            is_public=is_public,
            expires_at=expires_at,
            created_by=uuid.UUID(user_id),
        )
        db.add(share)
        await db.commit()
        await db.refresh(share)

    logger.info("share_link_created", session_id=session_id, token=token[:8], public=is_public)
    return {
        "share_token": token,
        "is_public": is_public,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "share_url": f"/api/shared/{token}",
    }


async def get_shared_report(token: str) -> Optional[dict]:
    """Retrieve a shared report by token.

    Validates expiry, increments view count, and returns the report content.
    """
    async with async_session() as db:
        result = await db.execute(
            select(ReportShare).where(ReportShare.share_token == token)
        )
        share = result.scalar_one_or_none()

        if not share:
            return None

        # Check expiry
        if share.expires_at and share.expires_at < datetime.now(timezone.utc):
            return None

        # Increment view count
        await db.execute(
            sa_update(ReportShare)
            .where(ReportShare.id == share.id)
            .values(view_count=ReportShare.view_count + 1)
        )
        await db.commit()

        # Fetch the report content
        session_id = str(share.session_id)
        try:
            report_md = _workspace.read_file(session_id, "report.md")
        except Exception:
            report_md = ""

        # Fetch session metadata
        session_result = await db.execute(
            select(ResearchSession).where(ResearchSession.id == share.session_id)
        )
        session = session_result.scalar_one_or_none()

        return {
            "session_id": session_id,
            "title": session.title if session else "Shared Report",
            "report": report_md,
            "is_public": share.is_public,
            "view_count": (share.view_count or 0) + 1,
            "created_at": share.created_at.isoformat() if share.created_at else None,
        }


async def list_share_links(session_id: str, user_id: str) -> list[dict]:
    """List all share links for a session."""
    async with async_session() as db:
        result = await db.execute(
            select(ReportShare)
            .where(
                ReportShare.session_id == uuid.UUID(session_id),
                ReportShare.created_by == uuid.UUID(user_id),
            )
            .order_by(ReportShare.created_at.desc())
        )
        shares = result.scalars().all()
        return [
            {
                "share_token": s.share_token,
                "is_public": s.is_public,
                "view_count": s.view_count or 0,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in shares
        ]


async def revoke_share_link(token: str, user_id: str) -> dict:
    """Delete a share link."""
    async with async_session() as db:
        from sqlalchemy import delete as sa_delete
        await db.execute(
            sa_delete(ReportShare)
            .where(
                ReportShare.share_token == token,
                ReportShare.created_by == uuid.UUID(user_id),
            )
        )
        await db.commit()
    logger.info("share_link_revoked", token=token[:8])
    return {"share_token": token, "status": "revoked"}
