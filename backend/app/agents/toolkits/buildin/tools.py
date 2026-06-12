import json
import logging
from typing import Annotated, Any

import httpx
from langchain.tools import InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.agents.toolkits.registry import get_tool_config, tool
from app.agents.toolkits.governance import fail_tool_call, finish_tool_call, start_tool_call
from app.agents.sandbox.paths import VIRTUAL_OUTPUTS_ROOT, resolve_host_path
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class PresentArtifactsInput(BaseModel):
    """需要展示给用户的交付物路径。"""

    filepaths: list[str] = Field(
        description="位于 /mnt/user-data/outputs 下的沙盒绝对路径列表"
    )


class TavilySearchInput(BaseModel):
    """Tavily 网页搜索输入。"""

    query: str = Field(
        min_length=1,
        description="需要搜索或查证的问题，应包含明确的主题、实体或时间范围。",
    )


def _runtime_context(runtime: ToolRuntime | None) -> Any:
    return runtime.context if runtime is not None else None


def _normalize_presented_artifact_path(filepath: str, runtime: ToolRuntime) -> str:
    """只允许展示当前会话沙盒 outputs 目录中的普通文件。"""
    context = _runtime_context(runtime)
    user_key = str(getattr(context, "user_key", "") or "").strip()
    conversation_id = getattr(context, "conversation_id", None)
    if not user_key or conversation_id is None:
        raise ValueError("当前运行时缺少用户或会话信息")

    normalized = str(filepath or "").strip()
    if not normalized:
        raise ValueError("文件路径不能为空")

    if not (
        normalized == VIRTUAL_OUTPUTS_ROOT
        or normalized.startswith(f"{VIRTUAL_OUTPUTS_ROOT}/")
    ):
        raise ValueError(f"只允许展示 {VIRTUAL_OUTPUTS_ROOT} 下的文件")
    actual_path = resolve_host_path(
        user_key,
        int(conversation_id),
        normalized,
    )
    if not actual_path.is_file():
        raise ValueError(f"文件不存在或不是普通文件: {normalized}")
    return str(actual_path)


PRESENT_ARTIFACTS_DESCRIPTION = """
将已经生成好的结果文件展示给用户。

只能传入 /mnt/user-data/outputs 下的最终交付物，不要传入中间过程文件。
"""


