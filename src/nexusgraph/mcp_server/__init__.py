"""MCP server package (read-only tool exposure over stdio/HTTP)."""

from nexusgraph.mcp_server.server import create_server, http_app, run_stdio

__all__ = ["create_server", "http_app", "run_stdio"]
