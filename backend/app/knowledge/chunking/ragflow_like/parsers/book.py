from __future__ import annotations

# Adapted from xerrors/Yuxi knowledge chunking under the MIT license.
from typing import Any

from app.knowledge.chunking.ragflow_like import nlp


def _unescape_delimiter(delimiter: str) -> str:
    """将配置中的转义分隔符还原为真实字符。"""
    return delimiter.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t").replace("\\\\", "\\")


def _iter_sections(markdown_content: str) -> list[tuple[str, str]]:
    """将书籍 Markdown 转为非空行 section，供标题层级识别使用。"""
    sections: list[tuple[str, str]] = []
    for line in (markdown_content or "").splitlines():
        text = line.strip()
        if not text:
            continue
        sections.append((text, ""))

    if not sections and markdown_content and markdown_content.strip():
        sections.append((markdown_content.strip(), ""))

    return sections


def _ensure_chunk_token_limit(chunks: list[str], chunk_token_num: int) -> list[str]:
    """对章节合并结果执行严格 token 上限保护。"""
    max_tokens = int(chunk_token_num or 0)
    normalized = [chunk.strip() for chunk in chunks if chunk and chunk.strip()]
    if max_tokens <= 0:
        return normalized

    protected: list[str] = []
    for chunk in normalized:
        if nlp.count_tokens(chunk) <= max_tokens:
            protected.append(chunk)
        else:
            protected.extend(nlp.hard_split_by_token_limit(chunk, max_tokens))
    return protected


def chunk_markdown(markdown_content: str, parser_config: dict[str, Any] | None = None) -> list[str]:
    """书籍分块：识别章节编号和标题层级，并把上级标题带入正文块。"""
    parser_config = parser_config or {}

    delimiter = _unescape_delimiter(str(parser_config.get("delimiter", "\n") or "\n"))
    chunk_token_num = int(parser_config.get("chunk_token_num", 512) or 512)
    overlapped_percent = int(parser_config.get("overlapped_percent", 0) or 0)

    sections = _iter_sections(markdown_content)
    if not sections:
        return []

    section_texts = [text for text, _ in sections]
    # 目录会制造大量与正文重复的标题，层级分析前先尝试移除。
    nlp.remove_contents_table(sections, eng=nlp.is_english(nlp.random_choices(section_texts, k=200)))
    nlp.make_colon_as_title(sections)

    bull = nlp.bullets_category([t for t in nlp.random_choices([t for t, _ in sections], k=100)])

    if bull >= 0:
        # 识别出稳定编号体系后，优先按标题层级组织上下文。
        chunks = ["\n".join(ck) for ck in nlp.hierarchical_merge(bull, sections, depth=5)]
    else:
        chunks = nlp.naive_merge(
            sections,
            chunk_token_num=chunk_token_num,
            delimiter=delimiter,
            overlapped_percent=overlapped_percent,
        )

    if chunks:
        return _ensure_chunk_token_limit(chunks, chunk_token_num)

    return _ensure_chunk_token_limit(
        nlp.naive_merge(
            sections,
            chunk_token_num=chunk_token_num,
            delimiter=delimiter,
            overlapped_percent=overlapped_percent,
        ),
        chunk_token_num,
    )
