"""根据已启用资源、Skill 状态和实际工具集合计算运行时能力。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.models import (
    ResolvedCapabilities,
    SkillDependencyNode,
)
from app.agents.capabilities.policy import (
    is_tool_executable,
    is_tool_model_visible,
    parse_tool_exposure,
    validate_agent_type,
)
from app.agents.skills.service import normalize_string_list
from app.agents.toolkits.registry import get_all_extra_metadata
from app.db.session import AsyncSessionLocal
from app.repositories.skill_repository import SkillRepository

logger = logging.getLogger(__name__)

DependencyMapLoader = Callable[[], Awaitable[dict[str, SkillDependencyNode]]]
ConfigurableToolNamesProvider = Callable[[], set[str]]


async def load_skill_dependency_map(
    db: AsyncSession | None = None,
) -> dict[str, SkillDependencyNode]:
    """从数据库读取 Skill 依赖图，供提示注入和能力解析共用。"""
    if db is not None:
        skills = await SkillRepository(db).list_all()
    else:
        async with AsyncSessionLocal() as session:
            skills = await SkillRepository(session).list_all()
    return {
        item.slug: {
            "tools": normalize_string_list(item.tool_dependencies),
            "mcps": normalize_string_list(item.mcp_dependencies),
            "skills": normalize_string_list(item.skill_dependencies),
        }
        for item in skills
    }


def expand_skill_closure(
    slugs: list[str] | None,
    dependency_map: dict[str, SkillDependencyNode],
) -> list[str]:
    """按稳定深度优先顺序展开 Skill 依赖，并跳过缺失节点和循环。"""
    result: list[str] = []
    seen: set[str] = set()

    def dfs(slug: str, stack: tuple[str, ...]) -> None:
        if slug in stack:
            logger.warning(
                "Skill dependency cycle skipped: %s",
                " -> ".join((*stack, slug)),
            )
            return
        if slug in seen:
            return
        node = dependency_map.get(slug)
        if node is None:
            logger.warning("Skill dependency target not found: %s", slug)
            return
        seen.add(slug)
        result.append(slug)
        for dependency in node["skills"]:
            dfs(dependency, (*stack, slug))

    for root in normalize_string_list(slugs):
        dfs(root, ())
    return result


def _default_configurable_tool_names() -> set[str]:
    """返回由扩展管理启停的 Tool；Middleware 自带工具不在此集合中。"""
    return {
        name
        for name, metadata in get_all_extra_metadata().items()
        if metadata.category in {"buildin", "external"}
    }


class CapabilityResolver:
    """计算 ToolNode 可执行集合与本次模型请求可见集合。"""

    def __init__(
        self,
        *,
        dependency_map_loader: DependencyMapLoader = load_skill_dependency_map,
        configurable_tool_names_provider: ConfigurableToolNamesProvider = _default_configurable_tool_names,
    ) -> None:
        self._dependency_map_loader = dependency_map_loader
        self._configurable_tool_names_provider = configurable_tool_names_provider

    async def resolve(
        self,
        *,
        context: Any,
        agent_type: str,
        subagent_type: str | None,
        activated_skills: list[str] | None,
        available_tool_names: Iterable[str],
        denied_tool_names: Iterable[str] = (),
    ) -> ResolvedCapabilities:
        """解析当前 Agent 的可执行集合与本轮模型可见集合。"""
        validate_agent_type(agent_type)
        profile_boundary = self._subagent_profile_boundary(
            context=context,
            agent_type=agent_type,
            subagent_type=subagent_type,
        )

        dependency_map = await self._dependency_map_loader()
        configured_skills = normalize_string_list(getattr(context, "skills", []) or [])
        # 激活状态不能扩大授权范围；可见 Skill 只来自当前 context 的配置闭包。
        visible_skill_slugs = expand_skill_closure(configured_skills, dependency_map)
        visible_skill_set = set(visible_skill_slugs)
        valid_activated_skills = [
            slug
            for slug in normalize_string_list(activated_skills)
            if slug in visible_skill_set
        ]
        activated_dependency_tools = self._activated_dependency_tools(
            valid_activated_skills,
            dependency_map,
        )

        resources_by_name = {
            str(resource.get("name") or "").strip(): resource
            for resource in getattr(context, "tools", []) or []
            if resource.get("name") and bool(resource.get("enabled", True))
        }
        allowed_mcp_servers = frozenset(
            str(resource.get("name") or "").strip()
            for resource in getattr(context, "mcps", []) or []
            if (
                str(resource.get("name") or "").strip()
                and bool(resource.get("enabled", True))
            )
        )
        mcp_server_by_tool = getattr(context, "_mcp_tool_servers", {}) or {}
        configurable_tool_names = self._configurable_tool_names_provider()
        denied = {
            str(name or "").strip()
            for name in denied_tool_names
            if str(name or "").strip()
        }

        executable: set[str] = set()
        for raw_name in available_tool_names:
            name = str(raw_name or "").strip()
            if not name or name in denied:
                continue
            # Profile 是子 Agent 的最终权限边界，必须先于工具来源分支统一收紧。
            if profile_boundary is not None and name not in profile_boundary:
                continue
            mcp_server = str(mcp_server_by_tool.get(name) or "").strip()
            if mcp_server:
                if mcp_server in allowed_mcp_servers:
                    executable.add(name)
                continue
            # Registry 中的普通 Tool 必须同时存在于当前已启用资源范围；
            # Sandbox、知识库、task 等 Middleware 工具不受扩展开关管理。
            if name in configurable_tool_names:
                resource = resources_by_name.get(name)
                if resource is None:
                    continue
                exposure = parse_tool_exposure(resource.get("config") or {})
                if exposure is None:
                    logger.warning(
                        "Invalid tool exposure denied: tool=%s exposure=%s",
                        name,
                        (resource.get("config") or {}).get("exposure"),
                    )
                    continue
                if not is_tool_executable(exposure, agent_type=agent_type):
                    continue
            executable.add(name)

        model_visible = set(executable)
        for name, resource in resources_by_name.items():
            if name not in executable:
                continue
            exposure = parse_tool_exposure(resource.get("config") or {})
            if exposure is None:
                model_visible.discard(name)
            elif not is_tool_model_visible(
                exposure,
                agent_type=agent_type,
                tool_name=name,
                activated_dependency_tools=activated_dependency_tools,
            ):
                model_visible.discard(name)

        return ResolvedCapabilities(
            executable_tool_names=frozenset(executable),
            model_visible_tool_names=frozenset(model_visible),
            allowed_mcp_servers=allowed_mcp_servers,
            visible_skill_slugs=frozenset(visible_skill_slugs),
        )

    @staticmethod
    def _subagent_profile_boundary(
        *,
        context: Any,
        agent_type: str,
        subagent_type: str | None,
    ) -> frozenset[str] | None:
        """读取 Runner 写入的完整白名单；身份缺失或不一致时失败关闭。"""
        if agent_type != "subagent":
            return None

        context_type = str(getattr(context, "subagent_type", "") or "").strip()
        requested_type = str(subagent_type or "").strip()
        if not context_type or not requested_type or context_type != requested_type:
            logger.warning(
                "Subagent profile boundary denied: context_type=%s requested_type=%s",
                context_type,
                requested_type,
            )
            return frozenset()
        return frozenset(
            name
            for name in normalize_string_list(
                getattr(context, "allowed_tool_names", []) or []
            )
            if name
        )

    @staticmethod
    def _activated_dependency_tools(
        activated_skills: list[str],
        dependency_map: dict[str, SkillDependencyNode],
    ) -> set[str]:
        """只展开直接激活 Skill 的 Tool 依赖，保持渐进式激活语义。"""
        result: set[str] = set()
        for slug in activated_skills:
            result.update(dependency_map.get(slug, {}).get("tools", []))
        return result
