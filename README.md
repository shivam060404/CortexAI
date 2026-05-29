# CortexAI — Autonomous Deep Research Agent Platform (v4.0)

> A production-grade, full-stack autonomous research agent that plans, searches, analyzes, debates, reflects, and generates comprehensive reports — all in real-time. Now featuring MCP Protocol, Human-in-the-Loop interventions, and a dedicated Chrome Extension.

---

## 🔍 Overview

CortexAI is an advanced research assistant powered by a central **Context Graph OS** and a **LangGraph Supervisor Multi-Agent Network**. Unlike simple search-and-summarize bots, CortexAI's Chief Research Officer (CRO) autonomously plans strategy, orchestrates specialized Search and Verification agents, and mutates a central knowledge graph. It features dynamic credibility scoring via a Trust Engine, temporal node versioning, and produces publication-ready reports with PowerPoint exports — all streamed to a premium React dashboard in real-time via WebSocket.

### ✨ Key Features

| Feature | Description |
|---------|-------------|
| 🧠 **Dynamic Planning & HITL** | Agent creates tasks via `write_todos`. **Human-in-the-loop** (HITL) gates allow you to pause, review, and modify the plan mid-flight. |
| 🔌 **MCP Protocol Architecture** | Tools are isolated into standalone Model Context Protocol (MCP) servers (`search_server`, `browser_server`, `data_server`, `export_server`) for ultimate extensibility. |
| 🌐 **Chrome Extension** | Context injector extension to tag and save active webpages directly into the agent's long-term memory. |
| 🤖 **Browser-Use Agent** | Headless browser automation capable of accessing gated content (X, LinkedIn, Quora) using encrypted session cookies. |
| ⚔️ **Multi-Agent Debate** | Defender vs. Skeptic debate engine eliminates confirmation bias over multiple rounds. |
| 🔬 **Self-Reflection** | Agent critically evaluates its own research (completeness, bias, evidence quality) before finalizing. |
| 🧪 **Python Execution Sandbox** | Secure, timeout-bound subprocess for running data analysis scripts and generating interactive Plotly charts. |
| 📊 **Advanced Search Engine** | Parallel orchestration of **Tavily**, **Exa**, and **Firecrawl** for deep scraping and academic queries. |
| 🧩 **GraphRAG Knowledge** | LanceDB-backed persistent fact storage across sessions extracting entities and community summaries. |
| 📋 **Automated PPTX & Reports** | Converts markdown reports into corporate-ready PowerPoint presentations and interactive HTML files. |
| 🛡️ **3-Layer Security & ML** | ML-based prompt injection classifier, Tool Output Guards, and LLM Output Guards (OWASP LLM Top 10 protected). |
| 🔐 **PII Redaction & Citations** | Automatic masking of emails, SSNs, credit cards. Flags hallucinated URLs. |
| ⚡ **Rate Limiter & Guards** | API rate-limiting via Token Bucket, max iterations, tokens, and timeout circuit breakers. |
| 📊 **Phoenix Observability** | Arize Phoenix OpenTelemetry (OTEL) traces + Structured JSON logs via `structlog`. |
| 🎯 **RLHF Alignment** | Query refinement, research mode selection, user preference learning from feedback. |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Frontend (React + Vite)                             │
│  Dashboard │ Research Lab (Image Dropzone, Plan Editor, Tagging)            │
│  Observability │ Knowledge Graph │ Settings │ Chrome Extension              │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │ REST + WebSocket (Duplex HITL)
┌──────────────────────────────▼──────────────────────────────────────────────┐
│                        Backend (FastAPI + LangGraph)                        │
│                                                                             │
│  ┌─── Security & Guards ──────────────────────────────────────────────┐    │
│  │ ML Classifier (Jailbreak Detection) │ Rate Limiter (Token Bucket)   │    │
│  │ PII Redaction │ Citation Verification │ Scope Drift Detection       │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─── Central Context Graph OS (NetworkX) ────────────────────────────┐    │
│  │ Node Types: User, Session, Source, Finding, Hypothesis              │    │
│  │ Edge Types: GENERATES, SUPPORTED_BY, INVALIDATES                    │    │
│  │ Engines: Trust Engine (Credibility Scoring) & Knowledge Versioning  │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─── Multi-Agent Core (LangGraph Supervisor) ────────────────────────┐    │
│  │ Chief Research Officer (CRO) -> Routes to specialized workers:      │    │
│  │ ├─ SearchAgent (Tavily/Exa population)                              │    │
│  │ └─ VerificationAgent (Fact checking & Trust updating)               │    │
│  │ + HITL Manager │ ExecutionGuard │ MemorySaver                       │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─── MCP Protocol (Standalone Tool Servers) ─────────────────────────┐    │
│  │ 1. Search Server (Tavily, Exa, Firecrawl orchestration)            │    │
│  │ 2. Browser Server (browser-use, authenticated scraping)            │    │
│  │ 3. Data Server (sandboxed python, plotly generation)               │    │
│  │ 4. Export Server (pptx, interactive HTML reports)                  │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─── Storage Layer ──────────────────────────────────────────────────┐    │
│  │ PostgreSQL (sessions, traces, KG, experiments, feedback, prefs)    │    │
│  │ LanceDB (GraphRAG vector semantic search across past research)     │    │
│  │ Redis (cache-aside pattern, graceful degradation)                  │    │
│  │ Local FS (sandboxed per-session workspace)                         │    │
│  └────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start (Docker Production Setup)

The easiest way to run the full v3.0 stack is via Docker Compose.

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

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/sessions` | Create research session |
| `GET` | `/api/sessions` | List all sessions |
| `GET` | `/api/sessions/{id}` | Get session details |
| `DELETE` | `/api/sessions/{id}` | Delete session |
| `GET` | `/api/sessions/{id}/todos` | Get session tasks |
| `GET` | `/api/sessions/{id}/files` | List workspace files |
| `POST` | `/api/context/pages` | **[NEW]** Inject Chrome extension context |
| `POST` | `/api/sessions/{id}/feedback` | Submit RLHF feedback (rating + comment) |
| `WS` | `/ws/{session_id}` | Real-time agent event stream & HITL duplex |

---

## 🛡️ Security & Guardrails

| Layer | Component | Protection |
|-------|-----------|------------|
| **Layer 1** | `MLClassifier` | Heuristic/ML engine to block jailbreaks (DAN, prompt extraction) |
| **Layer 2** | `Tool Output Guard` | Sanitizes poisoned web content from search results mid-loop |
| **Layer 3** | `LLM Output Guard` | Moderates LLM responses (weapons, hacking, self-harm) |
| **PII** | `redact_pii()` | Masks emails, phones, SSNs, credit cards |
| **Citations** | `verify_citations()` | Flags URLs the LLM never actually accessed |
| **Rate Limit**| `rate_limit_middleware` | Token bucket API throttling (default: 60 req/min) |

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
