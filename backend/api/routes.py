"""
FastAPI routes — REST + WebSocket endpoints.
REST: session CRUD, files, todos.
WebSocket: streams agent events in real-time.
Sessions are persisted to PostgreSQL and cached in-memory.
"""

import json
import uuid
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends
from langchain_core.messages import HumanMessage, AIMessage

from backend.auth.dependencies import get_current_active_user, get_optional_user
from backend.auth.models import User
from backend.core.session_store import session_store

from backend.api.schemas import (
    CreateSessionRequest, SessionResponse, SessionListResponse,
    TodoItemResponse, WorkspaceFileResponse, ExecutionMetrics, AgentEvent,
    WatchSessionRequest, ContextInjectRequest
)
from backend.core.graph import build_graph, get_execution_metrics, cleanup_session
from backend.tools.planning_tools import get_session_todos
from backend.tools.memory_tools import update_user_memory
from backend.db.workspace import WorkspaceManager
from backend.db.postgres import async_session, ExperimentTrack, ResearchSession, AgentTrace, KnowledgeNode, KnowledgeEdge, FeedbackLog, UserPreference
from sqlalchemy import select, update as sa_update, func, or_
from backend.core.alignment_engine import align_query, needs_clarification, RESEARCH_MODES
from backend.core.preference_learning import learn_from_feedback, get_user_preferences
from backend.core.guardrails import verify_citations, scan_user_input, scan_llm_output
from backend.core.scheduler import schedule_watch
from backend.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

_workspace = WorkspaceManager()


# ──────────────────────── DB Helpers ────────────────────────

async def _persist_session_to_db(session: dict):
    """Write a session dict to the ResearchSession table."""
    try:
        async with async_session() as db:
            db_session = ResearchSession(
                id=session["id"],
                title=session["title"],
                user_request=session["user_request"],
                status=session["status"],
                final_report=session.get("final_report", ""),
                iterations_used=session.get("iterations_used", 0),
                tokens_used=session.get("tokens_used", 0),
                tool_calls_count=session.get("tool_calls_count", 0),
            )
            db.add(db_session)
            await db.commit()
            logger.info("session_persisted_to_db", session_id=session["id"])
    except Exception as e:
        logger.error("session_persist_failed", session_id=session["id"], error=str(e))


async def _update_session_in_db(session_id: str, updates: dict):
    """Update specific fields of a session in PostgreSQL."""
    try:
        async with async_session() as db:
            # Map string status to enum if needed
            if "status" in updates:
                from backend.db.postgres import SessionStatus
                try:
                    updates["status"] = SessionStatus(updates["status"])
                except ValueError:
                    pass
            await db.execute(
                sa_update(ResearchSession)
                .where(ResearchSession.id == session_id)
                .values(**updates, updated_at=datetime.now(timezone.utc))
            )
            await db.commit()
    except Exception as e:
        logger.error("session_update_db_failed", session_id=session_id, error=str(e))


# ──────────────────────── REST Endpoints ────────────────────────

@router.post("/api/context/pages")
async def inject_page_context(req: ContextInjectRequest, current_user: User = Depends(get_current_active_user)):
    """Receive webpage context injected from the Chrome Extension."""
    try:
        session_id = req.session_id
        
        # If default, use the most recent active session, or create a global 'default' workspace
        if session_id == "default":
            user_sessions = await session_store.list_by_user(str(current_user.id))
            active_sessions = sorted([s for s in user_sessions if s["status"] in ("pending", "running")], 
                                     key=lambda x: x["created_at"], reverse=True)
            if active_sessions:
                session_id = active_sessions[0]["id"]
            else:
                session_id = "default"

        # Save context to the session's workspace
        filename = f"context_{int(datetime.now().timestamp())}.json"
        
        content_dict = {
            "url": req.url,
            "title": req.title,
            "tags": req.tags,
            "note": req.note,
            "extracted_text": req.content,
            "injected_at": datetime.now(timezone.utc).isoformat()
        }
        
        _workspace.write_file(session_id, filename, json.dumps(content_dict, indent=2))
        
        # Also update long-term user memory with this snippet
        memory_prompt = f"User explicitly saved this webpage for reference: {req.url}\nTags: {req.tags}\nNote: {req.note}\nTitle: {req.title}"
        await update_user_memory(memory_prompt)
        
        logger.info("context_injected", session_id=session_id, url=req.url, file=filename)
        return {"status": "success", "session_id": session_id, "file": filename}
        
    except Exception as e:
        logger.error("context_injection_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/sessions", response_model=SessionResponse)
