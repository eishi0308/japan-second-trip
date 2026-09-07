"""In-process MCP client session.

The agents talk to the gateway over a *real* MCP session — JSON-RPC initialise,
tools/list, tools/call — carried on in-memory streams rather than a subprocess.

That matters: it means argument validation, output-schema validation, and error
shaping are the protocol's, not a helpful wrapper's. A tool call from the
WhereNext graph goes through exactly the same code path as a tool call from
Claude Desktop over stdio. The only difference is the transport.
"""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import anyio
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from travel_mcp.backend import TravelBackend
from travel_mcp.server import build_server


class McpToolError(RuntimeError):
    """A tool call was rejected or failed inside the gateway."""

    def __init__(self, tool: str, message: str) -> None:
        super().__init__(f"{tool}: {message}")
        self.tool = tool
        self.message = message


@dataclass
class McpCallResult:
    tool: str
    data: dict[str, Any]
    is_error: bool = False
    raw_text: str | None = None


class TravelMcpSession:
    """Async context manager owning one connected client/server pair.

    Usage::

        async with TravelMcpSession(backend) as mcp:
            out = await mcp.call("search_transport", {"from_place": "Sendai", ...})
    """

    def __init__(self, backend: TravelBackend, *, name: str = "travel-intelligence-mcp") -> None:
        self._server = build_server(backend, name=name)
        self._stack: Any = None
        self._task_group: anyio.abc.TaskGroup | None = None
        self._session: ClientSession | None = None
        self._streams_cm: Any = None
        self._session_cm: Any = None

    async def __aenter__(self) -> TravelMcpSession:
        self._streams_cm = create_client_server_memory_streams()
        client_streams, server_streams = await self._streams_cm.__aenter__()
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()

        low = self._server._lowlevel_server
        init_options = low.create_initialization_options()

        async def _serve() -> None:
            await low.run(
                server_streams[0],
                server_streams[1],
                init_options,
                raise_exceptions=False,
            )

        self._task_group.start_soon(_serve)

        self._session_cm = ClientSession(client_streams[0], client_streams[1])
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        try:
            if self._session_cm is not None:
                await self._session_cm.__aexit__(exc_type, exc, tb)
        finally:
            # Tearing down memory streams can race with the server task's own
            # cancellation; neither failure is actionable and neither should mask
            # the exception the caller is already unwinding with.
            if self._task_group is not None:
                self._task_group.cancel_scope.cancel()
                with suppress(Exception):  # pragma: no cover - shutdown race
                    await self._task_group.__aexit__(None, None, None)
            if self._streams_cm is not None:
                with suppress(Exception):  # pragma: no cover - shutdown race
                    await self._streams_cm.__aexit__(None, None, None)
        return False

    def _require_session(self) -> ClientSession:
        """Return the live session, or fail clearly outside the context manager.

        Returns it rather than just checking, so callers get a non-optional
        value and the type checker needs no narrowing assert. An assert would
        vanish under ``python -O`` and the next line would raise
        ``AttributeError: 'NoneType' object has no attribute 'call_tool'``,
        which says nothing about the actual mistake.
        """
        if self._session is None:
            raise RuntimeError("TravelMcpSession must be entered before use: `async with session:`")
        return self._session

    async def list_tools(self) -> list[dict[str, Any]]:
        session = self._require_session()
        result = await session.list_tools()
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": getattr(t, "input_schema", None) or getattr(t, "inputSchema", None),
                "output_schema": getattr(t, "output_schema", None)
                or getattr(t, "outputSchema", None),
            }
            for t in result.tools
        ]

    async def call(self, tool: str, arguments: dict[str, Any]) -> McpCallResult:
        session = self._require_session()
        result = await session.call_tool(tool, arguments)

        texts = [
            getattr(block, "text", "") for block in result.content if getattr(block, "text", None)
        ]
        joined = "\n".join(texts) if texts else None

        if result.is_error:
            raise McpToolError(tool, joined or "tool call failed")

        data = result.structured_content
        if data is None and joined:
            try:
                parsed = json.loads(joined)
                data = parsed if isinstance(parsed, dict) else {"result": parsed}
            except json.JSONDecodeError:
                data = {"text": joined}
        return McpCallResult(tool=tool, data=data or {}, is_error=False, raw_text=joined)
