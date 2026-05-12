from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "miniBOT"
    api_prefix: str = "/api"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    database_url: str = "postgresql+asyncpg://minibot:minibot@localhost:5432/minibot"

    default_model: str = "mock"
    default_system_prompt: str = "You are miniBOT, a modular assistant."

    model_config = SettingsConfigDict(env_file=".env", env_prefix="MINIBOT_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
