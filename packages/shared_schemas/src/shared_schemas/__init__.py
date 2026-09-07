"""Contracts shared across package boundaries.

This package deliberately depends on nothing but Pydantic. It is the seam
between the API, the MCP gateway and (via generated TypeScript types) the web
app, so it must stay free of database, provider and framework imports.
"""

from shared_schemas.tools import (
    TOOL_CONTRACTS,
    ToolContract,
    ToolPermission,
)

__all__ = ["TOOL_CONTRACTS", "ToolContract", "ToolPermission"]
