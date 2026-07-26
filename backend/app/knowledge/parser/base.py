from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.knowledge.parser.schemas import ParsedDocument, ParserDocument


class DocumentParser(ABC):
    """Parser adapter contract modeled after Yuxi's processor registry."""

    parser_id = ""
    display_name = ""
    version = "1"
    priority = 0
    supported_extensions: frozenset[str] = frozenset()
    capabilities: frozenset[str] = frozenset()

    def supports(self, filename: str) -> bool:
        suffix = ParserDocument(filename=filename, content=b"").suffix
        return suffix in self.supported_extensions

    def is_auto_selectable(self) -> bool:
        """Return whether automatic routing may choose this parser."""

        return True

    def describe(self) -> dict[str, Any]:
        """Expose parser capabilities without importing implementation details."""

        return {
            "parser_id": self.parser_id,
            "display_name": self.display_name or self.parser_id,
            "version": self.version,
            "priority": self.priority,
            "supported_extensions": sorted(self.supported_extensions),
            "capabilities": sorted(self.capabilities),
        }

    async def health_check(self) -> dict[str, Any]:
        return {"status": "available", "parser_id": self.parser_id}

    @abstractmethod
    async def parse(
        self,
        document: ParserDocument,
        options: dict[str, Any] | None = None,
    ) -> ParsedDocument:
        """Convert one source document into a normalized parsed document."""
