"""``travel-intelligence-mcp`` — the shared AI-facing travel capability gateway.

Architectural boundary (docs/adr/0003-mcp.md, docs/mcp.md):

This package owns the *interface*: the tool list, their JSON schemas, argument
validation and error shaping. It owns none of the implementation. Everything
behind a tool arrives through the ``TravelBackend`` protocol, which the API
application implements. That is why this package has no database, provider, or
application imports — and why the same server can be run in-process for the
agents or over stdio for an external MCP client such as Claude Desktop.

What belongs here: reusable capabilities that more than one AI consumer needs.
What does not: ordinary internal CRUD. Routing every database call through
JSON-RPC would be architecture theatre, and it is explicitly avoided.
"""

from travel_mcp.backend import TravelBackend
from travel_mcp.server import build_server, tool_names

__all__ = ["TravelBackend", "build_server", "tool_names"]
