import importlib.util
import sys

from backend.core.supervisor_events import extract_supervisor_stream_messages
from scripts.run_phase2_evals import _resolve_pip_audit_command
from scripts.simulate_worker_load import _load_queue_runtime


def test_extract_supervisor_stream_messages_emits_phase_and_mapped_events():
    messages, phase, event_count = extract_supervisor_stream_messages(
        {
            "supervisor_phase": "PLANNING",
            "supervisor_events": [
                {"phase": "PLANNING", "event_type": "supervisor.plan.created", "version": 2},
                {"phase": "WAITING", "event_type": "worker.task.completed", "worker": "SearchAgent"},
                {"phase": "WAITING", "event_type": "ignored.event"},
            ],
        },
        last_phase=None,
        sent_event_count=0,
    )

    assert phase == "PLANNING"
    assert event_count == 3
    assert [message["type"] for message in messages] == [
        "phase_change",
        "plan_created",
        "task_completed",
    ]
    assert messages[1]["data"]["event_type"] == "supervisor.plan.created"
    assert messages[2]["data"]["worker"] == "SearchAgent"


def test_resolve_pip_audit_command_falls_back_to_module(monkeypatch):
    monkeypatch.setattr("scripts.run_phase2_evals.shutil.which", lambda _: None)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if name == "pip_audit" else None)

    assert _resolve_pip_audit_command() == [sys.executable, "-m", "pip_audit"]


def test_load_queue_runtime_reports_missing_dependency(monkeypatch):
    def fake_import_module(_module_name: str):
        raise ModuleNotFoundError("No module named 'redis'", name="redis")

    monkeypatch.setattr("scripts.simulate_worker_load.importlib.import_module", fake_import_module)

    runtime, error = _load_queue_runtime(25, "cortex:jobs:loadtest")

    assert runtime is None
    assert error == {
        "queue_name": "cortex:jobs:loadtest",
        "jobs_requested": 25,
        "status": "blocked",
        "error": "Missing dependency: redis",
    }
