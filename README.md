# CortexAI — Autonomous Deep Research Agent Platform

> A production-grade, full-stack autonomous research agent that plans, searches, analyzes, debates, reflects, and generates comprehensive reports — all in real-time.

---

## 🔍 Overview

CortexAI is an advanced research assistant powered by a dynamic **LangGraph ReAct** agent loop. Unlike simple search-and-summarize bots, CortexAI autonomously plans its own research strategy, executes multi-source searches, spawns specialized sub-agents, debates nuanced topics, self-evaluates its work, and produces publication-ready reports with PowerPoint exports — all streamed to a premium React dashboard in real-time via WebSocket.

### ✨ Key Features

| Feature | Description |
|---------|-------------|
| 🧠 **Dynamic Planning** | Agent creates and manages its own task list via `write_todos` tool with a full state machine |
| 📁 **File Workspace** | Sandboxed per-session filesystem — agent stores notes, drafts, charts, and final reports |
| 🤖 **Sub-Agent Delegation** | Spawns isolated specialist agents (analyst, writer, data) with separate resource budgets |
| ⚔️ **Multi-Agent Debate** | Defender vs. Skeptic debate engine eliminates confirmation bias over multiple rounds |
| 🔬 **Self-Reflection** | Agent critically evaluates its own research (completeness, bias, evidence quality) before finalizing |
| 🔄 **Hypothesis-Driven Research Loops** | Generates and tests hypotheses iteratively, like a real scientist |
| 🧪 **Python Execution Sandbox** | Secure, timeout-bound subprocess for running data analysis scripts and generating Matplotlib charts |
| 📊 **Source Ranking Engine** | Multi-signal credibility scoring (domain reputation + semantic relevance + citation density) |
| 🧩 **GraphRAG Knowledge** | LanceDB-backed persistent fact storage across sessions extracting entities and community summaries |
| ⏰ **Background Watcher** | APScheduler cron jobs for continuous, unattended research monitoring |
| 📋 **Automated PPTX Export** | Converts markdown reports into corporate-ready PowerPoint presentations |
| 📥 **PDF Download** | Client-side markdown-to-PDF conversion via `marked` + `html2pdf.js` |
| 🛡️ **3-Layer Security** | Input Guard → Tool Output Guard → LLM Output Guard (OWASP LLM Top 10 protected) |
| 🔐 **PII Redaction** | Automatic detection and masking of emails, phone numbers, SSNs, credit cards |
| 🔗 **Citation Verification** | Flags hallucinated URLs that the LLM never actually accessed |
| 🧭 **Semantic Scope Drift** | Uses Semantic Router to detect when the agent wanders too far from the original query |
| ⚡ **Execution Guard** | Hard limits: configurable max iterations, tokens, and timeout per session |
| 🔧 **Tool Safety** | Permission allowlist + path sandboxing prevents unauthorized filesystem access |
| ⚡ **Redis Caching** | Search results cached (1h TTL) to avoid duplicate API calls and reduce cost |
| 🔄 **Error Recovery** | Retry with exponential backoff + circuit breaker for external API resilience |
| 📊 **Phoenix Observability** | Arize Phoenix OpenTelemetry (OTEL) traces + Structured JSON logs via `structlog` |
| 🎯 **RLHF Alignment** | Query refinement, research mode selection, user preference learning from feedback |
| 🧠 **Failure Memory** | Prevents repeating the same failed approaches within a session |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Frontend (React + Vite)                             │
│  Dashboard │ Research Lab │ Workspace │ Tasks │ History │ Experiments       │
│  Observability │ Knowledge Graph │ Settings                                │
│  Services: REST API Client + WebSocket (auto-reconnect)                    │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │ REST + WebSocket
┌──────────────────────────────▼──────────────────────────────────────────────┐
│                        Backend (FastAPI + LangGraph)                        │
│                                                                             │
│  ┌─── Security Layer ──────────────────────────────────────────────────┐    │
│  │ Layer 1: Input Guard (jailbreak detection)                          │    │
│  │ Layer 2: Tool Output Guard (indirect injection sanitization)        │    │
│  │ Layer 3: LLM Output Guard (harmful content moderation)              │    │
│  │ + PII Redaction, Citation Verification, Scope Drift Detection       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─── Alignment Engine ───────────────────────────────────────────────┐    │
│  │ Query Refinement │ Research Mode Selection │ Preference Learning    │    │
│  │ Reward Engine (plan scoring) │ Ranking Engine (source credibility)  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─── Agent Core (LangGraph ReAct Loop) ──────────────────────────────┐    │
│  │ Tiered Inference (Mistral + Llama3) │ ExecutionGuard                │    │
│  │ Context Manager (auto-summarize) │ Failure Memory │ Retry/Backoff   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─── Tool System (13 tools) ─────────────────────────────────────────┐    │
│  │ Search: web, academic, news (cached + ranked)                       │    │
│  │ Filesystem: read, write, edit, list, grep (sandboxed)               │    │
│  │ Planning: write_todos, get_todos (state machine)                    │    │
│  │ Sub-agents: spawn_subagent (resource-isolated)                      │    │
│  │ Debate: run_debate (Defender vs Skeptic, multi-round)               │    │
│  │ Reflection: self_reflect, cross_reference_sources                   │    │
│  │ Research Loop: generate_hypothesis, evaluate_findings               │    │
│  │ Sandbox: execute_python_script (30s timeout subprocess)             │    │
│  │ Export: generate_presentation (PPTX)                                │    │
│  │ Knowledge Graph: add_to_knowledge_graph, query_knowledge_graph      │    │
│  │ Experiments: log_experiment                                         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─── Storage Layer ──────────────────────────────────────────────────┐    │
│  │ PostgreSQL (sessions, traces, KG, experiments, feedback, prefs)      │    │
│  │ LanceDB (GraphRAG vector semantic search across past research)       │    │
│  │ Redis (cache-aside pattern, graceful degradation)                   │    │
│  │ Local FS (sandboxed per-session workspace)                          │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─── Background Services ────────────────────────────────────────────┐    │
│  │ APScheduler: Background Watcher (periodic research updates)         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- PostgreSQL (optional — gracefully degrades to in-memory)
- Redis (optional — gracefully degrades)

