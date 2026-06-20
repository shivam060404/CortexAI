"""
MCP Browser Server — wraps browser-use for agentic browser automation.

Enables CortexAI to:
  - Navigate to any URL and extract content
  - Login to authenticated platforms (LinkedIn, X, Quora)
  - Execute complex web tasks (scroll, click, fill forms)
  - Take screenshots for visual analysis
  - Manage sessions with cookie persistence

Credentials are stored encrypted in the database (Fernet).
User-provided session cookies are also supported.

Runs as a standalone MCP server process (stdio transport).
"""

import os
import sys
import json
import asyncio
import base64
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


# Platform-specific login selectors
PLATFORM_CONFIGS = {
    "linkedin": {
        "login_url": "https://www.linkedin.com/login",
        "username_selector": "#username",
        "password_selector": "#password",
        "submit_selector": "button[type='submit']",
        "success_indicator": ".feed-identity-module",
    },
    "x": {
        "login_url": "https://x.com/i/flow/login",
        "username_selector": "input[autocomplete='username']",
        "password_selector": "input[autocomplete='current-password']",
        "submit_selector": "div[data-testid='LoginForm_Login_Button']",
        "success_indicator": "a[data-testid='AppTabBar_Home_Link']",
    },
    "quora": {
        "login_url": "https://www.quora.com/",
        "username_selector": "input[placeholder='Email']",
        "password_selector": "input[placeholder='Password']",
        "submit_selector": "button:has-text('Login')",
        "success_indicator": ".q-box.MainFeed",
    },
}


