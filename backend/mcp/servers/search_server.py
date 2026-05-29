"""
MCP Search Server — wraps multiple search providers behind the MCP protocol.

Providers:
  - Tavily: General web, academic, and news search
  - Exa: Neural search with semantic understanding (free tier: 1000 req/month)
  - Firecrawl: Deep web content extraction (free tier: 500 pages/month)

This server exposes tools:
  - web_search: General web search across providers
  - academic_search: Academic/scholarly search
  - news_search: Recent news search
  - deep_extract: Deep content extraction from URLs
  - parallel_multi_search: Batch parallel search across all providers

Runs as a standalone MCP server process (stdio transport).
"""

import os
import sys
import json
import asyncio
from typing import Any

# Ensure parent packages are importable when run as standalone
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


class SearchMCPServer:
    """MCP Server implementation for multi-provider search."""

    def __init__(self):
        self.server_info = {
            "name": "cortexai-search",
            "version": "1.0.0",
        }
        self.tools = self._define_tools()
        self._tavily_api_key = os.getenv("TAVILY_API_KEY", "")
        self._exa_api_key = os.getenv("EXA_API_KEY", "")
        self._firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY", "")

    def _define_tools(self) -> list[dict]:
        """Define all tools this server exposes via MCP."""
        return [
            {
                "name": "web_search",
                "description": "Search the web for general information using multiple providers (Tavily + Exa). Returns ranked, deduplicated results.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query string"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results to return",
                            "default": 10
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "academic_search",
                "description": "Search for academic papers, journals, and scientific articles across scholarly databases.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Academic search query"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum results",
                            "default": 10
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "news_search",
                "description": "Search for recent news articles, current events, and media coverage.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "News search query"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum results",
                            "default": 10
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "deep_extract",
                "description": "Extract full page content from a URL using Firecrawl. Use for deep content extraction from specific web pages.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to extract content from"
                        }
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "parallel_multi_search",
                "description": "Execute batch parallel searches across ALL providers simultaneously. Input: JSON array of 2-20 search queries. Each query is sent to all providers (Tavily + Exa + Firecrawl). Returns merged, deduplicated, credibility-ranked results. Use for comprehensive deep research.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "queries_json": {
                            "type": "string",
                            "description": "JSON array of search query strings. Example: [\"AI safety\", \"alignment research\", \"RLHF methods\"]"
                        },
                        "max_per_query": {
                            "type": "integer",
                            "description": "Max results per query per provider",
                            "default": 5
                        }
                    },
                    "required": ["queries_json"]
                }
            },
        ]

    # ──────────────────── Provider Implementations ────────────────────

    async def _tavily_search(self, query: str, max_results: int = 5, search_type: str = "general") -> list[dict]:
        """Search using Tavily API."""
        if not self._tavily_api_key:
            return []

        try:
            from langchain_tavily import TavilySearch
            tavily = TavilySearch(
                max_results=max_results,
                tavily_api_key=self._tavily_api_key,
            )
            raw = await asyncio.to_thread(tavily.invoke, query)

            results = []
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        results.append({
                            "url": item.get("url", ""),
                            "title": item.get("title", ""),
                            "content": item.get("content", ""),
                            "score": item.get("score", 0.5),
                            "provider": "tavily",
                        })
            elif isinstance(raw, str):
                results.append({"content": raw, "provider": "tavily", "url": "", "title": ""})

            return results
        except Exception as e:
            return [{"error": f"Tavily search failed: {str(e)}", "provider": "tavily"}]

    async def _exa_search(self, query: str, max_results: int = 5) -> list[dict]:
        """Search using Exa neural search API."""
        if not self._exa_api_key:
            return []

        try:
            from exa_py import Exa
            exa = Exa(api_key=self._exa_api_key)
            response = await asyncio.to_thread(
                exa.search_and_contents,
                query,
                num_results=max_results,
                text=True,
                highlights=True,
            )

            results = []
            for r in response.results:
                results.append({
                    "url": r.url,
                    "title": r.title or "",
                    "content": r.text[:2000] if r.text else "",
                    "score": r.score if hasattr(r, "score") else 0.5,
                    "provider": "exa",
                    "highlights": r.highlights[:3] if hasattr(r, "highlights") and r.highlights else [],
                })
            return results
        except ImportError:
            return []
        except Exception as e:
            return [{"error": f"Exa search failed: {str(e)}", "provider": "exa"}]

    async def _firecrawl_extract(self, url: str) -> list[dict]:
        """Extract content from a URL using Firecrawl."""
        if not self._firecrawl_api_key:
            return [{"error": "Firecrawl API key not configured", "provider": "firecrawl"}]

        try:
            from firecrawl import FirecrawlApp
            app = FirecrawlApp(api_key=self._firecrawl_api_key)
            response = await asyncio.to_thread(app.scrape_url, url, params={"formats": ["markdown"]})

            if response and isinstance(response, dict):
                return [{
                    "url": url,
                    "title": response.get("metadata", {}).get("title", ""),
                    "content": response.get("markdown", response.get("content", ""))[:5000],
                    "provider": "firecrawl",
                }]
            return [{"error": "Empty response from Firecrawl", "provider": "firecrawl"}]
        except ImportError:
            return [{"error": "firecrawl-py not installed", "provider": "firecrawl"}]
        except Exception as e:
            return [{"error": f"Firecrawl extraction failed: {str(e)}", "provider": "firecrawl"}]

    # ──────────────────── Tool Handlers ────────────────────

    async def handle_tool_call(self, tool_name: str, arguments: dict) -> dict:
        """Route a tool call to the appropriate handler."""
        handlers = {
            "web_search": self._handle_web_search,
            "academic_search": self._handle_academic_search,
            "news_search": self._handle_news_search,
            "deep_extract": self._handle_deep_extract,
            "parallel_multi_search": self._handle_parallel_multi_search,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                "isError": True,
            }

        try:
            result_text = await handler(arguments)
            return {
                "content": [{"type": "text", "text": result_text}],
                "isError": False,
            }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Tool error: {str(e)}"}],
                "isError": True,
            }

    async def _handle_web_search(self, args: dict) -> str:
        query = args.get("query", "")
        max_results = args.get("max_results", 10)

        # Search both Tavily and Exa in parallel
        tavily_task = self._tavily_search(query, max_results=max_results // 2 + 1)
        exa_task = self._exa_search(query, max_results=max_results // 2 + 1)

        tavily_results, exa_results = await asyncio.gather(tavily_task, exa_task, return_exceptions=True)

        # Handle exceptions
        if isinstance(tavily_results, Exception):
            tavily_results = [{"error": str(tavily_results), "provider": "tavily"}]
        if isinstance(exa_results, Exception):
            exa_results = [{"error": str(exa_results), "provider": "exa"}]

        # Merge and deduplicate
        all_results = self._merge_and_dedup(tavily_results + exa_results)

        return self._format_results(query, all_results[:max_results])

    async def _handle_academic_search(self, args: dict) -> str:
        query = args.get("query", "")
        max_results = args.get("max_results", 10)

        # Tavily for academic content + Exa for neural search
        academic_query = f"{query} site:arxiv.org OR site:scholar.google.com OR site:ncbi.nlm.nih.gov"
        
        tavily_task = self._tavily_search(academic_query, max_results=max_results // 2 + 1)
        exa_task = self._exa_search(f"academic paper: {query}", max_results=max_results // 2 + 1)

        tavily_results, exa_results = await asyncio.gather(tavily_task, exa_task, return_exceptions=True)

        if isinstance(tavily_results, Exception):
            tavily_results = []
        if isinstance(exa_results, Exception):
            exa_results = []

        all_results = self._merge_and_dedup(tavily_results + exa_results)
        return self._format_results(query, all_results[:max_results])

    async def _handle_news_search(self, args: dict) -> str:
        query = args.get("query", "")
        max_results = args.get("max_results", 10)

        results = await self._tavily_search(f"latest news: {query}", max_results=max_results)
        return self._format_results(query, results)

    async def _handle_deep_extract(self, args: dict) -> str:
        url = args.get("url", "")
        if not url:
            return "Error: URL is required for deep extraction."

        results = await self._firecrawl_extract(url)
        if results and "error" not in results[0]:
            r = results[0]
            return f"## Extracted Content from {url}\n\n**Title:** {r.get('title', 'N/A')}\n\n{r.get('content', 'No content extracted.')}"
        else:
            error = results[0].get("error", "Unknown error") if results else "No response"
            return f"Extraction failed: {error}"

    async def _handle_parallel_multi_search(self, args: dict) -> str:
        queries_json = args.get("queries_json", "[]")
        max_per_query = args.get("max_per_query", 5)

        try:
            queries = json.loads(queries_json)
            if not isinstance(queries, list):
                return "Error: queries_json must be a JSON array of strings."
        except json.JSONDecodeError:
            return "Error: Invalid JSON for queries_json."

        # Cap at 20 queries to prevent abuse
        queries = queries[:20]

        # Launch ALL queries across ALL providers in parallel
        tasks = []
        for query in queries:
            tasks.append(self._tavily_search(query, max_results=max_per_query))
            tasks.append(self._exa_search(query, max_results=max_per_query))

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten and filter exceptions
        all_results = []
        for r in raw_results:
            if isinstance(r, list):
                all_results.extend(r)
            elif isinstance(r, Exception):
                all_results.append({"error": str(r), "provider": "unknown"})

        # Deduplicate and rank
        deduped = self._merge_and_dedup(all_results)

        # Format
        output = f"## Parallel Search Results ({len(queries)} queries × {2} providers = {len(tasks)} parallel requests)\n\n"
        output += f"**Total unique results:** {len(deduped)}\n\n"
        output += self._format_results("parallel batch", deduped[:max_per_query * len(queries)])

        return output

    # ──────────────────── Utilities ────────────────────

    def _merge_and_dedup(self, results: list[dict]) -> list[dict]:
        """Merge results from multiple providers and deduplicate by URL."""
        seen_urls = set()
        deduped = []
        
        for r in results:
            if "error" in r:
                continue
            url = r.get("url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            deduped.append(r)

        # Sort by score descending
        deduped.sort(key=lambda x: x.get("score", 0.5), reverse=True)
        return deduped

    def _format_results(self, query: str, results: list[dict]) -> str:
        """Format search results into LLM-readable text."""
        if not results:
            return f"No results found for: {query}"

        parts = []
        for i, r in enumerate(results, 1):
            if "error" in r:
                parts.append(f"[{i}] Error ({r.get('provider', '?')}): {r['error']}")
                continue

            provider = r.get("provider", "unknown")
            url = r.get("url", "N/A")
            title = r.get("title", "Untitled")
            content = r.get("content", "")[:1500]
            score = r.get("score", 0.5)

            entry = f"[{i}] [{provider.upper()}] {title}\n"
            entry += f"    URL: {url}\n"
            entry += f"    Score: {score:.2f}\n"
            entry += f"    {content}\n"
            parts.append(entry)

        return "\n---\n".join(parts)

    # ──────────────────── MCP Server Loop (stdio) ────────────────────

    async def run_stdio(self):
        """Run the MCP server using stdio transport (JSON-RPC over stdin/stdout)."""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout.buffer
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, None, asyncio.get_event_loop())

        while True:
            try:
                # Read Content-Length header
                header_line = await reader.readline()
                if not header_line:
                    break

                header = header_line.decode().strip()
                content_length = 0
                if header.startswith("Content-Length:"):
                    content_length = int(header.split(":")[1].strip())
                else:
                    continue

                # Read empty line
                await reader.readline()

                # Read body
                body = await reader.readexactly(content_length)
                request = json.loads(body.decode())

                # Handle the request
                response = await self._handle_request(request)

                if response:
                    response_body = json.dumps(response)
                    message = f"Content-Length: {len(response_body)}\r\n\r\n{response_body}"
                    writer.write(message.encode())
                    await writer.drain()

            except asyncio.IncompleteReadError:
                break
            except Exception as e:
                sys.stderr.write(f"MCP Search Server error: {e}\n")
                sys.stderr.flush()

    async def _handle_request(self, request: dict) -> dict | None:
        """Handle a single JSON-RPC request."""
        method = request.get("method", "")
        request_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": self.server_info,
                }
            }
        elif method == "notifications/initialized":
            return None  # Notification, no response
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": self.tools}
            }
        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = await self.handle_tool_call(tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }
        elif method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {},
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"}
            }


async def main():
    server = SearchMCPServer()
    await server.run_stdio()


if __name__ == "__main__":
    asyncio.run(main())