### Backend Setup

```bash
# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment — edit .env with your API keys
# Required: MISTRAL_API_KEY, TAVILY_API_KEY

# Start backend
python -m uvicorn backend.api.app:app --reload --port 8000
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser.

---

## 📁 Project Structure

```
├── backend/
│   ├── config/              # Pydantic settings, env vars
│   ├── core/
│   │   ├── graph.py         # LangGraph orchestrator (async ReAct loop)
│   │   ├── execution_guard.py   # Iteration/token/timeout limiter
│   │   ├── tool_guard.py        # Tool allowlist + path sandboxing
│   │   ├── guardrails.py        # Semantic Router + 3-layer security (input/tool/output)
│   │   ├── alignment_engine.py  # Query refinement + research modes
│   │   ├── reward_engine.py     # RLHF plan scoring
│   │   ├── ranking_engine.py    # Source credibility scoring
│   │   ├── preference_learning.py # User preference learning from feedback
│   │   ├── failure_memory.py    # Anti-repetition memory
│   │   ├── scheduler.py         # APScheduler background watcher
│   │   ├── retry.py             # Exponential backoff + circuit breaker
│   │   ├── logger.py            # Structured JSON logging (structlog)
│   │   └── state.py             # AgentState TypedDict
│   ├── db/
│   │   ├── postgres.py      # SQLAlchemy async models (10+ tables)
│   │   ├── lancedb_store.py  # LanceDB GraphRAG Vector Store
│   │   ├── cache.py          # Redis cache-aside pattern
│   │   └── workspace.py      # Sandboxed local filesystem manager
│   ├── tools/               # 13 tool modules (search, fs, planning, debate, etc.)
│   ├── agents/
│   │   ├── deep_agent.py    # Agent factory (binds all tools to Tiered Inference routing)
│   │   ├── prompts.py       # System prompts for main + sub-agents
│   │   └── context_manager.py # Auto-summarization middleware
│   └── api/
│       ├── app.py           # FastAPI application factory
│       ├── routes.py        # REST + WebSocket endpoints (32KB)
│       └── schemas.py       # Pydantic request/response models
├── frontend/
│   └── src/
│       ├── components/      # Layout (Sidebar, MainLayout)
│       ├── pages/           # 9 pages (Dashboard, Research, Workspace, Tasks,
│       │                    #   History, Experiments, Observability, KnowledgeGraph, Settings)
│       └── services/        # API client, WebSocket manager
├── .env                     # API keys and configuration
└── requirements.txt         # Python dependencies
```

---

## 🔧 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/sessions` | Create research session |
| `GET` | `/api/sessions` | List all sessions |
| `GET` | `/api/sessions/{id}` | Get session details |
| `DELETE` | `/api/sessions/{id}` | Delete session |
| `GET` | `/api/sessions/{id}/todos` | Get session tasks |
| `GET` | `/api/sessions/{id}/files` | List workspace files |
| `GET` | `/api/sessions/{id}/files/content` | Read file content |
| `GET` | `/api/sessions/{id}/metrics` | Get execution metrics |
| `POST` | `/api/sessions/{id}/feedback` | Submit RLHF feedback (rating + comment) |
| `POST` | `/api/sessions/{id}/watch` | Schedule background monitoring |
| `GET` | `/api/knowledge/{session_id}` | Query knowledge graph |
| `GET` | `/api/experiments/{session_id}` | List experiment logs |
| `WS` | `/ws/{session_id}` | Real-time agent event stream |

