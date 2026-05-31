from backend.core.graph import (
    _analyze_query,
    _build_fallback_plan,
    decide_evaluation_outcome,
    decide_next_step,
)
from backend.tools.planning_tools import _derive_plan_status


def test_fallback_plan_creates_ordered_pending_tasks():
    tasks = _build_fallback_plan("Audit churn reduction opportunities")

    assert len(tasks) == 4
    assert [task["order"] for task in tasks] == [0, 1, 2, 3]
    assert all(task["status"] == "pending" for task in tasks)
    assert all(task["text"] for task in tasks)


def test_plan_status_derivation_tracks_progress():
    assert _derive_plan_status([]) == "draft"
    assert _derive_plan_status([{"status": "pending"}]) == "pending"
    assert _derive_plan_status([{"status": "in_progress"}, {"status": "pending"}]) == "in_progress"
    assert _derive_plan_status([{"status": "failed"}, {"status": "pending"}]) == "failed"
    assert _derive_plan_status([{"status": "completed"}, {"status": "completed"}]) == "completed"


def test_supervisor_requires_plan_before_worker_execution():
    assert decide_next_step(plan_version=0, plan_status="missing", iteration=0, last_worker=None) == "Planner"
    assert decide_next_step(plan_version=2, plan_status="failed", iteration=1, last_worker="SearchAgent") == "Planner"


def test_supervisor_finishes_or_alternates_workers():
    assert decide_next_step(plan_version=3, plan_status="completed", iteration=1, last_worker=None) == "FINISH"
    assert decide_next_step(plan_version=3, plan_status="pending", iteration=999, last_worker=None) == "FINISH"
    assert decide_next_step(plan_version=1, plan_status="pending", iteration=1, last_worker=None) == "SearchAgent"
    assert decide_next_step(plan_version=1, plan_status="in_progress", iteration=2, last_worker="SearchAgent") == "VerificationAgent"


def test_query_analysis_rejects_empty_requests_and_summarizes_valid_queries():
    invalid = _analyze_query("   ")
    valid = _analyze_query("Compare pipeline risk for enterprise retention accounts with benchmark evidence")

    assert invalid["valid"] is False
    assert "empty" in invalid["summary"].lower()
    assert valid["valid"] is True
    assert "pipeline" in valid["summary"].lower()
    assert "benchmark" in valid["summary"].lower()


def test_evaluation_outcome_routes_to_replan_dispatch_or_compile():
    assert decide_evaluation_outcome(
        plan_version=0,
        plan_status="missing",
        iteration=0,
        last_worker=None,
        evidence_confidence=0.0,
    ) == "REPLANNING"
    assert decide_evaluation_outcome(
        plan_version=2,
        plan_status="in_progress",
        iteration=1,
        last_worker="SearchAgent",
        evidence_confidence=0.55,
    ) == "DISPATCHING"
    assert decide_evaluation_outcome(
        plan_version=2,
        plan_status="in_progress",
        iteration=2,
        last_worker="VerificationAgent",
        evidence_confidence=0.91,
    ) == "COMPILING"
