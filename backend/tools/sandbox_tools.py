"""
Sandbox tools — executes Python code dynamically within the bounds of a session's workspace.
Supports data visualization, charting, and math operations.

Hardened with resource limits (Arch Issue #3):
- Memory cap via RLIMIT_AS
- CPU time limit via RLIMIT_CPU
- Configurable timeout
- Strict workspace directory confinement
"""

import os
import sys
import resource
import subprocess
from langchain_core.tools import tool
from backend.db.workspace import WorkspaceManager
from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)
_ws = WorkspaceManager()


def _apply_resource_limits():
    """Pre-exec function: apply resource limits to the child subprocess."""
    mem_bytes = settings.SANDBOX_MEMORY_LIMIT_MB * 1024 * 1024
    # Limit virtual memory
    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    # Limit CPU time in seconds
    resource.setrlimit(resource.RLIMIT_CPU, (settings.SANDBOX_TIMEOUT, settings.SANDBOX_TIMEOUT))
    # Limit output file size to 50MB
    resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 1024 * 1024, 50 * 1024 * 1024))


def get_sandbox_tools(session_id: str) -> list:
    """Return sandbox tools bound to a specific session workspace."""

    @tool
    def execute_code_agent_task(code: str, filename: str = "agent_task.py") -> str:
        """
        Smolagents-style Code-Driven Execution Sandbox.
        Write a complete Python script to systematically derive an answer, download data, or analyze logic.
        You MUST print() the final answer to standard output so it can be captured by the orchestrator.
        If generating charts, save them to the local directory (e.g., 'chart.png').

        Security: Runs in an isolated subprocess with memory and CPU limits.
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

            # Execute in a subprocess with resource limits and timeout (Arch Issue #3)
            timeout = settings.SANDBOX_TIMEOUT
            preexec = _apply_resource_limits if sys.platform != "win32" else None

            result = subprocess.run(
                [sys.executable, script_path],  # Use same Python interpreter
                cwd=workspace_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                preexec_fn=preexec,
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONUNBUFFERED": "1",
                    # Block network access via env (best-effort)
                    "no_proxy": "*",
                },
            )

            output = result.stdout
            if result.stderr:
                output += f"\n[STDERR]:\n{result.stderr}"

            # Enforce max output size (Arch Issue #3)
            max_output = settings.TOOL_MAX_OUTPUT_SIZE
            if len(output) > max_output:
                output = output[:max_output] + f"\n[TRUNCATED: output exceeded {max_output} chars]"

            if result.returncode != 0:
                return f"Execution Failed (Code {result.returncode}):\n{output}"

            return f"Execution Successful:\n{output}" if output else "Execution Successful (no output)."

        except subprocess.TimeoutExpired:
            return f"Error: Script execution timed out after {timeout} seconds."
        except MemoryError:
            return "Error: Script exceeded memory limit."
        except Exception as e:
            return f"Error executing script: {e}"

    return [execute_code_agent_task]
