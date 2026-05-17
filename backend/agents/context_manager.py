"""
Context Manager — auto-summarization middleware.
When the conversation context grows too large, summarizes older content
and stores full context in ChromaDB for retrieval.
"""

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from langchain_mistralai.chat_models import ChatMistralAI
from backend.config import settings
from backend.db.chromadb_store import ChromaStore
from backend.core.logger import get_logger

logger = get_logger(__name__)

TOKEN_THRESHOLD = 30_000  # trigger summarization when context exceeds this estimate
CHARS_PER_TOKEN = 4  # rough estimate


class ContextManager:
    """Manages agent context to prevent token overflow."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.chroma = ChromaStore()
        self.llm = ChatMistralAI(
            mistral_api_key=settings.MISTRAL_API_KEY,
            model=settings.LLM_MODEL,
            temperature=0.0,
            max_tokens=2000,
        )

    def _estimate_tokens(self, messages: list[BaseMessage]) -> int:
        total_chars = sum(len(m.content) for m in messages if hasattr(m, 'content'))
        return total_chars // CHARS_PER_TOKEN

    def should_summarize(self, messages: list[BaseMessage]) -> bool:
        return self._estimate_tokens(messages) > TOKEN_THRESHOLD

    async def summarize_and_compact(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Summarize older messages while keeping the system prompt and recent messages.

        Returns a compacted message list that fits within token limits.
        """
        if not self.should_summarize(messages):
            return messages

        logger.info("context_summarizing", session_id=self.session_id,
                     original_count=len(messages),
                     est_tokens=self._estimate_tokens(messages))

        # Keep system message (first) and last N messages
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]

        keep_recent = min(6, len(non_system))
        older = non_system[:-keep_recent] if keep_recent < len(non_system) else []
        recent = non_system[-keep_recent:] if keep_recent > 0 else non_system

        if not older:
            return messages

        # Store older messages in ChromaDB for future retrieval
        older_texts = [m.content for m in older if hasattr(m, 'content') and m.content]
        if older_texts:
            self.chroma.add_documents(self.session_id, older_texts)

        # Generate summary of older messages
        summary_prompt = (
            "Summarize the following research conversation concisely. "
            "Preserve key findings, important URLs, data points, and decisions made:\n\n"
            + "\n---\n".join(older_texts[:20])  # cap to avoid overflow
        )

        try:
            summary = await self.llm.ainvoke([HumanMessage(content=summary_prompt)])
            summary_msg = HumanMessage(
                content=f"[CONTEXT SUMMARY — Earlier research condensed]\n{summary.content}"
            )
            compacted = system_msgs + [summary_msg] + recent
            logger.info("context_compacted", session_id=self.session_id,
                         new_count=len(compacted),
                         est_tokens=self._estimate_tokens(compacted))
            return compacted
        except Exception as e:
            logger.error("context_summarize_error", error=str(e))
            # Fallback: just keep recent messages
            return system_msgs + recent

    def retrieve_relevant(self, query: str, n_results: int = 5) -> str:
        """Retrieve relevant past context from ChromaDB for a given query."""
        results = self.chroma.semantic_search(self.session_id, query, n_results)
        if not results:
            return ""
        context_parts = [r["content"] for r in results]
        return "\n---\n".join(context_parts)
