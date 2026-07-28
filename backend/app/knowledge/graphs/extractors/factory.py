from __future__ import annotations

from typing import Any

from app.knowledge.graphs.extractors.base import GraphExtractor
from app.knowledge.graphs.extractors.llm import LLMGraphExtractor


class GraphExtractorFactory:
    """根据抽取器类型创建实现。"""

    _extractors: dict[str, type[GraphExtractor]] = {
        "llm": LLMGraphExtractor,
    }

    @classmethod
    def create(
        cls,
        extractor_type: str | None,
        options: dict[str, Any] | None = None,
    ) -> GraphExtractor:
        normalized_type = str(extractor_type or "llm").strip().lower()
        extractor_class = cls._extractors.get(normalized_type)
        if extractor_class is None:
            raise ValueError(f"不支持的图抽取器类型：{normalized_type}")
        extractor = extractor_class(options)
        extractor.validate_options()
        return extractor

    @classmethod
    def supported_types(cls) -> list[str]:
        return sorted(cls._extractors)
