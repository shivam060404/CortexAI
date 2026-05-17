"""
Reward Engine — Simulated RLHF scoring for plan selection.
Scores research plans based on user preferences, mode, and heuristics.
Used to select the best plan from multiple generated candidates.
"""

from backend.core.logger import get_logger

logger = get_logger(__name__)


def score_plan(plan_todos: list[dict], preferences: dict, mode_config: dict) -> float:
    """Score a research plan based on preferences and heuristics.
    
    Args:
        plan_todos: List of todo dicts with 'text' field
        preferences: User preference dict (depth, verbosity, style)
        mode_config: Research mode config from alignment engine
    
    Returns:
        Score (higher is better)
    """
    score = 0.0
    texts = [t.get("text", "").lower() for t in plan_todos]
    all_text = " ".join(texts)
    
    # ── Task count scoring ──
    task_count = len(plan_todos)
    depth = mode_config.get("depth", "comprehensive")
    
    if depth == "overview":
        # Fast mode: prefer fewer, focused tasks
        score += max(0, 5 - abs(task_count - 4)) * 0.5
    elif depth == "scholarly":
        # Academic mode: prefer more thorough tasks
        score += min(task_count, 10) * 0.3
    else:
        # Deep mode: balanced
        score += min(task_count, 8) * 0.25
    
    # ── Search diversity scoring ──
    search_terms = sum(1 for t in texts if any(w in t for w in ["search", "find", "look up", "research"]))
    score += min(search_terms, 5) * 0.8
    
    # ── Analysis scoring ──
    analysis_terms = sum(1 for t in texts if any(w in t for w in ["analyze", "compare", "evaluate", "assess"]))
    score += analysis_terms * 1.0
    
    # ── Critical thinking scoring ──
    critical_terms = sum(1 for t in texts if any(w in t for w in ["critic", "challenge", "bias", "limitation", "counter"]))
    score += critical_terms * 1.5
    
    # ── Synthesis scoring ──
    synthesis_terms = sum(1 for t in texts if any(w in t for w in ["synthesize", "summarize", "report", "write", "compile"]))
    score += synthesis_terms * 0.7
    
    # ── Mode-specific bonuses ──
    if depth == "scholarly":
        academic_terms = sum(1 for t in texts if any(w in t for w in ["paper", "study", "journal", "peer", "citation", "methodology"]))
        score += academic_terms * 1.2
    elif depth == "overview":
        if "key" in all_text or "main" in all_text or "top" in all_text:
            score += 1.5
    
    # ── User preference bonuses ──
    user_depth = preferences.get("depth", "")
    if user_depth == "deep" and task_count >= 6:
        score += 2.0
    elif user_depth == "concise" and task_count <= 5:
        score += 2.0
    
    if preferences.get("style") == "technical" and any("technical" in t or "implementation" in t for t in texts):
        score += 1.5
    
    return round(score, 2)


def select_best_plan(plans: list[list[dict]], preferences: dict, mode_config: dict) -> tuple[list[dict], list[float]]:
    """Select the best plan from multiple candidates.
    
    Args:
        plans: List of plan candidates (each is a list of todo dicts)
        preferences: User preferences
        mode_config: Research mode config
    
    Returns:
        Tuple of (best_plan, all_scores)
    """
    if not plans:
        return [], []
    
    scores = [score_plan(p, preferences, mode_config) for p in plans]
    best_idx = scores.index(max(scores))
    
    logger.info("plan_selected",
                 plan_count=len(plans),
                 scores=scores,
                 best_idx=best_idx,
                 best_score=scores[best_idx])
    
    return plans[best_idx], scores
