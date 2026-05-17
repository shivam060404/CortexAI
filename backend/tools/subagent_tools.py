"""
Sub-agent spawning tools — delegates specialized tasks to isolated sub-agents.
Each sub-agent has its own ExecutionGuard budget (tokens, steps, timeout).
Supports both sequential and parallel sub-agent execution.
"""

import asyncio
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mistralai.chat_models import ChatMistralAI
from backend.config import settings
from backend.core.execution_guard import ExecutionGuard, ExecutionLimitExceeded
from backend.core.logger import get_logger

logger = get_logger(__name__)

ROLE_PROMPTS = {
    "research_analyst": (
        "You are a focused research analyst sub-agent. You have been delegated a specific research sub-task. "
        "Analyze the topic thoroughly and return a concise, well-structured summary of your findings. "
        "Be precise and cite key facts."
    ),
    "data_analyst": (
        "You are a data analysis sub-agent. You have been delegated a data processing task. "
        "Analyze the data, identify patterns, and return structured insights. "
        "Use numbers and statistics where relevant."
    ),
    "writer": (
        "You are a professional writing sub-agent. You have been delegated a writing task. "
        "Write clear, well-structured content based on the provided information. "
        "Ensure proper formatting with sections and bullet points."
    ),
    "research_synthesizer": (
        "You are a Smart Literature Review Engine. Your task is to perform auto paper clustering, extract key insights, and generate comparison tables based on the provided papers/data. "
        "Summarize the literature, identify differences between methods, results, and limitations, and present them clearly."
    ),
    "critic_agent": (
        "You are an AI Research Partner known as the Critic. Your job is to rigorously challenge assumptions, highlight missing information, and actively find flaws in the provided research. "
        "Ask 'What if this is wrong?' and 'What is missing?'. Provide constructive criticism to strengthen the overall research."
    ),
}


async def _run_single_subagent(session_id: str, task_description: str, agent_role: str) -> str:
    """Internal: run a single sub-agent with its own resource budget."""
    guard = ExecutionGuard(
        max_iterations=settings.SUBAGENT_MAX_STEPS,
        max_tokens=settings.SUBAGENT_MAX_TOKENS,
        timeout=settings.SUBAGENT_TIMEOUT,
    )

    system_prompt = ROLE_PROMPTS.get(agent_role, ROLE_PROMPTS["research_analyst"])

    try:
        guard.check()
        llm = ChatMistralAI(
            mistral_api_key=settings.MISTRAL_API_KEY,
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.SUBAGENT_MAX_TOKENS,
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Task: {task_description}"),
        ]

        response = await llm.ainvoke(messages)
        guard.record_iteration()

        tokens = getattr(response, 'usage_metadata', {})
        if tokens:
            guard.record_tokens(tokens.get('total_tokens', 0))

        logger.info("subagent_complete", session_id=session_id,
                     role=agent_role, metrics=guard.metrics())

        return f"[Sub-agent: {agent_role}]\n{response.content}"

    except ExecutionLimitExceeded as e:
        logger.warning("subagent_limit_exceeded", session_id=session_id,
                        role=agent_role, error=str(e))
        return f"[Sub-agent: {agent_role}] Terminated: {e}. Partial results may be incomplete."
    except Exception as e:
        logger.error("subagent_error", session_id=session_id,
                      role=agent_role, error=str(e))
        return f"[Sub-agent: {agent_role}] Failed: {str(e)}"


def get_subagent_tools(session_id: str):
    """Return sub-agent spawning tools (single + parallel) bound to a session."""

    @tool
    async def spawn_subagent(task_description: str, agent_role: str = "research_analyst") -> str:
        """Spawn a specialized sub-agent to handle a focused sub-task.
        The sub-agent runs in an isolated context with its own resource budget.

        Args:
            task_description: Detailed description of the sub-task to perform.
            agent_role: One of 'research_analyst', 'data_analyst', 'writer', 'research_synthesizer', 'critic_agent'.

        Returns:
            The sub-agent's result summary.
        """
        logger.info("subagent_spawn", session_id=session_id,
                     role=agent_role, task=task_description[:100])
        return await _run_single_subagent(session_id, task_description, agent_role)

    @tool
    async def spawn_parallel_subagents(tasks_json: str) -> str:
        """Spawn multiple sub-agents in PARALLEL for maximum efficiency.
        Use this when you have multiple independent research sub-tasks that can run simultaneously.

        Args:
            tasks_json: A JSON array of objects, each with 'task' (description) and 'role' (agent role).
                Example: [{"task": "Analyze paper X", "role": "research_analyst"}, {"task": "Critique methodology", "role": "critic_agent"}]

        Returns:
            Combined results from all sub-agents.
        """
        import json
        try:
            tasks = json.loads(tasks_json)
            if not isinstance(tasks, list) or len(tasks) == 0:
                return "Error: Input must be a non-empty JSON array of task objects."
        except json.JSONDecodeError:
            return "Error: Invalid JSON input."

        logger.info("parallel_subagents_spawn", session_id=session_id, count=len(tasks))

        # Launch all sub-agents concurrently
        coroutines = [
            _run_single_subagent(
                session_id,
                t.get("task", t.get("description", str(t))),
                t.get("role", "research_analyst"),
            )
            for t in tasks
        ]

        results = await asyncio.gather(*coroutines, return_exceptions=True)

        # Format combined output
        output_parts = []
        for i, result in enumerate(results):
            task_desc = tasks[i].get("task", tasks[i].get("description", ""))[:80]
            if isinstance(result, Exception):
                output_parts.append(f"### Task {i+1}: {task_desc}\n❌ Error: {result}\n")
            else:
                output_parts.append(f"### Task {i+1}: {task_desc}\n{result}\n")

        logger.info("parallel_subagents_complete", session_id=session_id, count=len(tasks))
        return "\n---\n".join(output_parts)

    return [spawn_subagent, spawn_parallel_subagents]


# Backward compatibility alias
def get_subagent_tool(session_id: str):
    """Legacy: returns just the single spawn_subagent tool."""
    tools = get_subagent_tools(session_id)
    return tools[0]
