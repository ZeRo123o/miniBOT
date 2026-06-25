""" MCP service: built-in definitions, discovery cache, and access policy."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)
_cache_lock = asyncio.Lock()
_tools_cache: dict[str, list[BaseTool]] = {}
_CLIENT_CONFIG_KEYS = {"transport", "command", "args", "url", "env", "headers", "timeout", "sse_read_timeout"}
_PERSISTED_CONFIG_KEYS = _CLIENT_CONFIG_KEYS | {"disabled_tools", "tags", "icon"}
_VALID_TRANSPORTS = {"stdio", "sse", "streamable_http"}

# Matches Yuxi's bundled chart MCP definition. It remains disabled until an
# administrator verifies that the host has a usable Node.js/npm runtime.
BUILTIN_MCP_SERVERS: tuple[dict[str, Any], ...] = (
    {
        "kind": "mcp",
        "name": "mcp-server-chart",
        "display_name": "图表生成",
        "description": "图表生成工具，支持生成柱状图、折线图、饼图等。",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@antv/mcp-server-chart"],
            "tags": ["内置", "图表"],
            "icon": "📊",
        },
    },
)


class McpToolEventCallback(BaseCallbackHandler):
    """Adapt LangChain's native MCP tool lifecycle callbacks to miniBOT SSE events.

    This replaces middleware wrapping: the graph remains responsible for tool
    execution, while this callback observes its native start/end/error events.
    """

    raise_error = False

    def __init__(self, context: Any) -> None:
        super().__init__()
        self._context = context
        self._events_by_run_id: dict[str, dict[str, Any] | None] = {}

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, *, run_id: Any, **kwargs: Any) -> None:
        del input_str
        tool_name = str(kwargs.get("name") or serialized.get("name") or "")
        server_name = getattr(self._context, "_mcp_tool_servers", {}).get(tool_name)
        if not server_name:
            return
        from app.agents.toolkits.governance import start_tool_call

        self._events_by_run_id[str(run_id)] = start_tool_call(
            self._context,
            tool_name=tool_name,
            tool_call_id=f"mcp_{run_id}",
            payload={"mcp_server": server_name, "description": f"MCP: {server_name}"},
        )

    def on_tool_end(self, output: Any, *, run_id: Any, **kwargs: Any) -> None:
        del kwargs
        event = self._events_by_run_id.pop(str(run_id), None)
        if event is not None:
            from app.agents.toolkits.governance import finish_tool_call

            chart_url = _extract_chart_url(output) if event.get("mcp_server") == "mcp-server-chart" else None
            finish_tool_call(event, **({"chart_url": chart_url} if chart_url else {}))

    def on_tool_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        del kwargs
        event = self._events_by_run_id.pop(str(run_id), None)
        if event is not None:
            from app.agents.toolkits.governance import fail_tool_call

            fail_tool_call(event, error)


def build_mcp_event_callback(context: Any) -> McpToolEventCallback:
    """Create one run-scoped observer for MCP tools injected into this Agent."""
    return McpToolEventCallback(context)


def _extract_chart_url(output: Any) -> str | None:
    """Extract only a safe image URL from the chart MCP result, never its full output."""
    candidates: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str):
            candidates.append(value)
            try:
                collect(json.loads(value))
            except (TypeError, ValueError):
                pass
        elif isinstance(value, dict):
            for key in ("text", "url", "content"):
                if key in value:
                    collect(value[key])
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    collect(getattr(output, "content", output))
    for candidate in candidates:
        for value in re.findall(r"https?://[^\s'\"<>\])]+", candidate):
            parsed = urlparse(value)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                return value
    return None


def validate_mcp_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate the MCP transport contract and retain allowed persisted fields."""
    transport = str(config.get("transport") or "").strip()
    if transport not in _VALID_TRANSPORTS:
        raise ValueError("MCP transport must be one of: stdio, sse, streamable_http")
    if transport == "stdio" and not str(config.get("command") or "").strip():
        raise ValueError("stdio MCP servers require config.command")
    if transport in {"sse", "streamable_http"} and not str(config.get("url") or "").strip():
        raise ValueError(f"{transport} MCP servers require config.url")
    return {key: value for key, value in config.items() if key in _PERSISTED_CONFIG_KEYS}


def _cache_key(server_name: str, config: dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return f"{server_name}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _disabled_tool_names(config: dict[str, Any]) -> set[str]:
    return {str(value).strip() for value in config.get("disabled_tools") or [] if str(value).strip()}


async def discover_mcp_tools(server_name: str, config: dict[str, Any], *, force_refresh: bool = False, include_disabled: bool = False) -> list[BaseTool]:
    """Discover a server's tools and return its currently enabled subset."""
    normalized = validate_mcp_config(config)
    key = _cache_key(server_name, normalized)
    async with _cache_lock:
        tools = None if force_refresh else _tools_cache.get(key)
    if tools is None:
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient

            client_config = {key: value for key, value in normalized.items() if key in _CLIENT_CONFIG_KEYS}
            tools = list(await MultiServerMCPClient({server_name: client_config}).get_tools())
        except Exception as error:  # noqa: BLE001
            logger.warning("MCP discovery failed: server=%s error_type=%s", server_name, type(error).__name__)
            raise RuntimeError(f"Unable to connect to MCP server '{server_name}'") from error
        for tool in tools:
            tool.handle_tool_error = True
            tool.metadata = {**(tool.metadata or {}), "minibot_mcp_server": server_name}
        async with _cache_lock:
            for stale_key in [item for item in _tools_cache if item.startswith(f"{server_name}:") and item != key]:
                _tools_cache.pop(stale_key, None)
            _tools_cache[key] = tools
    disabled = _disabled_tool_names(normalized)
    return list(tools) if include_disabled else [tool for tool in tools if tool.name not in disabled]


def clear_mcp_tools_cache(server_name: str | None = None) -> None:
    """Invalidate all discovery results, or one server after a resource change."""
    if server_name is None:
        _tools_cache.clear()
        return
    for key in [item for item in _tools_cache if item.startswith(f"{server_name}:")]:
        _tools_cache.pop(key, None)


def mcp_tool_metadata(tools: Iterable[BaseTool], disabled_tools: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Expose only UI-safe names, descriptions, and input schemas."""
    disabled = {str(name) for name in disabled_tools}
    result: list[dict[str, Any]] = []
    for tool in tools:
        schema = tool.args_schema
        json_schema = schema.model_json_schema() if hasattr(schema, "model_json_schema") else {}
        result.append({"name": tool.name, "description": str(tool.description or ""), "parameters": json_schema.get("properties", {}), "required": json_schema.get("required", []), "enabled": tool.name not in disabled})
    return result
