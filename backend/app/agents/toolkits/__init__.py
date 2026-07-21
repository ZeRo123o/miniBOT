"""Agent 可直接注入的工具包；导入子模块会触发 @tool 自动注册。"""

from app.agents.toolkits import buildin
from app.agents.toolkits import external
from app.agents.toolkits import sandbox
from app.agents.toolkits.resolver import (
    merge_runtime_tools,
    resolve_runtime_mcps,
    resolve_runtime_tools,
)

__all__ = [
    "buildin",
    "external",
    "sandbox",
    "resolve_runtime_tools",
    "resolve_runtime_mcps",
    "merge_runtime_tools",
]
