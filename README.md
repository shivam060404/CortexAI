# CortexAI — Autonomous Deep Research Agent Platform (v5.0)

> A production-grade, enterprise-ready autonomous research agent with multi-tenant architecture, SOC2 compliance, real-time collaboration, and a unified Agent Harness framework. Plans, searches, analyzes, debates, reflects, and generates comprehensive reports — all in real-time.

---

## 🔍 Overview

CortexAI is an advanced research assistant powered by a central **Context Graph OS** and a **LangGraph Supervisor Multi-Agent Network**. Unlike simple search-and-summarize bots, CortexAI's Chief Research Officer (CRO) autonomously plans strategy, orchestrates specialized Search and Verification agents, and mutates a central knowledge graph. It features dynamic credibility scoring via a Trust Engine, temporal node versioning, and produces publication-ready reports with PowerPoint, PDF, and DOCX exports — all streamed to a premium React dashboard in real-time via WebSocket.

### ✨ Key Features

| Feature | Description |
|---------|-------------|
| 🧠 **Dynamic Planning & HITL** | Agent creates tasks via `write_todos`. **Human-in-the-loop** (HITL) gates allow you to pause, review, and modify the plan mid-flight. |
| 🔌 **MCP Protocol Architecture** | Tools are isolated into standalone Model Context Protocol (MCP) servers with hot-reload support and a custom tool registry. |
| 🌐 **Chrome Extension** | Context injector extension to tag and save active webpages directly into the agent's long-term memory. |
| 🤖 **Browser-Use Agent** | Headless browser automation capable of accessing gated content (X, LinkedIn, Quora) using encrypted session cookies. |
| ⚔️ **Multi-Agent Debate** | Defender vs. Skeptic debate engine eliminates confirmation bias over multiple rounds. |
| 🔬 **Self-Reflection** | Agent critically evaluates its own research (completeness, bias, evidence quality) before finalizing. |
| 🧪 **Python Execution Sandbox** | Secure, resource-limited subprocess with memory caps, CPU limits, and timeout enforcement. |
| 📊 **Advanced Search Engine** | Parallel orchestration of **Tavily**, **Exa**, and **Firecrawl** with hybrid BM25+semantic RAG pipeline. |
| 🧩 **GraphRAG Knowledge** | LanceDB-backed persistent fact storage with hybrid search (BM25 + vector similarity) and reciprocal rank fusion. |
| 📋 **Multi-Format Exports** | Converts reports into PowerPoint, PDF (WeasyPrint), DOCX (python-docx), and interactive HTML files. |
| 🛡️ **3-Layer Security & ML** | ML-based prompt injection classifier, Tool Output Guards, and LLM Output Guards (OWASP LLM Top 10 protected). |
| 🔐 **PII Redaction & Citations** | Automatic masking of emails, SSNs, credit cards. Flags hallucinated URLs with citation verification. |
| ⚡ **Rate Limiter & Guards** | API rate-limiting via Token Bucket, per-key rate limits, max iterations, tokens, and timeout circuit breakers. |
| 📊 **Phoenix Observability** | Arize Phoenix OpenTelemetry traces with custom spans for supervisor phases, tool calls, and sub-agents. |
| 🎯 **RLHF Alignment** | Query refinement, research mode selection, preference learning with exponential decay and confidence thresholds. |
| 🏢 **Multi-Tenant & Orgs** | Organization model with role-based access (owner/admin/member/viewer), RLS tenant isolation, and org-scoped queries. |
| 🔑 **API Key Management** | Multi-key support per user with scopes, rotation grace periods, expiry, and last-used tracking. |
| 🔗 **Shareable Reports** | Token-based shareable report permalinks with expiry, view counting, and public/private access control. |
| 👥 **Real-Time Collaboration** | Multiple users can join a research session with WebSocket broadcasting and conflict resolution. |
| 📜 **SOC2 Compliance** | Comprehensive audit logging with data access tracking, config change logs, retention policies, and CSV/JSON export. |
| 🛡️ **Content Policy Engine** | Per-organization content policies with tiered approval modes: auto, supervised, and locked. |
| 🔧 **Custom Tool Registry** | Dynamic tool registration from MCP servers, capability discovery, validation, and per-org allowlists. |
| 🏗️ **Agent Harness Framework** | Unified 5-pillar configuration (Tool Orchestration, Context Compaction, Task Delegation, Guardrails, Observability) with health checks and scoring. |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Frontend (React + Vite)                             │
│  Dashboard │ Research Lab (Image Dropzone, Plan Editor, Tagging)            │
│  Observability │ Knowledge Graph │ Settings │ Chrome Extension              │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │ REST + WebSocket (Duplex HITL + Broadcasting)
┌──────────────────────────────▼──────────────────────────────────────────────┐
│                   Backend (FastAPI + LangGraph + Agent Harness)              │
│                                                                             │
│  ┌─── Security & Guards ──────────────────────────────────────────────┐    │
│  │ ML Classifier │ Rate Limiter (Token Bucket) │ PII Redaction         │    │
│  │ Citation Verification │ Scope Drift │ Content Policy Engine         │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─── Agent Harness (5 Pillars) ──────────────────────────────────────┐    │
│  │ 1. Tool Orchestration & Sandboxed Execution                         │    │
│  │ 2. Context Compaction & Memory Management                           │    │
│  │ 3. Task Delegation & Ephemeral Sub-Agents                           │    │
│  │ 4. Guardrails / Safety / HITL                                       │    │
│  │ 5. Observability & Error Recovery                                   │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─── Central Context Graph OS (Pluggable Backend) ───────────────────┐    │
│  │ NetworkX (default) │ Redis (multi-instance)                         │    │
│  │ Node Types: User, Session, Source, Finding, Hypothesis              │    │
│  │ Engines: Trust Engine (ML Credibility) & Knowledge Versioning       │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─── Multi-Agent Core (LangGraph Supervisor) ────────────────────────┐    │
│  │ CRO with Dynamic Temperature + Multi-Model Fallback + Circuit Breaker│    │
│  │ ├─ SearchAgent (Tavily/Exa + Hybrid RAG)                            │    │
│  │ └─ VerificationAgent (Fact checking & Trust updating)               │    │
│  │ + HITL Manager │ ExecutionGuard │ Loop Detection │ MemorySaver      │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─── MCP Protocol (Hot-Reload Tool Servers) ────────────────────────┐    │
│  │ Custom Tool Registry │ Per-Org Allowlists │ Config Hot-Reload      │    │
│  │ 1. Search Server  2. Browser Server  3. Data Server  4. Export    │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─── Enterprise Layer ───────────────────────────────────────────────┐    │
│  │ Multi-Tenant (RLS) │ Organizations │ API Key Management            │    │
│  │ Report Sharing │ Real-Time Collaboration │ SOC2 Audit Logging      │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─── Storage Layer ──────────────────────────────────────────────────┐    │
│  │ PostgreSQL (sessions, traces, KG, experiments, feedback, prefs,    │    │
│  │   orgs, api_keys, report_shares, participants, audit_logs)         │    │
│  │ LanceDB (Hybrid RAG: BM25 + Vector + Reciprocal Rank Fusion)      │    │
│  │ Redis (cache, session store, distributed graph backend)            │    │
│  │ Local FS (sandboxed per-session workspace)                         │    │
│  └────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start (Docker Production Setup)

