from __future__ import annotations

from typing import Any

from app.chunking.ragflow_like import nlp
from app.chunking.ragflow_like.parsers import book, general, laws, qa, separator
from app.chunking.ragflow_like.presets import (
    CHUNK_ENGINE_VERSION,
    map_to_internal_parser_id,
    resolve_chunk_processing_params,
)


def _build_chunk_records(
    text_chunks: list[str],
    *,
    file_id: str,
    filename: str,
    source_text: str,
    preset_id: str,
) -> list[dict[str, Any]]:
    """将 parser 产生的纯文本块转换为统一的入库记录。"""
    records: list[dict[str, Any]] = []
    search_from = 0

    for index, chunk_content in enumerate(text_chunks):
        text = (chunk_content or "").strip()
        if not text:
            continue

        start_char_pos = None
        end_char_pos = None
        # 从上一个块末尾继续定位，避免重复文本总是命中首次出现的位置。
        found_at = source_text.find(text, search_from)
        if found_at >= 0:
            start_char_pos = found_at
            end_char_pos = found_at + len(text)
            search_from = end_char_pos

        records.append(
            {
                "chunk_id": f"{file_id}_chunk_{index}",
                "content": text,
                "filename": filename,
                "chunk_index": index,
                "token_count": nlp.count_tokens(text),
                "start_char_pos": start_char_pos,
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
    """根据标准化后的策略 ID 调用对应分块器。"""
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
    """统一分块入口：补全配置、执行具体策略并生成标准 chunk 记录。"""
    params = resolve_chunk_processing_params(preset_id, parser_config)
    normalized_preset = params["chunk_preset_id"]
    text_chunks = _dispatch_parser(
        normalized_preset,
        filename,
        markdown_content,
        params["chunk_parser_config"],
    )
    return _build_chunk_records(
        text_chunks,
        file_id=file_id,
        filename=filename,
        source_text=markdown_content or "",
        preset_id=normalized_preset,
    )
