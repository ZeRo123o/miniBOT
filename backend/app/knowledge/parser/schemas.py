from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class ParserDocument:
    """Immutable source document passed to a parser implementation."""

    filename: str
    content: bytes
    content_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def suffix(self) -> str:
        return Path(self.filename).suffix.lower()


@dataclass(slots=True)
class ParsedAsset:
    """Binary artifact extracted while parsing, such as a figure or chart."""

    asset_id: str
    kind: str = "image"
    content: bytes | None = None
    content_type: str = ""
    filename: str = ""
    page_number: int | None = None
    bbox: list[float] | None = None
    caption: str = ""
    ocr_text: str = ""
    semantic_description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedDocument:
    """Normalized parser output consumed by storage and chunking services."""

    markdown: str
    parser_id: str
    parser_version: str
    file_ext: str = ""
    assets: list[ParsedAsset] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        """Return metadata safe to persist without embedding document contents."""

        return {
            "parser_id": self.parser_id,
            "parser_version": self.parser_version,
            "file_ext": self.file_ext,
            "asset_count": len(self.assets),
            "warnings": list(self.warnings),
            **self.metadata,
        }