async def create_session(req: CreateSessionRequest, current_user: User = Depends(get_current_active_user)):
    """Create a new research session."""
    session_id = str(uuid.uuid4())
    session = {
        "id": session_id,
        "title": req.query[:100],
        "user_request": req.query,
        "status": "pending",
        "final_report": "",
        "iterations_used": 0,
        "tokens_used": 0,
        "tool_calls_count": 0,
        "user_id": str(current_user.id),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await session_store.set(session_id, session, user_id=str(current_user.id))
    logger.info("session_created", session_id=session_id, query=req.query[:80])

    # Persist to DB (awaited to guarantee durability)
    await _persist_session_to_db(session)

    return SessionResponse(**session)


@router.get("/api/sessions", response_model=SessionListResponse)
async def list_sessions(current_user: User = Depends(get_current_active_user)):
    """List all research sessions for the current user."""
    sessions = await session_store.list_by_user(str(current_user.id))
    return SessionListResponse(
        sessions=[SessionResponse(**s) for s in sessions],
        total=len(sessions),
    )


@router.get("/api/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, current_user: User = Depends(get_current_active_user)):
    """Get a specific session."""
    session = await session_store.get(session_id)
    if not session or session.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse(**session)


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, current_user: User = Depends(get_current_active_user)):
    """Delete a research session."""
    session = await session_store.get(session_id)
    if not session or session.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=404, detail="Session not found")
    await session_store.delete(session_id, user_id=str(current_user.id))
    cleanup_session(session_id)

    # Delete from DB
    try:
        from sqlalchemy import delete as sa_delete
        async with async_session() as db:
            await db.execute(sa_delete(ResearchSession).where(ResearchSession.id == session_id))
            await db.commit()
    except Exception as e:
        logger.error("session_delete_db_failed", session_id=session_id, error=str(e))

    return {"status": "deleted"}


@router.post("/api/sessions/{session_id}/watch")
async def start_background_watch(session_id: str, req: WatchSessionRequest, current_user: User = Depends(get_current_active_user)):
    """Schedule a recurring background watch script for this session."""
    session = await session_store.get(session_id)
    if not session or session.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=404, detail="Session not found")
        
    job_id = schedule_watch(session_id, req.topic, req.frequency_hours)
    
    return {
        "status": "scheduled",
        "job_id": job_id,
        "topic": req.topic,
        "frequency_hours": req.frequency_hours
    }


@router.get("/api/sessions/{session_id}/todos")
async def get_todos(session_id: str, current_user: User = Depends(get_current_active_user)):
    """Get the todo list for a session."""
    todos = get_session_todos(session_id)
    return {"todos": todos}


@router.get("/api/sessions/{session_id}/files")
async def get_files(session_id: str, path: str = ".", current_user: User = Depends(get_current_active_user)):
    """List workspace files for a session."""
    try:
        entries = _workspace.list_dir(session_id, path)
        return {"files": [WorkspaceFileResponse(**e) for e in entries]}
    except Exception as e:
        return {"files": [], "error": str(e)}


@router.get("/api/sessions/{session_id}/files/content")
async def get_file_content(session_id: str, path: str, current_user: User = Depends(get_current_active_user)):
    """Read a workspace file's content."""
    try:
        content = _workspace.read_file(session_id, path)
        return {"content": content, "path": path}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/api/sessions/{session_id}/metrics")
