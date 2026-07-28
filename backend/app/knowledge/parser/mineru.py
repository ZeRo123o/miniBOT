from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from app.core.config import get_settings
from app.knowledge.parser.base import DocumentParser
from app.knowledge.parser.exceptions import DocumentParserError
from app.knowledge.parser.schemas import ParsedAsset, ParsedDocument, ParserDocument

_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"})
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


class MinerUDocumentParser(DocumentParser):
    """适配提供 ``POST /file_parse`` 的 MinerU 服务。"""

    parser_id = "mineru"
    display_name = "MinerU"
    version = "1"
    priority = 100
    supported_extensions = frozenset({".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"})
    capabilities = frozenset({"ocr", "layout", "table", "formula", "image_extraction"})

    def is_auto_selectable(self) -> bool:
        settings = get_settings()
        return settings.mineru_enabled and settings.mineru_auto_select

    def describe(self) -> dict[str, Any]:
        description = super().describe()
        settings = get_settings()
        description.update(
            {
                "configured": bool(settings.mineru_enabled and settings.mineru_api_url.strip()),
                "auto_select": self.is_auto_selectable(),
            }
        )
        return description

    async def health_check(self) -> dict[str, Any]:
        settings = get_settings()
        if not settings.mineru_enabled:
            return {
                "status": "disabled",
                "parser_id": self.parser_id,
                "message": "MinerU parser is disabled.",
            }

        url = f"{settings.mineru_api_url.rstrip('/')}/openapi.json"
        try:
            async with httpx.AsyncClient(timeout=settings.mineru_health_timeout_seconds) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException:
            return {"status": "timeout", "parser_id": self.parser_id, "message": "MinerU health check timed out."}
        except Exception as error:  # noqa: BLE001 - health checks return status instead of raising
            return {
                "status": "unavailable",
                "parser_id": self.parser_id,
                "message": f"MinerU health check failed: {error}",
            }

        if "/file_parse" not in (payload.get("paths") or {}):
            return {
                "status": "unhealthy",
                "parser_id": self.parser_id,
                "message": "MinerU service does not expose /file_parse.",
            }
        return {
            "status": "available",
            "parser_id": self.parser_id,
            "api_version": (payload.get("info") or {}).get("version", "unknown"),
        }

    async def parse(
        self,
        document: ParserDocument,
        options: dict[str, Any] | None = None,
    ) -> ParsedDocument:
        settings = get_settings()
        if not settings.mineru_enabled or not settings.mineru_api_url.strip():
            raise DocumentParserError(
                "MinerU parser is not enabled or configured.",
                parser_id=self.parser_id,
                code="parser_disabled",
            )

        options = dict(options or {})
        request_data = self._request_data(options)
        timeout_seconds = min(
            int(options.get("timeout_seconds") or settings.mineru_timeout_seconds),
            settings.mineru_timeout_seconds,
        )
        endpoint = f"{settings.mineru_api_url.rstrip('/')}/file_parse"
        files = {
            "files": (
                Path(document.filename).name,
                document.content,
                document.content_type or "application/octet-stream",
            )
        }

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(endpoint, files=files, data=request_data)
        except httpx.TimeoutException as error:
            raise DocumentParserError(
                f"MinerU request timed out after {timeout_seconds} seconds.",
                parser_id=self.parser_id,
                code="timeout",
            ) from error
        except httpx.RequestError as error:
            raise DocumentParserError(
                "Unable to connect to the MinerU service.",
                parser_id=self.parser_id,
                code="connection_error",
            ) from error

        if response.status_code != 200:
            raise DocumentParserError(
                f"MinerU request failed with HTTP {response.status_code}: {self._error_detail(response)}",
                parser_id=self.parser_id,
                code=f"http_{response.status_code}",
            )
        if len(response.content) > settings.mineru_max_response_bytes:
            raise DocumentParserError(
                "MinerU response exceeds the configured size limit.",
                parser_id=self.parser_id,
                code="response_too_large",
            )

        return self._parse_response(response)

    @staticmethod
    def _request_data(options: dict[str, Any]) -> dict[str, Any]:
        languages = options.get("lang_list") or ["ch"]
        if not isinstance(languages, list) or not all(isinstance(item, str) and item.strip() for item in languages):
            raise DocumentParserError(
                "MinerU lang_list must be a non-empty string list.",
                parser_id=MinerUDocumentParser.parser_id,
                code="invalid_options",
            )
        return {
            "lang_list": languages,
            "backend": str(options.get("backend") or "hybrid-auto-engine"),
            "parse_method": str(options.get("parse_method") or "auto"),
            "formula_enable": bool(options.get("formula_enable", True)),
            "table_enable": bool(options.get("table_enable", True)),
            "image_analysis": bool(options.get("image_analysis", True)),
            "start_page_id": max(int(options.get("start_page_id") or 0), 0),
            "end_page_id": max(int(options.get("end_page_id") or 99999), 0),
            "return_md": True,
            "response_format_zip": True,
            "return_images": True,
        }

    def _parse_response(self, response: httpx.Response) -> ParsedDocument:
        content_type = (response.headers.get("content-type") or "").lower()
        if response.content.startswith(b"PK") or "zip" in content_type:
            return self._parse_zip(response.content)

        # Some MinerU-compatible gateways return Markdown or JSON when ZIP
        # response mode is unavailable, so accept their common response forms.
        if "json" in content_type:
            try:
                payload = response.json()
            except ValueError as error:
                raise DocumentParserError(
                    "MinerU returned invalid JSON.",
                    parser_id=self.parser_id,
                    code="response_parse_error",
                ) from error
            markdown = self._markdown_from_json(payload)
        else:
            markdown = response.text

        if not markdown.strip():
            raise DocumentParserError(
                "MinerU returned no Markdown content.",
                parser_id=self.parser_id,
                code="empty_result",
            )
        return ParsedDocument(
            markdown=markdown.strip(),
            parser_id=self.parser_id,
            parser_version=self.version,
            metadata={"response_format": "json" if "json" in content_type else "markdown"},
        )

    def _parse_zip(self, content: bytes) -> ParsedDocument:
        settings = get_settings()
        try:
            archive = zipfile.ZipFile(BytesIO(content))
        except zipfile.BadZipFile as error:
            raise DocumentParserError(
                "MinerU returned an invalid ZIP archive.",
                parser_id=self.parser_id,
                code="response_parse_error",
            ) from error

        with archive:
            entries = archive.infolist()
            if len(entries) > settings.mineru_max_archive_files:
                raise DocumentParserError(
                    "MinerU archive contains too many files.",
                    parser_id=self.parser_id,
                    code="archive_limit_exceeded",
                )
            total_size = 0
            for entry in entries:
                self._validate_archive_path(entry.filename)
                total_size += entry.file_size
                if total_size > settings.mineru_max_archive_uncompressed_bytes:
                    raise DocumentParserError(
                        "MinerU archive exceeds the uncompressed size limit.",
                        parser_id=self.parser_id,
                        code="archive_limit_exceeded",
                    )

            markdown_entries = [entry for entry in entries if entry.filename.lower().endswith(".md")]
            if not markdown_entries:
                raise DocumentParserError(
                    "MinerU archive does not contain Markdown.",
                    parser_id=self.parser_id,
                    code="response_parse_error",
                )
            markdown_entry = next(
                (entry for entry in markdown_entries if PurePosixPath(entry.filename).name.lower() == "full.md"),
                markdown_entries[0],
            )
            try:
                markdown = archive.read(markdown_entry).decode("utf-8")
            except UnicodeDecodeError as error:
                raise DocumentParserError(
                    "MinerU Markdown is not UTF-8 encoded.",
                    parser_id=self.parser_id,
                    code="response_parse_error",
                ) from error

            assets = self._read_assets(archive, entries)
            markdown = self._replace_image_links(markdown, assets)

        return ParsedDocument(
            markdown=markdown.strip(),
            parser_id=self.parser_id,
            parser_version=self.version,
            assets=assets,
            metadata={
                "response_format": "zip",
                "markdown_path": markdown_entry.filename,
                "archive_file_count": len(entries),
            },
        )

    def _read_assets(self, archive: zipfile.ZipFile, entries: list[zipfile.ZipInfo]) -> list[ParsedAsset]:
        assets: list[ParsedAsset] = []
        assets_by_id: dict[str, ParsedAsset] = {}
        for entry in entries:
            suffix = PurePosixPath(entry.filename).suffix.lower()
            if entry.is_dir() or suffix not in _IMAGE_EXTENSIONS:
                continue
            content = archive.read(entry)
            digest = hashlib.sha256(content).hexdigest()
            asset_id = f"mineru_{digest[:16]}"
            existing = assets_by_id.get(asset_id)
            if existing is not None:
                aliases = existing.metadata.setdefault("source_aliases", [])
                aliases.append(entry.filename)
                continue
            filename = PurePosixPath(entry.filename).name
            asset = ParsedAsset(
                asset_id=asset_id,
                content=content,
                content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
                filename=filename,
                metadata={"source_path": entry.filename, "source_aliases": []},
            )
            assets.append(asset)
            assets_by_id[asset_id] = asset
        return assets

    @staticmethod
    def _replace_image_links(markdown: str, assets: list[ParsedAsset]) -> str:
        assets_by_path: dict[str, ParsedAsset] = {}
        for asset in assets:
            source_path = str(asset.metadata.get("source_path") or "").replace("\\", "/").lstrip("./")
            source_paths = [source_path, *(asset.metadata.get("source_aliases") or [])]
            for path in source_paths:
                normalized_path = str(path).replace("\\", "/").lstrip("./")
                assets_by_path[normalized_path] = asset
                assets_by_path[PurePosixPath(normalized_path).name] = asset

        def replace(match: re.Match[str]) -> str:
            alt_text, raw_path = match.groups()
            normalized_path = raw_path.replace("\\", "/").lstrip("./")
            asset = assets_by_path.get(normalized_path) or assets_by_path.get(PurePosixPath(normalized_path).name)
            if asset is None:
                return match.group(0)
            asset.caption = asset.caption or alt_text.strip()
            return f"![{alt_text}](kb-asset://{asset.asset_id})"

        return _MARKDOWN_IMAGE_PATTERN.sub(replace, markdown)

    @staticmethod
    def _validate_archive_path(path: str) -> None:
        normalized = PurePosixPath(path.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise DocumentParserError(
                "MinerU archive contains an unsafe path.",
                parser_id=MinerUDocumentParser.parser_id,
                code="unsafe_archive",
            )

    @staticmethod
    def _markdown_from_json(payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        if not isinstance(payload, dict):
            return ""
        for key in ("markdown", "md", "content", "text"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
        for key in ("data", "result"):
            value = payload.get(key)
            markdown = MinerUDocumentParser._markdown_from_json(value)
            if markdown:
                return markdown
        return ""

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        detail = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = str(payload.get("detail") or payload.get("message") or "")
            elif payload:
                detail = str(payload)
        except (ValueError, json.JSONDecodeError):
            detail = response.text
        return (detail or "unknown error").strip()[:500]
