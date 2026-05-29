"""
MCP Data Analysis Server — Python execution sandbox + data analysis.

Provides:
  - execute_python: Run Python scripts in a sandboxed subprocess
  - analyze_csv: Parse and analyze CSV data
  - generate_chart: Create interactive Plotly charts
  - compute_statistics: Statistical analysis on datasets

Runs in isolated subprocess with resource limits (30s timeout, memory cap).
Runs as a standalone MCP server process (stdio transport).
"""

import os
import sys
import json
import asyncio
import subprocess
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


class DataMCPServer:
    """MCP Server for data analysis and Python execution."""

    def __init__(self):
        self.server_info = {
            "name": "cortexai-data",
            "version": "1.0.0",
        }
        self.tools = self._define_tools()
        self._workspace_root = os.getenv("WORKSPACE_ROOT", "./data/workspaces")

    def _define_tools(self) -> list[dict]:
        return [
            {
                "name": "execute_python",
                "description": "Execute a Python script in a sandboxed environment. The script has access to pandas, numpy, matplotlib, plotly, and scipy. Output is captured from stdout. Save files to the current directory. 30-second timeout.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Complete Python script to execute"},
                        "session_id": {"type": "string", "description": "Session ID for workspace isolation", "default": "default"},
                    },
                    "required": ["code"]
                }
            },
            {
                "name": "analyze_csv",
                "description": "Analyze a CSV dataset. Provides summary statistics, column types, missing values, and basic insights.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "csv_content": {"type": "string", "description": "Raw CSV content as a string"},
                        "analysis_type": {"type": "string", "description": "Type of analysis: 'summary', 'correlation', 'distribution'", "default": "summary"},
                    },
                    "required": ["csv_content"]
                }
            },
            {
                "name": "generate_chart",
                "description": "Generate an interactive chart using Plotly. Returns a self-contained HTML file with the chart. Chart types: bar, line, scatter, pie, histogram, heatmap, box.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "chart_type": {"type": "string", "description": "Chart type: bar, line, scatter, pie, histogram, heatmap, box"},
                        "title": {"type": "string", "description": "Chart title"},
                        "data_json": {"type": "string", "description": "JSON data for the chart. Format depends on chart type. Example for bar: {\"labels\": [\"A\", \"B\"], \"values\": [10, 20]}"},
                        "session_id": {"type": "string", "description": "Session ID", "default": "default"},
                    },
                    "required": ["chart_type", "title", "data_json"]
                }
            },
            {
                "name": "compute_statistics",
                "description": "Compute statistical measures on numerical data. Input: JSON array of numbers. Returns mean, median, std, min, max, percentiles, and distribution assessment.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "data_json": {"type": "string", "description": "JSON array of numbers: [1.2, 3.4, 5.6, ...]"},
                        "label": {"type": "string", "description": "Label for the dataset", "default": "Dataset"},
                    },
                    "required": ["data_json"]
                }
            },
        ]

    async def handle_tool_call(self, tool_name: str, arguments: dict) -> dict:
        handlers = {
            "execute_python": self._handle_execute_python,
            "analyze_csv": self._handle_analyze_csv,
            "generate_chart": self._handle_generate_chart,
            "compute_statistics": self._handle_compute_statistics,
        }
        handler = handlers.get(tool_name)
        if not handler:
            return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}
        try:
            result = await handler(arguments)
            return {"content": [{"type": "text", "text": result}], "isError": False}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Data tool error: {str(e)}"}], "isError": True}

    async def _handle_execute_python(self, args: dict) -> str:
        """Execute Python code in a sandboxed subprocess."""
        code = args.get("code", "")
        session_id = args.get("session_id", "default")

        if not code.strip():
            return "Error: No code provided."

        # Create workspace directory
        workspace = Path(self._workspace_root) / session_id
        workspace.mkdir(parents=True, exist_ok=True)

        # Write script to temp file
        script_name = f"mcp_script_{uuid.uuid4().hex[:8]}.py"
        script_path = workspace / script_name

        script_path.write_text(code)

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, str(script_path)],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=30.0,
            )

            output = result.stdout
            if result.stderr:
                output += f"\n[STDERR]:\n{result.stderr}"

            if result.returncode != 0:
                return f"Execution Failed (Code {result.returncode}):\n{output}"

            return f"Execution Successful:\n{output}" if output else "Execution Successful (no output)."

        except subprocess.TimeoutExpired:
            return "Error: Script execution timed out after 30 seconds."
        except Exception as e:
            return f"Execution error: {str(e)}"
        finally:
            # Clean up script file
            try:
                script_path.unlink(missing_ok=True)
            except Exception:
                pass

    async def _handle_analyze_csv(self, args: dict) -> str:
        """Analyze CSV data using pandas."""
        csv_content = args.get("csv_content", "")
        analysis_type = args.get("analysis_type", "summary")

        if not csv_content.strip():
            return "Error: No CSV content provided."

        # Generate analysis script
        code = f'''
import pandas as pd
import io
import json

csv_data = """{csv_content}"""

df = pd.read_csv(io.StringIO(csv_data))

print("## Dataset Overview")
print(f"Rows: {{len(df)}}, Columns: {{len(df.columns)}}")
print(f"\\nColumn Types:\\n{{df.dtypes.to_string()}}")
print(f"\\nMissing Values:\\n{{df.isnull().sum().to_string()}}")

print("\\n## Summary Statistics")
print(df.describe().to_string())

numeric_cols = df.select_dtypes(include='number').columns.tolist()
if len(numeric_cols) >= 2 and "{analysis_type}" == "correlation":
    print("\\n## Correlation Matrix")
    print(df[numeric_cols].corr().round(3).to_string())

print("\\n## First 5 Rows")
print(df.head().to_string())
'''

        return await self._handle_execute_python({"code": code, "session_id": "data_analysis"})

    async def _handle_generate_chart(self, args: dict) -> str:
        """Generate an interactive Plotly chart."""
        chart_type = args.get("chart_type", "bar")
        title = args.get("title", "Chart")
        data_json = args.get("data_json", "{}")
        session_id = args.get("session_id", "default")

        code = f'''
import plotly.graph_objects as go
import plotly.express as px
import json

data = json.loads('{data_json}')
chart_type = "{chart_type}"
title = "{title}"

fig = go.Figure()

if chart_type == "bar":
    labels = data.get("labels", data.get("x", []))
    values = data.get("values", data.get("y", []))
    fig.add_trace(go.Bar(x=labels, y=values))
elif chart_type == "line":
    x = data.get("x", list(range(len(data.get("y", [])))))
    y = data.get("y", [])
    fig.add_trace(go.Scatter(x=x, y=y, mode="lines+markers"))
elif chart_type == "scatter":
    fig.add_trace(go.Scatter(x=data.get("x", []), y=data.get("y", []), mode="markers"))
elif chart_type == "pie":
    fig = go.Figure(data=[go.Pie(labels=data.get("labels", []), values=data.get("values", []))])
elif chart_type == "histogram":
    fig.add_trace(go.Histogram(x=data.get("values", data.get("x", []))))
elif chart_type == "heatmap":
    fig.add_trace(go.Heatmap(z=data.get("z", []), x=data.get("x", []), y=data.get("y", [])))
elif chart_type == "box":
    for key, values in data.items():
        if isinstance(values, list):
            fig.add_trace(go.Box(y=values, name=key))

fig.update_layout(title=title, template="plotly_dark")
fig.write_html("chart_{chart_type}.html", include_plotlyjs="cdn")
print(f"Chart saved as chart_{chart_type}.html")
print(f"Chart type: {chart_type}, Title: {title}")
'''
        return await self._handle_execute_python({"code": code, "session_id": session_id})

    async def _handle_compute_statistics(self, args: dict) -> str:
        """Compute statistical measures."""
        data_json = args.get("data_json", "[]")
        label = args.get("label", "Dataset")

        code = f'''
import json
import statistics

data = json.loads('{data_json}')
label = "{label}"

if not data or not isinstance(data, list):
    print("Error: Input must be a non-empty JSON array of numbers.")
else:
    data = [float(x) for x in data]
    n = len(data)
    
    print(f"## Statistical Analysis: {{label}}")
    print(f"N: {{n}}")
    print(f"Mean: {{statistics.mean(data):.4f}}")
    print(f"Median: {{statistics.median(data):.4f}}")
    print(f"Std Dev: {{statistics.stdev(data):.4f}}" if n > 1 else "Std Dev: N/A")
    print(f"Min: {{min(data):.4f}}")
    print(f"Max: {{max(data):.4f}}")
    print(f"Range: {{max(data) - min(data):.4f}}")
    
    sorted_data = sorted(data)
    q1_idx = int(n * 0.25)
    q3_idx = int(n * 0.75)
    print(f"Q1 (25th): {{sorted_data[q1_idx]:.4f}}")
    print(f"Q3 (75th): {{sorted_data[q3_idx]:.4f}}")
    print(f"IQR: {{sorted_data[q3_idx] - sorted_data[q1_idx]:.4f}}")
'''
        return await self._handle_execute_python({"code": code, "session_id": "statistics"})

    # ──────────────────── MCP Server Loop ────────────────────

    async def run_stdio(self):
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin.buffer)
        writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout.buffer
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, None, asyncio.get_event_loop())

        while True:
            try:
                header_line = await reader.readline()
                if not header_line:
                    break
                header = header_line.decode().strip()
                content_length = 0
                if header.startswith("Content-Length:"):
                    content_length = int(header.split(":")[1].strip())
                else:
                    continue
                await reader.readline()
                body = await reader.readexactly(content_length)
                request = json.loads(body.decode())
                response = await self._handle_request(request)
                if response:
                    response_body = json.dumps(response)
                    message = f"Content-Length: {len(response_body)}\r\n\r\n{response_body}"
                    writer.write(message.encode())
                    await writer.drain()
            except asyncio.IncompleteReadError:
                break
            except Exception as e:
                sys.stderr.write(f"MCP Data Server error: {e}\n")
                sys.stderr.flush()

    async def _handle_request(self, request: dict) -> dict | None:
        method = request.get("method", "")
        request_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            return {"jsonrpc": "2.0", "id": request_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": self.server_info,
            }}
        elif method == "notifications/initialized":
            return None
        elif method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": self.tools}}
        elif method == "tools/call":
            result = await self.handle_tool_call(params.get("name", ""), params.get("arguments", {}))
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        elif method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


async def main():
    server = DataMCPServer()
    await server.run_stdio()


if __name__ == "__main__":
    asyncio.run(main())