async def get_metrics(session_id: str, current_user: User = Depends(get_current_active_user)):
    """Get current execution metrics for a session."""
    metrics = get_execution_metrics(session_id)
    return ExecutionMetrics(**metrics) if metrics else ExecutionMetrics()


@router.get("/api/sessions/{session_id}/experiments")
async def get_experiments(session_id: str, current_user: User = Depends(get_current_active_user)):
    """Get experiment logs for a session."""
    try:
        async with async_session() as db:
            res = await db.execute(
                select(ExperimentTrack)
                .where(ExperimentTrack.session_id == session_id)
                .order_by(ExperimentTrack.created_at.asc())
            )
            tracks = res.scalars().all()
            return {"experiments": [
                {
                    "id": str(t.id),
                    "hypothesis": t.hypothesis,
                    "approach": t.approach,
                    "result": t.result,
                    "conclusion": t.conclusion,
                    "created_at": t.created_at.isoformat() if t.created_at else None
                } for t in tracks
            ]}
    except Exception as e:
        logger.error("get_experiments_error", error=str(e))
        return {"experiments": [], "error": str(e)}


# ──────────────────────── Observability (Traces) ────────────────────────

@router.get("/api/sessions/{session_id}/traces")
async def get_session_traces(session_id: str, limit: int = 100, current_user: User = Depends(get_current_active_user)):
    """Get agent traces for a session — tool calls, iterations, errors."""
    try:
        async with async_session() as db:
            res = await db.execute(
                select(AgentTrace)
                .where(AgentTrace.session_id == session_id)
                .order_by(AgentTrace.timestamp.asc())
                .limit(limit)
            )
            traces = res.scalars().all()
            return {"traces": [
                {
                    "id": str(t.id),
                    "event_type": t.event_type,
                    "tool_name": t.tool_name,
                    "input_data": t.input_data,
                    "output_data": t.output_data,
                    "latency_ms": round(t.latency_ms, 1) if t.latency_ms else 0,
                    "tokens_used": t.tokens_used or 0,
                    "is_error": t.is_error,
                    "error_detail": t.error_detail or "",
                    "timestamp": t.timestamp.isoformat() if t.timestamp else None,
                } for t in traces
            ]}
    except Exception as e:
        logger.error("get_traces_error", error=str(e))
        return {"traces": [], "error": str(e)}


# ──────────────────────── Knowledge Graph ────────────────────────

@router.get("/api/knowledge/nodes")
async def get_knowledge_nodes(limit: int = 50, current_user: User = Depends(get_current_active_user)):
    """Get all knowledge graph nodes with edge counts (single JOIN query)."""
    try:
        async with async_session() as db:
            # Count edges via subqueries to avoid N+1
            out_edges_sq = (
                select(KnowledgeEdge.source_id, func.count().label("cnt"))
                .group_by(KnowledgeEdge.source_id)
                .subquery()
            )
            in_edges_sq = (
                select(KnowledgeEdge.target_id, func.count().label("cnt"))
                .group_by(KnowledgeEdge.target_id)
                .subquery()
            )

            stmt = (
                select(
                    KnowledgeNode,
                    func.coalesce(out_edges_sq.c.cnt, 0).label("out_count"),
                    func.coalesce(in_edges_sq.c.cnt, 0).label("in_count"),
                )
                .outerjoin(out_edges_sq, KnowledgeNode.id == out_edges_sq.c.source_id)
                .outerjoin(in_edges_sq, KnowledgeNode.id == in_edges_sq.c.target_id)
                .order_by(KnowledgeNode.created_at.desc())
                .limit(limit)
            )
            res = await db.execute(stmt)
            rows = res.all()

            node_data = [
                {
                    "id": str(n.id),
                    "name": n.name,
                    "node_type": n.node_type,
                    "attributes": n.attributes or {},
                    "edge_count": out_c + in_c,
                    "created_at": n.created_at.isoformat() if n.created_at else None,
                }
                for n, out_c, in_c in rows
            ]

            return {"nodes": node_data, "total": len(node_data)}
    except Exception as e:
        logger.error("get_kg_nodes_error", error=str(e))
        return {"nodes": [], "total": 0, "error": str(e)}


