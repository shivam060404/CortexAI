"""
Search tools — TavilySearch with Redis caching and retry logic.
"""

from langchain_core.tools import tool
from langchain_community.tools.tavily_search import TavilySearchResults as TavilySearch
from backend.db.cache import CacheManager
from backend.core.retry import retry_with_backoff, CircuitBreaker
from backend.core.logger import get_logger
from backend.config import settings
from backend.core.ranking_engine import rank_search_results
from backend.core.rag_pipeline import rag_pipeline

logger = get_logger(__name__)
_cache = CacheManager()
_search_breaker = CircuitBreaker()


def _make_cached_search(name: str, description: str):
    """Factory: creates a cached, retry-wrapped search tool."""

    tavily = TavilySearch(
        max_results=5, 
        description=description,
        tavily_api_key=settings.TAVILY_API_KEY
    )

    @tool(name)
    async def search_tool(query: str) -> str:
        """Search the web for information on the given query. Returns relevant results."""
        # Check circuit breaker
        _search_breaker.check("tavily")

        # Check cache first
        cached = await _cache.get_search(f"{name}:{query}")
        if cached:
            logger.info("search_cache_hit", tool=name, query=query[:80])
            return str(cached)

        # Call Tavily with retry (wrapped in thread to avoid blocking event loop)
        import asyncio

        @retry_with_backoff(max_retries=3, exceptions=(Exception,))
        def _invoke():
            return tavily.invoke(query)

        try:
            raw_result = await asyncio.to_thread(_invoke)
            _search_breaker.record_success()
            
            # Format and rank the results (assuming list of dicts from tavily)
            if isinstance(raw_result, list):
                ranked = rank_search_results(query, raw_result)
                # Format into readability strings for the LLM
                formatted_list = [
                    f"URL: {r.get('url')} | Title: {r.get('title')} | {r.get('formatted_content')}"
                    for r in ranked
                ]
                final_str = "\n\n---\n\n".join(formatted_list)
                cache_payload = ranked
            else:
                final_str = str(raw_result)
                cache_payload = [{"content": final_str}]

            # Cache the result
            await _cache.set_search(f"{name}:{query}", cache_payload)
            logger.info("search_complete", tool=name, query=query[:80])
            return final_str
        except Exception as e:
            _search_breaker.record_failure("tavily")
            logger.error("search_failed", tool=name, query=query[:80], error=str(e))
            return f"Search failed after retries: {str(e)}"

    search_tool.__doc__ = description
    return search_tool


def get_search_tools():
    """Return the list of search tools.
    
    Tavily-based tools are always provided as the baseline search capability.
    MCP tools (when enabled) supplement these via the MCP protocol, but never
    replace the built-in tools — ensuring search always works (Feature Gap #3 fix).
    """
    tools = [
        _make_cached_search(
            "web_search",
            "Search the web for general information from websites, blogs, and forums."
        ),
        _make_cached_search(
            "academic_search",
            "Search for academic papers, journals, and scientific articles."
        ),
        _make_cached_search(
            "news_search",
            "Search for recent news articles, current events, and media coverage."
        ),
    ]

    # MCP tools are registered separately via the MCP registry and bound at
    # graph-build time; they *add to* the tool list rather than replacing it.

    # RAG search tool — queries the session's LanceDB vector store (Feature Gap #6)
    @tool
    async def rag_search(query: str) -> str:
        """Search the session's knowledge base for relevant previously ingested documents.
        Use this to find information from documents the user has uploaded or that have been
        stored during prior research in this session."""
        # The session_id is injected by the tool node at runtime via state
        # For the search agent, we pass "default" as session context
        results = await rag_pipeline.hybrid_search("default", query)
        if not results:
            return "No relevant documents found in the session knowledge base."
        formatted = []
        for r in results[:5]:
            content = r.get("content", "")[:500]
            score = r.get("relevance_score", 0)
            formatted.append(f"[Score: {score:.2f}] {content}")
        return "\n\n---\n\n".join(formatted)

    tools.append(rag_search)
    return tools
