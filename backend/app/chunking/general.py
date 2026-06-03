from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


@dataclass(frozen=True)
class GeneralChunkConfig:
    delimiter: str = "\n"
    chunk_token_num: int = 512
    overlapped_percent: int = 0


class GeneralMarkdownChunker:
    """RAGFlow-like general chunker for markdown text."""

    engine_version = "general_v1"

    def __init__(self, config: GeneralChunkConfig | None = None):
        self.config = config or GeneralChunkConfig()

    def chunk(self, markdown_content: str, *, file_id: str, filename: str) -> list[dict[str, Any]]:
        source_text = markdown_content or ""
        sections = self._iter_sections(source_text)
        text_chunks = self._ensure_chunk_token_limit(self._naive_merge(sections))
        return self._build_records(text_chunks, source_text=source_text, file_id=file_id, filename=filename)

    def _iter_sections(self, markdown_content: str) -> list[tuple[str, str]]:
        sections: list[tuple[str, str]] = []
        text = markdown_content or ""
        delimiter = self._unescape_delimiter(self.config.delimiter)

        if delimiter and delimiter not in {"\n", "\r\n"} and "`" not in delimiter:
            for part in text.split(delimiter):
                block = part.strip()
                if block:
                    sections.append((block, ""))
        else:
            for line in text.splitlines():
                block = line.strip()
                if block:
                    sections.append((block, ""))

        if not sections and text.strip():
            sections.append((text.strip(), ""))
        return sections

    def _naive_merge(self, sections: list[tuple[str, str]]) -> list[str]:
        if not sections:
            return []

        chunk_token_num = max(int(self.config.chunk_token_num or 0), 0)
        overlap = max(0, min(int(self.config.overlapped_percent or 0), 99))
        delimiter = self._unescape_delimiter(self.config.delimiter)

        custom_delimiters = self._extract_custom_delimiters(delimiter)
        if custom_delimiters:
            return self._split_by_custom_delimiters(sections, custom_delimiters)

        if chunk_token_num <= 0:
            merged = "\n".join(section for section, _ in sections if section and section.strip())
            return [merged] if merged.strip() else []

        chunks = [""]
        token_nums = [0]

        def add_chunk(text: str, pos: str) -> None:
            token_num = self.count_tokens(text)
            local_pos = pos if token_num >= 8 else ""
            threshold = chunk_token_num * (100 - overlap) / 100.0

            if chunks[-1] == "" or token_nums[-1] > threshold:
                if chunks:
                    previous = self._remove_pdf_tags(chunks[-1])
                    start = int(len(previous) * (100 - overlap) / 100.0)
                    text = previous[start:] + text
                if local_pos and local_pos not in text:
                    text += local_pos
                chunks.append(text)
                token_nums.append(token_num)
            else:
                if local_pos and local_pos not in chunks[-1]:
                    text += local_pos
                chunks[-1] += text
                token_nums[-1] += token_num

        for section, pos in sections:
            if section:
                add_chunk("\n" + section, pos)

        return [chunk for chunk in chunks if chunk.strip()]

    def _ensure_chunk_token_limit(self, chunks: list[str]) -> list[str]:
        max_tokens = int(self.config.chunk_token_num or 0)
        if max_tokens <= 0:
            return [chunk.strip() for chunk in chunks if chunk and chunk.strip()]

        protected: list[str] = []
        for chunk in chunks:
            cleaned = (chunk or "").strip()
            if not cleaned:
                continue
            if self.count_tokens(cleaned) <= max_tokens:
                protected.append(cleaned)
            else:
                protected.extend(self.hard_split_by_token_limit(cleaned, max_tokens))
        return protected

    def _build_records(
        self,
        text_chunks: list[str],
        *,
        source_text: str,
        file_id: str,
        filename: str,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        search_from = 0

        for index, chunk_content in enumerate(text_chunks):
            text = (chunk_content or "").strip()
            if not text:
                continue

            start_char_pos = None
            end_char_pos = None
            found_at = source_text.find(text, search_from)
            if found_at >= 0:
                start_char_pos = found_at
                end_char_pos = found_at + len(text)
                search_from = end_char_pos

            records.append(
                {
                    "chunk_id": f"{file_id}_chunk_{index}",
                    "content": text,
                    "filename": filename,
                    "chunk_index": index,
                    "token_count": self.count_tokens(text),
                    "start_char_pos": start_char_pos,
                    "end_char_pos": end_char_pos,
                    "metadata": {
                        "source": filename,
                        "engine": self.engine_version,
                    },
                }
            )

        return records

    def _split_by_custom_delimiters(
        self,
        sections: list[tuple[str, str]],
        custom_delimiters: list[str],
    ) -> list[str]:
        pattern = "|".join(re.escape(item) for item in sorted(set(custom_delimiters), key=len, reverse=True))
        chunks: list[str] = []
        for section, pos in sections:
            split_section = re.split(rf"({pattern})", section, flags=re.DOTALL)
            for sub_section in split_section:
                if re.fullmatch(pattern, sub_section or ""):
                    continue
                text = "\n" + sub_section
                local_pos = pos if self.count_tokens(text) >= 8 else ""
                if local_pos and local_pos not in text:
                    text += local_pos
                if text.strip():
                    chunks.append(text)
        return chunks

    @staticmethod
    def count_tokens(text: str) -> int:
        if not text:
            return 0
        parts = TOKEN_PATTERN.findall(text)
        return max(1, len(parts)) if text.strip() else 0

    @staticmethod
    def hard_split_by_token_limit(text: str, chunk_token_num: int) -> list[str]:
        token_iter = list(TOKEN_PATTERN.finditer(text or ""))
        if not token_iter:
            cleaned = (text or "").strip()
            return [cleaned] if cleaned else []

        chunks: list[str] = []
        start = 0
        index = 0
        max_tokens = max(int(chunk_token_num or 0), 1)

        while index < len(token_iter):
            next_index = min(index + max_tokens, len(token_iter))
            end = token_iter[next_index].start() if next_index < len(token_iter) else len(text)
            piece = text[start:end].strip()
            if piece:
                chunks.append(piece)
            start = end
            index = next_index

        tail = text[start:].strip()
        if tail:
            chunks.append(tail)
        return chunks

    @staticmethod
    def _unescape_delimiter(delimiter: str) -> str:
        return delimiter.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t").replace("\\\\", "\\")

    @staticmethod
    def _extract_custom_delimiters(delimiter: str) -> list[str]:
        return [match.group(1) for match in re.finditer(r"`([^`]+)`", delimiter or "")]

    @staticmethod
    def _remove_pdf_tags(text: str) -> str:
        return re.sub(r"@@[0-9-]+\t[0-9.\t]+##", "", text or "")


def chunk_markdown_general(
    markdown_content: str,
    *,
    file_id: str,
    filename: str,
    config: GeneralChunkConfig | None = None,
) -> list[dict[str, Any]]:
    return GeneralMarkdownChunker(config).chunk(markdown_content, file_id=file_id, filename=filename)
