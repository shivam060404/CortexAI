

## 🔍 Overview

Deep Research is an advanced research assistant that leverages multiple specialized AI agents to perform comprehensive research on any topic. The system uses a LangGraph workflow to coordinate different agents, each with specific research capabilities, to gather, analyze, and synthesize information into coherent research reports.

### Key Features

- **Multi-Agent Architecture**: Specialized agents for different research tasks (scoping, web search, academic research, news analysis, etc.)
- **Real-time Updates**: WebSocket-based streaming of research progress and agent activities
- **Interactive Clarification**: System can request clarification when needed to refine research scope
- **Comprehensive Research**: Gathers information from multiple sources with credibility and relevance scoring
- **Automated Analysis**: Synthesizes findings and extracts key insights
- **Report Generation**: Creates well-structured research reports with proper citations

### 🚀 Advanced Agentic Capabilities

- **Python Execution Sandbox**: Secure, timeout-bound environment for the agent to run Python scripts, perform statistical analysis, and render Matplotlib charts directly in the workspace.
- **Multi-Agent Debate Engine**: Eliminates confirmation bias by spawning Defender and Skeptic sub-agents to rigorously debate nuanced topics over multiple rounds before synthesizing a conclusion.
- **Background Watcher**: Asynchronous APScheduler integration allowing the agent to wake up periodically, perform incremental research, and update knowledge graphs without user intervention.
- **Global Institutional Memory**: Advanced Knowledge Graph integration that persists facts across user sessions, creating a permanent, shared institutional memory.
- **Automated PPTX Deliverables**: Automatically converts comprehensive markdown research reports into corporate-ready PowerPoint presentations.

### 🛡️ 3-Layer Security & Guardrails (OWASP LLM Top 10 Protected)

- **Layer 1 (Input Guard)**: Scans and neutralizes malicious user inputs at the WebSocket entry point before they reach the LLM.
- **Layer 2 (Tool Output Guard)**: Detects and sanitizes indirect prompt injections from scraped web content during the research loop.
- **Layer 3 (LLM Output Guard)**: Moderates the AI's generated responses to block harmful content categories (weapons, illegal acts, self-harm) before streaming to the user.
- **Additional Defenses**: Real-time PII Redaction, URL Citation Verification (prevents hallucinated links), and Semantic Scope Drift Detection.

## 🏗️ Architecture

### Backend

- **FastAPI Framework**: High-performance API with async support
- **LangGraph Workflow**: Orchestrates the multi-agent research process
- **Mistral AI Integration**: Powers the language models for different agents
- **WebSocket Communication**: Enables real-time updates and streaming responses

### Frontend

- **steamlit**
- **Zustand**: State management for research data and UI state
- **WebSocket Client**: Real-time communication with the backend


## 🧩 Components

### Agent Types

- **Scoping Agent**: Clarifies user intent and defines research parameters
- **Supervisor Agent**: Plans research strategy and coordinates specialist agents
- **Research Agents**: Specialized for different sources (web, academic, news)
- **Analyzer Agent**: Synthesizes findings and extracts insights
- **Writer Agent**: Creates comprehensive research reports

### Workflow

1. User submits a research query
2. Scoping agent clarifies intent and requirements
3. Supervisor plans research and assigns tasks to specialist agents
4. Research agents gather information from various sources
5. Analyzer synthesizes findings and extracts key insights
6. Writer creates a comprehensive research report
7. Results are presented to the user with citations and sources

## 🚀 Getting Started

### Prerequisites

- Python 3.9+
- Node.js 18+
- API keys for:
  - Mistral AI
  - Tavily (for search capabilities)

### Backend Setup

1. Clone the repository
2. Navigate to the backend directory
3. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
4. Install dependencies:
   ```bash
   pip install -r backend-requirements.txt
   ```
5. Create a `.env` file with your API keys:
   ```
   MISTRAL_API_KEY=your_mistral_api_key_here
   TAVILY_API_KEY=your_tavily_api_key_here
   ```
6. Start the backend server:
   ```bash
   uvicorn backend.backend-main:app --reload
   ```
   ```

## 🧪 Usage

1. Open your browser and navigate to `http://localhost:3000`
2. Enter a research query in the chat interface
3. The system will begin the research process, showing real-time updates
4. Respond to any clarification requests to refine the research scope
5. View the final research report when the process completes

## 🔄 State Management

### Research State

The system maintains a comprehensive state that includes:

- Research query and scope
- Active and completed tasks
- Messages between user and agents
- Collected sources with metadata
- Extracted insights and key findings
- Final research report

### WebSocket Communication

The frontend and backend communicate via WebSocket for real-time updates:

- Research progress and status
- Agent activities and messages
- Streaming responses for immediate feedback
- User responses for clarification requests

## 🛠️ Development

### Adding New Agent Types

To add a new specialist agent:

1. Define the agent type in `backend-state.py`
2. Create the agent implementation in the agents directory
3. Add the agent to the workflow in `backend-workflow.py`
4. Update the frontend to display the new agent type

### Extending Research Capabilities

To add new research capabilities:

1. Implement new tools in the tools directory
2. Add the tools to the appropriate agents
3. Update the workflow to incorporate the new capabilities

## 🙏 Acknowledgements

- [LangGraph](https://github.com/langchain-ai/langgraph) for the workflow orchestration
- [Mistral AI](https://mistral.ai/) for the language models
- [FastAPI](https://fastapi.tiangolo.com/) for the backend framework
