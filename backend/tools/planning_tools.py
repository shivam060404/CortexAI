"""Planning tools and persistence helpers for Phase 2 research plan storage."""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_core.tools import tool
from sqlalchemy import delete, func, select, update

from backend.core.logger import get_logger
from backend.db.postgres import ResearchPlan, ResearchSession, TodoItem, TodoStatus, async_session
from backend.db.tenant import get_tenant_context

logger = get_logger(__name__)

_session_todos: dict[str, list[dict[str, Any]]] = {}

VALID_STATUSES = {"pending", "in_progress", "completed", "failed"}
VALID_TRANSITIONS = {
    "pending": {"pending", "in_progress"},
    "in_progress": {"in_progress", "completed", "failed"},
    "completed": {"completed"},
    "failed": {"failed", "pending"},
}


def _ensure_tenant_context() -> Any:
    context = get_tenant_context()
    if context.source != "system" and not context.user_id:
        raise PermissionError("Tenant context is required for plan persistence operations")
    return context


def _coerce_uuid(value: Any) -> uuid.UUID:
    return uuid.UUID(str(value))


def _coerce_todo_status(value: Any) -> str:
    status = str(value or "pending").strip().lower()
    return status if status in VALID_STATUSES else "pending"


def _normalize_todo_items(items: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            item = {"text": str(item)}

        raw_id = item.get("id")
        try:
            todo_id = str(_coerce_uuid(raw_id)) if raw_id else str(uuid.uuid4())
        except (TypeError, ValueError, AttributeError):
            todo_id = str(uuid.uuid4())

        normalized.append(
            {
                "id": todo_id,
                "text": str(item.get("text") or item.get("task") or "").strip()[:1000],
                "status": _coerce_todo_status(item.get("status")),
                "order": index,
                "error_message": str(item.get("error_message") or "").strip()[:2000],
            }
        )
    return [todo for todo in normalized if todo["text"]]


def _derive_plan_status(items: list[dict[str, Any]]) -> str:
    if not items:
        return "draft"

    statuses = {_coerce_todo_status(item.get("status")) for item in items}
    if "failed" in statuses:
        return "failed"
    if statuses == {"completed"}:
        return "completed"
    if "in_progress" in statuses:
        return "in_progress"
    return "pending"


def _build_plan_summary(items: list[dict[str, Any]]) -> str:
    preview = [todo["text"] for todo in items[:3]]
    if not preview:
        return "No active tasks"
    summary = "; ".join(preview)
    if len(items) > 3:
        summary += f"; +{len(items) - 3} more"
    return summary[:1000]


def _serialize_todo(todo: TodoItem | dict[str, Any]) -> dict[str, Any]:
    if isinstance(todo, dict):
        return {
            "id": str(todo["id"]),
            "text": todo["text"],
            "status": _coerce_todo_status(todo.get("status")),
            "order": int(todo.get("order", 0)),
            "error_message": str(todo.get("error_message") or ""),
        }
    return {
        "id": str(todo.id),
        "text": todo.text,
        "status": todo.status.value if hasattr(todo.status, "value") else str(todo.status),
        "order": todo.order,
        "error_message": todo.error_message or "",
    }


def _serialize_plan(plan: ResearchPlan) -> dict[str, Any]:
    return {
        "id": str(plan.id),
        "session_id": str(plan.session_id),
        "version": int(plan.version),
        "status": plan.status,
        "source": plan.source,
        "summary": plan.summary or "",
        "todos": list(plan.todos or []),
        "is_current": bool(plan.is_current),
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }


async def _load_owned_session(db, session_id: str, context) -> ResearchSession | None:
    query = select(ResearchSession).where(ResearchSession.id == _coerce_uuid(session_id))
    if not context.is_admin and context.user_id:
        query = query.where(ResearchSession.user_id == _coerce_uuid(context.user_id))
    return (await db.execute(query)).scalar_one_or_none()


async def _replace_session_todos(db, session_uuid: uuid.UUID, items: list[dict[str, Any]]) -> None:
    await db.execute(delete(TodoItem).where(TodoItem.session_id == session_uuid))
    for item in items:
        db.add(
            TodoItem(
                id=_coerce_uuid(item["id"]),
                session_id=session_uuid,
                text=item["text"],
                status=TodoStatus(item["status"]),
                order=item["order"],
                error_message=item["error_message"],
            )
        )


async def persist_research_plan(
    session_id: str,
    todos: list[Any],
    *,
    source: str = "tool",
    summary: str | None = None,
) -> dict[str, Any]:
    context = _ensure_tenant_context()
    normalized_todos = _normalize_todo_items(todos)
    session_uuid = _coerce_uuid(session_id)

    async with async_session() as db:
        session = await _load_owned_session(db, session_id, context)
        if session is None:
            raise PermissionError("Session not found in the active tenant context")

        next_version = (
            await db.execute(
                select(func.coalesce(func.max(ResearchPlan.version), 0)).where(
                    ResearchPlan.session_id == session_uuid
                )
            )
        ).scalar_one()
        next_version = int(next_version or 0) + 1

        await db.execute(
            update(ResearchPlan)
            .where(ResearchPlan.session_id == session_uuid, ResearchPlan.is_current.is_(True))
            .values(is_current=False)
        )

        plan = ResearchPlan(
            session_id=session_uuid,
            version=next_version,
            status=_derive_plan_status(normalized_todos),
            source=source[:50],
            summary=(summary or _build_plan_summary(normalized_todos))[:1000],
            todos=normalized_todos,
            is_current=True,
        )
        db.add(plan)
        await _replace_session_todos(db, session_uuid, normalized_todos)
        await db.commit()
        await db.refresh(plan)

    serialized = _serialize_plan(plan)
    _session_todos[session_id] = list(serialized["todos"])
    logger.info(
        "research_plan_persisted",
        session_id=session_id,
        version=serialized["version"],
        status=serialized["status"],
        todo_count=len(serialized["todos"]),
    )
    return serialized


async def load_latest_plan(session_id: str) -> dict[str, Any] | None:
    context = _ensure_tenant_context()
    async with async_session() as db:
        session = await _load_owned_session(db, session_id, context)
        if session is None:
            raise PermissionError("Session not found in the active tenant context")

        plan = (
            await db.execute(
                select(ResearchPlan)
                .where(ResearchPlan.session_id == _coerce_uuid(session_id))
                .order_by(ResearchPlan.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if plan is None:
            return None
        serialized = _serialize_plan(plan)
        _session_todos[session_id] = list(serialized["todos"])
        return serialized


async def list_plan_versions(session_id: str) -> list[dict[str, Any]]:
    context = _ensure_tenant_context()
    async with async_session() as db:
        session = await _load_owned_session(db, session_id, context)
        if session is None:
            raise PermissionError("Session not found in the active tenant context")

        plans = (
            await db.execute(
                select(ResearchPlan)
                .where(ResearchPlan.session_id == _coerce_uuid(session_id))
                .order_by(ResearchPlan.version.desc())
            )
        ).scalars().all()
    return [_serialize_plan(plan) for plan in plans]


async def get_session_todos(session_id: str) -> list[dict[str, Any]]:
    context = _ensure_tenant_context()
    async with async_session() as db:
        session = await _load_owned_session(db, session_id, context)
        if session is None:
            raise PermissionError("Session not found in the active tenant context")

        todos = (
            await db.execute(
                select(TodoItem)
                .where(TodoItem.session_id == _coerce_uuid(session_id))
                .order_by(TodoItem.order.asc())
            )
        ).scalars().all()

    serialized = [_serialize_todo(todo) for todo in todos]
    _session_todos[session_id] = serialized
    return serialized


def get_cached_session_todos(session_id: str) -> list[dict[str, Any]]:
    return list(_session_todos.get(session_id, []))


def _parse_todo_payload(todos_json: str) -> list[Any]:
    text = str(todos_json or "").strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [line.strip("- ").strip() for line in text.splitlines() if line.strip()]

    if isinstance(parsed, dict) and "todos" in parsed:
        parsed = parsed["todos"]
    if isinstance(parsed, list):
        return parsed
    return [parsed]


def get_planning_tools(session_id: str):
    @tool
    async def write_todos(todos_json: str) -> str:
        """Persist a research plan as JSON. Accepts an array of todo objects with `text` and optional `status`."""
        parsed_todos = _parse_todo_payload(todos_json)
        plan = await persist_research_plan(session_id, parsed_todos, source="tool")
        todo_lines = [f"{item['order'] + 1}. [{item['status']}] {item['text']}" for item in plan["todos"]]
        return (
            f"Persisted research plan v{plan['version']} with status '{plan['status']}'.\n"
            + "\n".join(todo_lines)
        )

    @tool
    async def get_todos() -> str:
        """Return the active persisted todo list for the session."""
        todos = await get_session_todos(session_id)
        return json.dumps(todos)

    return [write_todos, get_todos]