@router.get("/api/knowledge/edges")
async def get_knowledge_edges(limit: int = 100, current_user: User = Depends(get_current_active_user)):
    """Get knowledge graph edges with source/target names."""
    try:
        async with async_session() as db:
            res = await db.execute(
                select(KnowledgeEdge).order_by(KnowledgeEdge.created_at.desc()).limit(limit)
            )
            edges = res.scalars().all()

            edge_data = []
            for e in edges:
                src = await db.execute(select(KnowledgeNode).where(KnowledgeNode.id == e.source_id))
                tgt = await db.execute(select(KnowledgeNode).where(KnowledgeNode.id == e.target_id))
                src_node = src.scalar_one_or_none()
                tgt_node = tgt.scalar_one_or_none()
                edge_data.append({
                    "id": str(e.id),
                    "source": src_node.name if src_node else "unknown",
                    "target": tgt_node.name if tgt_node else "unknown",
                    "relation": e.relation,
                    "source_id": str(e.source_id),
                    "target_id": str(e.target_id),
                })

            return {"edges": edge_data, "total": len(edge_data)}
    except Exception as e:
        logger.error("get_kg_edges_error", error=str(e))
        return {"edges": [], "total": 0, "error": str(e)}


@router.get("/api/knowledge/search")
async def search_knowledge(q: str, limit: int = 20, current_user: User = Depends(get_current_active_user)):
    """Search the knowledge graph for concepts matching a query."""
    try:
        async with async_session() as db:
            res = await db.execute(
                select(KnowledgeNode)
                .where(KnowledgeNode.name.ilike(f"%{q}%"))
                .limit(limit)
            )
            nodes = res.scalars().all()

            results = []
            for n in nodes:
                # Get related edges
                edge_res = await db.execute(
                    select(KnowledgeEdge).where(
                        or_(KnowledgeEdge.source_id == n.id, KnowledgeEdge.target_id == n.id)
                    ).limit(10)
                )
                edges = edge_res.scalars().all()
                relations = []
                for edge in edges:
                    other_id = edge.target_id if edge.source_id == n.id else edge.source_id
                    other = await db.execute(select(KnowledgeNode).where(KnowledgeNode.id == other_id))
                    other_node = other.scalar_one_or_none()
                    if other_node:
                        direction = "→" if edge.source_id == n.id else "←"
                        relations.append(f"{direction} [{edge.relation}] {other_node.name}")

                results.append({
                    "id": str(n.id),
                    "name": n.name,
                    "node_type": n.node_type,
                    "relations": relations,
                })

            return {"results": results}
    except Exception as e:
        logger.error("kg_search_error", error=str(e))
        return {"results": [], "error": str(e)}


# ──────────────────────── Experiment Stats ────────────────────────

@router.get("/api/experiments/stats")
async def get_experiment_stats(current_user: User = Depends(get_current_active_user)):
    """Get aggregate experiment statistics across all sessions."""
    try:
        async with async_session() as db:
            total = await db.execute(select(func.count()).select_from(ExperimentTrack))
            total_count = total.scalar() or 0

            sessions_with_experiments = await db.execute(
                select(func.count(func.distinct(ExperimentTrack.session_id)))
            )
            session_count = sessions_with_experiments.scalar() or 0

            recent = await db.execute(
                select(ExperimentTrack)
                .order_by(ExperimentTrack.created_at.desc())
                .limit(5)
            )
            recent_experiments = [
                {
                    "id": str(t.id),
                    "hypothesis": t.hypothesis[:100],
                    "conclusion": (t.conclusion or "")[:100],
                    "session_id": str(t.session_id),
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                } for t in recent.scalars().all()
            ]

            return {
                "total_experiments": total_count,
                "sessions_with_experiments": session_count,
                "recent": recent_experiments,
            }
    except Exception as e:
        logger.error("experiment_stats_error", error=str(e))
        return {"total_experiments": 0, "sessions_with_experiments": 0, "recent": [], "error": str(e)}


