"""
MCP (Model Context Protocol) Integration Layer.

Provides a modular, extensible tool ecosystem for CortexAI.
Tools are abstracted behind MCP servers, enabling:
- Independent development, deployment, and scaling of each tool
- Standardized interface via MCP protocol
- Security isolation between tool environments
- Hot-reload: add/remove tools without restarting the agent
"""

from backend.mcp.server_registry import MCPServerRegistry
from backend.mcp.client import MCPClientAdapter

__all__ = ["MCPServerRegistry", "MCPClientAdapter"]
