from dataclasses import MISSING, dataclass, field, fields
from typing import Annotated, Any, get_args, get_origin


@dataclass(kw_only=True)
class BaseAgentContext:
    """Base schema shared by agent runtimes."""

    user_id: str = field(
        default="default",
        metadata={
            "name": "用户ID",
            "configurable": False,
            "description": "用来唯一标识一个用户，后续登录系统接入后由认证层提供。",
        },
    )
    conversation_id: int | None = field(
        default=None,
        metadata={
            "name": "会话ID",
            "configurable": False,
            "description": "当前对话会话 ID。",
        },
    )
    system_prompt: Annotated[str, {"__template_metadata__": {"kind": "prompt"}}] = field(
        default="You are a helpful assistant.",
        metadata={
            "name": "系统提示词",
            "description": "用来描述智能体的角色和行为。",
        },
    )
    model_use: Annotated[str, {"__template_metadata__": {"kind": "llm_use"}}] = field(
        default="",
        metadata={
            "name": "模型用途",
            "description": "用于从配置中选择具体模型，例如 deep_research_model；聊天模型由请求 model_spec 指定。",
        },
    )
    model_spec: str | None = field(
        default=None,
        metadata={"configurable": False, "hide": True},
    )
    current_datetime: str = field(
        default="",
        metadata={
            "name": "当前时间",
            "configurable": False,
            "description": "运行时注入的当前时间字符串。",
        },
    )
    timezone: str = field(
        default="Asia/Shanghai",
        metadata={
            "name": "时区",
            "description": "运行时展示和提示词注入使用的时区。",
        },
    )
    mcps: Annotated[list[dict], {"__template_metadata__": {"kind": "mcps"}}] = field(
        default_factory=list,
        metadata={
            "name": "MCP 服务",
            "description": "当前运行可见的 MCP 资源元数据。",
            "type": "list",
        },
    )
    skills: Annotated[list[str], {"__template_metadata__": {"kind": "skills"}}] = field(
        default_factory=list,
        metadata={
            "name": "Skills",
            "description": "当前运行可见的 Skill slug 列表。",
            "type": "list",
        },
    )
    tools: Annotated[list[dict], {"__template_metadata__": {"kind": "tools"}}] = field(
        default_factory=list,
        metadata={
            "name": "工具",
            "description": "当前运行可见的工具资源元数据。",
            "type": "list",
        },
    )
    max_tool_calls: int = field(
        default=3,
        metadata={
            "name": "工具调用上限",
            "description": "单轮 Agent 运行允许的最大工具调用次数。",
            "type": "number",
        },
    )

    def update_from_dict(self, data: dict[str, Any]) -> None:
        """Update known context fields from a plain dict."""
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)

    @classmethod
    def get_configurable_items(cls) -> dict[str, dict[str, Any]]:
        """Return UI-friendly metadata for configurable context fields."""
        items: dict[str, dict[str, Any]] = {}
        for item in fields(cls):
            if not item.init or item.metadata.get("hide", False):
                continue
            if item.metadata.get("configurable", True) is False:
                continue
            items[item.name] = {
                "type": item.metadata.get("type", cls._get_type_name(item.type)),
                "name": item.metadata.get("name", item.name),
                "default": cls._default_value(item),
                "description": item.metadata.get("description", ""),
                "template_metadata": cls._extract_template_metadata(item.type),
            }
        return items

    @classmethod
    def _default_value(cls, item: Any) -> Any:
        if item.default is not MISSING:
            return item.default
        if item.default_factory is not MISSING:
            return item.default_factory()
        return None

    @classmethod
    def _get_type_name(cls, field_type: Any) -> str:
        origin = get_origin(field_type)
        if origin is None:
            return getattr(field_type, "__name__", str(field_type))
        if getattr(origin, "__name__", "") == "Annotated":
            args = get_args(field_type)
            return cls._get_type_name(args[0]) if args else "Any"
        return getattr(origin, "__name__", str(origin))

    @classmethod
    def _extract_template_metadata(cls, field_type: Any) -> dict[str, Any]:
        origin = get_origin(field_type)
        if getattr(origin, "__name__", "") != "Annotated":
            return {}
        for metadata in get_args(field_type)[1:]:
            if isinstance(metadata, dict) and "__template_metadata__" in metadata:
                return metadata["__template_metadata__"]
        return {}
