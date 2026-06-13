import logging
from collections.abc import Iterable

from langchain_core.tools import BaseTool

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.toolkits.registry import get_tool_instance
from app.core.config import get_settings

logger = logging.getLogger(__name__)


def resolve_runtime_tools(
    context: AgentContext,
    *,
    include_direct: bool = True,
    extra_tool_names: Iterable[str] = (),
) -> list[BaseTool]:
    """Resolve direct tools and explicitly requested Skill dependencies."""
    resolved: list[BaseTool] = []
    seen: set[str] = set()
    resources_by_name = {
        str(resource.get("name") or "").strip(): resource
        for resource in context.tools
        if resource.get("name")
    }
    direct_names = (
        tuple(
            name
            for name, resource in resources_by_name.items()
            if (resource.get("config") or {}).get("expose_directly", True) is not False
        )
        if include_direct
        else ()
    )
    dependency_names = tuple(
        dict.fromkeys(
            str(name or "").strip()
            for name in extra_tool_names
            if str(name or "").strip()
        )
    )
    dependency_name_set = set(dependency_names)

    for name in (*direct_names, *dependency_names):
        if not name or name in seen:
            continue
        resource = resources_by_name.get(name)
        if resource is None:
            logger.warning("Skill dependency tool is unavailable or unauthorized: %s", name)
            continue
        if name in dependency_name_set and (resource.get("config") or {}).get(
            "allow_skill_dependency",
            True,
        ) is False:
            logger.warning("Tool blocks Skill dependency activation: %s", name)
            continue
        if name.startswith("sandbox_") and not get_settings().sandbox_enabled:
            continue

        tool_instance = get_tool_instance(name)
        if tool_instance is None:
            logger.warning("No trusted runtime implementation registered for tool: %s", name)
            continue
        resolved.append(tool_instance)
        seen.add(name)

    return resolved