The easiest way to run the full v5.0 stack is via Docker Compose.

### Prerequisites
- Docker & Docker Compose
- Node.js 18+ (for local frontend dev, optional if using Docker)

### Setup

1. **Configure Environment Variables**
Create a `.env` file in the root directory:
```env
# Required API Keys
MISTRAL_API_KEY=your_mistral_key_here
TAVILY_API_KEY=your_tavily_key_here
EXA_API_KEY=your_exa_key_here
FIRECRAWL_API_KEY=your_firecrawl_key_here
GROQ_API_KEY=your_groq_key_here

# Backend configuration is handled by Docker automatically.
```

2. **Launch with Docker Compose**
```bash
docker-compose up --build
```
This will spin up:
- CortexAI FastAPI Backend (`localhost:8000`)
- CortexAI React Frontend (`localhost:3000`)
- PostgreSQL Database
- Redis Cache

3. **Install the Chrome Extension**
- Open Chrome and navigate to `chrome://extensions/`.
- Enable **Developer Mode** (top right toggle).
- Click **Load unpacked** and select the `chrome-extension/` directory.
- Click the extension icon to connect it to `http://localhost:8000`.

---

## 🔧 API Endpoints

### Core Research

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/sessions` | Create research session |
| `GET` | `/api/sessions` | List all sessions |
| `GET` | `/api/sessions/{id}` | Get session details |
| `DELETE` | `/api/sessions/{id}` | Delete session |
| `GET` | `/api/sessions/{id}/todos` | Get session tasks |
| `GET` | `/api/sessions/{id}/files` | List workspace files |
| `POST` | `/api/context/pages` | Inject Chrome extension context |
| `POST` | `/api/sessions/{id}/feedback` | Submit RLHF feedback |
| `GET` | `/api/sessions/{id}/export/{format}` | Export report (PDF/DOCX) |
| `WS` | `/ws/{session_id}` | Real-time agent event stream & HITL |

### Report Sharing

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/sessions/{id}/share` | Create shareable link |
| `GET` | `/api/sessions/{id}/shares` | List share links |
| `GET` | `/api/shared/{token}` | View shared report (no auth) |
| `DELETE` | `/api/shared/{token}` | Revoke share link |

