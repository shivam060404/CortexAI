"""
Enhanced RAG Pipeline (Feature Gap #6).

Provides:
- Document ingestion with chunking and overlap
- Hybrid search (keyword BM25 + semantic vector similarity)
- Result reranking with relevance scoring
- Integration with LanceDB vector store
"""

import re
import math
import uuid
from typing import List, Dict, Optional
from collections import Counter

from backend.core.logger import get_logger
from backend.db.lancedb_store import LanceDBStore

logger = get_logger(__name__)

# Default chunking parameters
DEFAULT_CHUNK_SIZE = 512  # tokens
DEFAULT_CHUNK_OVERLAP = 64  # tokens
DEFAULT_TOP_K = 10
RERANK_TOP_K = 5


class RAGPipeline:
    """End-to-end Retrieval-Augmented Generation pipeline.

    Ingestion: text → chunk → embed → store in LanceDB
    Retrieval: query → hybrid search → rerank → inject into context
    """

    def __init__(self):
        self._store = LanceDBStore()

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def chunk_text(self, text: str, chunk_size: int = DEFAULT_CHUNK_SIZE,
                   overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
        """Split text into overlapping chunks by approximate token count.

        Uses whitespace-based tokenization as a lightweight approximation.
        Preserves sentence boundaries when possible.
        """
        if not text or not text.strip():
            return []

        words = text.split()
        if len(words) <= chunk_size:
            return [text.strip()]

        chunks: list[str] = []
        start = 0
        while start < len(words):
            end = start + chunk_size
            chunk_words = words[start:end]
            chunk_text = " ".join(chunk_words).strip()
            if chunk_text:
                chunks.append(chunk_text)
            start += chunk_size - overlap

        return chunks

    async def ingest_document(self, session_id: str, text: str,
                              metadata: Optional[Dict] = None,
                              source: str = "upload") -> int:
        """Ingest a document: chunk, embed, and store.

        Returns the number of chunks stored.
        """
        if not text or not text.strip():
            return 0

        chunks = self.chunk_text(text)
        if not chunks:
            return 0

        base_metadata = metadata or {}
        base_metadata["source"] = source
        base_metadata["chunk_count"] = len(chunks)

        metadatas = []
        ids = []
        for i, chunk in enumerate(chunks):
            meta = {**base_metadata, "chunk_index": i}
            metadatas.append(meta)
            ids.append(str(uuid.uuid4()))

        self._store.add_documents(session_id, chunks, metadatas=metadatas, ids=ids)
        logger.info("rag_document_ingested", session_id=session_id,
                     chunks=len(chunks), source=source)
        return len(chunks)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    async def hybrid_search(self, session_id: str, query: str,
                            top_k: int = DEFAULT_TOP_K) -> list[dict]:
        """Hybrid search combining BM25 keyword matching + semantic vector similarity.

        1. Run semantic search via LanceDB (vector similarity)
        2. Run keyword search (BM25 approximation) on retrieved docs
        3. Merge and rerank using Reciprocal Rank Fusion (RRF)
        """
        # Semantic search
        semantic_results = self._store.semantic_search(session_id, query, n_results=top_k)

        if not semantic_results:
            return []

        # BM25 keyword scoring on semantic results
        keyword_scores = self._bm25_score(query, semantic_results)

        # Reciprocal Rank Fusion
        fused = self._reciprocal_rank_fusion(semantic_results, keyword_scores, top_k)

        # Rerank by composite score
        reranked = self._rerank(query, fused)

        return reranked[:RERANK_TOP_K]

    def _bm25_score(self, query: str, documents: list[dict],
                    k1: float = 1.5, b: float = 0.75) -> list[float]:
        """Compute BM25 relevance scores for a query against a set of documents."""
        query_terms = set(query.lower().split())
        if not query_terms:
            return [0.0] * len(documents)

        # Document lengths
        doc_lengths = []
        for doc in documents:
            content = doc.get("content", "")
            doc_lengths.append(len(content.split()))

        avg_dl = sum(doc_lengths) / max(len(doc_lengths), 1)

        # Document frequency
        N = len(documents)
        df: dict[str, int] = {}
        for doc in documents:
            content_words = set(doc.get("content", "").lower().split())
            for term in query_terms:
                if term in content_words:
                    df[term] = df.get(term, 0) + 1

        scores = []
        for i, doc in enumerate(documents):
            content_words = doc.get("content", "").lower().split()
            word_counts = Counter(content_words)
            dl = doc_lengths[i]
            score = 0.0
            for term in query_terms:
                tf = word_counts.get(term, 0)
                if tf == 0:
                    continue
                idf = math.log(max(1, (N - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5)) + 1)
                tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
                score += idf * tf_norm
            scores.append(score)

        return scores

    def _reciprocal_rank_fusion(self, semantic_results: list[dict],
                                 keyword_scores: list[float],
                                 k: int = 60) -> list[dict]:
        """Merge semantic and keyword rankings using RRF."""
        # Create ranked lists
        semantic_ranked = list(enumerate(semantic_results))  # (index, doc)
        keyword_ranked = sorted(
            enumerate(keyword_scores), key=lambda x: x[1], reverse=True
        )

        # RRF scores
        rrf_scores: dict[int, float] = {}
        for rank, (idx, _) in enumerate(semantic_ranked):
            rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
        for rank, (idx, _) in enumerate(keyword_ranked):
            rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (k + rank + 1)

        # Sort by RRF score
        sorted_indices = sorted(rrf_scores.keys(), key=lambda i: rrf_scores[i], reverse=True)
        fused = []
        for idx in sorted_indices:
            doc = semantic_results[idx]
            doc["rrf_score"] = rrf_scores[idx]
            fused.append(doc)

        return fused

    def _rerank(self, query: str, documents: list[dict]) -> list[dict]:
        """Simple relevance reranking based on query term coverage and position."""
        query_terms = set(query.lower().split())
        scored = []

        for doc in documents:
            content = doc.get("content", "").lower()
            words = set(content.split())

            # Term coverage: what fraction of query terms appear
            coverage = len(query_terms & words) / max(len(query_terms), 1)

            # Title boost: if metadata has a title matching query
            title = doc.get("metadata", {}).get("title", "").lower()
            title_boost = 0.2 if any(t in title for t in query_terms) else 0.0

            # Position boost: terms appearing earlier in text score higher
            first_positions = []
            for term in query_terms:
                pos = content.find(term)
                if pos >= 0:
                    first_positions.append(pos)
            position_score = 0.0
            if first_positions:
                avg_pos = sum(first_positions) / len(first_positions)
                max_len = max(len(content), 1)
                position_score = 0.1 * (1.0 - avg_pos / max_len)

            rrf = doc.get("rrf_score", 0.0)
            composite = (0.4 * rrf) + (0.3 * coverage) + (0.2 * position_score) + title_boost

            scored.append({**doc, "relevance_score": round(composite, 4)})

        scored.sort(key=lambda d: d["relevance_score"], reverse=True)
        return scored

    # ------------------------------------------------------------------
    # Context injection
    # ------------------------------------------------------------------

    async def get_context_for_query(self, session_id: str, query: str,
                                     max_tokens: int = 2000) -> str:
        """Retrieve and format context chunks for injection into LLM prompt."""
        results = await self.hybrid_search(session_id, query)
        if not results:
            return ""

        context_parts = []
        total_tokens = 0
        for r in results:
            content = r.get("content", "")
            tokens = len(content.split())
            if total_tokens + tokens > max_tokens:
                break
            context_parts.append(content)
            total_tokens += tokens

        return "\n\n---\n\n".join(context_parts)


# Module-level singleton
rag_pipeline = RAGPipeline()
