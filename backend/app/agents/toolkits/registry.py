from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import BaseTool


@dataclass(frozen=True)
class ToolExtraMetadata:
    """工具的 UI 与资源分类元数据，不参与模型参数 schema。"""

    category: str = ""
    tags: list[str] = field(default_factory=list)
    display_name: str = ""
    icon: str = ""
    config_guide: str = ""


_EXTRA_REGISTRY: dict[str, ToolExtraMetadata] = {}
_ALL_TOOL_INSTANCES: list[BaseTool] = []


def tool(
    category: str = "",
    tags: list[str] | None = None,
    display_name: str = "",
    icon: str = "",
    config_guide: str = "",
    name_or_callable: str | Callable | None = None,
    description: str | None = None,
    args_schema: type | None = None,
    return_direct: bool = False,
) -> Callable:
    """基于 LangChain tool 的扩展装饰器，自动注册工具实例。"""
    from langchain.tools import tool as langchain_tool

    langchain_decorator = langchain_tool(
        name_or_callable=name_or_callable,
        description=description,
        args_schema=args_schema,
        return_direct=return_direct,
    )

    def decorator(func: Callable) -> BaseTool:
        tool_instance = langchain_decorator(func)
        tool_instance.handle_tool_error = True
        _EXTRA_REGISTRY[tool_instance.name] = ToolExtraMetadata(
            category=category,
            tags=tags or [],
            display_name=display_name,
            icon=icon,
            config_guide=config_guide,
        )
        _ALL_TOOL_INSTANCES.append(tool_instance)
        return tool_instance

    return decorator


def get_all_tool_instances() -> list[BaseTool]:
    """返回模块导入期间由 @tool 自动收集的全部工具。"""
    return list(_ALL_TOOL_INSTANCES)


def get_tool_instance(name: str) -> BaseTool | None:
    """按稳定运行时名称查找工具实例。"""
    return next((item for item in _ALL_TOOL_INSTANCES if item.name == name), None)


def get_extra_metadata(name: str) -> ToolExtraMetadata | None:
    """读取工具的展示与分类元数据。"""
    return _EXTRA_REGISTRY.get(name)


def get_all_extra_metadata() -> dict[str, ToolExtraMetadata]:
    """返回工具元数据副本，避免调用方修改全局注册表。"""
    return dict(_EXTRA_REGISTRY)


def get_registered_tool_names() -> set[str]:
    """返回全部已注册工具名称。"""
    return {item.name for item in _ALL_TOOL_INSTANCES}


def get_tool_config(context: Any, tool_name: str) -> dict[str, Any]:
    """从运行时上下文的已授权资源中读取指定工具配置。"""
    resources = context.get("tools", []) if isinstance(context, dict) else getattr(context, "tools", [])
    for resource in resources or []:
        if resource.get("name") == tool_name:
            return resource.get("config") or {}
    return {}
