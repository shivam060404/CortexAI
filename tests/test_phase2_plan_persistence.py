import asyncio

import pytest

from backend.tools.planning_tools import _normalize_todo_items, _parse_todo_payload, get_session_todos


def test_parse_todo_payload_accepts_json_and_plaintext():
    assert _parse_todo_payload('{"todos":[{"text":"First step"}]}') == [{"text": "First step"}]
    assert _parse_todo_payload("- One\n- Two") == ["One", "Two"]


def test_normalize_todo_items_discards_empty_values_and_normalizes_statuses():
    todos = _normalize_todo_items(
        [
            {"text": "Collect evidence", "status": "IN_PROGRESS"},
            {"text": " ", "status": "completed"},
            {"task": "Summarize findings", "status": "not-a-real-status"},
        ]
    )

    assert len(todos) == 2
    assert todos[0]["status"] == "in_progress"
    assert todos[1]["text"] == "Summarize findings"
    assert todos[1]["status"] == "pending"


def test_plan_repository_calls_require_tenant_context():
    with pytest.raises(PermissionError):
        asyncio.run(get_session_todos("session-without-context"))