# ──────────────────────── RLHF Alignment ────────────────────────

@router.get("/api/research/modes")
async def get_research_modes(current_user: User = Depends(get_current_active_user)):
    """Get available research modes for the mode selector."""
    return {"modes": [
        {"id": k, "label": v["label"], "depth": v["depth"], "max_sources": v["max_sources"]}
        for k, v in RESEARCH_MODES.items()
    ]}


@router.post("/api/research/align")
async def align_research_query(req: dict, current_user: User = Depends(get_current_active_user)):
    """Pre-research alignment — refines query, decomposes sub-queries, detects ambiguity."""
    query = req.get("query", "")
    mode = req.get("mode", "deep")

    if not query.strip():
        raise HTTPException(status_code=400, detail="Query is required")

    # Check if clarification is needed
    clarification = needs_clarification(query)
    if clarification:
        return {"needs_clarification": True, **clarification}

    # Load user preferences
    prefs = await get_user_preferences()

    # Align the query
    alignment = await align_query(query, mode=mode, user_prefs=prefs)

    return {
        "needs_clarification": False,
        "original_query": query,
        "refined_query": alignment["refined_query"],
        "sub_queries": alignment["sub_queries"],
        "search_strategy": alignment["search_strategy"],
        "mode": mode,
        "mode_config": alignment["mode_config"],
    }


@router.post("/api/feedback")
async def submit_feedback(req: dict, current_user: User = Depends(get_current_active_user)):
    """RLHF feedback capture — rate and comment on research quality."""
    session_id = req.get("session_id", "")
    rating = req.get("rating", 0)
    comment = req.get("comment", "")

    if not session_id or not rating:
        raise HTTPException(status_code=400, detail="session_id and rating required")

    # Get session query for context
    session = await session_store.get(session_id)
    query = session.get("user_request", "") if session else ""

    try:
        # Store feedback
        async with async_session() as db:
            feedback = FeedbackLog(
                session_id=session_id,
                rating=rating,
                comment=comment,
                query=query,
                research_mode=req.get("mode", "deep"),
            )
            db.add(feedback)
            await db.commit()

        # Learn from the feedback (update preferences)
        await learn_from_feedback(session_id, rating, comment)

        logger.info("feedback_captured", session_id=session_id, rating=rating)
        return {"status": "ok", "message": "Thank you for your feedback"}
    except Exception as e:
        logger.error("feedback_error", error=str(e))
        return {"status": "error", "message": str(e)}


@router.get("/api/preferences")
async def get_preferences(current_user: User = Depends(get_current_active_user)):
    """Get learned user preferences."""
    prefs = await get_user_preferences()
    return {"preferences": prefs}


# ──────────────────────── WebSocket ────────────────────────

