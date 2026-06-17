from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.backends.filesystem import create_agent_filesystem_backend
from app.agents.backends.sandbox.paths import (
    VIRTUAL_UPLOADS_ROOT,
    VIRTUAL_USER_DATA_ROOT,
    VIRTUAL_WORKSPACE_ROOT,
    conversation_uploads_dir,
    ensure_scope_dirs,
)
from app.agents.buildin.chatbot.context import AgentContext


class AgentFilesystemBackendTests(unittest.TestCase):
    def _backend(self, root: Path):
        context = AgentContext(user_id="default", conversation_id=7)
        runtime = SimpleNamespace(context=context)
        with patch("app.agents.backends.sandbox.paths.runtime_root", return_value=root):
            ensure_scope_dirs("default", 7)
            backend = create_agent_filesystem_backend(runtime)
        self.assertIsNotNone(backend)
        return backend

    def test_workspace_write_read_list_glob_and_grep(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = self._backend(root)

            with patch("app.agents.backends.sandbox.paths.runtime_root", return_value=root):
                write_result = backend.write(f"{VIRTUAL_WORKSPACE_ROOT}/notes/demo.txt", "hello miniBOT\nbye")
                self.assertIsNone(write_result.error)

                read_result = backend.read(f"{VIRTUAL_WORKSPACE_ROOT}/notes/demo.txt")
                self.assertIsNone(read_result.error)
                self.assertEqual(read_result.content, "hello miniBOT\nbye")

                list_result = backend.ls(VIRTUAL_USER_DATA_ROOT)
                self.assertIsNone(list_result.error)
                self.assertEqual(
                    [entry["path"] for entry in list_result.entries],
                    [
                        f"{VIRTUAL_WORKSPACE_ROOT}",
                        f"{VIRTUAL_UPLOADS_ROOT}",
                        "/mnt/user-data/outputs",
                    ],
                )

                glob_result = backend.glob(VIRTUAL_WORKSPACE_ROOT, "**/*.txt")
                self.assertIsNone(glob_result.error)
                self.assertEqual(glob_result.matches, [f"{VIRTUAL_WORKSPACE_ROOT}/notes/demo.txt"])

                grep_result = backend.grep(VIRTUAL_WORKSPACE_ROOT, "minibot", glob="**/*.txt")
                self.assertIsNone(grep_result.error)
                self.assertEqual(
                    grep_result.matches,
                    [f"{VIRTUAL_WORKSPACE_ROOT}/notes/demo.txt:1: hello miniBOT"],
                )

    def test_rejects_read_only_upload_writes_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = self._backend(root)

            with patch("app.agents.backends.sandbox.paths.runtime_root", return_value=root):
                upload_root = conversation_uploads_dir("default", 7)
                upload_root.mkdir(parents=True, exist_ok=True)
                (upload_root / "input.txt").write_text("uploaded", encoding="utf-8")

                read_result = backend.read(f"{VIRTUAL_UPLOADS_ROOT}/input.txt")
                self.assertIsNone(read_result.error)
                self.assertEqual(read_result.content, "uploaded")

                write_result = backend.write(f"{VIRTUAL_UPLOADS_ROOT}/input.txt", "changed")
                self.assertIsNotNone(write_result.error)
                self.assertIn("write is allowed only", write_result.error)

                traversal_result = backend.read(f"{VIRTUAL_WORKSPACE_ROOT}/../secret.txt")
                self.assertIsNotNone(traversal_result.error)
                self.assertIn("path traversal", traversal_result.error)


if __name__ == "__main__":
    unittest.main()
