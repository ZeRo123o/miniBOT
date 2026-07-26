from __future__ import annotations

import asyncio
import time
from typing import Any

from app.knowledge.parser.exceptions import (
    DocumentParserError,
    EmptyParseResultError,
    UnsupportedDocumentTypeError,
)
from app.knowledge.parser.registry import ParserRegistry, parser_registry
from app.knowledge.parser.schemas import ParsedDocument, ParserDocument

DEFAULT_PARSER_ID = "auto"
DEFAULT_FALLBACK_PARSER_ID = "builtin"
DEFAULT_TIMEOUT_SECONDS = 1800


def normalize_parser_config(
    parser_id: str | None = None,
    parser_config: dict[str, Any] | None = None,
    *,
    registry: ParserRegistry | None = None,
) -> dict[str, Any]:
    """Normalize persisted parser settings while retaining adapter-specific options."""

    config = dict(parser_config or {})
    configured_parser_id = config.pop("parser_id", None)
    selected_id = str(parser_id or configured_parser_id or DEFAULT_PARSER_ID).strip().lower()
    fallback_id = str(config.get("fallback_parser_id") or DEFAULT_FALLBACK_PARSER_ID).strip().lower()
    try:
        timeout_seconds = int(config.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    except (TypeError, ValueError) as error:
        raise ValueError("Parser timeout_seconds must be an integer.") from error
    if timeout_seconds < 1 or timeout_seconds > 3600:
        raise ValueError("Parser timeout_seconds must be between 1 and 3600.")
    resolved_registry = registry or parser_registry
    if selected_id != DEFAULT_PARSER_ID:
        resolved_registry.get(selected_id)
    resolved_registry.get(fallback_id)

    config["fallback_parser_id"] = fallback_id
    config["timeout_seconds"] = timeout_seconds
    return {"parser_id": selected_id, "parser_config": config}


class ParserFacade:
    """Select a parser, enforce timeout, and normalize fallback behavior."""

    def __init__(self, registry: ParserRegistry | None = None) -> None:
        self.registry = registry or parser_registry

    async def parse(
        self,
        document: ParserDocument,
        *,
        parser_id: str | None = None,
        parser_config: dict[str, Any] | None = None,
    ) -> ParsedDocument:
        settings = normalize_parser_config(parser_id, parser_config, registry=self.registry)
        selected = self._select_parser(settings["parser_id"], document.filename)
        fallback_id = settings["parser_config"]["fallback_parser_id"]
        timeout_seconds = settings["parser_config"]["timeout_seconds"]

        started_at = time.perf_counter()
        try:
            result = await self._run_parser(selected, document, settings["parser_config"], timeout_seconds)
        except (DocumentParserError, TimeoutError) as primary_error:
            if selected.parser_id == fallback_id:
                raise
            fallback = self.registry.get(fallback_id)
            if not fallback.supports(document.filename):
                raise primary_error
            result = await self._run_parser(fallback, document, settings["parser_config"], timeout_seconds)
            result.warnings.append(f"Parser '{selected.parser_id}' failed; used fallback '{fallback.parser_id}'.")
            result.metadata["fallback_from"] = selected.parser_id

        result.metadata.setdefault("duration_ms", round((time.perf_counter() - started_at) * 1000))
        return result

    def _select_parser(self, parser_id: str, filename: str):
        if parser_id != DEFAULT_PARSER_ID:
            parser = self.registry.get(parser_id)
            if not parser.supports(filename):
                raise UnsupportedDocumentTypeError(
                    f"Parser '{parser_id}' does not support this document type.",
                    parser_id=parser_id,
                )
            return parser

        # Registry priority lets future OCR/layout parsers take precedence over
        # builtin extraction without changing persisted "auto" configurations.
        for parser in self.registry.list():
            if parser.is_auto_selectable() and parser.supports(filename):
                return parser
        raise UnsupportedDocumentTypeError(f"Unsupported document type for file: {filename}")

    async def _run_parser(
        self,
        parser,
        document: ParserDocument,
        options: dict[str, Any],
        timeout_seconds: int,
    ) -> ParsedDocument:
        try:
            result = await asyncio.wait_for(parser.parse(document, options), timeout=timeout_seconds)
        except TimeoutError as error:
            raise DocumentParserError(
                f"Document parser timed out after {timeout_seconds} seconds.",
                parser_id=parser.parser_id,
            ) from error
        if not result.markdown.strip():
            raise EmptyParseResultError("Parsed markdown is empty.", parser_id=parser.parser_id)
        return result


async def parse_document(
    filename: str,
    content: bytes,
    *,
    content_type: str = "",
    parser_id: str | None = None,
    parser_config: dict[str, Any] | None = None,
) -> ParsedDocument:
    """Public structured parsing entry point used by knowledge ingestion."""

    document = ParserDocument(filename=filename, content=content, content_type=content_type)
    return await ParserFacade().parse(
        document,
        parser_id=parser_id,
        parser_config=parser_config,
    )


def get_parser_options() -> list[dict[str, Any]]:
    """Return UI-safe parser options including automatic selection."""

    return [
        {
            "parser_id": DEFAULT_PARSER_ID,
            "display_name": "Automatic",
            "version": "1",
            "supported_extensions": sorted(
                {extension for parser in parser_registry.list() for extension in parser.supported_extensions}
            ),
            "capabilities": sorted(
                {capability for parser in parser_registry.list() for capability in parser.capabilities}
            ),
        },
        *(parser.describe() for parser in parser_registry.list()),
    ]


async def get_parser_health(parser_id: str) -> dict[str, Any]:
    """Run the selected adapter's non-mutating availability check."""

    return await parser_registry.get(parser_id).health_check()
