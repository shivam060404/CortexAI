"""
Human-in-the-Loop (HITL) Manager.
Provides mechanisms to pause agent execution, request user review, and resume with modifications.
"""

import asyncio
from typing import Optional

from backend.core.logger import get_logger

logger = get_logger(__name__)

# Global registry for active HITL pauses
# session_id -> asyncio.Event
_active_pauses: dict[str, asyncio.Event] = {}

# session_id -> dict (user modifications injected on resume)
_injected_modifications: dict[str, dict] = {}


class HITLManager:
    """Manages the pause/resume lifecycle for Human-in-the-Loop interventions."""

    @staticmethod
    async def pause_for_review(session_id: str, checkpoint_type: str, data: dict, timeout_seconds: int = 300) -> dict | None:
        """
        Pause the current task and wait for user intervention.
        This blocks the current coroutine until resumed by the user or timeout occurs.
        """
        event = asyncio.Event()
        _active_pauses[session_id] = event
        _injected_modifications[session_id] = {}

        logger.info("hitl_paused", session_id=session_id, checkpoint_type=checkpoint_type)

        try:
            # Wait for resume or timeout
            await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
            
            # Fetch modifications provided during resume
            mods = _injected_modifications.pop(session_id, {})
            logger.info("hitl_resumed", session_id=session_id, modifications_keys=list(mods.keys()))
            return mods

        except asyncio.TimeoutError:
            logger.warning("hitl_timeout", session_id=session_id, timeout=timeout_seconds)
            return None
        finally:
            _active_pauses.pop(session_id, None)
            _injected_modifications.pop(session_id, None)

    @staticmethod
    def resume_with_input(session_id: str, modifications: dict):
        """
        Resume a paused session, optionally injecting modifications.
        Called from the WebSocket route when the user clicks 'Approve' or 'Modify'.
        """
        event = _active_pauses.get(session_id)
        if event:
            _injected_modifications[session_id] = modifications
            event.set()
            return True
        return False

    @staticmethod
    def is_paused(session_id: str) -> bool:
        """Check if a session is currently paused for HITL."""
        return session_id in _active_pauses

    @staticmethod
    def cancel_pause(session_id: str):
        """Cancel a pause without providing input (acts like a timeout)."""
        event = _active_pauses.get(session_id)
        if event:
            event.set()
