from __future__ import annotations

import unittest
import zipfile
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.knowledge.parser import get_parser_options, parse_document, parse_document_to_markdown
from app.knowledge.parser.base import DocumentParser
from app.knowledge.parser.builtin import BuiltinDocumentParser
from app.knowledge.parser.exceptions import DocumentParserError, ParserNotFoundError
from app.knowledge.parser.facade import ParserFacade, normalize_parser_config
from app.knowledge.parser.registry import ParserRegistry
from app.knowledge.parser.schemas import ParsedAsset, ParsedDocument, ParserDocument


class FailingTextParser(DocumentParser):
    parser_id = "failing"
    display_name = "Failing parser"
    version = "test"
    priority = 100
    supported_extensions = frozenset({".txt"})

    async def parse(self, document: ParserDocument, options=None) -> ParsedDocument:
        del document, options
        raise DocumentParserError("expected test failure", parser_id=self.parser_id)


class DocumentParserTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_parser_returns_structured_builtin_result(self):
        result = await parse_document("notes.txt", "你好，miniBOT".encode())

        self.assertEqual(result.markdown, "你好，miniBOT")
        self.assertEqual(result.parser_id, "builtin")
        self.assertEqual(result.file_ext, ".txt")
        self.assertIn("duration_ms", result.metadata)

    def test_sync_compatibility_entry_point_preserves_csv_behavior(self):
        markdown = parse_document_to_markdown("items.csv", b"name,value\nalpha,1")

        self.assertIn("| name | value |", markdown)
        self.assertIn("| alpha | 1 |", markdown)

    async def test_facade_falls_back_to_builtin_parser(self):
        registry = ParserRegistry()
        registry.register(FailingTextParser())
        registry.register(BuiltinDocumentParser())

        result = await ParserFacade(registry).parse(
            ParserDocument(filename="notes.txt", content=b"fallback"),
            parser_id="auto",
            parser_config={"fallback_parser_id": "builtin"},
        )

        self.assertEqual(result.parser_id, "builtin")
        self.assertEqual(result.metadata["fallback_from"], "failing")
        self.assertEqual(len(result.warnings), 1)

    def test_unknown_parser_is_rejected_during_config_normalization(self):
        with self.assertRaises(ParserNotFoundError):
            normalize_parser_config("missing")

    def test_parser_options_expose_auto_and_builtin(self):
        parser_ids = [item["parser_id"] for item in get_parser_options()]

        self.assertEqual(parser_ids[0], "auto")
        self.assertIn("builtin", parser_ids)
        self.assertIn("mineru", parser_ids)

    async def test_mineru_zip_response_returns_markdown_and_assets(self):
        archive_buffer = BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as archive:
            archive.writestr("result/full.md", "# Report\n\n![Revenue](images/chart.png)")
            archive.writestr("result/images/chart.png", b"fake-png-content")

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return False

            async def post(self, url, **kwargs):
                self.request_url = url
                request = httpx.Request("POST", url)
                return httpx.Response(
                    200,
                    request=request,
                    headers={"content-type": "application/zip"},
                    content=archive_buffer.getvalue(),
                )

        settings = SimpleNamespace(
            mineru_enabled=True,
            mineru_auto_select=False,
            mineru_api_url="http://mineru.test:30001",
            mineru_timeout_seconds=1800,
            mineru_health_timeout_seconds=5.0,
            mineru_max_response_bytes=1024 * 1024,
            mineru_max_archive_files=20,
            mineru_max_archive_uncompressed_bytes=1024 * 1024,
        )
        with (
            patch("app.knowledge.parser.mineru.get_settings", return_value=settings),
            patch("app.knowledge.parser.mineru.httpx.AsyncClient", FakeAsyncClient),
        ):
            result = await parse_document(
                "report.pdf",
                b"%PDF-test",
                content_type="application/pdf",
                parser_id="mineru",
            )

        self.assertEqual(result.parser_id, "mineru")
        self.assertIn("kb-asset://mineru_", result.markdown)
        self.assertEqual(len(result.assets), 1)
        self.assertEqual(result.assets[0].caption, "Revenue")
        self.assertEqual(result.assets[0].content, b"fake-png-content")

    async def test_disabled_mineru_health_check_is_non_mutating(self):
        settings = SimpleNamespace(
            mineru_enabled=False,
            mineru_auto_select=False,
            mineru_api_url="",
        )
        with patch("app.knowledge.parser.mineru.get_settings", return_value=settings):
            from app.knowledge.parser import get_parser_health

            result = await get_parser_health("mineru")

        self.assertEqual(result["status"], "disabled")

    async def test_knowledge_service_persists_parser_assets_without_binary_metadata(self):
        from app.services.knowledge_service import KnowledgeService

        writes: list[tuple[str, bytes, str]] = []

        class FakeStorage:
            async def put_bytes(self, object_key, data, content_type=None):
                writes.append((object_key, data, content_type))
                return object_key

        service = KnowledgeService.__new__(KnowledgeService)
        service.storage = FakeStorage()
        parsed_document = ParsedDocument(
            markdown="![Chart](kb-asset://asset_1)",
            parser_id="mineru",
            parser_version="1",
            assets=[
                ParsedAsset(
                    asset_id="asset_1",
                    filename="chart.png",
                    content=b"image-bytes",
                    content_type="image/png",
                    caption="Chart",
                )
            ],
        )

        records = await service._persist_parsed_assets(
            knowledge_base_id=7,
            file_hash="abc123",
            parsed_document=parsed_document,
        )

        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0], "knowledge-bases/7/documents/abc123/assets/asset_1.png")
        self.assertEqual(records[0]["object_key"], writes[0][0])
        self.assertNotIn("content", records[0])
        self.assertIsNone(parsed_document.assets[0].content)


if __name__ == "__main__":
    unittest.main()
