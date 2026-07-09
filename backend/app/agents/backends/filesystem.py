from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from langgraph.runtime import Runtime

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.backends.sandbox.paths import (
    VIRTUAL_OUTPUTS_ROOT,
    VIRTUAL_SKILLS_ROOT,
    VIRTUAL_UPLOADS_ROOT,
    VIRTUAL_USER_DATA_ROOT,
    VIRTUAL_WORKSPACE_ROOT,
    can_list,
    can_read,
    can_write,
    conversation_outputs_dir,
    conversation_skills_dir,
    conversation_uploads_dir,
    ensure_scope_dirs,
    is_same_or_child,
    normalize_virtual_path,
    resolve_host_path,
    user_workspace_dir,
)


@dataclass(slots=True)
class BackendWriteResult:
    path: str
    error: str | None = None
    files_update: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BackendReadResult:
    path: str
    content: str = ""
    error: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    total_lines: int | None = None
    truncated: bool = False


@dataclass(slots=True)
class BackendListResult:
    path: str
    entries: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


@dataclass(slots=True)
class BackendGlobResult:
    path: str
    matches: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass(slots=True)
class BackendGrepResult:
    path: str
    matches: list[str] = field(default_factory=list)
    error: str | None = None


class AgentFilesystemBackend:
    """Read and write files through miniBOT's virtual agent filesystem.

    The model only sees virtual paths. This backend is the single place that maps
    those paths to host-side storage for the current user and conversation.
    """

    def __init__(self, context: AgentContext):
        self._context = context

    @property
    def _scope(self) -> tuple[str, int]:
        if self._context.conversation_id is None:
            raise ValueError("conversation_id is required")
        return self._context.user_id, int(self._context.conversation_id)

    def _ensure_scope(self) -> tuple[str, int]:
        user_id, conversation_id = self._scope
        ensure_scope_dirs(user_id, conversation_id)
        return user_id, conversation_id

    def _root_mappings(self) -> tuple[tuple[str, Path], ...]:
        user_id, conversation_id = self._ensure_scope()
        return (
            (VIRTUAL_WORKSPACE_ROOT, user_workspace_dir(user_id)),
            (VIRTUAL_UPLOADS_ROOT, conversation_uploads_dir(user_id, conversation_id)),
            (VIRTUAL_OUTPUTS_ROOT, conversation_outputs_dir(user_id, conversation_id)),
            (VIRTUAL_SKILLS_ROOT, conversation_skills_dir(user_id, conversation_id)),
        )

    def _virtual_for_host_path(self, host_path: Path) -> str:
        resolved = host_path.resolve()
        for virtual_root, host_root in self._root_mappings():
            root = host_root.resolve()
            try:
                relative = resolved.relative_to(root)
            except ValueError:
                continue
            suffix = relative.as_posix()
            return virtual_root if suffix in {"", "."} else f"{virtual_root}/{suffix}"
        raise ValueError("host path is outside allowed filesystem roots")

    def _root_entry(self, virtual_path: str, name: str) -> dict[str, Any]:
        return {
            "path": virtual_path,
            "name": name,
            "is_dir": True,
            "size": 0,
        }

    def _entry_for_path(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        virtual_path = self._virtual_for_host_path(path)
        return {
            "path": virtual_path,
            "name": path.name,
            "is_dir": path.is_dir(),
            "size": 0 if path.is_dir() else stat.st_size,
            "modified_at": stat.st_mtime,
        }

    @staticmethod
    def _sort_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            entries,
            key=lambda item: (
                not bool(item.get("is_dir")),
                str(item.get("name") or item.get("path") or "").lower(),
            ),
        )

    def _readable_roots_for_search(self, path: str) -> list[str]:
        normalized = normalize_virtual_path(path)
        if can_read(normalized):
            return [normalized]
        if normalized == VIRTUAL_USER_DATA_ROOT:
            return [VIRTUAL_WORKSPACE_ROOT, VIRTUAL_UPLOADS_ROOT, VIRTUAL_OUTPUTS_ROOT]
        return [
            virtual_root
            for virtual_root, _host_root in self._root_mappings()
            if is_same_or_child(virtual_root, normalized)
        ]

    @staticmethod
    def _validate_glob_pattern(pattern: str) -> str:
        clean = str(pattern or "*").strip() or "*"
        if PurePosixPath(clean).is_absolute() or ".." in PurePosixPath(clean).parts:
            raise ValueError("glob traversal is not allowed")
        return clean

    def read(
        self,
        path: str,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
        max_chars: int | None = None,
    ) -> BackendReadResult:
        try:
            normalized = normalize_virtual_path(path)
            if not can_read(normalized):
                raise PermissionError("path is outside readable filesystem roots")
            user_id, conversation_id = self._ensure_scope()
            host_path = resolve_host_path(user_id, conversation_id, normalized)
            if not host_path.exists():
                raise FileNotFoundError(f"file not found: {normalized}")
            if not host_path.is_file():
                raise IsADirectoryError(f"path is a directory: {normalized}")
            content = host_path.read_text(encoding="utf-8")
            lines = content.splitlines()
            total_lines = len(lines)
            selected_start, selected_end = self._normalize_line_window(
                start_line,
                end_line,
                total_lines,
            )
            if selected_start is not None and selected_end is not None:
                content = "\n".join(lines[selected_start - 1 : selected_end])
            content, truncated = self._truncate_chars(content, max_chars)
        except Exception as exc:  # noqa: BLE001
            return BackendReadResult(path=path, error=str(exc))
        return BackendReadResult(
            path=normalized,
            content=content,
            start_line=selected_start,
            end_line=selected_end,
            total_lines=total_lines,
            truncated=truncated,
        )

    async def aread(
        self,
        path: str,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
        max_chars: int | None = None,
    ) -> BackendReadResult:
        return await asyncio.to_thread(
            self.read,
            path,
            start_line=start_line,
            end_line=end_line,
            max_chars=max_chars,
        )

    @staticmethod
    def _normalize_line_window(
        start_line: int | None,
        end_line: int | None,
        total_lines: int,
    ) -> tuple[int | None, int | None]:
        if start_line is None and end_line is None:
            return None, None
        if total_lines <= 0:
            return 1, 0
        start = 1 if start_line is None else max(1, int(start_line))
        end = total_lines if end_line is None else max(start, int(end_line))
        return min(start, total_lines), min(end, total_lines)

    @staticmethod
    def _truncate_chars(content: str, max_chars: int | None) -> tuple[str, bool]:
        if max_chars is None or max_chars <= 0 or len(content) <= max_chars:
            return content, False
        return content[:max_chars], True

    def write(self, path: str, content: str) -> BackendWriteResult:
        try:
            normalized = normalize_virtual_path(path)
            if not can_write(normalized):
                raise PermissionError(
                    "write is allowed only under /mnt/user-data/workspace or /mnt/user-data/outputs"
                )
            user_id, conversation_id = self._ensure_scope()
            host_path = resolve_host_path(
                user_id,
                conversation_id,
                normalized,
                write=True,
            )
            host_path.parent.mkdir(parents=True, exist_ok=True)
            host_path.write_text(content, encoding="utf-8")
        except Exception as exc:
            return BackendWriteResult(path=path, error=str(exc))
        return BackendWriteResult(path=normalized, files_update={normalized: {"path": normalized}})

    async def awrite(self, path: str, content: str) -> BackendWriteResult:
        return await asyncio.to_thread(self.write, path, content)

    def ls(self, path: str) -> BackendListResult:
        try:
            normalized = normalize_virtual_path(path)
            if not can_list(normalized):
                raise PermissionError("path is outside listable filesystem roots")
            self._ensure_scope()
            if normalized == VIRTUAL_USER_DATA_ROOT:
                entries = [
                    self._root_entry(VIRTUAL_WORKSPACE_ROOT, "workspace"),
                    self._root_entry(VIRTUAL_UPLOADS_ROOT, "uploads"),
                    self._root_entry(VIRTUAL_OUTPUTS_ROOT, "outputs"),
                ]
                return BackendListResult(path=normalized, entries=entries)
            if normalized == VIRTUAL_SKILLS_ROOT:
                host_path = conversation_skills_dir(*self._scope)
            else:
                user_id, conversation_id = self._scope
                host_path = resolve_host_path(user_id, conversation_id, normalized)
            if not host_path.exists():
                return BackendListResult(path=normalized, entries=[])
            if not host_path.is_dir():
                raise NotADirectoryError(f"path is not a directory: {normalized}")
            entries = [self._entry_for_path(child) for child in host_path.iterdir()]
        except Exception as exc:  # noqa: BLE001
            return BackendListResult(path=path, error=str(exc))
        return BackendListResult(path=normalized, entries=self._sort_entries(entries))

    async def als(self, path: str) -> BackendListResult:
        return await asyncio.to_thread(self.ls, path)

    def glob(self, path: str, pattern: str) -> BackendGlobResult:
        try:
            normalized = normalize_virtual_path(path)
            search_pattern = self._validate_glob_pattern(pattern)
            search_roots = self._readable_roots_for_search(normalized)
            if not search_roots:
                raise PermissionError("path is outside readable filesystem roots")

            matches: list[str] = []
            for virtual_root in search_roots:
                user_id, conversation_id = self._ensure_scope()
                host_root = resolve_host_path(user_id, conversation_id, virtual_root)
                if not host_root.exists():
                    continue
                candidates = host_root.rglob(search_pattern) if host_root.is_dir() else [host_root]
                for candidate in candidates:
                    try:
                        if candidate.is_file():
                            matches.append(self._virtual_for_host_path(candidate))
                    except OSError:
                        continue
            matches = sorted(dict.fromkeys(matches))
        except Exception as exc:  # noqa: BLE001
            return BackendGlobResult(path=path, error=str(exc))
        return BackendGlobResult(path=normalized, matches=matches)

    async def aglob(self, path: str, pattern: str) -> BackendGlobResult:
        return await asyncio.to_thread(self.glob, path, pattern)

    def grep(
        self,
        path: str,
        pattern: str,
        *,
        glob: str = "**/*",
        literal: bool = True,
        limit: int = 100,
    ) -> BackendGrepResult:
        try:
            import re

            normalized = normalize_virtual_path(path)
            if not pattern:
                raise ValueError("pattern is required")
            matcher = None if literal else re.compile(pattern, flags=re.IGNORECASE)
            files = self.glob(normalized, glob)
            if files.error:
                raise ValueError(files.error)

            matches: list[str] = []
            user_id, conversation_id = self._ensure_scope()
            for virtual_file in files.matches:
                host_path = resolve_host_path(user_id, conversation_id, virtual_file)
                try:
                    text = host_path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                for line_number, line in enumerate(text.splitlines(), start=1):
                    found = (
                        pattern.lower() in line.lower()
                        if literal
                        else bool(matcher and matcher.search(line))
                    )
                    if not found:
                        continue
                    matches.append(f"{virtual_file}:{line_number}: {line}")
                    if len(matches) >= limit:
                        return BackendGrepResult(path=normalized, matches=matches)
        except Exception as exc:  # noqa: BLE001
            return BackendGrepResult(path=path, error=str(exc))
        return BackendGrepResult(path=normalized, matches=matches)

    async def agrep(
        self,
        path: str,
        pattern: str,
        *,
        glob: str = "**/*",
        literal: bool = True,
        limit: int = 100,
    ) -> BackendGrepResult:
        return await asyncio.to_thread(
            self.grep,
            path,
            pattern,
            glob=glob,
            literal=literal,
            limit=limit,
        )


def create_agent_filesystem_backend(runtime: Runtime) -> AgentFilesystemBackend | None:
    context = getattr(runtime, "context", None)
    if not isinstance(context, AgentContext):
        return None
    return AgentFilesystemBackend(context)
