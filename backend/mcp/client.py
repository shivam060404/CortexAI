"""
MCP Client Adapter — bridges MCP tools into LangChain @tool-compatible wrappers.

Converts MCP tool schemas (JSON Schema) into LangChain tools that the
LangGraph agent can call natively. This allows MCP-provided tools to be
used alongside built-in tools seamlessly.
"""

import asyncio
import json
from typing import Any
from functools import partial

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from backend.mcp.server_registry import MCPServerRegistry
from backend.core.logger import get_logger

logger = get_logger(__name__)


def _json_schema_to_pydantic_fields(schema: dict) -> dict:
    """Convert a JSON Schema 'properties' dict into Pydantic field definitions.
    
    Returns a dict of {field_name: (type, Field)} suitable for create_model().
    """
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields = {}

    type_map = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    for name, prop in properties.items():
        json_type = prop.get("type", "string")
        py_type = type_map.get(json_type, str)
        description = prop.get("description", "")
        default = prop.get("default", ...)

        if name in required:
            fields[name] = (py_type, Field(description=description))
        else:
            fields[name] = (py_type, Field(default=default, description=description))

    return fields


def _create_mcp_tool(
    registry: MCPServerRegistry,
    server_name: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict,
) -> StructuredTool:
    """Create a LangChain StructuredTool that delegates to an MCP server.
    
    The tool's args_schema is dynamically generated from the MCP tool's
    JSON Schema, allowing the LLM to call it with proper argument validation.
    """
    # Generate a Pydantic model from the JSON Schema
    fields = _json_schema_to_pydantic_fields(input_schema)
    
    # Create unique model name to avoid collisions
    model_name = f"MCP_{server_name}_{tool_name}_Args"
    
    if fields:
        ArgsModel = create_model(model_name, **fields)
    else:
        # Fallback for tools with no parameters
        ArgsModel = create_model(model_name, query=(str, Field(default="", description="Input query")))

    # Namespaced tool name to avoid collisions with built-in tools
    namespaced_name = f"mcp_{server_name}_{tool_name}"

    async def _call_mcp_tool(**kwargs) -> str:
        """Async wrapper that calls the MCP server tool."""
        try:
            result = await registry.call_tool(server_name, tool_name, kwargs)
            
            if "error" in result:
                error_msg = result["error"]
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", str(error_msg))
                logger.error("mcp_tool_call_error", 
                           server=server_name, tool=tool_name, error=error_msg)
                return f"Error from MCP server '{server_name}': {error_msg}"
            
            raw_result = result.get("result", "No result returned from MCP server.")
            
            # Format as Graph Node schema for Context Graph ingestion
            node_payload = {
                "type": "MCPToolResult",
                "server": server_name,
                "tool": tool_name,
                "data": raw_result
            }
            
            # If it's a search result with URLs, tag it as a Source
            if server_name == "search_server" or isinstance(raw_result, dict) and "url" in str(raw_result).lower():
                node_payload["type"] = "Source"
                
            return json.dumps(node_payload)
            
        except Exception as e:
            logger.error("mcp_tool_call_exception",
                       server=server_name, tool=tool_name, error=str(e))
            return json.dumps({"type": "Error", "data": f"MCP tool call failed: {str(e)}"})

    # Build the StructuredTool
    tool = StructuredTool(
        name=namespaced_name,
        description=f"[MCP:{server_name}] {tool_description}",
        func=None,  # We only use async
        coroutine=_call_mcp_tool,
        args_schema=ArgsModel,
    )

    return tool


class MCPClientAdapter:
    """
    Adapts MCP server tools into LangChain-compatible tools.
    
    Usage:
        registry = MCPServerRegistry()
        await registry.load_config()
        await registry.start_all()
        
        adapter = MCPClientAdapter(registry)
        langchain_tools = adapter.get_langchain_tools()
        # These tools can be passed directly to llm.bind_tools(langchain_tools)
    """

    def __init__(self, registry: MCPServerRegistry):
        self.registry = registry
        self._tools_cache: list[StructuredTool] = []
        self._cache_valid = False

    def get_langchain_tools(self) -> list[StructuredTool]:
        """Convert all discovered MCP tools into LangChain StructuredTools.
        
        Returns a list of tools that can be merged with built-in tools and
        passed to llm.bind_tools().
        """
        if self._cache_valid and self._tools_cache:
            return self._tools_cache

        mcp_tools_metadata = self.registry.get_all_tools()
        langchain_tools = []

        for tool_meta in mcp_tools_metadata:
            try:
                tool = _create_mcp_tool(
                    registry=self.registry,
                    server_name=tool_meta["server"],
                    tool_name=tool_meta["name"],
                    tool_description=tool_meta["description"],
                    input_schema=tool_meta.get("input_schema", {}),
                )
                langchain_tools.append(tool)
                logger.debug("mcp_tool_registered",
                           server=tool_meta["server"],
                           tool=tool_meta["name"])

            except Exception as e:
                logger.error("mcp_tool_creation_failed",
                           server=tool_meta["server"],
                           tool=tool_meta["name"],
                           error=str(e))

        self._tools_cache = langchain_tools
        self._cache_valid = True

        logger.info("mcp_tools_loaded", count=len(langchain_tools),
                   names=[t.name for t in langchain_tools])

        return langchain_tools

    def invalidate_cache(self):
        """Force re-discovery of MCP tools on next call."""
        self._cache_valid = False
        self._tools_cache = []

    def get_tool_by_name(self, name: str) -> StructuredTool | None:
        """Look up a specific MCP tool by its namespaced name."""
        tools = self.get_langchain_tools()
        for tool in tools:
            if tool.name == name:
                return tool
        return None

    def get_tools_for_server(self, server_name: str) -> list[StructuredTool]:
        """Get all LangChain tools from a specific MCP server."""
        prefix = f"mcp_{server_name}_"
        return [t for t in self.get_langchain_tools() if t.name.startswith(prefix)]
