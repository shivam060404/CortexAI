"""
Custom Tool Registry (Feature Gap #10 / Task 19).

Dynamic tool registration from MCP servers at runtime.
Supports tool capability discovery, validation, and per-organization allowlists.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from backend.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ToolDefinition:
    """A registered tool with metadata and capabilities."""
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    source: str = "builtin"  # builtin | mcp | custom
    server: str = ""  # MCP server name (if source == "mcp")
    categories: list[str] = field(default_factory=list)  # search, analysis, export, etc.
    requires_approval: bool = False
    rate_limit: int = 0  # 0 = no limit
    org_allowlist: list[str] | None = None  # None = available to all orgs
    registered_at: float = field(default_factory=time.time)
    handler: Callable | None = None  # Optional direct handler reference
    is_enabled: bool = True
    version: str = "1.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def tool_id(self) -> str:
        """Unique identifier for this tool."""
        return f"{self.source}:{self.server}:{self.name}" if self.server else f"{self.source}:{self.name}"


class ToolRegistry:
    """
    Central registry for all tools available to the agent system.
    
    Manages tool lifecycle from registration through discovery, validation,
    and per-organization access control.
    
    Usage:
        registry = ToolRegistry()
        registry.register_builtin_tools()
        await registry.discover_mcp_tools(mcp_registry)
        available = registry.get_tools_for_org("org-123")
    """

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._org_allowlists: dict[str, set[str]] = {}  # org_id -> set of allowed tool names
        self._tool_usage_count: dict[str, int] = {}  # tool_id -> call count
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register(self, tool: ToolDefinition) -> str:
        """Register a tool definition. Returns the tool_id."""
        tool_id = tool.tool_id
        self._tools[tool_id] = tool
        logger.info("tool_registered", tool_id=tool_id, source=tool.source, name=tool.name)
        return tool_id

    def unregister(self, tool_id: str) -> bool:
        """Remove a tool from the registry."""
        if tool_id in self._tools:
            del self._tools[tool_id]
            logger.info("tool_unregistered", tool_id=tool_id)
            return True
        return False

    def register_builtin_tools(self):
        """Register all built-in tools from the ALLOWED_TOOLS settings."""
        from backend.config import settings

        for tool_name in settings.ALLOWED_TOOLS:
            tool = ToolDefinition(
                name=tool_name,
                description=f"Built-in tool: {tool_name}",
                source="builtin",
                categories=self._infer_category(tool_name),
            )
            self.register(tool)

    async def discover_mcp_tools(self, mcp_registry) -> list[str]:
        """Discover and register tools from all connected MCP servers.
        
        Args:
            mcp_registry: An MCPServerRegistry instance.
            
        Returns:
            List of newly registered tool IDs.
        """
        new_tools = []
        all_mcp_tools = mcp_registry.get_all_tools()

        for mcp_tool in all_mcp_tools:
            tool = ToolDefinition(
                name=mcp_tool.get("name", ""),
                description=mcp_tool.get("description", ""),
                input_schema=mcp_tool.get("input_schema", {}),
                source="mcp",
                server=mcp_tool.get("server", ""),
                categories=["mcp"],
            )
            tool_id = tool.tool_id
            if tool_id not in self._tools:
                self.register(tool)
                new_tools.append(tool_id)

        logger.info("mcp_tools_discovered", total=len(all_mcp_tools), new=len(new_tools))
        return new_tools

    # ------------------------------------------------------------------
    # Discovery & Query
    # ------------------------------------------------------------------
    def get_tool(self, tool_id: str) -> ToolDefinition | None:
        """Get a tool by its ID."""
        return self._tools.get(tool_id)

    def get_tool_by_name(self, name: str) -> ToolDefinition | None:
        """Get a tool by name (first match across all sources)."""
        for tool in self._tools.values():
            if tool.name == name and tool.is_enabled:
                return tool
        return None

    def get_all_tools(self) -> list[ToolDefinition]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_enabled_tools(self) -> list[ToolDefinition]:
        """Get all enabled tools."""
        return [t for t in self._tools.values() if t.is_enabled]

    def get_tools_by_source(self, source: str) -> list[ToolDefinition]:
        """Get tools by source type (builtin, mcp, custom)."""
        return [t for t in self._tools.values() if t.source == source]

    def get_tools_by_category(self, category: str) -> list[ToolDefinition]:
        """Get tools by category."""
        return [t for t in self._tools.values() if category in t.categories]

    def get_tools_for_org(self, org_id: str) -> list[ToolDefinition]:
        """Get tools available to a specific organization.
        
        If an org has an explicit allowlist, only those tools are returned.
        Otherwise, all enabled tools without org restrictions are available.
        """
        org_allowed = self._org_allowlists.get(org_id)

        result = []
        for tool in self._tools.values():
            if not tool.is_enabled:
                continue
            # Check org-specific allowlist on the tool definition
            if tool.org_allowlist is not None and org_id not in tool.org_allowlist:
                continue
            # Check org-level allowlist
            if org_allowed is not None and tool.name not in org_allowed:
                continue
            result.append(tool)
        return result

    def search_tools(self, query: str) -> list[ToolDefinition]:
        """Search tools by name or description."""
        query_lower = query.lower()
        return [
            t for t in self._tools.values()
            if query_lower in t.name.lower() or query_lower in t.description.lower()
        ]

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate_tool_input(self, tool_name: str, input_data: dict) -> tuple[bool, str]:
        """Validate input data against a tool's schema.
        
        Returns (is_valid, error_message).
        """
        tool = self.get_tool_by_name(tool_name)
        if not tool:
            return False, f"Tool '{tool_name}' not found"
        if not tool.is_enabled:
            return False, f"Tool '{tool_name}' is disabled"
        if not tool.input_schema:
            return True, ""  # No schema to validate against

        # Basic JSON schema validation (required fields)
        required = tool.input_schema.get("required", [])
        properties = tool.input_schema.get("properties", {})
        missing = [f for f in required if f not in input_data]
        if missing:
            return False, f"Missing required fields: {', '.join(missing)}"

        # Type checking for provided fields
        for field_name, field_value in input_data.items():
            if field_name in properties:
                expected_type = properties[field_name].get("type")
                if expected_type and not self._check_type(field_value, expected_type):
                    return False, f"Field '{field_name}' expected type '{expected_type}'"

        return True, ""

    @staticmethod
    def _check_type(value: Any, expected_type: str) -> bool:
        """Basic JSON Schema type checking."""
        type_map = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
            "null": type(None),
        }
        py_type = type_map.get(expected_type)
        if py_type is None:
            return True  # Unknown type, skip check
        return isinstance(value, py_type)

    # ------------------------------------------------------------------
    # Organization Allowlists
    # ------------------------------------------------------------------
    def set_org_allowlist(self, org_id: str, tool_names: list[str]) -> None:
        """Set the allowed tools for an organization."""
        self._org_allowlists[org_id] = set(tool_names)
        logger.info("org_allowlist_set", org_id=org_id, tools_count=len(tool_names))

    def get_org_allowlist(self, org_id: str) -> list[str]:
        """Get the allowed tool names for an organization."""
        return list(self._org_allowlists.get(org_id, []))

    def remove_org_allowlist(self, org_id: str) -> None:
        """Remove org-level allowlist (reverts to default access)."""
        self._org_allowlists.pop(org_id, None)

    # ------------------------------------------------------------------
    # Usage Tracking
    # ------------------------------------------------------------------
    def record_usage(self, tool_id: str) -> None:
        """Record a tool invocation for usage tracking."""
        self._tool_usage_count[tool_id] = self._tool_usage_count.get(tool_id, 0) + 1

    def get_usage_stats(self) -> dict[str, int]:
        """Get usage counts for all tools."""
        return dict(self._tool_usage_count)

    # ------------------------------------------------------------------
    # Hot-Reload Support
    # ------------------------------------------------------------------
    async def refresh_mcp_tools(self, mcp_registry) -> dict:
        """Re-discover MCP tools, removing stale ones and adding new ones.
        
        Called when MCP config changes are detected.
        """
        # Remove old MCP tools
        old_mcp_tools = [tid for tid, t in self._tools.items() if t.source == "mcp"]
        for tid in old_mcp_tools:
            self.unregister(tid)

        # Re-discover
        new_tools = await self.discover_mcp_tools(mcp_registry)

        return {
            "removed": len(old_mcp_tools),
            "added": len(new_tools),
            "new_tool_ids": new_tools,
        }

    # ------------------------------------------------------------------
    # Status & Introspection
    # ------------------------------------------------------------------
    def get_status(self) -> dict:
        """Get registry status for observability."""
        by_source: dict[str, int] = {}
        for tool in self._tools.values():
            by_source[tool.source] = by_source.get(tool.source, 0) + 1

        return {
            "total_tools": len(self._tools),
            "enabled_tools": len(self.get_enabled_tools()),
            "by_source": by_source,
            "org_allowlists": len(self._org_allowlists),
            "tools": [
                {"id": t.tool_id, "name": t.name, "source": t.source, "enabled": t.is_enabled}
                for t in self._tools.values()
            ],
        }

    @staticmethod
    def _infer_category(tool_name: str) -> list[str]:
        """Infer tool category from its name."""
        name = tool_name.lower()
        if any(k in name for k in ("search", "query", "find", "grep")):
            return ["search"]
        if any(k in name for k in ("export", "pdf", "docx", "presentation")):
            return ["export"]
        if any(k in name for k in ("file", "read", "write", "edit", "list")):
            return ["filesystem"]
        if any(k in name for k in ("spawn", "subagent", "delegate")):
            return ["orchestration"]
        if any(k in name for k in ("reflect", "evaluate", "verify")):
            return ["analysis"]
        if any(k in name for k in ("knowledge", "graph", "extract")):
            return ["knowledge"]
        return ["general"]


# Module-level singleton
tool_registry = ToolRegistry()
