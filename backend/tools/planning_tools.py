"""
Planning tools — write_todos / get_todos with state machine transitions.
Agents use these to manage their own task lists dynamically.
Includes autonomous task expansion for vague plans.
"""

import json
import uuid
import asyncio
from langchain_core.tools import tool
from langchain_mistralai.chat_models import ChatMistralAI
from backend.core.logger import get_logger
from backend.config import settings

logger = get_logger(__name__)

# In-memory per-session todo storage (synced to DB asynchronously)
_session_todos: dict[str, list[dict]] = {}

VALID_STATUSES = {"pending", "in_progress", "completed", "failed"}
VALID_TRANSITIONS = {
    "pending": {"in_progress"},
    "in_progress": {"completed", "failed"},
    "completed": set(),
    "failed": {"pending"},  # allow retry
}


async def _sync_todos_to_db(session_id: str, todos: list[dict]):
    """Fire-and-forget: persist current todos to the TodoItem table."""
    try:
        from backend.db.postgres import async_session, TodoItem
        from sqlalchemy import delete

        async with async_session() as db:
            # Clear existing todos for this session
            await db.execute(
                delete(TodoItem).where(TodoItem.session_id == session_id)
            )
            # Insert current todos
            for t in todos:
                db.add(TodoItem(
                    session_id=session_id,
                    text=t["text"],
                    status=t["status"],
                    order=t["order"],
                    error_message=t.get("error_message", ""),
                ))
            await db.commit()
            logger.info("todos_synced_to_db", session_id=session_id, count=len(todos))
    except Exception as e:
        logger.error("todos_db_sync_failed", session_id=session_id, error=str(e))


def get_planning_tools(session_id: str):
    """Return planning tools bound to a specific session."""

    @tool
    async def write_todos(todos_json: str) -> str:
        """Create or replace the research task list. Input must be a JSON array of objects with 'text' and optional 'status' fields.
        Example: [{"text": "Search for climate data", "status": "pending"}, {"text": "Analyze trends", "status": "pending"}]
        Valid statuses: pending, in_progress, completed, failed.
        State transitions: pending→in_progress, in_progress→completed|failed, failed→pending (retry)."""
        try:
            items = json.loads(todos_json)
            if not isinstance(items, list):
                return "Error: Input must be a JSON array of todo objects."

            # Autonomous Task Expansion: If plan is too brief, auto-expand it
            if len(items) > 0 and len(items) <= 3:
                logger.info("expanding_vague_plan", session_id=session_id)
                try:
                    llm = ChatMistralAI(
                        model="mistral-large-latest",
                        temperature=0.3,
                        api_key=settings.MISTRAL_API_KEY,
                    )
                    prompt = (
                        "You are an expert research planner assisting an AI lab assistant. "
                        "The user provided a very brief or vague research plan:\n"
                        f"{json.dumps(items)}\n"
                        "Break this down into 5 to 10 highly detailed, actionable, concrete steps for a deep research agent. "
                        "Return ONLY a raw JSON array of objects with a 'text' field (the task description) and 'status' (set to 'pending'). "
                        "Do not include markdown formatting or backticks."
                    )
                    res = await llm.ainvoke(prompt)
                    expanded_text = res.content.strip()
                    if expanded_text.startswith("```json"):
                        expanded_text = expanded_text.replace("```json", "").replace("```", "").strip()
                    elif expanded_text.startswith("```"):
                        expanded_text = expanded_text.replace("```", "").strip()

                    expanded_items = json.loads(expanded_text)
                    if isinstance(expanded_items, list) and len(expanded_items) > 0:
                        items = expanded_items
                        logger.info("plan_expanded", session_id=session_id, new_count=len(items))
                except Exception as e:
                    logger.error("plan_expansion_failed", error=str(e))

            todos = []
            for i, item in enumerate(items):
                if isinstance(item, str):
                    item = {"text": item}
                status = item.get("status", "pending")
                if status not in VALID_STATUSES:
                    status = "pending"

                # Validate state transitions if updating existing todos
                existing = _session_todos.get(session_id, [])
                if i < len(existing):
                    old_status = existing[i].get("status", "pending")
                    if status != old_status and status not in VALID_TRANSITIONS.get(old_status, set()):
                        return f"Error: Invalid transition for item {i}: {old_status} → {status}"

                todos.append({
                    "id": str(uuid.uuid4()),
                    "text": item.get("text", item.get("task", str(item))),
                    "status": status,
                    "order": i,
                    "error_message": item.get("error_message", ""),
                })

            _session_todos[session_id] = todos
            logger.info("todos_updated", session_id=session_id, count=len(todos))

            # Persist to DB (awaited to guarantee durability)
            await _sync_todos_to_db(session_id, todos)

            return f"Task list updated: {len(todos)} items."
        except json.JSONDecodeError:
            return "Error: Invalid JSON. Please provide a JSON array."

    @tool
    def get_todos() -> str:
        """Retrieve the current research task list with status for each item."""
        todos = _session_todos.get(session_id, [])
        if not todos:
            return "No tasks yet. Use write_todos to create a plan."
        lines = []
        status_icons = {
            "pending": "⏳", "in_progress": "🔄",
            "completed": "✅", "failed": "❌"
        }
        for t in todos:
            icon = status_icons.get(t["status"], "•")
            err = f" (Error: {t['error_message']})" if t.get("error_message") else ""
            lines.append(f"{icon} [{t['status']}] {t['text']}{err}")
        return "\n".join(lines)

    return [write_todos, get_todos]


def get_session_todos(session_id: str) -> list[dict]:
    """Get raw todos for a session (used by API)."""
    return _session_todos.get(session_id, [])
