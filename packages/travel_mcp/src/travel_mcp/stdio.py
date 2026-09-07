"""stdio entry point for external MCP clients.

Registered as the ``travel-intelligence-mcp`` console script. This is what an
external consumer (Claude Desktop, another agent runtime, an internal tool)
connects to. The backend factory is resolved lazily by import path so this
package still has no build-time dependency on the API application.

    travel-intelligence-mcp
    JST_MCP_BACKEND=jst_api.services.mcp_backend:build_backend travel-intelligence-mcp
"""

from __future__ import annotations

import importlib
import os
import sys

DEFAULT_BACKEND = "jst_api.services.mcp_backend:build_backend"


def _load_backend():
    spec = os.environ.get("JST_MCP_BACKEND", DEFAULT_BACKEND)
    module_name, _, attr = spec.partition(":")
    if not attr:
        raise SystemExit(f"JST_MCP_BACKEND must be 'module:factory', got {spec!r}")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:  # pragma: no cover - deployment misconfiguration
        raise SystemExit(
            f"Could not import MCP backend '{module_name}': {exc}\n"
            "Install the API package (pip install -e backend) or set JST_MCP_BACKEND."
        ) from exc
    return getattr(module, attr)()


def main() -> None:
    backend = _load_backend()
    from travel_mcp.server import build_server

    server = build_server(backend)
    print(
        f"travel-intelligence-mcp starting on stdio ({len(server._tool_manager.list_tools())} tools)",
        file=sys.stderr,
    )
    server.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
