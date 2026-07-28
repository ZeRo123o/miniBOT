from __future__ import annotations

from typing import Any

from app.knowledge.chunking.ragflow_like import nlp
from app.knowledge.chunking.ragflow_like.parsers import book, general, laws, qa, separator
from app.knowledge.chunking.ragflow_like.presets import (
    CHUNK_ENGINE_VERSION,
    map_to_internal_parser_id,
    resolve_chunk_processing_params,
)

def _build_chunk_records(
    text_chunks: list[str],
    *,
    file_id: str,
    filename: str,
    preset_id: str,
    source_text: str,
) -> list[dict[str, Any]]:
    """将解析器输出直接转换为唯一的、可检索的单层 Chunk。"""
    records: list[dict[str, Any]] = []
    search_start = 0
    for index, chunk_content in enumerate(text_chunks):
        text = (chunk_content or "").strip()
        if not text:
            continue

        # 位置只用于文档内定位；找不到时保持为空，不影响索引与召回。
        start_char_pos = source_text.find(text, search_start)
        if start_char_pos < 0:
            start_char_pos = source_text.find(text)
        end_char_pos = start_char_pos + len(text) if start_char_pos >= 0 else None
        if end_char_pos is not None:
            search_start = end_char_pos

        records.append(
            {
                "chunk_id": f"{file_id}_chunk_{index}",
                "content": text,
                "filename": filename,
                "chunk_index": index,
                "token_count": nlp.count_tokens(text),
                "start_char_pos": start_char_pos if start_char_pos >= 0 else None,
                "end_char_pos": end_char_pos,
                "metadata": {
                    "source": filename,
                    "engine": CHUNK_ENGINE_VERSION,
                    "chunk_preset_id": preset_id,
                },
            }
        )

    return records


def _dispatch_parser(
    preset_id: str,
    filename: str,
    markdown_content: str,
    parser_config: dict[str, Any],
) -> list[str]:
    """Route normalized preset IDs to the existing first-level chunker."""
    parser_id = map_to_internal_parser_id(preset_id)
    if parser_id == "naive":
        return general.chunk_markdown(markdown_content, parser_config)
    if parser_id == "qa":
        return qa.chunk_markdown(filename, markdown_content, parser_config)
    if parser_id == "book":
        return book.chunk_markdown(markdown_content, parser_config)
    if parser_id == "laws":
        return laws.chunk_markdown(filename, markdown_content, parser_config)
    if parser_id == "separator":
        return separator.chunk_markdown(markdown_content, parser_config)
    return general.chunk_markdown(markdown_content, parser_config)


def chunk_markdown(
    markdown_content: str,
    *,
    file_id: str,
    filename: str,
    preset_id: str | None = None,
    parser_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """按所选策略把 Markdown 切成单层 Chunk。"""
    params = resolve_chunk_processing_params(preset_id, parser_config)
    normalized_preset = params["chunk_preset_id"]
    normalized_config = params["chunk_parser_config"]
    text_chunks = _dispatch_parser(
        normalized_preset,
        filename,
        markdown_content,
        normalized_config,
    )
    return _build_chunk_records(
        text_chunks,
        file_id=file_id,
        filename=filename,
        preset_id=normalized_preset,
        source_text=markdown_content,
    )
