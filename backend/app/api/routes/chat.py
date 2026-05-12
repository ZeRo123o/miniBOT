from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConversationMessage
from app.db.repositories import ConversationMessageRepository, ConversationRepository, UserSelectionRepository
from app.db.session import get_db
from app.graph.builder import build_chat_graph
from app.plugins.registry import resolve_resources_by_name
from app.schemas import ChatRequest

router = APIRouter()


def _to_langchain_message(message: ConversationMessage) -> BaseMessage | None:
    if message.role == "user":
        return HumanMessage(content=message.content)
    if message.role == "assistant":
        return AIMessage(content=message.content)
    return None


@router.post("")
async def chat(payload: ChatRequest, db: AsyncSession = Depends(get_db)) -> dict:
    conversation_repo = ConversationRepository(db)
    message_repo = ConversationMessageRepository(db)

    if payload.conversation_id is None:
        conversation = await conversation_repo.create(
            user_key=payload.user_key,
            title=payload.message[:24] or "新对话",
        )
    else:
        conversation = await conversation_repo.get(payload.conversation_id, user_key=payload.user_key)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        existing_messages = await message_repo.list(conversation.id)
        if not existing_messages and conversation.title == "新对话":
            conversation = await conversation_repo.update(conversation, title=payload.message[:24] or "新对话")

    await message_repo.create(conversation.id, role="user", content=payload.message)
    persisted_messages = await message_repo.list(conversation.id)
    graph_messages = [
        converted
        for message in persisted_messages
        if (converted := _to_langchain_message(message)) is not None
    ]

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
            "messages": graph_messages,
            "mcps": resources["mcps"],
            "skills": resources["skills"],
            "subagents": resources["subagents"],
            "runtime": {"user_key": payload.user_key, "conversation_id": conversation.id},
        }
    )

    answer = result["messages"][-1].content
    await message_repo.create(
        conversation.id,
        role="assistant",
        content=answer,
        metadata={"resources": resources},
    )
    messages = await message_repo.list(conversation.id)
    conversation = await conversation_repo.get(conversation.id, user_key=payload.user_key)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    return {
        "answer": answer,
        "conversation_id": conversation.id,
        "conversation": conversation.to_dict(),
        "messages": [message.to_dict() for message in messages],
        "selection": selection,
        "resources": resources,
    }
