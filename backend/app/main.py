import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal, init_db
from app.plugins.registry import seed_builtin_resources
from app.agents.backends.sandbox import shutdown_sandbox_provider
from app.agents.checkpoints import checkpoint_manager
from app.llm.providers import ensure_builtin_model_providers_in_db, refresh_model_runtime_cache


# psycopg's async PostgreSQL pool is incompatible with Windows' Proactor loop.
# Set this before uvicorn creates the application event loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def configure_app_logging() -> None:
    app_logger = logging.getLogger("app")
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(levelname)s: %(name)s - %(message)s")
        )
        app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await checkpoint_manager.initialize()
    async with AsyncSessionLocal() as session:
        await seed_builtin_resources(session)
        await ensure_builtin_model_providers_in_db(session)
        await refresh_model_runtime_cache(session)
    try:
        yield
    finally:
        await checkpoint_manager.close()
        shutdown_sandbox_provider()


settings = get_settings()
configure_app_logging()

app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_prefix)
