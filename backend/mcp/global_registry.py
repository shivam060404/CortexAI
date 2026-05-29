"""
Global MCP Registry instance to be used across the application.
"""

from backend.mcp.server_registry import MCPServerRegistry
from backend.mcp.client import MCPClientAdapter

# Global instances
mcp_registry = MCPServerRegistry()
mcp_client = MCPClientAdapter(mcp_registry)
