from __future__ import annotations

# Adapted from xerrors/Yuxi knowledge chunking under the MIT license.
from typing import Any

from app.chunking.ragflow_like import nlp
from app.chunking.ragflow_like.parsers.general import _iter_sections, _unescape_delimiter


def _slice_text_by_tokens(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    """按近似 token 上限切分单个超长 section，并保留指定重叠内容。"""
    if max_tokens <= 0:
        return [text] if text.strip() else []

    units = [part for part in text]
    chunks: list[str] = []
    start = 0

    while start < len(units):
        current = ""
        current_tokens = 0
        end = start

        while end < len(units):
            next_text = current + units[end]
            next_tokens = nlp.count_tokens(next_text)
            if current and next_tokens > max_tokens:
                break
            current = next_text
            current_tokens = next_tokens
            end += 1
            if current_tokens >= max_tokens:
                break

        chunk = current.strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(units):
            break

        if overlap_tokens <= 0:
            start = end
            continue

        # 从当前切点向前回溯，计算下一块需要携带的重叠文本。
        backtrack = end
        overlap_text = ""
        while backtrack > start:
            candidate = units[backtrack - 1] + overlap_text
            if nlp.count_tokens(candidate) > overlap_tokens:
                break
            overlap_text = candidate
            backtrack -= 1

        start = backtrack if backtrack < end else end

    return chunks


def _split_section_with_overlap(section: str, chunk_token_num: int, overlapped_percent: int) -> list[str]:
    """把百分比重叠配置换算为 token 数后切分 section。"""
    overlap_tokens = 0
    if chunk_token_num > 0 and overlapped_percent > 0:
        overlap_tokens = int(chunk_token_num * max(0, min(overlapped_percent, 99)) / 100)
    return _slice_text_by_tokens(section, chunk_token_num, overlap_tokens)


def chunk_markdown(markdown_content: str, parser_config: dict[str, Any] | None = None) -> list[str]:
    """严格分隔策略：每个 section 独立成块，仅超长 section 继续切分。"""
    parser_config = parser_config or {}

    delimiter = _unescape_delimiter(str(parser_config.get("delimiter", "\n") or "\n"))
    chunk_token_num = int(parser_config.get("chunk_token_num", 512) or 512)
    overlapped_percent = int(parser_config.get("overlapped_percent", 0) or 0)

    sections = _iter_sections(markdown_content, delimiter)
    chunks: list[str] = []

    for section, _ in sections:
        text = (section or "").strip()
        if not text:
            continue

        if chunk_token_num > 0 and nlp.count_tokens(text) > chunk_token_num:
            chunks.extend(_split_section_with_overlap(text, chunk_token_num, overlapped_percent))
            continue

        chunks.append(text)

    return chunks
