from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.agents.buildin.chatbot.prompt import DEFAULT_SYSTEM_PROMPT


class Settings(BaseSettings):
    app_name: str = "miniBOT"
    api_prefix: str = "/api"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    database_url: str = "postgresql+asyncpg://minibot:minibot@localhost:5432/minibot"
    storage_provider: str = "minio"
    storage_bucket: str = "minibot"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minibot"
    minio_secret_key: str = "minibot123"
    minio_secure: bool = False
    vector_store_provider: str = "milvus"
    milvus_uri: str = "http://localhost:19530"
    milvus_token: str = ""
    milvus_db: str = "minibot"
    milvus_collection_prefix: str = "kb_"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "minibot123"
    lightrag_work_dir: str = "./data/lightrag"
    lightrag_workspace_prefix: str = "kb_"
    lightrag_language: str = "Chinese"
    lightrag_query_mode: str = "mix"
    lightrag_model_provider: str = ""
    lightrag_model_name: str = ""
    lightrag_embedding_max_tokens: int = 8192
    lightrag_llm_timeout: float = 600.0
    lightrag_milvus_uri: str = ""
    lightrag_milvus_token: str = ""
    lightrag_milvus_db: str = "minibot_lightrag"
    embedding_provider: str = "mock"
    embedding_model_name: str = "mock"
    embedding_dimension: int = 384
    embedding_batch_size: int = 10

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
