"""Agent 可直接注入的工具包；导入子模块会触发 @tool 自动注册。"""

from app.agents.toolkits import buildin
from app.agents.toolkits.resolver import resolve_runtime_tools

__all__ = ["buildin", "resolve_runtime_tools"]
