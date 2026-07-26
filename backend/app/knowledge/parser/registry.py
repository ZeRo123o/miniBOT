from __future__ import annotations

from app.knowledge.parser.base import DocumentParser
from app.knowledge.parser.builtin import BuiltinDocumentParser
from app.knowledge.parser.exceptions import ParserNotFoundError
from app.knowledge.parser.mineru import MinerUDocumentParser


class ParserRegistry:
    """Small trusted registry for parser adapters bundled with the backend."""

    def __init__(self) -> None:
        self._parsers: dict[str, DocumentParser] = {}

    def register(self, parser: DocumentParser) -> None:
        parser_id = parser.parser_id.strip()
        if not parser_id:
            raise ValueError("Parser id is required.")
        if parser_id in self._parsers:
            raise ValueError(f"Parser already registered: {parser_id}")
        self._parsers[parser_id] = parser

    def get(self, parser_id: str) -> DocumentParser:
        parser = self._parsers.get(parser_id)
        if parser is None:
            raise ParserNotFoundError(f"Unknown document parser: {parser_id}", parser_id=parser_id)
        return parser

    def list(self) -> list[DocumentParser]:
        # Specialized OCR/layout parsers can opt into automatic selection by
        # declaring a higher priority than the dependency-light builtin parser.
        return sorted(self._parsers.values(), key=lambda parser: parser.priority, reverse=True)


parser_registry = ParserRegistry()
parser_registry.register(BuiltinDocumentParser())
parser_registry.register(MinerUDocumentParser())
