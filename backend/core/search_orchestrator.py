"""
Batch & Deep Search Orchestration (Phase 3).

Provides advanced search capabilities beyond single-query search:
  - **Batch mode**: Execute multiple queries in parallel with deduplication
  - **Deep mode**: Iterative deepening with follow-up queries from initial results
  - **Priority scheduling**: Critical queries execute first
  - **Result synthesis**: Aggregate and deduplicate across all queries
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from backend.core.logger import get_logger

logger = get_logger(__name__)


class SearchDepth(str, Enum):
    """Search depth levels."""
    SURFACE = "surface"     # Quick, top results only
    STANDARD = "standard"   # Normal depth
    DEEP = "deep"          # Iterative deepening with follow-ups
    EXHAUSTIVE = "exhaustive"  # Maximum depth with cross-referencing


class SearchPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass
class SearchQuery:
    """A single search query with metadata."""
    text: str
    priority: SearchPriority = SearchPriority.NORMAL
    depth: SearchDepth = SearchDepth.STANDARD
    category: str = "web"  # web, academic, news
    source_query: str = ""  # The original query that generated this (for deep mode)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def query_hash(self) -> str:
        return hashlib.sha256(self.text.lower().strip().encode()).hexdigest()[:16]


@dataclass
class SearchResult:
    """A single search result with provenance."""
    url: str
    title: str
    content: str
    score: float = 0.0
    source: str = ""  # tavily, exa, firecrawl, rag
    query_text: str = ""
    depth_level: int = 0
    retrieved_at: float = field(default_factory=time.time)


@dataclass
class BatchSearchResult:
    """Result of a batch search operation."""
    query: SearchQuery
    results: list[SearchResult] = field(default_factory=list)
    error: str = ""
    duration_ms: float = 0.0
    cache_hit: bool = False


@dataclass
class SearchOrchestrationResult:
    """Aggregated result from a batch/deep search operation."""
    results: list[SearchResult] = field(default_factory=list)
    query_results: list[BatchSearchResult] = field(default_factory=list)
    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0
    total_duration_ms: float = 0.0
    unique_urls: int = 0
    synthesis: str = ""


class SearchOrchestrator:
    """
    Orchestrates batch and deep search operations.

    Usage:
        orchestrator = SearchOrchestrator()
        queries = [
            SearchQuery("What is quantum computing?", depth=SearchDepth.DEEP),
            SearchQuery("Latest quantum computing breakthroughs", category="news"),
        ]
        result = await orchestrator.execute_batch(queries)
    """

    def __init__(self):
        self._seen_urls: set[str] = set()
        self._seen_hashes: set[str] = set()

    # ------------------------------------------------------------------
    # Batch Search
    # ------------------------------------------------------------------
    async def execute_batch(
        self,
        queries: list[SearchQuery],
        max_concurrent: int = 5,
        timeout_per_query: float = 30.0,
    ) -> SearchOrchestrationResult:
        """Execute multiple search queries in parallel with deduplication.

        Args:
            queries: List of search queries to execute.
            max_concurrent: Maximum parallel search queries.
            timeout_per_query: Timeout per individual query in seconds.

        Returns:
            Aggregated search results with deduplication.
        """
        start_time = time.time()

        # Deduplicate queries by hash
        unique_queries = self._deduplicate_queries(queries)
        logger.info("batch_search_start", total=len(queries), unique=len(unique_queries))

        # Sort by priority (critical first)
        priority_order = {
            SearchPriority.CRITICAL: 0,
            SearchPriority.HIGH: 1,
            SearchPriority.NORMAL: 2,
            SearchPriority.LOW: 3,
        }
        unique_queries.sort(key=lambda q: priority_order.get(q.priority, 2))

        # Execute with concurrency limit
        semaphore = asyncio.Semaphore(max_concurrent)
        tasks = [
            self._execute_single_query(query, semaphore, timeout_per_query)
            for query in unique_queries
        ]
        query_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        all_results: list[SearchResult] = []
        successful = 0
        failed = 0
        processed_results: list[BatchSearchResult] = []

        for qr in query_results:
            if isinstance(qr, Exception):
                failed += 1
                logger.warning("batch_query_exception", error=str(qr))
                continue
            if isinstance(qr, BatchSearchResult):
                processed_results.append(qr)
                if qr.error:
                    failed += 1
                else:
                    successful += 1
                    for result in qr.results:
                        if result.url not in self._seen_urls:
                            self._seen_urls.add(result.url)
                            all_results.append(result)

        total_duration = (time.time() - start_time) * 1000

        # Sort results by score descending
        all_results.sort(key=lambda r: r.score, reverse=True)

        result = SearchOrchestrationResult(
            results=all_results,
            query_results=processed_results,
            total_queries=len(queries),
            successful_queries=successful,
            failed_queries=failed,
            total_duration_ms=round(total_duration, 1),
            unique_urls=len(all_results),
        )

        logger.info(
            "batch_search_complete",
            total=len(queries),
            successful=successful,
            failed=failed,
            unique_urls=len(all_results),
            duration_ms=round(total_duration, 1),
        )
        return result

    # ------------------------------------------------------------------
    # Deep Search (Iterative Deepening)
    # ------------------------------------------------------------------
    async def execute_deep(
        self,
        initial_query: str,
        max_depth: int = 3,
        follow_ups_per_level: int = 3,
        category: str = "web",
    ) -> SearchOrchestrationResult:
        """Execute an iterative deep search with automatic follow-up generation.

        Starts with an initial query, then generates follow-up queries based
        on results at each depth level.

        Args:
            initial_query: The starting search query.
            max_depth: Maximum depth levels to explore.
            follow_ups_per_level: Number of follow-up queries per level.
            category: Search category (web, academic, news).

        Returns:
            Aggregated results across all depth levels.
        """
        start_time = time.time()
        all_results: list[SearchResult] = []
        all_query_results: list[BatchSearchResult] = []
        current_queries = [
            SearchQuery(
                text=initial_query,
                depth=SearchDepth.DEEP,
                category=category,
                priority=SearchPriority.HIGH,
            )
        ]

        for depth_level in range(max_depth):
            if not current_queries:
                break

            logger.info("deep_search_level", depth=depth_level, queries=len(current_queries))

            # Execute current level queries
            batch_result = await self.execute_batch(
                current_queries,
                max_concurrent=3,
                timeout_per_query=30.0,
            )

            all_results.extend(batch_result.results)
            all_query_results.extend(batch_result.query_results)

            # Generate follow-up queries for next level
            if depth_level < max_depth - 1:
                current_queries = self._generate_follow_ups(
                    batch_result.results,
                    follow_ups_per_level,
                    depth_level + 1,
                    category,
                )
            else:
                current_queries = []

        # Deduplicate final results
        seen = set()
        unique_results = []
        for r in all_results:
            if r.url not in seen:
                seen.add(r.url)
                unique_results.append(r)

        unique_results.sort(key=lambda r: r.score, reverse=True)
        total_duration = (time.time() - start_time) * 1000

        result = SearchOrchestrationResult(
            results=unique_results,
            query_results=all_query_results,
            total_queries=len(all_query_results),
            successful_queries=sum(1 for qr in all_query_results if not qr.error),
            failed_queries=sum(1 for qr in all_query_results if qr.error),
            total_duration_ms=round(total_duration, 1),
            unique_urls=len(unique_results),
        )

        logger.info(
            "deep_search_complete",
            max_depth=max_depth,
            unique_urls=len(unique_results),
            duration_ms=round(total_duration, 1),
        )
        return result

    # ------------------------------------------------------------------
    # Internal Methods
    # ------------------------------------------------------------------
    async def _execute_single_query(
        self,
        query: SearchQuery,
        semaphore: asyncio.Semaphore,
        timeout: float,
    ) -> BatchSearchResult:
        """Execute a single search query with concurrency control."""
        start = time.time()
        async with semaphore:
            try:
                results = await asyncio.wait_for(
                    self._perform_search(query),
                    timeout=timeout,
                )
                duration = (time.time() - start) * 1000
                return BatchSearchResult(
                    query=query,
                    results=results,
                    duration_ms=round(duration, 1),
                )
            except asyncio.TimeoutError:
                duration = (time.time() - start) * 1000
                return BatchSearchResult(
                    query=query,
                    error=f"Timeout after {timeout}s",
                    duration_ms=round(duration, 1),
                )
            except Exception as e:
                duration = (time.time() - start) * 1000
                return BatchSearchResult(
                    query=query,
                    error=str(e),
                    duration_ms=round(duration, 1),
                )

    async def _perform_search(self, query: SearchQuery) -> list[SearchResult]:
        """Perform the actual search using the appropriate provider."""
        from backend.tools.search_tools import _cache
        from backend.core.retry import retry_with_backoff
        from backend.config import settings

        # Check cache
        cache_key = f"orchestrator:{query.category}:{query.text}"
        cached = await _cache.get_search(cache_key)
        if cached:
            return [
                SearchResult(
                    url=r.get("url", ""),
                    title=r.get("title", ""),
                    content=r.get("content", r.get("formatted_content", "")),
                    score=r.get("relevance_score", r.get("score", 0.5)),
                    source=r.get("source", "cache"),
                    query_text=query.text,
                )
                for r in cached
            ]

        # Execute search via Tavily
        try:
            from langchain_community.tools.tavily_search import TavilySearchResults

            max_results = {
                SearchDepth.SURFACE: 3,
                SearchDepth.STANDARD: 5,
                SearchDepth.DEEP: 8,
                SearchDepth.EXHAUSTIVE: 12,
            }.get(query.depth, 5)

            search = TavilySearchResults(
                max_results=max_results,
                tavily_api_key=settings.TAVILY_API_KEY,
            )

            import asyncio as _asyncio

            @retry_with_backoff(max_retries=2, exceptions=(Exception,))
            def _invoke():
                return search.invoke(query.text)

            raw = await _asyncio.to_thread(_invoke)

            results = []
            if isinstance(raw, list):
                for r in raw:
                    results.append(SearchResult(
                        url=r.get("url", ""),
                        title=r.get("title", r.get("url", "")),
                        content=r.get("content", r.get("formatted_content", "")),
                        score=float(r.get("score", r.get("relevance_score", 0.5))),
                        source="tavily",
                        query_text=query.text,
                    ))
            elif isinstance(raw, str):
                results.append(SearchResult(
                    url="",
                    title="",
                    content=raw,
                    score=0.5,
                    source="tavily",
                    query_text=query.text,
                ))

            # Cache results
            if results:
                cache_payload = [
                    {"url": r.url, "title": r.title, "content": r.content,
                     "relevance_score": r.score, "source": r.source}
                    for r in results
                ]
                await _cache.set_search(cache_key, cache_payload)

            return results

        except Exception as e:
            logger.error("orchestrator_search_error", query=query.text[:80], error=str(e))
            return []

    def _deduplicate_queries(self, queries: list[SearchQuery]) -> list[SearchQuery]:
        """Remove duplicate queries by normalized text hash."""
        seen: set[str] = set()
        unique: list[SearchQuery] = []
        for q in queries:
            h = q.query_hash
            if h not in seen:
                seen.add(h)
                unique.append(q)
        return unique

    def _generate_follow_ups(
        self,
        results: list[SearchResult],
        max_follow_ups: int,
        depth_level: int,
        category: str,
    ) -> list[SearchQuery]:
        """Generate follow-up queries based on search results.

        Extracts key entities and topics from results to form new queries.
        """
        if not results:
            return []

        follow_ups: list[SearchQuery] = []

        # Extract top URLs/titles for follow-up context
        top_results = sorted(results, key=lambda r: r.score, reverse=True)[:5]

        for i, result in enumerate(top_results):
            if i >= max_follow_ups:
                break

            # Generate follow-up from result title/content
            if result.title and result.title != result.url:
                follow_up_text = f"{result.title} details analysis"
            elif result.content:
                # Extract first meaningful sentence
                sentences = result.content.split(".")
                follow_up_text = sentences[0].strip()[:200] if sentences else result.query_text
            else:
                continue

            if follow_up_text and follow_up_text not in self._seen_hashes:
                self._seen_hashes.add(follow_up_text)
                follow_ups.append(SearchQuery(
                    text=follow_up_text,
                    depth=SearchDepth.DEEP,
                    category=category,
                    priority=SearchPriority.NORMAL,
                    source_query=result.query_text,
                    metadata={"depth_level": depth_level},
                ))

        return follow_ups


# Module-level singleton
search_orchestrator = SearchOrchestrator()
