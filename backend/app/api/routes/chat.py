from fastapi import APIRouter, Depends
from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import UserSelectionRepository
from app.db.session import get_db
from app.graph.builder import build_chat_graph
from app.plugins.registry import resolve_resources_by_name
from app.schemas import ChatRequest

router = APIRouter()


@router.post("")
async def chat(payload: ChatRequest, db: AsyncSession = Depends(get_db)) -> dict:
    selection_item = await UserSelectionRepository(db).get(payload.user_key)
    selection = (
        selection_item.to_dict()
        if selection_item
        else {"user_key": payload.user_key, "mcps": [], "skills": [], "subagents": []}
    )
    resources = {
        "mcps": await resolve_resources_by_name(db, kind="mcp", names=selection["mcps"]),
        "skills": await resolve_resources_by_name(db, kind="skill", names=selection["skills"]),
        "subagents": await resolve_resources_by_name(db, kind="subagent", names=selection["subagents"]),
    }
    graph = build_chat_graph()
    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content=payload.message)],
            "mcps": resources["mcps"],
            "skills": resources["skills"],
            "subagents": resources["subagents"],
        }
    )
    return {
        "answer": result["messages"][-1].content,
        "selection": selection,
        "resources": resources,
    }