---

## 🛡️ Security: 3-Layer Defense System

| Layer | Component | Protection |
|-------|-----------|------------|
| **Layer 1** | `scan_user_input()` | Blocks jailbreak attempts (DAN, role hijacking, prompt extraction) BEFORE the LLM |
| **Layer 2** | `scan_for_prompt_injection()` | Sanitizes poisoned web content from search results mid-loop |
| **Layer 3** | `scan_llm_output()` | Moderates LLM responses (weapons, hacking, self-harm, drugs) BEFORE streaming to user |
| **PII** | `redact_pii()` | Masks emails, phones, SSNs, credit cards |
| **Citations** | `verify_citations()` | Flags URLs the LLM never actually accessed |
| **Drift** | `check_scope_drift()` | Detects when agent wanders off-topic |

---

## 🎯 Research Modes

| Mode | Depth | Sources | Behavior |
|------|-------|---------|----------|
| ⚡ **Fast** | Overview | 3-5 | Quick focused summary |
| 🧠 **Deep** | Comprehensive | 15-20 | Multi-angle, contrasting viewpoints |
| 🔬 **Academic** | Scholarly | 25-30 | Peer-reviewed papers, formal citations |

---

## 🔑 Environment Variables

```env
# Required
MISTRAL_API_KEY=your_key_here
TAVILY_API_KEY=your_key_here

# Optional (graceful degradation)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/cortexai
REDIS_URL=redis://localhost:6379/0
# LanceDB Vector Store
LANCEDB_PERSIST_DIR=./data/lancedb
WORKSPACE_ROOT=./data/workspaces

# Execution Limits
MAX_ITERATIONS=20
MAX_TOKENS_PER_SESSION=50000
AGENT_TIMEOUT_SECONDS=120
```

---

## 🙏 Acknowledgements

- [LangGraph](https://github.com/langchain-ai/langgraph) — Workflow orchestration
- [Mistral AI](https://mistral.ai/) — Language models
- [FastAPI](https://fastapi.tiangolo.com/) — Backend framework
- [React](https://react.dev/) + [Vite](https://vitejs.dev/) — Frontend
- [Tavily](https://tavily.com/) — Search API

---

## 📝 License

MIT License
