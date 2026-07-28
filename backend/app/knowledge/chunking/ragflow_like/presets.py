from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

logger = logging.getLogger(__name__)

CHUNK_PRESET_GENERAL = "general"
CHUNK_PRESET_QA = "qa"
CHUNK_PRESET_BOOK = "book"
CHUNK_PRESET_LAWS = "laws"
CHUNK_PRESET_SEPARATOR = "separator"

CHUNK_PRESET_IDS = {
    CHUNK_PRESET_GENERAL,
    CHUNK_PRESET_QA,
    CHUNK_PRESET_BOOK,
    CHUNK_PRESET_LAWS,
    CHUNK_PRESET_SEPARATOR,
}

CHUNK_PRESET_DESCRIPTIONS = {
    CHUNK_PRESET_GENERAL: "按分隔符和长度合并，适合大多数普通文档。",
    CHUNK_PRESET_QA: "提取问题与回答结构，适合 FAQ、题库和问答手册。",
    CHUNK_PRESET_BOOK: "识别章节标题并保留层级上下文，适合教材、手册和长文档。",
    CHUNK_PRESET_LAWS: "按章、节、条层级组织，适合法律法规和制度规范。",
    CHUNK_PRESET_SEPARATOR: "命中分隔符即切分，仅对超长片段继续按长度切分。",
}

CHUNK_ENGINE_VERSION = "ragflow_like_v3_single_chunk"
GENERAL_INTERNAL_PARSER_ID = "naive"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并配置，调用方配置覆盖默认配置。"""
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def normalize_chunk_preset_id(value: str | None) -> str:
    """规范化策略 ID；空值或未知值回退到 General。"""
    if not value:
        return CHUNK_PRESET_GENERAL

    normalized = str(value).strip().lower()
    if normalized == GENERAL_INTERNAL_PARSER_ID:
        return CHUNK_PRESET_GENERAL
    if normalized in CHUNK_PRESET_IDS:
        return normalized

    logger.warning("Unknown chunk preset id '%s', fallback to general", value)
    return CHUNK_PRESET_GENERAL


def map_to_internal_parser_id(preset_id: str) -> str:
    """把对外的 general 名称映射为分块器内部的 naive 名称。"""
    normalized = normalize_chunk_preset_id(preset_id)
    return GENERAL_INTERNAL_PARSER_ID if normalized == CHUNK_PRESET_GENERAL else normalized


def get_default_chunk_parser_config(preset_id: str) -> dict[str, Any]:
    """返回指定策略的默认 parser 配置。"""
    normalized = normalize_chunk_preset_id(preset_id)
    config: dict[str, Any] = {
        # 与分块解析器的默认值保持一致：目标 512 个近似 token，
        # General 等策略最多允许保留到 1.5 倍后再执行硬切分。
        "chunk_token_num": 512,
        "delimiter": "\\n",
        "overlapped_percent": 0,
    }
    if normalized == CHUNK_PRESET_QA:
        return {"language": "Chinese"}
    return config


def resolve_chunk_processing_params(
    preset_id: str | None,
    parser_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """合并默认配置与用户配置，形成可持久化的标准分块参数。"""
    normalized = normalize_chunk_preset_id(preset_id)
    merged_config = deep_merge(
        get_default_chunk_parser_config(normalized),
        parser_config if isinstance(parser_config, dict) else {},
    )
    allowed_keys = (
        {"language"}
        if normalized == CHUNK_PRESET_QA
        else {"chunk_token_num", "delimiter", "overlapped_percent"}
    )
    return {
        "chunk_preset_id": normalized,
        "chunk_parser_config": {
            key: value
            for key, value in merged_config.items()
            if key in allowed_keys
        },
        "chunk_engine_version": CHUNK_ENGINE_VERSION,
    }


def get_chunk_preset_options() -> list[dict[str, Any]]:
    """返回前端分块策略选择器所需的选项和默认配置。"""
    labels = {
        CHUNK_PRESET_GENERAL: "General",
        CHUNK_PRESET_QA: "QA",
        CHUNK_PRESET_BOOK: "Book",
        CHUNK_PRESET_LAWS: "Laws",
        CHUNK_PRESET_SEPARATOR: "Separator",
    }
    return [
        {
            "value": preset_id,
            "label": labels[preset_id],
            "description": CHUNK_PRESET_DESCRIPTIONS[preset_id],
            "default_config": get_default_chunk_parser_config(preset_id),
        }
        for preset_id in (
            CHUNK_PRESET_GENERAL,
            CHUNK_PRESET_QA,
            CHUNK_PRESET_BOOK,
            CHUNK_PRESET_LAWS,
            CHUNK_PRESET_SEPARATOR,
        )
    ]
