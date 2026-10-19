"""Gateway: MCP read tool invocation (M1)."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


@dataclass(frozen=True)
class InvokeSuccess:
    content: Any
    duration_ms: int


@dataclass(frozen=True)
class InvokeFailure:
    message: str
    timed_out: bool = False
    duration_ms: int = 0


InvokeHook = Callable[..., Awaitable[Any]]


def _parse_tool_result(result: Any) -> Any:
    if result is None:
        return None
    if getattr(result, "is_error", False):
        text = result.content[0].text if result.content else "tool error"
        raise RuntimeError(text)
    if not result.content:
        return None
    text = result.content[0].text
    # Structured results come back as JSON text; anything else (e.g. "No matching categories") is plain text.
    # Only parse what looks like JSON, and keep the text when it doesn't parse.
    stripped = (text or "").strip()
    if stripped[:1] in ("[", "{", '"') or stripped in ("null", "true", "false"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return text
    return text


def _root_message(exc: BaseException) -> str:
    """The MCP client fails inside task groups; report the first underlying error, not "unhandled errors"."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


class ToolGateway:
    """Calls connector read tools. Tests may replace ``invoke_hook`` with an in-memory MCP client."""

    def __init__(
        self,
        *,
        connector_urls: dict[str, str],
        timeout_s: float = 10.0,
        invoke_hook: InvokeHook | None = None,
    ) -> None:
        self._urls = dict(connector_urls)
        self._timeout_s = timeout_s
        self._invoke_hook = invoke_hook

    async def invoke_read(
        self,
        *,
        connector: str,
        tool: str,
        args: dict[str, Any],
        token: str,
    ) -> InvokeSuccess | InvokeFailure:
        started = time.monotonic()
        call_args = {**args, "token": token}
        try:
            if self._invoke_hook is not None:
                raw = await asyncio.wait_for(
                    self._invoke_hook(connector=connector, tool=tool, arguments=call_args),
                    timeout=self._timeout_s,
                )
            else:
                raw = await asyncio.wait_for(
                    self._invoke_http(connector=connector, tool=tool, arguments=call_args),
                    timeout=self._timeout_s,
                )
        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - started) * 1000)
            return InvokeFailure("Connector call timed out.", timed_out=True, duration_ms=elapsed)
        except Exception as exc:  # noqa: BLE001 — mapped to connector_failed at the kernel
            elapsed = int((time.monotonic() - started) * 1000)
            return InvokeFailure(_root_message(exc), timed_out=False, duration_ms=elapsed)
        elapsed = int((time.monotonic() - started) * 1000)
        try:
            content = _parse_tool_result(raw)
        except RuntimeError as exc:
            return InvokeFailure(str(exc), duration_ms=elapsed)
        return InvokeSuccess(content=content, duration_ms=elapsed)

    async def _invoke_http(self, *, connector: str, tool: str, arguments: dict[str, Any]) -> Any:
        url = self._urls.get(connector)
        if not url:
            raise KeyError(f"no MCP URL configured for connector {connector!r}")
        async with streamable_http_client(url) as streams:
            # mcp 2.x yields (read, write); 1.x added a session-id getter as a third item.
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(tool, arguments)
