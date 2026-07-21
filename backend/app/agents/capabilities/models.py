"""能力解析使用的稳定数据结构。"""

from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict


class ToolExposure(StrEnum):
    """普通 Tool 的执行域和模型暴露策略。"""

    DIRECT = "direct"
    SKILL_ONLY = "skill_only"
    SUBAGENT_ONLY = "subagent_only"
    INTERNAL = "internal"


class SkillDependencyNode(TypedDict):
    """一个 Skill 声明的直接依赖。"""

    tools: list[str]
    mcps: list[str]
    skills: list[str]


@dataclass(frozen=True)
class ResolvedCapabilities:
    """当前 Agent 本轮可执行和对模型可见的能力集合。"""

    executable_tool_names: frozenset[str]
    model_visible_tool_names: frozenset[str]
    allowed_mcp_servers: frozenset[str]
    visible_skill_slugs: frozenset[str]
