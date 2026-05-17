import json
from datetime import datetime, timezone
from sqlalchemy import select, String, cast
from sqlalchemy.ext.asyncio import AsyncSession
from backend.db.postgres import async_session, UserMemory
from backend.core.logger import get_logger

logger = get_logger(__name__)

async def get_user_memory_context() -> str:
    """Retrieve top interests from user memory."""
    try:
        async with async_session() as db:
            res = await db.execute(
                select(UserMemory).order_by(UserMemory.relevance_score.desc()).limit(10)
            )
            memories = res.scalars().all()
            if not memories:
                return "No past preferences recorded yet."
            
            topics = [f"- {m.topic} (Relevance: {m.relevance_score})" for m in memories]
            return "User's past research interests:\n" + "\n".join(topics)
    except Exception as e:
        logger.error("get_user_memory_error", error=str(e))
        return "Failed to retrieve user memory."

async def update_user_memory(query: str):
    """Extract and update user interests based on a new search query."""
    # A simple keyword heuristic: assume the query itself or key words are the topic.
    # In a full production system, we'd use an LLM or NLP to extract exact topics.
    # For now, we will just save the full query if it's short, or split it.
    
    topic = query.strip()[:100] # Limiting size for simplicity
    if not topic:
        return

    try:
        async with async_session() as db:
            # Check if this topic exists
            res = await db.execute(select(UserMemory).where(UserMemory.topic == topic))
            memory = res.scalars().first()
            
            if memory:
                memory.relevance_score += 1
                memory.last_accessed = datetime.now(timezone.utc)
            else:
                db.add(UserMemory(topic=topic))
            
            await db.commit()
            logger.info("user_memory_updated", topic=topic)
    except Exception as e:
        logger.error("update_user_memory_error", error=str(e))
