"""
MCP Server Registry — manages discovery, connection, and lifecycle of MCP servers.

Supports transports:
  - stdio: subprocess-based (default for local Docker Compose)
  - sse: Server-Sent Events over HTTP
  - streamable-http: HTTP-based streaming

Features:
  - Hot-reload: add/remove servers at runtime
  - Health checks with automatic reconnection
  - Configuration via mcp_servers.json manifest
"""

import json
import asyncio
import subprocess
import os
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

from backend.core.logger import get_logger
from backend.config import settings

logger = get_logger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"  # stdio | sse | streamable-http
    url: str = ""  # For sse/http transports
    enabled: bool = True
    auto_start: bool = True
    health_check_interval: int = 60  # seconds


@dataclass
class MCPServerInstance:
    """Runtime state of a connected MCP server."""
    config: MCPServerConfig
    process: Optional[subprocess.Popen] = None
    reader: Optional[asyncio.StreamReader] = None
    writer: Optional[asyncio.StreamWriter] = None
    tools: list[dict] = field(default_factory=list)
    is_connected: bool = False
    last_health_check: float = 0.0
    _request_id: int = 0

    def next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id


class MCPServerRegistry:
    """
    Manages the lifecycle of all MCP servers.
    
    Usage:
        registry = MCPServerRegistry()
        await registry.load_config("mcp_servers.json")
        await registry.start_all()
        tools = registry.get_all_tools()
        result = await registry.call_tool("search", "web_search", {"query": "test"})
        await registry.shutdown_all()
    """

    def __init__(self):
        self._servers: dict[str, MCPServerInstance] = {}
        self._lock = asyncio.Lock()

    async def load_config(self, config_path: str = None):
        """Load server configurations from the JSON manifest."""
        path = config_path or settings.MCP_SERVERS_CONFIG
        
        if not os.path.exists(path):
            logger.warning("mcp_config_not_found", path=path)
            return
        
        try:
            with open(path, "r") as f:
                data = json.load(f)
            
            servers = data.get("servers", {})
            for name, cfg in servers.items():
                server_config = MCPServerConfig(
                    name=name,
                    command=cfg.get("command", "python"),
                    args=cfg.get("args", []),
                    env=cfg.get("env", {}),
                    transport=cfg.get("transport", "stdio"),
                    url=cfg.get("url", ""),
                    enabled=cfg.get("enabled", True),
                    auto_start=cfg.get("auto_start", True),
                    health_check_interval=cfg.get("health_check_interval", 60),
                )
                self._servers[name] = MCPServerInstance(config=server_config)
            
            logger.info("mcp_config_loaded", servers=list(self._servers.keys()))
        except Exception as e:
            logger.error("mcp_config_load_failed", error=str(e))

    async def start_all(self):
        """Start all enabled MCP servers."""
        for name, instance in self._servers.items():
            if instance.config.enabled and instance.config.auto_start:
                await self._start_server(name)

    async def _start_server(self, name: str):
        """Start a single MCP server process (stdio transport)."""
        instance = self._servers.get(name)
        if not instance:
            logger.error("mcp_server_not_found", name=name)
            return

        config = instance.config

        if config.transport == "stdio":
            await self._start_stdio_server(name, instance)
        elif config.transport in ("sse", "streamable-http"):
            # For network transports, we just mark as connected
            # The server is expected to be already running
            instance.is_connected = True
            logger.info("mcp_server_connected", name=name, transport=config.transport)
        else:
            logger.error("mcp_unknown_transport", name=name, transport=config.transport)

    async def _start_stdio_server(self, name: str, instance: MCPServerInstance):
        """Start a stdio-based MCP server as a subprocess."""
        config = instance.config

        # Merge environment variables
        env = os.environ.copy()
        env.update(config.env)

        try:
            cmd = [config.command] + config.args
            logger.info("mcp_server_starting", name=name, cmd=" ".join(cmd))

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=str(Path(settings.MCP_SERVERS_CONFIG).parent) if settings.MCP_SERVERS_CONFIG else None,
            )

            instance.process = process
            instance.is_connected = True

            # Discover tools via the MCP initialize + tools/list handshake
            await self._mcp_initialize(name, instance)
            await self._discover_tools(name, instance)

            logger.info("mcp_server_started", name=name, tools_count=len(instance.tools))

        except FileNotFoundError:
            logger.error("mcp_server_command_not_found", name=name, command=config.command)
            instance.is_connected = False
        except Exception as e:
            logger.error("mcp_server_start_failed", name=name, error=str(e))
            instance.is_connected = False

    async def _send_jsonrpc(self, instance: MCPServerInstance, method: str, params: dict = None) -> dict:
        """Send a JSON-RPC 2.0 message to a stdio MCP server and read the response."""
        if not instance.process or not instance.process.stdin or not instance.process.stdout:
            raise ConnectionError(f"MCP server {instance.config.name} is not running")

        request_id = instance.next_request_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params:
            request["params"] = params

        # Encode and send
        body = json.dumps(request)
        message = f"Content-Length: {len(body)}\r\n\r\n{body}"

        instance.process.stdin.write(message.encode())
        await instance.process.stdin.drain()

        # Read response (Content-Length header + body)
        try:
            header_line = await asyncio.wait_for(
                instance.process.stdout.readline(), timeout=30.0
            )
            if not header_line:
                raise ConnectionError("MCP server closed connection")

            header = header_line.decode().strip()
            content_length = 0
            if header.startswith("Content-Length:"):
                content_length = int(header.split(":")[1].strip())

            # Read empty line separator
            await instance.process.stdout.readline()

            # Read body
            if content_length > 0:
                body_bytes = await asyncio.wait_for(
                    instance.process.stdout.readexactly(content_length), timeout=30.0
                )
                response = json.loads(body_bytes.decode())
                return response
            else:
                return {"error": "Empty response from MCP server"}

        except asyncio.TimeoutError:
            logger.error("mcp_response_timeout", server=instance.config.name, method=method)
            return {"error": "Timeout waiting for MCP response"}

    async def _mcp_initialize(self, name: str, instance: MCPServerInstance):
        """Perform the MCP initialize handshake."""
        try:
            response = await self._send_jsonrpc(instance, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {
                    "name": "CortexAI",
                    "version": "3.0.0"
                }
            })

            if "error" in response:
                logger.error("mcp_initialize_failed", name=name, error=response["error"])
                return

            # Send initialized notification
            await self._send_jsonrpc(instance, "notifications/initialized")
            logger.info("mcp_initialized", name=name, 
                       server_info=response.get("result", {}).get("serverInfo", {}))

        except Exception as e:
            logger.error("mcp_initialize_error", name=name, error=str(e))

    async def _discover_tools(self, name: str, instance: MCPServerInstance):
        """Discover available tools from an MCP server via tools/list."""
        try:
            response = await self._send_jsonrpc(instance, "tools/list")

            if "error" in response:
                logger.error("mcp_tool_discovery_failed", name=name, error=response["error"])
                return

            tools = response.get("result", {}).get("tools", [])
            instance.tools = tools
            logger.info("mcp_tools_discovered", name=name,
                       tools=[t.get("name", "?") for t in tools])

        except Exception as e:
            logger.error("mcp_tool_discovery_error", name=name, error=str(e))

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> dict:
        """Call a tool on a specific MCP server."""
        instance = self._servers.get(server_name)
        if not instance or not instance.is_connected:
            return {"error": f"MCP server '{server_name}' is not connected"}

        try:
            response = await self._send_jsonrpc(instance, "tools/call", {
                "name": tool_name,
                "arguments": arguments,
            })

            if "error" in response:
                return {"error": response["error"]}

            result = response.get("result", {})
            content = result.get("content", [])

            # Extract text content from MCP response
            text_parts = []
            for item in content:
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif item.get("type") == "image":
                    text_parts.append(f"[Image: {item.get('mimeType', 'unknown')}]")

            return {
                "result": "\n".join(text_parts),
                "is_error": result.get("isError", False),
            }

        except Exception as e:
            logger.error("mcp_tool_call_error", server=server_name, tool=tool_name, error=str(e))
            return {"error": str(e)}

    def get_all_tools(self) -> list[dict]:
        """Get all discovered tools from all connected MCP servers.
        Returns tools in a format compatible with LangChain tool binding.
        """
        all_tools = []
        for name, instance in self._servers.items():
            if instance.is_connected:
                for tool in instance.tools:
                    all_tools.append({
                        "server": name,
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "input_schema": tool.get("inputSchema", {}),
                    })
        return all_tools

    def get_server_names(self) -> list[str]:
        """Get names of all registered servers."""
        return list(self._servers.keys())

    def get_server_status(self) -> dict[str, dict]:
        """Get status of all servers for observability."""
        return {
            name: {
                "connected": instance.is_connected,
                "transport": instance.config.transport,
                "tools_count": len(instance.tools),
                "tools": [t.get("name", "?") for t in instance.tools],
                "enabled": instance.config.enabled,
            }
            for name, instance in self._servers.items()
        }

    async def shutdown_all(self):
        """Gracefully shut down all MCP servers."""
        for name, instance in self._servers.items():
            await self._shutdown_server(name, instance)
        logger.info("mcp_all_servers_shutdown")

    async def _shutdown_server(self, name: str, instance: MCPServerInstance):
        """Gracefully shut down a single MCP server."""
        try:
            if instance.process:
                instance.process.terminate()
                try:
                    await asyncio.wait_for(
                        asyncio.create_task(self._wait_process(instance.process)),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    instance.process.kill()
                    logger.warning("mcp_server_force_killed", name=name)

            instance.is_connected = False
            logger.info("mcp_server_stopped", name=name)

        except Exception as e:
            logger.error("mcp_server_shutdown_error", name=name, error=str(e))

    @staticmethod
    async def _wait_process(process):
        """Await subprocess termination."""
        while process.returncode is None:
            await asyncio.sleep(0.1)
            try:
                process.poll() if hasattr(process, 'poll') else None
            except Exception:
                break

    async def restart_server(self, name: str):
        """Restart a specific MCP server (hot-reload)."""
        instance = self._servers.get(name)
        if not instance:
            logger.error("mcp_restart_unknown_server", name=name)
            return

        await self._shutdown_server(name, instance)
        await self._start_server(name)
        logger.info("mcp_server_restarted", name=name)

    async def add_server(self, name: str, config: MCPServerConfig):
        """Dynamically add a new MCP server at runtime."""
        async with self._lock:
            self._servers[name] = MCPServerInstance(config=config)
            if config.enabled and config.auto_start:
                await self._start_server(name)
            logger.info("mcp_server_added", name=name)

    async def remove_server(self, name: str):
        """Dynamically remove an MCP server at runtime."""
        async with self._lock:
            instance = self._servers.pop(name, None)
            if instance:
                await self._shutdown_server(name, instance)
                logger.info("mcp_server_removed", name=name)

    async def hot_reload_config(self, config_path: str = None):
        """Reload MCP server configuration from disk.

        Compares the new config with the current state:
        - New servers are added and started.
        - Removed servers are shut down.
        - Changed servers are restarted with new config.
        - Unchanged servers are left alone.

        Also triggers a refresh of the tool registry if available.
        """
        path = config_path or settings.MCP_SERVERS_CONFIG

        if not os.path.exists(path):
            logger.warning("mcp_hot_reload_config_not_found", path=path)
            return {"status": "error", "message": "Config file not found"}

        try:
            with open(path, "r") as f:
                data = json.load(f)

            new_configs: dict[str, dict] = data.get("servers", {})
            old_names = set(self._servers.keys())
            new_names = set(new_configs.keys())

            added = new_names - old_names
            removed = old_names - new_names
            possibly_changed = old_names & new_names

            # Determine which existing servers have config changes
            changed = set()
            for name in possibly_changed:
                old_cfg = self._servers[name].config
                new_cfg = new_configs[name]
                if (
                    old_cfg.command != new_cfg.get("command", "python")
                    or old_cfg.args != new_cfg.get("args", [])
                    or old_cfg.transport != new_cfg.get("transport", "stdio")
                ):
                    changed.add(name)

            async with self._lock:
                # Remove servers no longer in config
                for name in removed:
                    instance = self._servers.pop(name, None)
                    if instance:
                        await self._shutdown_server(name, instance)
                    logger.info("mcp_hot_reload_removed", name=name)

                # Restart changed servers
                for name in changed:
                    instance = self._servers.pop(name, None)
                    if instance:
                        await self._shutdown_server(name, instance)
                    # Fall through to add with new config

                # Add new + changed servers
                for name in added | changed:
                    cfg = new_configs[name]
                    server_config = MCPServerConfig(
                        name=name,
                        command=cfg.get("command", "python"),
                        args=cfg.get("args", []),
                        env=cfg.get("env", {}),
                        transport=cfg.get("transport", "stdio"),
                        url=cfg.get("url", ""),
                        enabled=cfg.get("enabled", True),
                        auto_start=cfg.get("auto_start", True),
                        health_check_interval=cfg.get("health_check_interval", 60),
                    )
                    self._servers[name] = MCPServerInstance(config=server_config)
                    if server_config.enabled and server_config.auto_start:
                        await self._start_server(name)

            # Refresh tool registry
            try:
                from backend.core.tool_registry import tool_registry
                refresh_result = await tool_registry.refresh_mcp_tools(self)
                logger.info("mcp_hot_reload_tools_refreshed", **refresh_result)
            except ImportError:
                pass

            result = {
                "status": "ok",
                "added": list(added),
                "removed": list(removed),
                "changed": list(changed),
                "unchanged": list(possibly_changed - changed),
            }
            logger.info("mcp_hot_reload_complete", **result)
            return result

        except Exception as e:
            logger.error("mcp_hot_reload_error", error=str(e))
            return {"status": "error", "message": str(e)}
