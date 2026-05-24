"""
Sandbox tools — executes Python code dynamically within the bounds of a session's workspace.
Supports data visualization, charting, and math operations.
"""

import os
import subprocess
from langchain_core.tools import tool
from backend.db.workspace import WorkspaceManager
from backend.core.logger import get_logger

logger = get_logger(__name__)
_ws = WorkspaceManager()

def get_sandbox_tools(session_id: str) -> list:
    """Return sandbox tools bound to a specific session workspace."""

    @tool
    def execute_code_agent_task(code: str, filename: str = "agent_task.py") -> str:
        """
        Smolagents-style Code-Driven Execution Sandbox.
        Write a complete Python script to systematically derive an answer, download data, or analyze logic.
        You MUST print() the final answer to standard output so it can be captured by the orchestrator.
        If generating charts, save them to the local directory (e.g., 'chart.png').
        """
        try:
            # Enforce clean filename and ensure workspace exists
            if "/" in filename or "\\" in filename:
                return "Error: filename must be a flat string without directories."
                
            # Write the code to the workspace
            _ws.write_file(session_id, filename, code)
            
            # Resolve the absolute path to the workspace
            workspace_dir = _ws.get_workspace_path(session_id)
            script_path = os.path.join(workspace_dir, filename)
            
            logger.info("executing_python_script", session_id=session_id, filename=filename)
            
            # Execute in a subprocess with a timeout to prevent infinite loops (30s)
            result = subprocess.run(
                ["python", script_path],
                cwd=workspace_dir,  # Execute strictly inside the workspace
                capture_output=True,
                text=True,
                timeout=30.0
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
            return f"Error executing script: {e}"

    return [execute_code_agent_task]