@tool(
    category="buildin",
    tags=["文件", "交付物"],
    display_name="展示交付物",
    description=PRESENT_ARTIFACTS_DESCRIPTION,
    args_schema=PresentArtifactsInput,
)
def present_artifacts(
    filepaths: list[str],
    runtime: ToolRuntime,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """登记当前会话 outputs 目录下的交付物。"""
    context = _runtime_context(runtime)
    event = start_tool_call(
        context,
        tool_name="present_artifacts",
        payload={"filepaths": filepaths},
    )

    try:
        normalized_paths = [
            _normalize_presented_artifact_path(filepath, runtime)
            for filepath in filepaths
        ]
    except ValueError as error:
        fail_tool_call(event, error)
        return Command(
            update={"messages": [ToolMessage(content=f"Error: {error}", tool_call_id=tool_call_id)]}
        )

    finish_tool_call(event, artifacts=normalized_paths)
    return Command(
        update={
            "artifacts": normalized_paths,
            "messages": [
                ToolMessage(content="已将交付物展示给用户", tool_call_id=tool_call_id)
            ],
        }
    )


ASK_USER_QUESTION_DESCRIPTION = """
在执行过程中，当需要用户做决定或补充关键需求时，使用这个工具发起交互式提问。

questions 提供 1-5 个问题，每项包含 question、options、multi_select、allow_other，
可选 question_id。不要询问是否继续执行，也不要在信息充分时滥用。
"""


def _normalize_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """规范化交互问题，生成稳定 question_id 并过滤无效选项。"""
    normalized = []
    for index, item in enumerate(questions[:5], start=1):
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            continue

        options = []
        for option in (item.get("options") or [])[:5]:
            if not isinstance(option, dict):
                continue
            label = str(option.get("label") or "").strip()
            value = str(option.get("value") or label).strip()
            if label and value:
                options.append({"label": label, "value": value})

        normalized.append(
            {
                "question_id": str(item.get("question_id") or f"question_{index}"),
                "question": question,
                "options": options,
                "multi_select": bool(item.get("multi_select", False)),
                "allow_other": bool(item.get("allow_other", True)),
            }
        )
    return normalized


@tool(
    category="buildin",
    tags=["交互"],
    display_name="向用户提问",
    description=ASK_USER_QUESTION_DESCRIPTION,
)
def ask_user_question(
    questions: Annotated[
        list[dict] | str | None,
        "问题列表，每项格式为 {question, options, multi_select, allow_other, question_id(optional)}",
    ] = None,
) -> dict:
    """向用户发起问题并等待回答。"""
    if isinstance(questions, str):
        try:
            questions = json.loads(questions)
        except json.JSONDecodeError:
            questions = None

    normalized_questions = _normalize_questions(questions or [])
    if not normalized_questions:
        raise ValueError("questions 至少需要包含一个有效问题")

    answer = interrupt(
        {
            "questions": normalized_questions,
            "source": "ask_user_question",
        }
    )
    return {"questions": normalized_questions, "answer": answer}


@tool(
    category="buildin",
    tags=["搜索"],
    display_name="Tavily 网页搜索",
    args_schema=TavilySearchInput,
)
async def tavily_search(
    query: str,
    runtime: ToolRuntime | None = None,
) -> str:
    """搜索网页以获取最新信息、新闻、版本变化、价格或外部事实。"""
    clean_query = query.strip()
    if not clean_query:
        return "请提供需要搜索的问题。"

    context = _runtime_context(runtime)
    event = start_tool_call(
        context,
        tool_name="tavily_search",
        payload={"query": clean_query},
    )

    try:
        result = await _run_tavily_search(
            clean_query,
            config=get_tool_config(context, "tavily_search"),
        )
    except Exception as error:
        fail_tool_call(event, error)
        return f"Tavily 搜索调用失败：{error}"

    finish_tool_call(event)
    return result


async def _run_tavily_search(
    query: str,
    config: dict[str, Any] | None = None,
) -> str:
    """调用 Tavily API，并把响应整理成适合模型阅读的文本。"""
    settings = get_settings()
    tool_config = config or {}
    api_key = tool_config.get("api_key") or settings.tavily_api_key
    if not api_key:
        return "Tavily 搜索未配置 API Key，请设置 MINIBOT_TAVILY_API_KEY。"

    payload = {
        "query": query,
        "max_results": int(tool_config.get("max_results") or settings.tavily_max_results),
        "search_depth": tool_config.get("search_depth") or settings.tavily_search_depth,
        "include_answer": bool(tool_config.get("include_answer", False)),
        "include_raw_content": bool(tool_config.get("include_raw_content", False)),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{settings.tavily_base_url.rstrip('/')}/search",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        return _format_tavily_result(response.json())


def _format_tavily_result(data: dict[str, Any]) -> str:
    """整理 Tavily 的标题、链接、摘要和可选综合回答。"""
    lines = ["Tavily 搜索结果:"]
    if data.get("answer"):
        lines.append(f"综合回答: {data['answer']}")

    results = data.get("results") or []
    if not results:
        lines.append("未找到相关结果。")
        return "\n".join(lines)

    for index, item in enumerate(results, start=1):
        lines.append(f"{index}. {item.get('title') or '未命名结果'}")
        if item.get("url"):
            lines.append(f"   URL: {item['url']}")
        content = item.get("content") or item.get("raw_content") or ""
        if content:
            lines.append(f"   摘要: {content[:600]}")
    return "\n".join(lines)