@router.websocket("/ws/{session_id}")
async def websocket_research(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for streaming research agent events."""
    await websocket.accept()
    logger.info("ws_connected", session_id=session_id)

    try:
        # Wait for the research query
        data = await websocket.receive_text()
        payload = json.loads(data)
        query = payload.get("query", data)
        research_mode = payload.get("mode", "deep")

        # ─── LAYER 1: INPUT JAILBREAK GUARD ───
        input_scan = scan_user_input(query)
        if not input_scan.is_safe:
            logger.warning("user_input_blocked", session_id=session_id, risk_score=input_scan.risk_score)
            await websocket.send_json({
                "type": "error",
                "data": {
                    "message": input_scan.rejection_message,
                    "blocked": True,
                    "risk_score": input_scan.risk_score,
                }
            })
            await websocket.close()
            return
        
        # Use sanitized query (single-pattern matches get cleaned, multi-pattern get blocked above)
        query = input_scan.sanitized_query if input_scan.sanitized_query else query

        # Create or update session
        if session_id not in _sessions:
            _sessions[session_id] = {
                "id": session_id,
                "title": query[:100],
                "user_request": query,
                "status": "running",
                "final_report": "",
                "iterations_used": 0,
                "tokens_used": 0,
                "tool_calls_count": 0,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        _sessions[session_id]["status"] = "running"
        await _update_session_in_db(session_id, {"status": "running"})

        await websocket.send_json({"type": "status", "data": {"status": "running", "message": "Research started"}})

        # ─── RLHF ALIGNMENT LAYER (before execution) ───
        await websocket.send_json({"type": "thinking", "data": {"message": "🟣 Aligning query with RLHF preferences..."}})

        user_prefs = await get_user_preferences()
        alignment = await align_query(query, mode=research_mode, user_prefs=user_prefs)

        aligned_query = alignment["refined_query"]
        sub_queries = alignment.get("sub_queries", [])
        mode_config = alignment.get("mode_config", {})
        strategy = alignment.get("search_strategy", "balanced")

        await websocket.send_json({"type": "thinking", "data": {"message": f"✅ Query aligned — strategy: {strategy}, mode: {research_mode}"}})

        if sub_queries:
            await websocket.send_json({"type": "thinking", "data": {"message": f"🔀 Decomposed into {len(sub_queries)} sub-queries"}})

        # Build enriched query with alignment context
        enriched_query = f"""{aligned_query}

[ALIGNMENT CONTEXT]
- Research Mode: {mode_config.get('label', 'Deep')} ({mode_config.get('depth', 'comprehensive')})
- Mode Instructions: {mode_config.get('instructions', '')}
- Search Strategy: {strategy}
- Sub-questions to address: {chr(10).join(f'  {i+1}. {sq}' for i, sq in enumerate(sub_queries)) if sub_queries else 'None'}
- User preferences: {user_prefs if user_prefs else 'No preferences learned yet'}
"""

        # Extract and update user memory based on query
        await update_user_memory(query)

        # Build the graph for this session
        graph = await build_graph(session_id)

        initial_state = {
            "messages": [HumanMessage(content=enriched_query)],
            "session_id": session_id,
            "status": "running",
            "iteration": 0,
            "consecutive_failures": 0,
            "accessed_urls": set(),
            "hitl_mode": "supervised", # Defaulting to supervised for testing
            "pending_approval": None,
            "user_modifications": [],
        }
        
        # Setup duplex communication
        from backend.core.hitl import HITLManager
        
        async def listen_to_client():
            while True:
                try:
                    msg = await websocket.receive_text()
                    payload = json.loads(msg)
                    msg_type = payload.get("type")
                    
                    if msg_type == "hitl_resume":
                        action = payload.get("data", {}).get("action", "continue")
                        modifications = payload.get("data", {}).get("modifications", {})
                        modifications["action"] = action
                        HITLManager.resume_with_input(session_id, modifications)
                    
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error("ws_listen_error", error=str(e))
                    break
                    
        # Start client listener
        listener_task = asyncio.create_task(listen_to_client())

        tracked_urls = set()
        # Stream agent events
        async for event in graph.astream_events(initial_state, {"configurable": {"thread_id": session_id}}, version="v2"):
            try:
                # Intercept HITL pause logging and send event
                if event.get("event") == "on_chat_model_start" and HITLManager.is_paused(session_id):
                    # We are in a paused state, we need to send the hitl_pause event
                    # This happens when the graph blocks inside the agent node.
                    pass # Actually handled below in a generic way

                event_type = event.get("event", "")
                event_name = event.get("name", "")
                
                # Expose HITL pause event by checking if HITLManager just got paused
                if HITLManager.is_paused(session_id) and event_type == "on_chain_start" and event_name == "agent_node":
                    await websocket.send_json({
                        "type": "hitl_pause",
                        "data": {
                            "checkpoint_type": "checkpoint",
                            "data": {}
                        }
                    })

                # Extract tracked URLs
                output = event.get("data", {}).get("output", {})
                if isinstance(output, dict) and "accessed_urls" in output:
                    tracked_urls.update(output["accessed_urls"])

                if event_type == "on_chat_model_start":
                    await websocket.send_json({
                        "type": "thinking",
                        "data": {"message": "Analyzing and reasoning..."}
                    })

                elif event_type == "on_chat_model_end":
                    output = event.get("data", {}).get("output", None)
                    if output:
                        content = getattr(output, 'content', '')
                        tool_calls = getattr(output, 'tool_calls', [])

                        if tool_calls:
                            for tc in tool_calls:
                                await websocket.send_json({
                                    "type": "tool_call",
                                    "data": {
                                        "tool": tc.get("name", ""),
                                        "input": tc.get("args", {}),
                                    }
                                })
                        elif content:
                            # ─── LAYER 3: OUTPUT SAFETY GUARD ───
                            output_scan = scan_llm_output(content)
                            safe_content = output_scan.sanitized_content
                            
                            if not output_scan.is_safe:
                                logger.warning("harmful_output_intercepted", session_id=session_id, categories=output_scan.blocked_categories)
                            
                            await websocket.send_json({
                                "type": "message",
                                "data": {"content": safe_content}
                            })

                elif event_type == "on_tool_end":
                    output = event.get("data", {}).get("output", "")
                    tool_name = event_name
                    content = str(output.content) if hasattr(output, 'content') else str(output)

                    await websocket.send_json({
                        "type": "tool_result",
                        "data": {
                            "tool": tool_name,
                            "result": content[:2000],  # cap result size
                        }
                    })

                    # Send updated todos if planning tool was used
                    if tool_name in ("write_todos", "get_todos"):
                        todos = get_session_todos(session_id)
                        await websocket.send_json({
                            "type": "todo_update",
                            "data": {"todos": todos}
                        })

                    # Send metrics periodically
                    metrics = get_execution_metrics(session_id)
                    if metrics:
                        await websocket.send_json({
                            "type": "metrics",
                            "data": metrics
                        })

            except Exception as e:
                logger.error("ws_event_error", error=str(e), event_type=event.get("event", ""))

        # Cancel listener task
        listener_task.cancel()

        # Research complete
        _sessions[session_id]["status"] = "completed"
        metrics = get_execution_metrics(session_id)
        if metrics:
            _sessions[session_id]["iterations_used"] = metrics.get("iterations_count", 0)
            _sessions[session_id]["tokens_used"] = metrics.get("tokens_used", 0)
            _sessions[session_id]["tool_calls_count"] = metrics.get("tool_calls_count", 0)

        # Try to read the report from workspace
        try:
            report = _workspace.read_file(session_id, "report.md")
            # Apply Citation Verifier Guardrail
            report, fabricated = verify_citations(report, tracked_urls)
            if fabricated:
                # Update file on disk with the [Unverified] tags
                _workspace.write_file(session_id, "report.md", report)
                
            _sessions[session_id]["final_report"] = report
        except FileNotFoundError:
            pass

        # Persist final state to DB
        await _update_session_in_db(session_id, {
            "status": "completed",
            "iterations_used": _sessions[session_id].get("iterations_used", 0),
            "tokens_used": _sessions[session_id].get("tokens_used", 0),
            "tool_calls_count": _sessions[session_id].get("tool_calls_count", 0),
            "final_report": _sessions[session_id].get("final_report", ""),
        })

        await websocket.send_json({
            "type": "complete",
            "data": {
                "status": "completed",
                "session": _sessions[session_id],
            }
        })

    except WebSocketDisconnect:
        logger.info("ws_disconnected", session_id=session_id)
        if session_id in _sessions:
            _sessions[session_id]["status"] = "cancelled"
            await _update_session_in_db(session_id, {"status": "cancelled"})

    except Exception as e:
        logger.error("ws_error", session_id=session_id, error=str(e))
        if session_id in _sessions:
            _sessions[session_id]["status"] = "failed"
            await _update_session_in_db(session_id, {"status": "failed"})
        try:
            await websocket.send_json({
                "type": "error",
                "data": {"message": str(e)}
            })
        except Exception:
            pass

    finally:
        # Always clean up session resources regardless of how we exit
        cleanup_session(session_id)
        logger.info("ws_cleanup_complete", session_id=session_id)
