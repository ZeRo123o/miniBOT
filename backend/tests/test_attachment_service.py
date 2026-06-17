from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import UploadFile

from app.agents.backends.sandbox.paths import conversation_uploads_dir
from app.services.attachment_service import (
    build_attachment_state_files,
    save_chat_uploads,
    truncate_attachment_markdown,
)


class AttachmentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_limit_uses_chat_upload_setting(self):
        file = UploadFile(filename="demo.txt", file=BytesIO(b"hello"))

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("app.agents.backends.sandbox.paths.runtime_root", return_value=Path(tmp)),
                patch(
                    "app.services.attachment_service.get_settings",
                    return_value=SimpleNamespace(
                        chat_upload_max_bytes=8,
                        chat_attachment_markdown_max_chars=32000,
                    ),
                ),
            ):
                uploads = await save_chat_uploads(user_id="default", conversation_id=1, files=[file])

        self.assertEqual(uploads[0]["file_name"], "demo.txt")
        self.assertEqual(uploads[0]["size"], 5)
        self.assertTrue(uploads[0]["path"].startswith("/mnt/user-data/uploads/demo-"))
        self.assertTrue(uploads[0]["path"].endswith(".extracted.md"))
        self.assertTrue(uploads[0]["original_path"].startswith("/mnt/user-data/uploads/demo-"))

    async def test_upload_saves_readable_sidecar_for_supported_documents(self):
        file = UploadFile(filename="notes.txt", file=BytesIO(b"hello miniBOT"))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("app.agents.backends.sandbox.paths.runtime_root", return_value=root):
                uploads = await save_chat_uploads(user_id="default", conversation_id=2, files=[file])

            readable_name = uploads[0]["path"].rsplit("/", 1)[-1]
            original_name = uploads[0]["original_path"].rsplit("/", 1)[-1]
            with patch("app.agents.backends.sandbox.paths.runtime_root", return_value=root):
                upload_root = conversation_uploads_dir("default", 2)

            self.assertEqual((upload_root / readable_name).read_text(encoding="utf-8"), "hello miniBOT")
            self.assertEqual((upload_root / original_name).read_bytes(), b"hello miniBOT")
            self.assertEqual(uploads[0]["status"], "parsed")
            self.assertEqual(uploads[0]["markdown"], "hello miniBOT")

    def test_attachment_markdown_truncation_and_state_files(self):
        markdown, truncated = truncate_attachment_markdown("abcdef", 5)

        self.assertTrue(truncated)
        self.assertLessEqual(len(markdown), len("[内容已截断，超出 5 字符限制]") + 2)

        files = build_attachment_state_files(
            [
                {
                    "status": "parsed",
                    "file_path": "/mnt/user-data/uploads/demo.extracted.md",
                    "markdown": "line1\nline2",
                    "uploaded_at": "2026-06-17T00:00:00+08:00",
                }
            ]
        )

        self.assertEqual(
            files["/mnt/user-data/uploads/demo.extracted.md"]["content"],
            ["line1", "line2"],
        )

    async def test_extracted_file_keeps_full_markdown_but_state_uses_preview(self):
        file = UploadFile(filename="long.txt", file=BytesIO(b"abcdefghij"))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch("app.agents.backends.sandbox.paths.runtime_root", return_value=root),
                patch(
                    "app.services.attachment_service.get_settings",
                    return_value=SimpleNamespace(
                        chat_upload_max_bytes=128,
                        chat_attachment_markdown_max_chars=6,
                    ),
                ),
            ):
                uploads = await save_chat_uploads(user_id="default", conversation_id=3, files=[file])

            readable_name = uploads[0]["path"].rsplit("/", 1)[-1]
            with patch("app.agents.backends.sandbox.paths.runtime_root", return_value=root):
                upload_root = conversation_uploads_dir("default", 3)

            self.assertEqual((upload_root / readable_name).read_text(encoding="utf-8"), "abcdefghij")
            self.assertTrue(uploads[0]["truncated"])
            self.assertNotEqual(uploads[0]["markdown"], "abcdefghij")
            self.assertEqual(uploads[0]["markdown_chars"], 10)


if __name__ == "__main__":
    unittest.main()
