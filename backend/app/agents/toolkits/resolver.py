import logging
from collections.abc import Iterable
from typing import Any

from langchain_core.tools import BaseTool

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.capabilities import (
    is_tool_executable,
    parse_tool_exposure,
    validate_agent_type,
)
from app.agents.mcp import discover_mcp_tools
from app.agents.toolkits.registry import get_extra_metadata, get_tool_instance
from app.core.config import get_settings

logger = logging.getLogger(__name__)


def merge_runtime_tools(*groups: Iterable[BaseTool]) -> list[BaseTool]:
    """Merge tool sources by name so a model never receives duplicate schemas."""
    merged: list[BaseTool] = []
    seen: set[str] = set()
    for group in groups:
        for tool in group:
            if tool.name in seen:
                logger.warning("Duplicate runtime tool name skipped: %s", tool.name)
                continue
            merged.append(tool)
            seen.add(tool.name)
    return merged


def resolve_runtime_tools(
    context: AgentContext,
    *,
    agent_type: str = "chatbot",
    denied_tool_names: Iterable[str] = (),
) -> list[BaseTool]:
    """解析允许注册到当前 Agent ToolNode 的普通 Tool。"""
    validate_agent_type(agent_type)
    resolved: list[BaseTool] = []
    seen: set[str] = set()
    denied = {
        str(name or "").strip()
        for name in denied_tool_names
        if str(name or "").strip()
    }
    resources_by_name = {
        str(resource.get("name") or "").strip(): resource
        for resource in context.tools
        if resource.get("name") and bool(resource.get("enabled", True))
    }
    for name, resource in resources_by_name.items():
        if not name or name in seen or name in denied:
            continue
        exposure = parse_tool_exposure(resource.get("config") or {})
        if exposure is None:
            logger.warning(
                "Invalid tool exposure skipped during graph registration: tool=%s",
                name,
            )
            continue
        if not is_tool_executable(exposure, agent_type=agent_type):
            continue
        if name.startswith("sandbox_") and not get_settings().sandbox_enabled:
            continue

        tool_instance = get_tool_instance(name)
        if tool_instance is None:
            # A long-lived API worker may have imported the resolver before a
            # newly deployed trusted integration was discovered. Re-import the
            # aggregate package once before treating the resource as missing.
            import app.agents.toolkits.external  # noqa: F401

            tool_instance = get_tool_instance(name)
        if tool_instance is None:
            logger.warning("No trusted runtime implementation registered for tool: %s", name)
            continue
        metadata = get_extra_metadata(name)
        if metadata and metadata.category == "sandbox":
            logger.warning("Sandbox middleware tool cannot be configured directly: %s", name)
            continue
        resolved.append(tool_instance)
        seen.add(name)

    return resolved


async def resolve_runtime_mcps(
    context: AgentContext,
    *,
    server_names: Iterable[str] = (),
) -> list[BaseTool]:
    """Resolve configured MCP servers for direct or activated-Skill use."""
    source_names = server_names or tuple(item.get("name") for item in context.mcps)
    requested = tuple(
        dict.fromkeys(
            str(name or "").strip()
            for name in source_names
            if str(name or "").strip()
        )
    )
    resources_by_name = {
        str(resource.get("name") or "").strip(): resource
        for resource in context.mcps
        if resource.get("name")
    }
    result: list[BaseTool] = []
    seen: set[str] = set()
    for name in requested:
        resource = resources_by_name.get(name)
        if resource is None:
            logger.warning("MCP server is unavailable or unauthorized: %s", name)
            continue
        for tool in await _load_mcp_tools(name, resource.get("config") or {}):
            if tool.name not in seen:
                result.append(tool)
                seen.add(tool.name)
                server_by_tool = getattr(context, "_mcp_tool_servers", {})
                server_by_tool[tool.name] = name
                setattr(context, "_mcp_tool_servers", server_by_tool)
    return result


async def _load_mcp_tools(server_name: str, config: dict[str, Any]) -> list[BaseTool]:
    """Discover one MCP server without logging its configuration."""
    try:
        tools = await discover_mcp_tools(server_name, config)
    except Exception as error:  # noqa: BLE001
        logger.warning("Failed to load MCP tools: server=%s error_type=%s", server_name, type(error).__name__)
        return []
    return list(tools)
