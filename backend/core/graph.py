"""
LangGraph Orchestrator — tool-augmented agent loop with ExecutionGuard middleware.
Replaces the old fixed-node graph with a dynamic ReAct loop.
Persists AgentTrace records to PostgreSQL for observability.
"""

import json
import time
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from backend.core.state import AgentState
from backend.core.execution_guard import ExecutionGuard, ExecutionLimitExceeded
from backend.core.tool_guard import ToolPermissionGuard, ToolNotAllowed
from backend.agents.deep_agent import create_research_agent
from backend.agents.context_manager import ContextManager
from backend.tools.memory_tools import get_user_memory_context
from backend.core.failure_memory import record_failure, get_failure_context, clear_failures
from backend.core.guardrails import scan_for_prompt_injection, redact_pii, check_scope_drift
from backend.core.logger import get_logger
import re

logger = get_logger(__name__)

# Per-session guards stored here (keyed by session_id)
_session_guards: dict[str, ExecutionGuard] = {}
_session_tool_guards: dict[str, ToolPermissionGuard] = {}
_session_context_managers: dict[str, ContextManager] = {}


def _get_guard(session_id: str) -> ExecutionGuard:
    if session_id not in _session_guards:
        _session_guards[session_id] = ExecutionGuard()
    return _session_guards[session_id]


def _get_tool_guard(session_id: str) -> ToolPermissionGuard:
    if session_id not in _session_tool_guards:
        _session_tool_guards[session_id] = ToolPermissionGuard()
    return _session_tool_guards[session_id]


def _get_context_manager(session_id: str) -> ContextManager:
    if session_id not in _session_context_managers:
        _session_context_managers[session_id] = ContextManager(session_id)
    return _session_context_managers[session_id]


def get_execution_metrics(session_id: str) -> dict:
    """Get current execution metrics for a session."""
    guard = _session_guards.get(session_id)
    return guard.metrics() if guard else {}


async def _persist_trace(session_id: str, event_type: str, tool_name: str = "",
                         input_data: dict | None = None, output_data: dict | None = None,
                         latency_ms: float = 0.0, tokens_used: int = 0,
                         is_error: bool = False, error_detail: str = ""):
    """Persist an AgentTrace record to PostgreSQL."""
    try:
        from backend.db.postgres import async_session as db_session_factory, AgentTrace
        async with db_session_factory() as db:
            trace = AgentTrace(
                session_id=session_id,
                event_type=event_type,
                tool_name=tool_name,
                input_data=input_data or {},
                output_data=output_data or {},
                latency_ms=latency_ms,
                tokens_used=tokens_used,
                is_error=is_error,
                error_detail=error_detail,
            )
            db.add(trace)
            await db.commit()
    except Exception as e:
        logger.error("trace_persist_failed", session_id=session_id, error=str(e))


