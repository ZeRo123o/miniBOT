"""Compatibility entry point for callers that still need synchronous parsing."""

from app.knowledge.parser.builtin import (
    BUILTIN_SUPPORTED_EXTENSIONS,
    parse_builtin_document_to_markdown,
)

SUPPORTED_MARKDOWN_EXTENSIONS = set(BUILTIN_SUPPORTED_EXTENSIONS)


def parse_document_to_markdown(filename: str, content: bytes) -> str:
    """Parse with the dependency-light builtin adapter.

    Knowledge-base ingestion uses the structured async facade. This function is
    intentionally retained for existing attachment integrations.
    """

    return parse_builtin_document_to_markdown(filename, content)
