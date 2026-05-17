"""
Preference Learning — Updates user preferences from RLHF feedback.
Analyzes feedback comments and ratings to learn what the user wants.
"""

from sqlalchemy import select
from backend.db.postgres import async_session, UserPreference, FeedbackLog
from backend.core.logger import get_logger

logger = get_logger(__name__)

# Keyword → preference mapping for automatic learning
FEEDBACK_SIGNALS = {
    # Depth preferences
    "too shallow": ("depth", "deep"),
    "not detailed enough": ("depth", "deep"),
    "more depth": ("depth", "deep"),
    "too deep": ("depth", "concise"),
    "too long": ("depth", "concise"),
    "too verbose": ("verbosity", "low"),
    "more concise": ("verbosity", "low"),
    "too short": ("verbosity", "high"),
    "more detail": ("verbosity", "high"),
    # Style preferences
    "more technical": ("style", "technical"),
    "too technical": ("style", "simple"),
    "needs data": ("style", "data-driven"),
    "more examples": ("style", "example-rich"),
    "more sources": ("source_count", "high"),
    "fewer sources": ("source_count", "low"),
    # Focus preferences
    "more academic": ("focus", "academic"),
    "more practical": ("focus", "practical"),
    "more recent": ("recency", "recent"),
}


async def learn_from_feedback(session_id: str, rating: int, comment: str):
    """Analyze feedback and update user preferences.
    
    - Negative ratings (1-2): extract what went wrong from comment
    - Positive ratings (4-5): reinforce current preferences
    - Comments are keyword-matched for automatic learning
    """
    updates = []
    comment_lower = comment.lower() if comment else ""
    
    # Extract signals from comment text
    for keyword, (pref_key, pref_value) in FEEDBACK_SIGNALS.items():
        if keyword in comment_lower:
            # Higher confidence for explicit feedback
            updates.append((pref_key, pref_value, 0.8))
    
    # Infer from rating without specific comment
    if rating <= 2 and not updates:
        # Bad rating without specific comment — increase depth by default
        updates.append(("depth", "deep", 0.3))
    elif rating >= 4 and not updates:
        # Good rating — reinforce current preferences slightly
        pass  # No changes needed, system is working
    
    # Apply updates
    for key, value, confidence in updates:
        await _upsert_preference(key, value, confidence)
    
    logger.info("feedback_learned",
                 session_id=session_id,
                 rating=rating,
                 updates=[(k, v) for k, v, _ in updates])


async def _upsert_preference(key: str, value: str, confidence: float):
    """Insert or update a user preference with blended confidence."""
    try:
        async with async_session() as db:
            res = await db.execute(
                select(UserPreference).where(UserPreference.key == key)
            )
            existing = res.scalar_one_or_none()
            
            if existing:
                if existing.value == value:
                    # Same direction — increase confidence
                    existing.confidence = min(1.0, existing.confidence + 0.1)
                else:
                    # Different direction — only override if new confidence is higher
                    if confidence > existing.confidence:
                        existing.value = value
                        existing.confidence = confidence
                    else:
                        existing.confidence = max(0.1, existing.confidence - 0.1)
            else:
                db.add(UserPreference(key=key, value=value, confidence=confidence))
            
            await db.commit()
    except Exception as e:
        logger.error("preference_upsert_error", key=key, error=str(e))


async def get_user_preferences() -> dict:
    """Load all user preferences as a dict."""
    try:
        async with async_session() as db:
            res = await db.execute(
                select(UserPreference).where(UserPreference.confidence >= 0.3)
            )
            prefs = res.scalars().all()
            return {p.key: p.value for p in prefs}
    except Exception:
        return {}
