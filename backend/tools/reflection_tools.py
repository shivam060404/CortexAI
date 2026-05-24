"""
Reflection Tools — self-evaluation before final output.
The agent uses this to critically review its own work before presenting results.
"""

from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_community.chat_models import ChatLiteLLM
from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


def get_reflection_tools(session_id: str):
    """Return reflection tools for agent self-evaluation."""

    @tool
    async def self_reflect(research_summary: str) -> str:
        """Critically evaluate your own research before presenting the final report.
        Identify gaps, weak evidence, unsupported claims, and missing perspectives.
        Use this BEFORE writing the final report to improve its quality.

        Args:
            research_summary: A summary of all findings gathered so far.

        Returns:
            A structured self-evaluation with confidence scores and improvement suggestions.
        """
        logger.info("self_reflect", session_id=session_id)
        llm = ChatLiteLLM(
            model=settings.FAST_MODEL,
            temperature=0.3,
        )
        messages = [
            SystemMessage(content=(
                "You are a rigorous meta-cognitive research evaluator. "
                "Your job is to critically examine the provided research findings and assess:\n"
                "1. **Completeness** (0-10): Are there major gaps or unexplored angles?\n"
                "2. **Evidence Quality** (0-10): Are claims well-supported by sources?\n"
                "3. **Bias Check** (0-10): Is the analysis balanced or one-sided?\n"
                "4. **Logical Consistency** (0-10): Are there contradictions or unsupported leaps?\n"
                "5. **Actionability** (0-10): Does it give the reader clear, useful takeaways?\n\n"
                "For each dimension, give a score and a one-line explanation.\n"
                "Then provide 3-5 specific improvement suggestions.\n"
                "Finally, give an overall confidence rating (Low / Medium / High) for the research.\n"
                "Be honest and constructive. This evaluation WILL be used to improve the final output."
            )),
            HumanMessage(content=f"Research findings to evaluate:\n\n{research_summary}")
        ]
        try:
            response = await llm.ainvoke(messages)
            return f"🔍 Self-Reflection Report:\n{response.content}"
        except Exception as e:
            logger.error("self_reflect_error", session_id=session_id, error=str(e))
            return f"Reflection failed: {str(e)}. Proceed with current findings."

    @tool
    async def cross_reference_sources(topic: str, sources_summaries: str) -> str:
        """Cross-examine multiple information sources to find consensus and contradictions.
        Use this tool when search results give conflicting numbers or differing perspectives.
        
        Args:
            topic: The specific claim or subject being cross-referenced (e.g. "Efficacy of drug X").
            sources_summaries: A combined string containing the excerpts from multiple sources.

        Returns:
            A synthesis indicating exact points of:
            - CONCENSUS (everyone agrees)
            - CONTRADICTION (sources conflict, pointing out who said what)
            - UNVERIFIED/NUANCE (isolated claims or gaps)
        """
        logger.info("cross_reference_sources", session_id=session_id)
        llm = ChatLiteLLM(
            model=settings.FAST_MODEL,
            temperature=0.1,
        )
        messages = [
            SystemMessage(content=(
                "You are an expert fact-checker and source reconciliator. "
                "Your task is to analyze the provided source excerpts regarding the given topic.\n"
                "Output MUST be in the following markdown format:\n\n"
                "### 🤝 Consensus\n(List facts all sources agree on)\n\n"
                "### ⚠️ Contradictions\n(List conflicting facts, explicitly noting which source claims what)\n\n"
                "### 🧩 Nuance & Unverified\n(List claims made by only one source, or data that lacks full context)\n\n"
                "Do not hallucinate external knowledge. Rely STRICTLY on the text provided."
            )),
            HumanMessage(content=f"Topic: {topic}\n\nSources Extracts:\n{sources_summaries}")
        ]
        try:
            response = await llm.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.error("cross_ref_error", session_id=session_id, error=str(e))
            return f"Source cross-referencing failed: {str(e)}"

    return [self_reflect, cross_reference_sources]
