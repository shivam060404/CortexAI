"""
Research Loop Tools — explicit tools for recursive hypothesis generation and evaluation.
"""

from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_litellm import ChatLiteLLM
from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

def get_research_loop_tools(session_id: str):
    """Return tools for recursive research loops."""

    @tool
    async def generate_hypothesis(current_findings: str) -> str:
        """Analyze current findings and generate a new testable hypothesis to drive the next phase of research."""
        logger.info("generate_hypothesis", session_id=session_id)
        llm = ChatLiteLLM(
            model=settings.FAST_MODEL,
            temperature=0.7,
        )
        messages = [
            SystemMessage(content="You are an expert lead scientist. Based on the provided findings or context, generate a single clear, testable hypothesis for further research. Keep it concise (1-2 sentences)."),
            HumanMessage(content=current_findings)
        ]
        try:
            response = await llm.ainvoke(messages)
            return f"New Hypothesis: {response.content}"
        except Exception as e:
            logger.error("generate_hypothesis_error", session_id=session_id, error=str(e))
            return f"Failed to generate hypothesis: {str(e)}"

    @tool
    async def evaluate_findings(hypothesis: str, findings: str) -> str:
        """Evaluate how well the current findings support the given hypothesis."""
        logger.info("evaluate_findings", session_id=session_id)
        llm = ChatLiteLLM(
            model=settings.FAST_MODEL,
            temperature=0.2,
        )
        messages = [
            SystemMessage(content="You are an expert scientific peer reviewer. Determine if the findings support, contradict, or are inconclusive regarding the hypothesis. Explain your reasoning briefly and suggest the next logical step."),
            HumanMessage(content=f"Hypothesis: {hypothesis}\nFindings: {findings}")
        ]
        try:
            response = await llm.ainvoke(messages)
            return f"Reflection Evaluation:\n{response.content}"
        except Exception as e:
            logger.error("evaluate_findings_error", session_id=session_id, error=str(e))
            return f"Failed to evaluate findings: {str(e)}"

    return [generate_hypothesis, evaluate_findings]
