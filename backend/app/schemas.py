from pydantic import BaseModel, Field

from app.plugins.types import PluginResourceOut, SelectionOut


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    user_key: str = "default"


class ChatResponse(BaseModel):
    answer: str
    selection: SelectionOut
    resources: dict[str, list[PluginResourceOut]]
