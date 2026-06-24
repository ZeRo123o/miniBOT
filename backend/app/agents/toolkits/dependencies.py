from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


class SkillDependencyProvider(Protocol):
    """Resolve one Skill dependency kind into model-callable tools."""

    kind: str

    async def resolve(self, names: Sequence[str], context: Any) -> list[BaseTool]:
        ...


ProviderFactory = Callable[[], SkillDependencyProvider]
_PROVIDER_FACTORIES: dict[str, ProviderFactory] = {}


def register_skill_dependency_provider(
    kind: str,
    factory: ProviderFactory,
) -> None:
    """Register or replace a dependency provider by stable kind."""
    normalized = str(kind or "").strip()
    if not normalized:
        raise ValueError("dependency provider kind is required")
    _PROVIDER_FACTORIES[normalized] = factory


async def resolve_skill_dependency_tools(
    context: Any,
    *,
    tool_names: Sequence[str] = (),
    mcp_names: Sequence[str] = (),
) -> list[BaseTool]:
    """Resolve activated Skill dependencies through registered providers."""
    requested = {
        "tool": tuple(tool_names),
        "mcp": tuple(mcp_names),
    }
    resolved: list[BaseTool] = []
    seen: set[str] = set()

    for kind, names in requested.items():
        if not names:
            continue
        factory = _PROVIDER_FACTORIES.get(kind)
        if factory is None:
            logger.warning("No Skill dependency provider registered for kind: %s", kind)
            continue
        for tool in await factory().resolve(names, context):
            if tool.name in seen:
                continue
            seen.add(tool.name)
            resolved.append(tool)
    return resolved


class ToolDependencyProvider:
    kind = "tool"

    async def resolve(self, names: Sequence[str], context: Any) -> list[BaseTool]:
        from app.agents.toolkits.resolver import resolve_runtime_tools

        return resolve_runtime_tools(
            context,
            include_direct=False,
            extra_tool_names=names,
        )


class McpDependencyProvider:
    kind = "mcp"

    async def resolve(self, names: Sequence[str], context: Any) -> list[BaseTool]:
        from app.agents.toolkits.resolver import resolve_runtime_mcps

        return await resolve_runtime_mcps(context, server_names=names)


register_skill_dependency_provider("tool", ToolDependencyProvider)
register_skill_dependency_provider("mcp", McpDependencyProvider)
