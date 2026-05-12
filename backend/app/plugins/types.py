from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ResourceKind(StrEnum):
    mcp = "mcp"
    skill = "skill"
    subagent = "subagent"


class PluginResourceIn(BaseModel):
    kind: ResourceKind
    name: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=128)
    description: str = ""
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class PluginResourceOut(PluginResourceIn):
    id: int


class SelectionIn(BaseModel):
    user_key: str = Field(default="default", min_length=1, max_length=128)
    mcps: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    subagents: list[str] = Field(default_factory=list)


class SelectionOut(SelectionIn):
    pass
