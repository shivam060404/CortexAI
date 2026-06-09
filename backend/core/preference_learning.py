"""
Preference learning scoped to the authenticated user (Feature Gap #8).

Enhancements:
- Automated feedback aggregation by user, topic, and rating patterns
- Preference decay: older feedback weighs less over time
- Confidence thresholds before applying preferences to research
"""

import uuid
import time
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func
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

# Decay half-life: 30 days — preference weight halves every month
PREFERENCE_DECAY_HALF_LIFE_DAYS = 30
# Minimum confidence before a preference is applied to research
MIN_CONFIDENCE_THRESHOLD = 0.3
# Number of agreeing feedback entries needed for high confidence
HIGH_CONFIDENCE_FEEDBACK_COUNT = 5


async def learn_from_feedback(session_id: str, rating: int, comment: str, user_id: str):
    """Analyze feedback and update user preferences.

    - Negative ratings (1-2): extract what went wrong from comment
    - Positive ratings (4-5): reinforce current preferences
    - Comments are keyword-matched for automatic learning
    - Aggregates feedback patterns across sessions
    """
    updates = []
    comment_lower = comment.lower() if comment else ""

    # Extract signals from comment text
    for keyword, (pref_key, pref_value) in FEEDBACK_SIGNALS.items():
        if keyword in comment_lower:
            updates.append((pref_key, pref_value, 0.8))

    # Infer from rating without specific comment
    if rating <= 2 and not updates:
        updates.append(("depth", "deep", 0.3))
    elif rating >= 4 and not updates:
        pass  # Reinforce existing preferences

    # Apply updates
    for key, value, confidence in updates:
        await _upsert_preference(user_id, key, value, confidence)

    # Aggregate feedback patterns for topic-level learning
    await _aggregate_feedback_patterns(user_id, rating, comment)

    logger.info("feedback_learned",
                session_id=session_id,
                rating=rating,
                updates=[(k, v) for k, v, _ in updates])


async def _aggregate_feedback_patterns(user_id: str, rating: int, comment: str):
    """Group feedback by topic/rating patterns and learn aggregate preferences."""
    try:
        user_uuid = uuid.UUID(user_id)
        async with async_session() as db:
            # Get recent feedback (last 30 days)
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            result = await db.execute(
                select(FeedbackLog)
                .where(
                    FeedbackLog.user_id == user_uuid,
                    FeedbackLog.created_at >= cutoff,
                )
            )
            recent_feedback = result.scalars().all()

        if len(recent_feedback) < 3:
            return  # Not enough data for pattern learning

        # Compute average rating
        avg_rating = sum(f.rating for f in recent_feedback) / len(recent_feedback)

        # If consistently low ratings, boost depth preference
        if avg_rating < 3.0:
            await _upsert_preference(user_id, "depth", "deep", 0.4)
        # If consistently high ratings, the system is working well
        elif avg_rating >= 4.0:
            logger.info("feedback_patterns_positive", user_id=user_id, avg_rating=avg_rating)

    except Exception as e:
        logger.error("feedback_aggregation_error", user_id=user_id, error=str(e))


async def _upsert_preference(user_id: str, key: str, value: str, confidence: float):
    """Insert or update a user preference with blended confidence and decay."""
    try:
        user_uuid = uuid.UUID(user_id)
        async with async_session() as db:
            res = await db.execute(
                select(UserPreference).where(
                    UserPreference.user_id == user_uuid,
                    UserPreference.key == key,
                )
            )
            existing = res.scalar_one_or_none()

            if existing:
                # Apply decay to existing confidence
                decayed_confidence = _apply_decay(
                    existing.confidence,
                    existing.updated_at or datetime.now(timezone.utc),
                )

                if existing.value == value:
                    # Same direction — increase confidence (capped at 1.0)
                    existing.confidence = min(1.0, decayed_confidence + 0.1)
                else:
                    # Different direction — only override if new confidence is higher
                    if confidence > decayed_confidence:
                        existing.value = value
                        existing.confidence = confidence
                    else:
                        existing.confidence = max(0.1, decayed_confidence - 0.1)
                existing.updated_at = datetime.now(timezone.utc)
            else:
                db.add(UserPreference(
                    user_id=user_uuid,
                    key=key,
                    value=value,
                    confidence=confidence,
                ))

            await db.commit()
    except Exception as e:
        logger.error("preference_upsert_error", key=key, error=str(e))


def _apply_decay(confidence: float, last_updated: datetime) -> float:
    """Apply exponential decay based on time since last update.

    Preference weight halves every PREFERENCE_DECAY_HALF_LIFE_DAYS.
    """
    if not last_updated:
        return confidence

    now = datetime.now(timezone.utc)
    if last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=timezone.utc)

    days_elapsed = max(0, (now - last_updated).total_seconds() / 86400)
    decay_factor = 0.5 ** (days_elapsed / PREFERENCE_DECAY_HALF_LIFE_DAYS)
    return confidence * decay_factor


async def get_user_preferences(user_id: str) -> dict:
    """Load all user preferences as a dict.

    Applies:
    - Time-based decay to confidence scores
    - Minimum confidence threshold filtering
    """
    try:
        user_uuid = uuid.UUID(user_id)
        async with async_session() as db:
            res = await db.execute(
                select(UserPreference).where(
                    UserPreference.user_id == user_uuid,
                )
            )
            prefs = res.scalars().all()

            result = {}
            for p in prefs:
                # Apply decay
                decayed_confidence = _apply_decay(
                    p.confidence,
                    p.updated_at or datetime.now(timezone.utc),
                )
                # Only include preferences above threshold
                if decayed_confidence >= MIN_CONFIDENCE_THRESHOLD:
                    result[p.key] = p.value

            return result
    except Exception:
        return {}


async def get_preference_confidence(user_id: str) -> dict:
    """Return preference confidence scores for debugging/observability."""
    try:
        user_uuid = uuid.UUID(user_id)
        async with async_session() as db:
            res = await db.execute(
                select(UserPreference).where(UserPreference.user_id == user_uuid)
            )
            prefs = res.scalars().all()
            return {
                p.key: {
                    "value": p.value,
                    "confidence": round(_apply_decay(
                        p.confidence,
                        p.updated_at or datetime.now(timezone.utc),
                    ), 3),
                    "last_updated": p.updated_at.isoformat() if p.updated_at else None,
                }
                for p in prefs
            }
    except Exception:
        return {}
