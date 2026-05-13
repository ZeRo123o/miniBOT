from typing import Any

import httpx

from app.core.config import get_settings


async def tavily_search(query: str, config: dict[str, Any] | None = None) -> str:
    """调用 Tavily Search API 并把搜索结果格式化为适合模型阅读的文本。"""
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
        data = response.json()

    return _format_tavily_result(data)


def _format_tavily_result(data: dict[str, Any]) -> str:
    """把 Tavily 的 JSON 响应整理成包含标题、链接和摘要的文本。"""
    lines = ["Tavily 搜索结果:"]
    answer = data.get("answer")
    if answer:
        lines.append(f"综合回答: {answer}")

    results = data.get("results") or []
    if not results:
        lines.append("未找到相关结果。")
        return "\n".join(lines)

    for index, item in enumerate(results, start=1):
        title = item.get("title") or "未命名结果"
        url = item.get("url") or ""
        content = item.get("content") or item.get("raw_content") or ""
        lines.append(f"{index}. {title}")
        if url:
            lines.append(f"   URL: {url}")
        if content:
            lines.append(f"   摘要: {content[:600]}")
    return "\n".join(lines)
