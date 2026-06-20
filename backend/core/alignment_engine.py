"""
Alignment Engine — Pre-research intelligence layer.
Refines user queries, detects ambiguity, adapts to user preferences.
This runs BEFORE the agent starts planning — the RLHF alignment core.
"""

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_litellm import ChatLiteLLM
from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

# Research modes define how the alignment engine shapes the query
RESEARCH_MODES = {
    "fast": {
        "label": "⚡ Fast",
        "max_sources": 5,
        "depth": "overview",
        "instructions": "Provide a quick, focused summary. Prioritize speed over depth. Use 3-5 sources max.",
    },
    "deep": {
        "label": "🧠 Deep",
        "max_sources": 20,
        "depth": "comprehensive",
        "instructions": "Conduct thorough multi-angle research. Explore contrasting viewpoints. Use 15-20 sources. Include detailed analysis.",
    },
    "academic": {
        "label": "🔬 Academic",
        "max_sources": 30,
        "depth": "scholarly",
        "instructions": "Focus on peer-reviewed papers, academic databases, and scholarly sources. Use formal structure with methodology discussion. Cite with proper academic format.",
    },
}


def needs_clarification(query: str) -> dict | None:
    """Detect if a query is too vague and needs clarification.
    
    Returns None if query is clear enough, or a dict with clarification details.
    """
    words = query.strip().split()
    
    # Too short
    if len(words) < 3:
        return {
            "reason": "too_short",
            "message": "Your query is very brief. Could you provide more details about what you'd like to research?",
            "question": "What specifically would you like to research about this topic?",
            "suggestions": [
                "Give me a comprehensive deep dive",
                "Just a quick overview with key facts",
                "Focus on recent developments and news",
                "Academic and peer-reviewed sources only",
            ],
        }
    
    # Extremely vague single-concept queries
    vague_patterns = ["tell me about", "what is", "explain", "describe"]
    lower = query.lower().strip()
    if any(lower.startswith(p) for p in vague_patterns) and len(words) < 6:
        return {
            "reason": "too_vague",
            "message": "This is a broad topic. Would you like to focus on a specific aspect, time period, or application?",
            "question": "Which angle interests you most?",
            "suggestions": [
                "Historical background and evolution",
                "Current state and recent breakthroughs",
                "Practical applications and real-world impact",
                "Technical deep dive with academic sources",
                "Pros, cons, and critical analysis",
            ],
        }
    
    return None


async def align_query(query: str, mode: str = "deep", user_prefs: dict | None = None) -> dict:
    """Align the user query before research starts.
    
    This is the RLHF alignment core - refines the query based on:
    1. Research mode (fast/deep/academic)
    2. User preferences from past feedback
    3. Ambiguity resolution
    
    Returns:
        dict with 'refined_query', 'mode_config', 'decomposed_queries', 'search_strategy'
    """
    mode_config = RESEARCH_MODES.get(mode, RESEARCH_MODES["deep"])
    prefs_text = ""
    
    if user_prefs:
        pref_parts = []
        if user_prefs.get("verbosity"):
            pref_parts.append(f"Verbosity preference: {user_prefs['verbosity']}")
        if user_prefs.get("depth"):
            pref_parts.append(f"Depth preference: {user_prefs['depth']}")
        if user_prefs.get("style"):
            pref_parts.append(f"Style preference: {user_prefs['style']}")
        if user_prefs.get("topics"):
            pref_parts.append(f"Known interests: {', '.join(user_prefs['topics'][:5])}")
        if pref_parts:
            prefs_text = "\n".join(pref_parts)

    llm = ChatLiteLLM(
        model=settings.FAST_MODEL,
        temperature=0.2,
    )

    messages = [
        SystemMessage(content=f"""You are a research query optimizer. Your job is to refine and decompose research queries for maximum effectiveness.

Research Mode: {mode_config['label']} ({mode_config['depth']})
Mode Instructions: {mode_config['instructions']}
{f'User Preferences: {prefs_text}' if prefs_text else ''}

Given the user's research query, output a JSON object with:
1. "refined_query": An improved, more specific version of the query that will produce better research results
2. "sub_queries": An array of 2-5 focused sub-questions that decompose the main query into searchable components
3. "search_strategy": A brief string describing the search approach (e.g. "academic-first", "recent-news-focus", "multi-perspective")

Output ONLY valid JSON. No markdown, no explanation."""),
        HumanMessage(content=query),
    ]

    try:
        response = await llm.ainvoke(messages)
        import json
        # Try to parse JSON from response
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        
        result = json.loads(text)
        
        logger.info("query_aligned", 
                     original=query[:80], 
                     refined=result.get("refined_query", "")[:80],
                     sub_queries=len(result.get("sub_queries", [])),
                     mode=mode)
        
        return {
            "refined_query": result.get("refined_query", query),
            "sub_queries": result.get("sub_queries", []),
            "search_strategy": result.get("search_strategy", "balanced"),
            "mode_config": mode_config,
            "original_query": query,
        }
    except Exception as e:
        logger.error("alignment_failed", error=str(e), query=query[:80])
        # Graceful fallback — use original query
        return {
            "refined_query": query,
            "sub_queries": [],
            "search_strategy": "balanced",
            "mode_config": mode_config,
            "original_query": query,
        }
