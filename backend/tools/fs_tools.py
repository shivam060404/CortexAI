"""
Filesystem tools — sandboxed read, write, edit, list, grep.
All operations confined to the session workspace via WorkspaceManager.
"""

from langchain_core.tools import tool
from backend.db.workspace import WorkspaceManager
from backend.core.logger import get_logger

logger = get_logger(__name__)
_ws = WorkspaceManager()


def get_fs_tools(session_id: str):
    """Return filesystem tools bound to a specific session workspace."""

    @tool
    def read_file(path: str) -> str:
        """Read the contents of a file from the research workspace. Path is relative to the workspace root."""
        try:
            return _ws.read_file(session_id, path)
        except (FileNotFoundError, PermissionError) as e:
            return f"Error: {e}"

    @tool
    def write_file(path: str, content: str) -> str:
        """Write content to a file in the research workspace. Path is relative to the workspace root. Creates directories as needed."""
        try:
            return _ws.write_file(session_id, path, content)
        except (PermissionError, ValueError) as e:
            return f"Error: {e}"

    @tool
    def edit_file(path: str, old_text: str, new_text: str) -> str:
        """Edit a file by replacing old_text with new_text. Only the first occurrence is replaced."""
        try:
            return _ws.edit_file(session_id, path, old_text, new_text)
        except (FileNotFoundError, PermissionError, ValueError) as e:
            return f"Error: {e}"

    @tool
    def list_files(path: str = ".") -> str:
        """List files and directories in the workspace. Path is relative, defaults to root."""
        try:
            entries = _ws.list_dir(session_id, path)
            if not entries:
                return "Directory is empty."
            lines = []
            for e in entries:
                prefix = "📁" if e["is_dir"] else "📄"
                size = f" ({e['size']} bytes)" if not e["is_dir"] else ""
                lines.append(f"{prefix} {e['name']}{size}")
            return "\n".join(lines)
        except (NotADirectoryError, PermissionError) as e:
            return f"Error: {e}"

    @tool
    def grep_files(pattern: str, path: str = ".") -> str:
        """Search for a regex pattern in workspace files. Returns matching lines with file paths and line numbers."""
        try:
            results = _ws.grep_files(session_id, pattern, path)
            if not results:
                return "No matches found."
            lines = [f"{r['file']}:{r['line']}: {r['content']}" for r in results]
            return "\n".join(lines)
        except PermissionError as e:
            return f"Error: {e}"

    return [read_file, write_file, edit_file, list_files, grep_files]