async def build_graph(session_id: str):
    """Build and compile the LangGraph for a specific research session.

    Returns a compiled graph that can be streamed.
    """
    user_memory = await get_user_memory_context()
    llm_with_tools, tools, system_prompt = create_research_agent(session_id, user_memory)
    tool_node = ToolNode(tools)

    # Agent node — calls LLM with tool-augmented messages
    async def agent_node(state: AgentState) -> dict:
        guard = _get_guard(state["session_id"])
        ctx_mgr = _get_context_manager(state["session_id"])

        # Check execution limits
        try:
            guard.check()
        except ExecutionLimitExceeded as e:
            logger.warning("agent_limit_reached", session_id=state["session_id"], error=str(e))
            await _persist_trace(state["session_id"], "limit_exceeded", is_error=True, error_detail=str(e))
            return {
                "messages": [AIMessage(content=f"⚠️ Research stopped: {e}. Presenting findings collected so far.")],
                "status": "completed",
                "iteration": state.get("iteration", 0),
            }

        guard.record_iteration()

        # Compact context if needed
        messages = list(state["messages"])
        messages = await ctx_mgr.summarize_and_compact(messages)

        # Add system prompt if not present, with failure memory injected
        failure_ctx = get_failure_context(state["session_id"])
        enriched_prompt = system_prompt + failure_ctx if failure_ctx else system_prompt
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=enriched_prompt)] + messages
        else:
            # Update existing system message with failure context
            if failure_ctx:
                messages[0] = SystemMessage(content=enriched_prompt)

        # Call LLM
        iter_start = time.time()
        try:
            response = await llm_with_tools.ainvoke(messages)
        except Exception as e:
            logger.error("llm_invoke_error", session_id=state["session_id"], error=str(e))
            await _persist_trace(state["session_id"], "llm_error", is_error=True, error_detail=str(e))
            return {
                "messages": [AIMessage(content=f"⚠️ LLM error: {e}. Attempting to continue...")],
                "status": "running",
                "iteration": state.get("iteration", 0) + 1,
            }

        iter_latency = (time.time() - iter_start) * 1000

        # Track tokens
        usage = getattr(response, 'usage_metadata', None)
        tokens = 0
        if usage:
            tokens = usage.get('total_tokens', 0)
            guard.record_tokens(tokens)

        # Track tool calls
        if response.tool_calls:
            for tc in response.tool_calls:
                guard.record_tool_call()

        iteration = state.get("iteration", 0) + 1
        
        # Guardrail: Check for Scope Drift
        if iteration > 1 and iteration % getattr(settings, 'GUARD_SCOPE_DRIFT_THRESHOLD', 5) == 0:
            # Extract basic actions from recent AI tool calls
            recent_actions = []
            for msg in messages[-10:]:
                if isinstance(msg, AIMessage) and msg.tool_calls:
                    for tc in msg.tool_calls:
                        recent_actions.append(f"{tc['name']} {str(tc.get('args', {}))}")
            
            # Simple heuristic matching against original system prompt request
            # Original request is usually embedded early or in the messages.
            # Using the first Human message as the "query"
            query_msg = next((m.content for m in state["messages"] if isinstance(m, HumanMessage)), "")
            if check_scope_drift(query_msg, recent_actions):
                # Inject a system drift warning
                response = AIMessage(
                    content="I have drifted off-topic. I will stop current actions and refocus on the original goal.",
                    tool_calls=[{"name": "write_todos", "args": {"todos_json": '[{"text": "Re-evaluate the original user query and adjust search plan", "status": "pending"}]'}, "id": "call_drift_" + str(iteration)}]
                )
        logger.info("agent_iteration", session_id=state["session_id"],
                     iteration=iteration,
                     has_tool_calls=bool(response.tool_calls),
                     metrics=guard.metrics())

        # Persist iteration trace
        await _persist_trace(
            state["session_id"], "agent_iteration",
            latency_ms=iter_latency, tokens_used=tokens,
            output_data={"iteration": iteration, "has_tool_calls": bool(response.tool_calls)},
        )

        return {
            "messages": [response],
            "status": "running",
            "iteration": iteration,
        }

    # Tool execution node with permission guard
    async def guarded_tool_node(state: AgentState) -> dict:
        guard = _get_tool_guard(state["session_id"])
        last_msg = state["messages"][-1]

        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            for tc in last_msg.tool_calls:
                try:
                    guard.check(tc["name"])
                except ToolNotAllowed as e:
                    logger.warning("tool_blocked_in_graph", tool=tc["name"],
                                    session_id=state["session_id"])
                    await _persist_trace(
                        state["session_id"], "tool_blocked",
                        tool_name=tc["name"], is_error=True, error_detail=str(e),
                    )
                    return {
                        "messages": [ToolMessage(
                            content=f"Error: {e}",
                            tool_call_id=tc["id"],
                        )],
                    }

        tool_start = time.time()
        try:
            result = await tool_node.ainvoke(state)
        except Exception as tool_err:
            # Record failure in failure memory
            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                for tc in last_msg.tool_calls:
                    record_failure(
                        state["session_id"],
                        tc["name"],
                        str(tc.get("args", {}))[:200],
                        str(tool_err)[:300],
                    )
            raise
        tool_latency = (time.time() - tool_start) * 1000

        # Check for error results and apply Content Safety Guardrails (PII & Prompt Injection)
        new_urls = set()
        if isinstance(result, dict) and "messages" in result:
            for i, msg in enumerate(result["messages"]):
                if hasattr(msg, "content") and isinstance(msg.content, str):
                    original_content = msg.content
                    
                    # Track URLs for citation verification
                    urls = re.findall(r'https?://[^\s|)]+', original_content)
                    for u in urls:
                        new_urls.add(u)
                        
                    # Apply Guardrails
                    safe_content = redact_pii(original_content)
                    safe_content = scan_for_prompt_injection(safe_content)
                    
                    # Pydantic v2 safe message mutation
                    if isinstance(msg, ToolMessage):
                        msg = ToolMessage(content=safe_content, name=msg.name, tool_call_id=msg.tool_call_id)
                        result["messages"][i] = msg
                    else:
                        msg.content = safe_content
                    
                    if msg.content.startswith("Error:") or msg.content.startswith("Failed"):
                        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                            for tc in last_msg.tool_calls:
                                record_failure(
                                    state["session_id"],
                                    tc["name"],
                                    str(tc.get("args", {}))[:200],
                                    msg.content[:300],
                                )
                                
        if new_urls:
            result["accessed_urls"] = new_urls

        # Persist tool call trace
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            for tc in last_msg.tool_calls:
                await _persist_trace(
                    state["session_id"], "tool_call",
                    tool_name=tc["name"],
                    input_data=tc.get("args", {}),
                    latency_ms=tool_latency,
                )

        # Step-level Replanning: Evaluate the quality of the tool results
        if isinstance(result, dict) and "messages" in result:
            messages = result["messages"]
            poor_quality = False
            error_count = 0
            empty_search = False

            for msg in messages:
                if not hasattr(msg, "content") or not isinstance(msg.content, str):
                    continue
                
                # Check for errors
                if msg.content.startswith("Error:") or msg.content.startswith("Failed"):
                    error_count += 1
                
                # Check for empty search results
                if "Search failed" in msg.content or "No results found" in msg.content or len(msg.content.strip()) < 50:
                    empty_search = True
            
            # Heuristic for poor step quality
            if error_count > 0 and error_count == len(messages):
                poor_quality = True  # Everything failed
            elif empty_search and len(messages) == 1:
                poor_quality = True  # The only thing we did was search and it failed/empty

            current_failures = state.get("consecutive_failures", 0)

            if poor_quality:
                current_failures += 1
                result["consecutive_failures"] = current_failures
                
                if current_failures >= 2:
                    # STRATEGY SWITCH
                    replan_msg = SystemMessage(
                        content=(
                            "🔥 **CRITICAL STRATEGY FAILURE**: You have failed consecutive steps while trying this approach. "
                            "You are caught in a loop or hitting a dead end. "
                            "**YOU MUST INITIATE A STRATEGY SWITCH IMMEDIATELY.**\n"
                            "Do not use `web_search` for this exact query again. Instead, forcefully pivot your strategy:\n"
                            "- Option A (Deep/Scientific): Use `academic_search`.\n"
                            "- Option B (Parallelization): Use `spawn_subagent` or `spawn_parallel_subagents` to delegate the roadblock.\n"
                            "- Option C (Pivot): Use `write_todos` to delete the current task and attack the problem from a completely different domain."
                        )
                    )
                    logger.warning("strategy_switch_triggered", session_id=state["session_id"], failures=current_failures)
                else:
                    # LOCAL REPLAN
                    replan_msg = SystemMessage(
                        content="⚠️ **CRITICAL EVALUATION**: The previous step yielded poor results (errors or empty data). "
                                "Do NOT continue blindly or hallucinate. You MUST call the `write_todos` tool immediately "
                                "to update your research plan and try a completely different approach/query."
                    )
                    logger.warning("step_replanning_triggered", session_id=state["session_id"])
                
                result["messages"].append(replan_msg)
            else:
                # Reset consecutive failures on a successful tool execution
                result["consecutive_failures"] = 0

        return result

    # Routing function
    def should_continue(state: AgentState) -> str:
        last_msg = state["messages"][-1]

        # If it's an AI message with tool calls → execute tools
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "tools"

        # Otherwise → done
        return "end"

    # Build the graph
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", guarded_tool_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "end": END},
    )
    graph.add_edge("tools", "agent")

    compiled = graph.compile()
    logger.info("graph_compiled", session_id=session_id)
    return compiled


def cleanup_session(session_id: str):
    """Clean up per-session state."""
    _session_guards.pop(session_id, None)
    _session_tool_guards.pop(session_id, None)
    _session_context_managers.pop(session_id, None)
    clear_failures(session_id)
