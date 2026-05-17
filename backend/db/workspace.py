"""
Local filesystem workspace manager — sandboxed per-session directories.
All paths are strictly confined to WORKSPACE_ROOT/{session_id}/.
"""

import os
import re
from pathlib import Path

from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


class WorkspaceManager:
    """Sandboxed filesystem workspace per research session."""

    def __init__(self):
        self.root = Path(settings.WORKSPACE_ROOT).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _session_dir(self, session_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", str(session_id))
        d = (self.root / safe_id).resolve()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_workspace_path(self, session_id: str) -> str:
        """Public method: return the absolute path string to a session's workspace directory."""
        return str(self._session_dir(session_id))

    def _safe_path(self, session_id: str, relative_path: str) -> Path:
        """Resolve and validate path is inside session sandbox."""
        base = self._session_dir(session_id)
        target = (base / relative_path).resolve()
        if not str(target).startswith(str(base)):
            raise PermissionError(f"Path traversal blocked: {relative_path}")
        return target

    def read_file(self, session_id: str, relative_path: str) -> str:
        fp = self._safe_path(session_id, relative_path)
        if not fp.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        content = fp.read_text(encoding="utf-8")
        logger.info("workspace_read", session_id=session_id, path=relative_path, size=len(content))
        return content

    def write_file(self, session_id: str, relative_path: str, content: str) -> str:
        fp = self._safe_path(session_id, relative_path)
        if len(content.encode("utf-8")) > MAX_FILE_SIZE:
            raise ValueError(f"File too large (max {MAX_FILE_SIZE} bytes)")
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        logger.info("workspace_write", session_id=session_id, path=relative_path, size=len(content))
        return f"Written {len(content)} chars to {relative_path}"

    def edit_file(self, session_id: str, relative_path: str,
                  old_text: str, new_text: str) -> str:
        content = self.read_file(session_id, relative_path)
        if old_text not in content:
            raise ValueError(f"Target text not found in {relative_path}")
        updated = content.replace(old_text, new_text, 1)
        self.write_file(session_id, relative_path, updated)
        return f"Edited {relative_path}: replaced target text"

    def list_dir(self, session_id: str, relative_path: str = ".") -> list[dict]:
        dp = self._safe_path(session_id, relative_path)
        if not dp.is_dir():
            raise NotADirectoryError(f"Not a directory: {relative_path}")
        entries = []
        for item in sorted(dp.iterdir()):
            entries.append({
                "name": item.name,
                "is_dir": item.is_dir(),
                "size": item.stat().st_size if item.is_file() else 0,
            })
        return entries

    def grep_files(self, session_id: str, pattern: str,
                   relative_path: str = ".") -> list[dict]:
        dp = self._safe_path(session_id, relative_path)
        results = []
        compiled = re.compile(pattern, re.IGNORECASE)
        for fp in dp.rglob("*"):
            if fp.is_file() and fp.stat().st_size < MAX_FILE_SIZE:
                try:
                    for i, line in enumerate(fp.read_text(encoding="utf-8").splitlines(), 1):
                        if compiled.search(line):
                            results.append({
                                "file": str(fp.relative_to(self._session_dir(session_id))),
                                "line": i,
                                "content": line.strip(),
                            })
                except (UnicodeDecodeError, PermissionError):
                    continue
        return results[:100]  # cap results
