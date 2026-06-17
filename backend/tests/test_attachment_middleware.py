from __future__ import annotations

import unittest

from app.agents.middlewares.attachment import ATTACHMENT_PROMPT_MARKER, build_attachment_prompt


class AttachmentMiddlewareTests(unittest.TestCase):
    def test_build_attachment_prompt_points_model_to_sandbox_read_file(self):
        prompt = build_attachment_prompt(
            [
                {
                    "file_name": "notes.txt",
                    "path": "/mnt/user-data/uploads/notes-abc.txt",
                    "content_type": "text/plain",
                    "size": 12,
                }
            ]
        )

        self.assertIsNotNone(prompt)
        self.assertIn(ATTACHMENT_PROMPT_MARKER, prompt)
        self.assertIn("notes.txt: /mnt/user-data/uploads/notes-abc.txt", prompt)
        self.assertIn("sandbox_read_file", prompt)

    def test_build_attachment_prompt_ignores_invalid_uploads(self):
        self.assertIsNone(build_attachment_prompt([{"file_name": "missing-path"}]))


if __name__ == "__main__":
    unittest.main()
