"""
Real-Time Collaboration (Feature Gap #5 / Task 20).

Shared workspace model: multiple users can join a research session.
WebSocket broadcasting to all session participants.
Conflict resolution for concurrent modifications.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, delete as sa_delete, update as sa_update
from backend.db.postgres import async_session, SessionParticipant, ResearchSession
from backend.core.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# In-memory participant tracking (per-process)
# Maps session_id -> set of (user_id, websocket_ref) for live broadcasting.
# ---------------------------------------------------------------------------
_active_connections: dict[str, set[tuple[str, Any]]] = {}
_connections_lock = asyncio.Lock()


class CollaborationManager:
    """Manages real-time collaboration on research sessions."""

    # ------------------------------------------------------------------
    # Participant Management
    # ------------------------------------------------------------------
    async def join_session(
        self,
        session_id: str,
        user_id: str,
        role: str = "viewer",
    ) -> dict:
        """Add a user as a participant to a research session.
        
        Args:
            session_id: The research session to join.
            user_id: The user joining.
            role: viewer, editor, or owner.
            
        Returns:
            Participant info dict.
        """
        async with async_session() as db:
            # Check if already a participant
            result = await db.execute(
                select(SessionParticipant).where(
                    SessionParticipant.session_id == uuid.UUID(session_id),
                    SessionParticipant.user_id == uuid.UUID(user_id),
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                logger.info("collaboration_already_joined", session_id=session_id, user_id=user_id)
                return {
                    "session_id": session_id,
                    "user_id": user_id,
                    "role": existing.role,
                    "joined_at": existing.joined_at.isoformat() if existing.joined_at else None,
                    "status": "already_joined",
                }

            # Verify session exists
            session_result = await db.execute(
                select(ResearchSession).where(ResearchSession.id == uuid.UUID(session_id))
            )
            session = session_result.scalar_one_or_none()
            if not session:
                raise ValueError(f"Session {session_id} not found")

            participant = SessionParticipant(
                session_id=uuid.UUID(session_id),
                user_id=uuid.UUID(user_id),
                role=role,
            )
            db.add(participant)
            await db.commit()
            await db.refresh(participant)

        logger.info("collaboration_joined", session_id=session_id, user_id=user_id, role=role)
        return {
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "joined_at": participant.joined_at.isoformat() if participant.joined_at else None,
            "status": "joined",
        }

    async def leave_session(self, session_id: str, user_id: str) -> dict:
        """Remove a user from a research session."""
        async with async_session() as db:
            await db.execute(
                sa_delete(SessionParticipant).where(
                    SessionParticipant.session_id == uuid.UUID(session_id),
                    SessionParticipant.user_id == uuid.UUID(user_id),
                )
            )
            await db.commit()

        # Also remove from active connections
        await self.unregister_connection(session_id, user_id)
        logger.info("collaboration_left", session_id=session_id, user_id=user_id)
        return {"session_id": session_id, "user_id": user_id, "status": "left"}

    async def update_role(self, session_id: str, user_id: str, new_role: str) -> dict:
        """Update a participant's role in a session."""
        async with async_session() as db:
            await db.execute(
                sa_update(SessionParticipant)
                .where(
                    SessionParticipant.session_id == uuid.UUID(session_id),
                    SessionParticipant.user_id == uuid.UUID(user_id),
                )
                .values(role=new_role)
            )
            await db.commit()

        logger.info("collaboration_role_updated", session_id=session_id, user_id=user_id, role=new_role)
        return {"session_id": session_id, "user_id": user_id, "role": new_role}

    async def list_participants(self, session_id: str) -> list[dict]:
        """List all participants in a session."""
        async with async_session() as db:
            result = await db.execute(
                select(SessionParticipant)
                .where(SessionParticipant.session_id == uuid.UUID(session_id))
                .order_by(SessionParticipant.joined_at)
            )
            participants = result.scalars().all()
            return [
                {
                    "user_id": str(p.user_id),
                    "role": p.role,
                    "joined_at": p.joined_at.isoformat() if p.joined_at else None,
                    "is_online": self._is_user_connected(session_id, str(p.user_id)),
                }
                for p in participants
            ]

    # ------------------------------------------------------------------
    # WebSocket Connection Management (for broadcasting)
    # ------------------------------------------------------------------
    async def register_connection(self, session_id: str, user_id: str, websocket: Any) -> None:
        """Register a WebSocket connection for a session participant."""
        async with _connections_lock:
            if session_id not in _active_connections:
                _active_connections[session_id] = set()
            _active_connections[session_id].add((user_id, websocket))
        logger.info("collaboration_ws_registered", session_id=session_id, user_id=user_id,
                     total=len(_active_connections.get(session_id, set())))

    async def unregister_connection(self, session_id: str, user_id: str) -> None:
        """Remove a WebSocket connection."""
        async with _connections_lock:
            connections = _active_connections.get(session_id, set())
            _active_connections[session_id] = {
                (uid, ws) for uid, ws in connections if uid != user_id
            }
            if not _active_connections[session_id]:
                del _active_connections[session_id]

    async def broadcast_to_session(
        self,
        session_id: str,
        message: dict,
        exclude_user: str | None = None,
    ) -> int:
        """Broadcast a message to all connected participants of a session.
        
        Args:
            session_id: The session to broadcast to.
            message: The JSON-serializable message to send.
            exclude_user: Optional user_id to exclude (e.g., the sender).
            
        Returns:
            Number of participants the message was sent to.
        """
        connections = _active_connections.get(session_id, set())
        sent_count = 0
        stale = []

        for uid, ws in connections:
            if exclude_user and uid == exclude_user:
                continue
            try:
                await ws.send_json(message)
                sent_count += 1
            except Exception:
                stale.append((uid, ws))

        # Clean up stale connections
        if stale:
            async with _connections_lock:
                for item in stale:
                    _active_connections.get(session_id, set()).discard(item)

        return sent_count

    async def broadcast_event(
        self,
        session_id: str,
        event_type: str,
        data: dict,
        exclude_user: str | None = None,
    ) -> int:
        """Broadcast a typed event to session participants."""
        message = {"type": event_type, "data": data}
        return await self.broadcast_to_session(session_id, message, exclude_user=exclude_user)

    # ------------------------------------------------------------------
    # Conflict Resolution
    # ------------------------------------------------------------------
    async def resolve_edit_conflict(
        self,
        session_id: str,
        user_id: str,
        operation: str,
        payload: dict,
    ) -> dict:
        """Handle concurrent modification conflicts.
        
        Strategy: last-writer-wins with conflict notification.
        In production, could be upgraded to OT/CRDT-based resolution.
        
        Args:
            session_id: The session being modified.
            user_id: The user making the edit.
            operation: The type of edit (e.g., "update_query", "add_context").
            payload: The edit payload.
            
        Returns:
            Resolution result with conflict flag.
        """
        # Check if there are other active editors
        connections = _active_connections.get(session_id, set())
        other_editors = [uid for uid, _ in connections if uid != user_id]

        conflict_detected = len(other_editors) > 0

        if conflict_detected:
            # Notify other participants about the edit
            await self.broadcast_event(
                session_id,
                "edit_conflict",
                {
                    "editor_id": user_id,
                    "operation": operation,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                exclude_user=user_id,
            )

        logger.info(
            "collaboration_edit",
            session_id=session_id,
            user_id=user_id,
            operation=operation,
            conflict=conflict_detected,
        )

        return {
            "session_id": session_id,
            "user_id": user_id,
            "operation": operation,
            "conflict_detected": conflict_detected,
            "resolution": "last_writer_wins",
            "other_active_editors": other_editors if conflict_detected else [],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _is_user_connected(self, session_id: str, user_id: str) -> bool:
        """Check if a user has an active WebSocket connection to a session."""
        connections = _active_connections.get(session_id, set())
        return any(uid == user_id for uid, _ in connections)

    def get_active_sessions(self) -> dict[str, int]:
        """Get sessions with active connections and participant counts."""
        return {
            sid: len(conns)
            for sid, conns in _active_connections.items()
            if conns
        }


# Module-level singleton
collaboration_manager = CollaborationManager()