### Collaboration

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/sessions/{id}/collaborate/join` | Join session |
| `POST` | `/api/sessions/{id}/collaborate/leave` | Leave session |
| `GET` | `/api/sessions/{id}/collaborate/participants` | List participants |
| `PUT` | `/api/sessions/{id}/collaborate/role` | Update participant role |
| `GET` | `/api/collaboration/active` | Active connections |

### Analytics & Observability

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/analytics/usage` | Usage stats over time |
| `GET` | `/api/analytics/costs` | Per-session cost breakdown |
| `GET` | `/api/analytics/performance` | Latency & success rates |

### SOC2 Audit

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/audit/summary` | Audit event statistics |
| `GET` | `/api/audit/export` | Export logs (JSON/CSV) |
| `POST` | `/api/audit/retention` | Apply retention policy |

### Agent Harness

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/harness/config` | Full harness configuration |
| `GET` | `/api/harness/health` | Live pillar health check |
| `GET` | `/api/harness/score` | Pillar scoring breakdown |

### Tool Registry & MCP

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/tools` | List registered tools |
| `GET` | `/api/tools/status` | Tool registry status |
| `POST` | `/api/mcp/reload` | Hot-reload MCP config |

---

## 🛡️ Security & Guardrails

| Layer | Component | Protection |
|-------|-----------|------------|
| **Layer 1** | `MLClassifier` | Heuristic/ML engine to block jailbreaks (DAN, prompt extraction) |
| **Layer 2** | `Tool Output Guard` | Sanitizes poisoned web content from search results mid-loop |
| **Layer 3** | `LLM Output Guard` | Moderates LLM responses (weapons, hacking, self-harm) |
| **Content Policy** | `ContentPolicyEngine` | Per-org tiered approval: auto, supervised, locked |
| **PII** | `redact_pii()` | Masks emails, phones, SSNs, credit cards |
| **Citations** | `verify_citations()` | Flags URLs the LLM never actually accessed |
| **Rate Limit** | `rate_limit_middleware` | Token bucket + per-key rate limits (default: 60 req/min) |
| **Request Size** | `RequestBodyLimitMiddleware` | Configurable max body size (default 10MB) |
| **Audit** | `AuditLogger` | SOC2-compliant data access & config change logging |

---

## 🏗️ Agent Harness Framework (5 Pillars)

The Agent Harness provides a unified configuration and health monitoring framework across all platform capabilities:

| Pillar | Score | Key Capabilities |
|--------|-------|------------------|
| **1. Tool Orchestration** | 90/100 | Sandbox isolation, resource limits, timeout enforcement, output size caps |
| **2. Context Compaction** | 88/100 | Token budgets, context summarization, pluggable graph backends, hybrid RAG |
| **3. Task Delegation** | 85/100 | Dynamic temperature, multi-model fallback, circuit breaker, loop detection |
| **4. Guardrails/Safety** | 92/100 | PII redaction, injection shield, output moderation, HITL, content policy |
| **5. Observability** | 90/100 | OpenTelemetry traces, custom spans, cost tracking, SOC2 audit logging |

---

## 🎯 Research Modes

| Mode | Depth | Sources | Behavior |
|------|-------|---------|----------|
| ⚡ **Fast** | Overview | 3-5 | Quick focused summary |
| 🧠 **Deep** | Comprehensive | 15-20 | Multi-angle, contrasting viewpoints |
| 🔬 **Academic** | Scholarly | 25-30 | Peer-reviewed papers, formal citations |

---

## 🙏 Acknowledgements

- [LangGraph](https://github.com/langchain-ai/langgraph) — Workflow orchestration
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io) — Standalone tool servers
- [browser-use](https://github.com/browser-use/browser-use) — Browser automation
- [React](https://react.dev/) + [Vite](https://vitejs.dev/) — Frontend
- [Mistral AI](https://mistral.ai/) & [Groq](https://groq.com/) — Language & Vision models

---

## 📝 License

MIT License
