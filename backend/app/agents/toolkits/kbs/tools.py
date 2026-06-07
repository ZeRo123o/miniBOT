"""供 Agent middleware 动态注入的知识库工具。"""

import logging
from typing import Any

from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime
from pydantic import BaseModel, Field

from app.db.repositories import KnowledgeBaseRepository
from app.db.session import AsyncSessionLocal
from app.services.knowledge_retrieval_service import KnowledgeRetrievalService
from app.tools.governance import (
    context_value,
    fail_tool_call,
    finish_tool_call,
    start_tool_call,
)

logger = logging.getLogger(__name__)


class ListKBsInput(BaseModel):
    """列出当前会话已启用知识库的输入模型。"""

    dummy: str = Field(default="", description="占位参数，请忽略")


class QueryKBInput(BaseModel):
    """查询指定知识库的输入模型。"""

    kb_id: int = Field(description="知识库id，用于指定要在哪个知识库中检索")
    query_text: str = Field(min_length=1,
                            description="查询的关键词，查询的时候，应该尽量以可能帮助回答这个问题的关键词进行查询，"
                            "不要直接使用用户的原始输入去查询。")
    file_name: str | None = Field(default=None, description="可选的文件名过滤条件，支持部分匹配")


def _resolve_runtime_scope(runtime: ToolRuntime | None) -> tuple[str | None, list[int]]:
    """从 ToolRuntime 提取用户标识和当前会话启用的知识库 ID。"""
    if runtime is None or runtime.context is None:
        return None, []

    context = runtime.context
    user_key = context_value(context, "user_key", None)
    raw_ids = context_value(context, "knowledge_base_ids", []) or []
    knowledge_base_ids = []
    for item in raw_ids:
        try:
            knowledge_base_ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return user_key, list(dict.fromkeys(knowledge_base_ids))


@tool("list_kbs", args_schema=ListKBsInput)
async def list_kbs(dummy: str = "", runtime: ToolRuntime = None) -> list[dict[str, Any]] | str:
    """列出当前用户在本轮会话中已启用的知识库。

    当需要确定可查询的 kb_id、知识库名称或描述时使用。
    """
    user_key, enabled_ids = _resolve_runtime_scope(runtime)
    if not user_key:
        return "无法获取当前用户信息。"
    if not enabled_ids:
        return "当前会话没有启用知识库。"
    event, limit_error = start_tool_call(
        runtime.context,
        tool_name="list_kbs",
        payload={},
    )
    if limit_error:
        return limit_error

    try:
        async with AsyncSessionLocal() as db:
            repo = KnowledgeBaseRepository(db)
            visible = []
            for kb_id in enabled_ids:
                knowledge_base = await repo.get(kb_id, user_key=user_key)
                if knowledge_base is not None:
                    visible.append(
                        {
                            "kb_id": knowledge_base.id,
                            "name": knowledge_base.name,
                            "description": knowledge_base.description,
                        }
                    )
    except Exception as error:
        fail_tool_call(event, error)
        logger.exception("知识库列表工具调用失败: user_key=%s", user_key)
        return f"知识库列表查询失败: {error}"

    finish_tool_call(event, result_count=len(visible))
    return visible or "当前会话没有可访问的知识库。"


@tool("query_kb", args_schema=QueryKBInput)
async def query_kb(
    kb_id: int,
    query_text: str,
    file_name: str | None = None,
    runtime: ToolRuntime = None,
) -> dict[str, Any] | str:
    """在指定知识库中检索相关内容。

    kb_id 必须来自当前会话启用的知识库；返回结果中的 metadata 包含文档来源和 citation_id。
    """
    clean_query = query_text.strip()
    if not clean_query:
        return "请提供查询内容。"

    user_key, enabled_ids = _resolve_runtime_scope(runtime)
    if not user_key:
        return "无法获取当前用户信息。"
    if int(kb_id) not in enabled_ids:
        return f"知识库资源 '{kb_id}' 不存在或当前会话未启用。"
    event, limit_error = start_tool_call(
        runtime.context,
        tool_name="query_kb",
        payload={
            "kb_id": int(kb_id),
            "query": clean_query,
            "file_name": file_name,
        },
    )
    if limit_error:
        return limit_error

    try:
        async with AsyncSessionLocal() as db:
            knowledge_base = await KnowledgeBaseRepository(db).get(int(kb_id), user_key=user_key)
            if knowledge_base is None:
                fail_tool_call(event, "knowledge_base_not_found")
                return f"知识库资源 '{kb_id}' 不存在或当前用户无权访问。"

            result = await KnowledgeRetrievalService(db).query(
                user_key=user_key,
                query=clean_query,
                knowledge_base_ids=[int(kb_id)],
                search_mode="hybrid",
                file_name=file_name,
            )
    except Exception as error:
        logger.exception("知识库工具查询失败: user_key=%s kb_id=%s", user_key, kb_id)
        fail_tool_call(event, error)
        return f"知识库检索失败: {error}"

    finish_tool_call(event, results=result.get("results") or [])
    return {
        "kb_id": int(kb_id),
        "query": clean_query,
        "search_mode": result.get("search_mode"),
        "results": result.get("results") or [],
    }


def get_kb_tools() -> list:
    """返回可由 middleware 注入 Agent 的通用知识库工具列表。"""
    return [list_kbs, query_kb]
