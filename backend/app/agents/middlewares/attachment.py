from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

ATTACHMENT_PROMPT_MARKER = "<!-- attachment_context -->"


def _upload_line(upload: dict[str, Any]) -> str | None:
    path = upload.get("path")
    if not isinstance(path, str) or not path.strip():
        return None
    file_name = upload.get("file_name")
    label = str(file_name or path).strip()
    content_type = str(upload.get("content_type") or "").strip()
    size = upload.get("size")
    markdown_chars = upload.get("markdown_chars")
    truncated = bool(upload.get("truncated"))
    details = []
    if content_type:
        details.append(content_type)
    if isinstance(size, int) and size > 0:
        details.append(f"{size} bytes")
    if isinstance(markdown_chars, int) and markdown_chars > 0:
        details.append(f"{markdown_chars} Markdown chars")
    if truncated:
        details.append("state preview truncated")
    suffix = f" ({', '.join(details)})" if details else ""
    return f"- {label}: {path}{suffix}"


def build_attachment_prompt(uploads: Sequence[dict[str, Any]]) -> str | None:
    """Render uploaded file paths into a concise model instruction block."""
    lines = [line for upload in uploads if (line := _upload_line(upload))]
    if not lines:
        return None
    return "\n".join(
        [
            ATTACHMENT_PROMPT_MARKER,
            "The user uploaded the following files for this turn:",
            "",
            *lines,
            "",
            "Use sandbox_read_file to inspect file contents before answering. Do not guess file contents.",
            "Attachment paths point to readable files; state metadata may contain only a truncated preview.",
        ]
    )


class AttachmentMiddleware(AgentMiddleware):
    """Inject current-turn uploaded file paths into the system prompt."""

    @staticmethod
    def _uploads_from_request(request: ModelRequest) -> list[dict[str, Any]]:
        state = request.state if isinstance(request.state, dict) else {}
        uploads = state.get("uploads") or []
        return [item for item in uploads if isinstance(item, dict)]

    @staticmethod
    def _system_text(request: ModelRequest) -> str:
        if not request.system_message:
            return ""
        blocks = getattr(request.system_message, "content_blocks", []) or []
        return "\n".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )

    def _override_request(self, request: ModelRequest) -> ModelRequest:
        uploads = self._uploads_from_request(request)
        attachment_prompt = build_attachment_prompt(uploads)
        if not attachment_prompt:
            return request
        if ATTACHMENT_PROMPT_MARKER in self._system_text(request):
            return request

        existing_blocks = list(request.system_message.content_blocks) if request.system_message else []
        return request.override(
            system_message=SystemMessage(
                content=[
                    *existing_blocks,
                    {"type": "text", "text": attachment_prompt},
                ]
            )
        )

    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelResponse:
        return handler(self._override_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return await handler(self._override_request(request))
