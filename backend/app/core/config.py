from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.graph.prompt import DEFAULT_SYSTEM_PROMPT


class Settings(BaseSettings):
    app_name: str = "miniBOT"
    api_prefix: str = "/api"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    database_url: str = "postgresql+asyncpg://minibot:minibot@localhost:5432/minibot"

    default_model: str = "mock"
    default_model_provider: str = "mock"
    default_model_name: str = "mock"
    chat_model_provider: str = ""
    chat_model_name: str = ""
    deep_research_model_provider: str = ""
    deep_research_model_name: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_temperature: float = 0.2
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com"
    tavily_max_results: int = 5
    tavily_search_depth: str = "basic"
    runtime_tool_call_limit: int = 3
    runtime_timezone: str = "Asia/Shanghai"
    summary_context_window_tokens: int = 128000
    summary_trigger_ratio: float = 0.7
    summary_trigger_tokens: int = 90000
    summary_keep_messages: int = 8
    summary_max_chars: int = 3000
    default_system_prompt: str = DEFAULT_SYSTEM_PROMPT

    model_config = SettingsConfigDict(env_file=".env", env_prefix="MINIBOT_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
