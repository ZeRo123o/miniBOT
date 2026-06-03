from fastapi import APIRouter

from app.api.routes import chat, conversations, health, knowledge, resources, selections

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(resources.router, prefix="/resources", tags=["resources"])
api_router.include_router(selections.router, prefix="/selections", tags=["selections"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(knowledge.router, tags=["knowledge"])
