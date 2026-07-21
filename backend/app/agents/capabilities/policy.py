"""普通 Tool 的执行域与模型暴露策略。"""

from __future__ import annotations

from collections.abc import Mapping, Set
from typing import Any

from app.agents.capabilities.models import ToolExposure

SUPPORTED_AGENT_TYPES = frozenset({"chatbot", "subagent"})


def validate_agent_type(agent_type: str) -> None:
    """拒绝未知 Agent 类型，避免新执行域意外继承宽松默认权限。"""
    if agent_type not in SUPPORTED_AGENT_TYPES:
        raise ValueError(f"unsupported agent_type: {agent_type}")


def parse_tool_exposure(config: Mapping[str, Any] | None) -> ToolExposure | None:
    """解析工具暴露类型；旧数据缺失时兼容 direct，非法值失败关闭。"""
    raw_value = (config or {}).get("exposure")
    if raw_value is None or not str(raw_value).strip():
        return ToolExposure.DIRECT
    try:
        return ToolExposure(str(raw_value).strip())
    except ValueError:
        return None


def is_tool_executable(
    exposure: ToolExposure,
    *,
    agent_type: str,
) -> bool:
    """判断普通 Tool 是否允许注册到当前 Agent 的 ToolNode。"""
    validate_agent_type(agent_type)
    if exposure in {ToolExposure.DIRECT, ToolExposure.SKILL_ONLY}:
        return True
    if exposure is ToolExposure.SUBAGENT_ONLY:
        return agent_type == "subagent"
    # internal 只允许后端受控调用，不进入任何模型驱动的 ToolNode。
    return False


def is_tool_model_visible(
    exposure: ToolExposure,
    *,
    agent_type: str,
    tool_name: str,
    activated_dependency_tools: Set[str],
) -> bool:
    """判断已具备执行资格的普通 Tool 是否向本次模型请求暴露 Schema。"""
    validate_agent_type(agent_type)
    if exposure is ToolExposure.DIRECT:
        return True
    if exposure is ToolExposure.SKILL_ONLY:
        return tool_name in activated_dependency_tools
    if exposure is ToolExposure.SUBAGENT_ONLY:
        return agent_type == "subagent"
    return False