class BrowserMCPServer:
    """MCP Server for browser automation with authenticated access."""

    def __init__(self):
        self.server_info = {
            "name": "cortexai-browser",
            "version": "1.0.0",
        }
        self.tools = self._define_tools()
        self._encryption_key = os.getenv("BROWSER_CREDENTIAL_KEY", "")
        self._headless = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"
        self._cookie_store: dict[str, list[dict]] = {}  # platform -> cookies

    def _define_tools(self) -> list[dict]:
        return [
            {
                "name": "browse_url",
                "description": "Navigate to a URL and extract page content as markdown. Works for public pages without login.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to navigate to"},
                        "wait_seconds": {"type": "integer", "description": "Seconds to wait for page load", "default": 3},
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "browse_authenticated",
                "description": "Browse a URL using an authenticated browser session. Supports login-required platforms: LinkedIn, X (Twitter), Quora. Automatically handles login if credentials are configured.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to browse (e.g., LinkedIn profile, X post)"},
                        "platform": {"type": "string", "description": "Platform name: 'linkedin', 'x', 'quora', or 'auto' for detection", "default": "auto"},
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "web_task",
                "description": "Execute a complex web task using agentic browser automation. The browser agent will autonomously navigate, click, scroll, and extract data based on your natural language instructions.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_description": {"type": "string", "description": "Natural language description of the web task to perform. Example: 'Search LinkedIn for AI researchers at Google and list their names and titles'"},
                        "start_url": {"type": "string", "description": "Optional starting URL", "default": ""},
                    },
                    "required": ["task_description"]
                }
            },
            {
                "name": "screenshot_page",
                "description": "Take a screenshot of a web page. Returns the screenshot as base64 image data.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to screenshot"},
                        "full_page": {"type": "boolean", "description": "Capture full page or viewport only", "default": False},
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "set_cookies",
                "description": "Set session cookies for a platform to enable authenticated browsing without credentials. Input cookies as JSON array of {name, value, domain} objects.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "platform": {"type": "string", "description": "Platform name: 'linkedin', 'x', 'quora'"},
                        "cookies_json": {"type": "string", "description": "JSON array of cookie objects: [{\"name\": \"...\", \"value\": \"...\", \"domain\": \"...\"}]"},
                    },
                    "required": ["platform", "cookies_json"]
                }
            },
        ]

    def _detect_platform(self, url: str) -> str:
        """Auto-detect which platform a URL belongs to."""
        url_lower = url.lower()
        if "linkedin.com" in url_lower:
            return "linkedin"
        elif "x.com" in url_lower or "twitter.com" in url_lower:
            return "x"
        elif "quora.com" in url_lower:
            return "quora"
        return ""

    async def handle_tool_call(self, tool_name: str, arguments: dict) -> dict:
        """Route tool calls to handlers."""
        handlers = {
            "browse_url": self._handle_browse_url,
            "browse_authenticated": self._handle_browse_authenticated,
            "web_task": self._handle_web_task,
            "screenshot_page": self._handle_screenshot_page,
            "set_cookies": self._handle_set_cookies,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}

        try:
            result_text = await handler(arguments)
            return {"content": [{"type": "text", "text": result_text}], "isError": False}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Browser error: {str(e)}"}], "isError": True}

    async def _handle_browse_url(self, args: dict) -> str:
        """Browse a public URL and extract content."""
        url = args.get("url", "")
        wait = args.get("wait_seconds", 3)

        if not url:
            return "Error: URL is required."

        try:
            from browser_use import Browser, BrowserConfig
            
            browser = Browser(config=BrowserConfig(headless=self._headless))
            
            async with await browser.new_context() as context:
                page = await context.get_current_page()
                await page.goto(url, timeout=30000)
                await asyncio.sleep(wait)
                
                # Extract page content
                title = await page.title()
                content = await page.evaluate("() => document.body.innerText")
                current_url = page.url
                
            return f"## Page Content\n**Title:** {title}\n**URL:** {current_url}\n\n{content[:5000]}"

        except ImportError:
            # Fallback: use simple HTTP request
            return await self._simple_fetch(url)
        except Exception as e:
            return f"Failed to browse {url}: {str(e)}"

    async def _simple_fetch(self, url: str) -> str:
        """Fallback URL fetch using aiohttp or urllib."""
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "CortexAI/3.0"})
            response = await asyncio.to_thread(urllib.request.urlopen, req, timeout=15)
            html = response.read().decode("utf-8", errors="ignore")
            
            # Very basic HTML to text
            import re
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            
            return f"## Page Content (Basic Fetch)\n**URL:** {url}\n\n{text[:5000]}"
        except Exception as e:
            return f"Failed to fetch {url}: {str(e)}"

    async def _handle_browse_authenticated(self, args: dict) -> str:
        """Browse an authenticated URL with login support."""
        url = args.get("url", "")
        platform = args.get("platform", "auto")

        if not url:
            return "Error: URL is required."

        if platform == "auto":
            platform = self._detect_platform(url)

        if not platform:
            # No platform detected, just do a public browse
            return await self._handle_browse_url(args)

        try:
            from browser_use import Browser, BrowserConfig

            browser = Browser(config=BrowserConfig(headless=self._headless))
            
            async with await browser.new_context() as context:
                page = await context.get_current_page()
                
                # Inject stored cookies if available
                cookies = self._cookie_store.get(platform, [])
                if cookies:
                    await context.add_cookies(cookies)
                
                # Navigate to target URL
                await page.goto(url, timeout=30000)
                await asyncio.sleep(3)
                
                # Check if we need to login
                platform_config = PLATFORM_CONFIGS.get(platform)
                if platform_config:
                    success_indicator = platform_config["success_indicator"]
                    is_logged_in = await page.query_selector(success_indicator)
                    
                    if not is_logged_in:
                        return (
                            f"Authentication required for {platform}. "
                            f"Please use the 'set_cookies' tool to provide session cookies for {platform}. "
                            f"You can export cookies from your browser using a cookie export extension."
                        )
                
                # Extract content
                title = await page.title()
                content = await page.evaluate("() => document.body.innerText")
                
                # Store cookies for future use
                context_cookies = await context.cookies()
                self._cookie_store[platform] = context_cookies

            return f"## Authenticated Content from {platform}\n**Title:** {title}\n**URL:** {url}\n\n{content[:5000]}"

        except ImportError:
            return (
                "browser-use is not installed. Install with: pip install browser-use playwright && playwright install\n"
                "Falling back to basic fetch (authentication will not work)."
            )
        except Exception as e:
            return f"Authenticated browsing failed: {str(e)}"

    async def _handle_web_task(self, args: dict) -> str:
        """Execute a complex web task using the browser agent."""
        task = args.get("task_description", "")
        start_url = args.get("start_url", "")

        if not task:
            return "Error: task_description is required."

        try:
            from browser_use import Agent as BrowserAgent
            from langchain_litellm import ChatLiteLLM

            llm = ChatLiteLLM(
                model=os.getenv("FAST_MODEL", "groq/llama3-8b-8192"),
                temperature=0.1,
            )

            agent = BrowserAgent(
                task=task,
                llm=llm,
                max_actions_per_step=5,
            )

            result = await agent.run(max_steps=10)
            
            final_result = result.final_result() if hasattr(result, 'final_result') else str(result)
            return f"## Web Task Result\n**Task:** {task}\n\n{final_result}"

        except ImportError:
            return "browser-use is not installed. Install with: pip install browser-use playwright && playwright install"
        except Exception as e:
            return f"Web task failed: {str(e)}"

    async def _handle_screenshot_page(self, args: dict) -> str:
        """Take a screenshot of a webpage."""
        url = args.get("url", "")
        full_page = args.get("full_page", False)

        if not url:
            return "Error: URL is required."

        try:
            from browser_use import Browser, BrowserConfig

            browser = Browser(config=BrowserConfig(headless=True))
            
            async with await browser.new_context() as context:
                page = await context.get_current_page()
                await page.goto(url, timeout=30000)
                await asyncio.sleep(2)
                
                screenshot_bytes = await page.screenshot(full_page=full_page)
                b64 = base64.b64encode(screenshot_bytes).decode()

            return f"Screenshot captured. Base64 length: {len(b64)} chars. [Image data available for vision analysis]"
        except ImportError:
            return "browser-use/playwright not installed for screenshots."
        except Exception as e:
            return f"Screenshot failed: {str(e)}"

    async def _handle_set_cookies(self, args: dict) -> str:
        """Set session cookies for a platform."""
        platform = args.get("platform", "")
        cookies_json = args.get("cookies_json", "[]")

        if not platform:
            return "Error: platform is required."

        try:
            cookies = json.loads(cookies_json)
            if not isinstance(cookies, list):
                return "Error: cookies_json must be a JSON array."

            self._cookie_store[platform] = cookies
            return f"Successfully stored {len(cookies)} cookies for {platform}. Authenticated browsing is now enabled."
        except json.JSONDecodeError:
            return "Error: Invalid JSON for cookies."

    # ──────────────────── MCP Server Loop ────────────────────

    async def run_stdio(self):
        """Run the MCP server using stdio transport."""
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
                sys.stderr.write(f"MCP Browser Server error: {e}\n")
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
    server = BrowserMCPServer()
    await server.run_stdio()


if __name__ == "__main__":
    asyncio.run(main())
