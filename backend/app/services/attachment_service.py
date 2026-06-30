from __future__ import annotations

import hashlib
import asyncio
import logging
from pathlib import Path, PurePosixPath

from fastapi import HTTPException, UploadFile

from app.agents.backends.sandbox.paths import VIRTUAL_UPLOADS_ROOT, conversation_uploads_dir
from app.core.config import get_settings
from app.knowledge.parser import parse_document_to_markdown

MAX_CHAT_UPLOAD_FILES = 10
MARKDOWN_READABLE_EXTENSIONS = {".csv", ".docx", ".md", ".markdown", ".pdf", ".txt", ".xlsx"}
logger = logging.getLogger(__name__)


def _safe_filename(filename: str | None) -> str:
    """Return a single safe filename component for uploads."""
    raw_name = Path(filename or "upload").name.strip()
    if not raw_name or raw_name in {".", ".."}:
        raw_name = "upload"
    if "/" in raw_name or "\\" in raw_name or ".." in PurePosixPath(raw_name).parts:
        raise HTTPException(status_code=400, detail="Invalid upload filename.")
    return raw_name


def _unique_upload_name(filename: str, content: bytes, existing: set[str]) -> str:
    stem = Path(filename).stem or "upload"
    suffix = Path(filename).suffix
    digest = hashlib.sha256(content).hexdigest()[:10]
    candidate = f"{stem}-{digest}{suffix}"
    index = 2
    while candidate in existing:
        candidate = f"{stem}-{digest}-{index}{suffix}"
        index += 1
    existing.add(candidate)
    return candidate


def _markdown_sidecar_name(stored_name: str, existing: set[str]) -> str:
    stem = Path(stored_name).stem or "upload"
    candidate = f"{stem}.extracted.md"
    index = 2
    while candidate in existing:
        candidate = f"{stem}.extracted-{index}.md"
        index += 1
    existing.add(candidate)
    return candidate


def _should_extract_readable_copy(filename: str) -> bool:
    return Path(filename).suffix.lower() in MARKDOWN_READABLE_EXTENSIONS


def truncate_attachment_markdown(markdown: str, max_chars: int) -> tuple[str, bool]:
    """Trim extracted attachment Markdown before it enters prompt or graph state."""
    clean = markdown or "(empty extracted text)"
    if max_chars <= 0 or len(clean) <= max_chars:
        return clean, False
    marker = f"\n\n[内容已截断，超出 {max_chars} 字符限制]"
    keep_chars = max(0, max_chars - len(marker))
    return f"{clean[:keep_chars].rstrip()}{marker}", True


def build_attachment_state_files(uploads: list[dict]) -> dict:
    """Build a Yuxi-style state files mapping from parsed attachment Markdown."""
    files: dict[str, dict] = {}
    for upload in uploads:
        if not isinstance(upload, dict) or upload.get("status") != "parsed":
            continue
        file_path = upload.get("file_path") or upload.get("path")
        markdown = upload.get("markdown")
        if not isinstance(file_path, str) or not file_path.strip():
            continue
        if not isinstance(markdown, str) or not markdown:
            continue
        files[file_path] = {
            "content": markdown.splitlines(),
            "created_at": upload.get("uploaded_at") or "",
            "modified_at": upload.get("uploaded_at") or "",
        }
    return files


async def save_chat_uploads(
    *,
    user_id: str,
    conversation_id: int,
    files: list[UploadFile] | None,
) -> list[dict]:
    """Persist chat uploads into the conversation-scoped read-only uploads root."""
    if not files:
        return []
    if len(files) > MAX_CHAT_UPLOAD_FILES:
        raise HTTPException(status_code=400, detail=f"Up to {MAX_CHAT_UPLOAD_FILES} files can be uploaded at once.")

    target_root = conversation_uploads_dir(user_id, conversation_id)
    target_root.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    max_bytes = settings.chat_upload_max_bytes
    max_markdown_chars = settings.chat_attachment_markdown_max_chars
    existing = {child.name for child in target_root.iterdir()}
    uploads: list[dict] = []

    for file in files:
        safe_name = _safe_filename(file.filename)
        content = await file.read()
        if len(content) > max_bytes:
            raise HTTPException(status_code=400, detail=f"Upload is larger than {max_bytes} bytes: {safe_name}")

        stored_name = _unique_upload_name(safe_name, content, existing)
        target = target_root / stored_name
        await asyncio.to_thread(target.write_bytes, content)

        readable_name = stored_name
        full_markdown = ""
        preview_markdown = ""
        truncated = False
        status = "uploaded"
        if _should_extract_readable_copy(safe_name):
            try:
                full_markdown = parse_document_to_markdown(safe_name, content) or "(empty extracted text)"
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Chat attachment extraction failed: user_id=%s conversation_id=%s filename=%s error=%s",
                    user_id,
                    conversation_id,
                    safe_name,
                    exc,
                )
                full_markdown = f"Attachment text extraction failed: {exc}"
            preview_markdown, truncated = truncate_attachment_markdown(full_markdown, max_markdown_chars)
            sidecar_name = _markdown_sidecar_name(stored_name, existing)
            sidecar_target = target_root / sidecar_name
            await asyncio.to_thread(sidecar_target.write_text, full_markdown, encoding="utf-8")
            readable_name = sidecar_name
            status = "parsed"

        logger.info(
            "Chat attachment saved: user_id=%s conversation_id=%s filename=%s size=%s path=%s original_path=%s",
            user_id,
            conversation_id,
            safe_name,
            len(content),
            f"{VIRTUAL_UPLOADS_ROOT}/{readable_name}",
            f"{VIRTUAL_UPLOADS_ROOT}/{stored_name}",
        )

        uploads.append(
            {
                "file_name": safe_name,
                "path": f"{VIRTUAL_UPLOADS_ROOT}/{readable_name}",
                "file_path": f"{VIRTUAL_UPLOADS_ROOT}/{readable_name}",
                "original_path": f"{VIRTUAL_UPLOADS_ROOT}/{stored_name}",
                "content_type": file.content_type or "",
                "size": len(content),
                "status": status,
                "markdown": preview_markdown,
                "markdown_chars": len(full_markdown),
                "truncated": truncated,
            }
        )

    return uploads
