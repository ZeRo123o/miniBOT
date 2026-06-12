from __future__ import annotations

import hashlib
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

from app.core.config import get_settings

VIRTUAL_USER_DATA_ROOT = "/mnt/user-data"
VIRTUAL_WORKSPACE_ROOT = f"{VIRTUAL_USER_DATA_ROOT}/workspace"
VIRTUAL_UPLOADS_ROOT = f"{VIRTUAL_USER_DATA_ROOT}/uploads"
VIRTUAL_OUTPUTS_ROOT = f"{VIRTUAL_USER_DATA_ROOT}/outputs"
VIRTUAL_SKILLS_ROOT = "/mnt/skills"

READABLE_ROOTS = (
    VIRTUAL_WORKSPACE_ROOT,
    VIRTUAL_UPLOADS_ROOT,
    VIRTUAL_OUTPUTS_ROOT,
    VIRTUAL_SKILLS_ROOT,
)
WRITABLE_ROOTS = (VIRTUAL_WORKSPACE_ROOT, VIRTUAL_OUTPUTS_ROOT)


def safe_user_segment(user_key: str) -> str:
    """把客户端 user_key 转为不会泄漏原值的稳定目录名。"""
    digest = hashlib.sha256(user_key.encode("utf-8")).hexdigest()[:12]
    return f"user-{digest}"


def sandbox_id_for_scope(user_key: str, conversation_id: int) -> str:
    """生成与用户和会话绑定的稳定沙盒 ID。"""
    identity = f"{user_key}:{conversation_id}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def runtime_root() -> Path:
    return Path(get_settings().sandbox_data_dir).expanduser().resolve()


def user_workspace_dir(user_key: str) -> Path:
    return runtime_root() / "users" / safe_user_segment(user_key) / "workspace"


def conversation_root(user_key: str, conversation_id: int) -> Path:
    return (
        runtime_root()
        / "users"
        / safe_user_segment(user_key)
        / "conversations"
        / str(conversation_id)
    )


def conversation_uploads_dir(user_key: str, conversation_id: int) -> Path:
    return conversation_root(user_key, conversation_id) / "uploads"


def conversation_outputs_dir(user_key: str, conversation_id: int) -> Path:
    return conversation_root(user_key, conversation_id) / "outputs"


def conversation_skills_dir(user_key: str, conversation_id: int) -> Path:
    return conversation_root(user_key, conversation_id) / "skills"


def ensure_scope_dirs(user_key: str, conversation_id: int) -> None:
    """创建沙盒允许持久化的最小目录集合。"""
    for path in (
        user_workspace_dir(user_key),
        conversation_uploads_dir(user_key, conversation_id),
        conversation_outputs_dir(user_key, conversation_id),
        conversation_skills_dir(user_key, conversation_id),
    ):
        path.mkdir(parents=True, exist_ok=True)


def normalize_virtual_path(path: str) -> str:
    """规范化 POSIX 虚拟路径并拒绝目录穿越。"""
    raw = str(path or "").strip()
    if not raw or not raw.startswith("/"):
        raise ValueError("path must be an absolute sandbox path")
    pure = PurePosixPath(raw)
    if ".." in pure.parts:
        raise ValueError("path traversal is not allowed")
    return str(pure)


def is_same_or_child(path: str, root: str) -> bool:
    clean_root = root.rstrip("/")
    return path == clean_root or path.startswith(f"{clean_root}/")


def can_read(path: str) -> bool:
    return any(is_same_or_child(path, root) for root in READABLE_ROOTS)


def can_list(path: str) -> bool:
    """允许列出命名空间根节点，但不扩展到其他容器路径。"""
    if path in {VIRTUAL_USER_DATA_ROOT, VIRTUAL_SKILLS_ROOT}:
        return True
    return can_read(path)


def can_write(path: str) -> bool:
    return any(is_same_or_child(path, root) for root in WRITABLE_ROOTS)


def resolve_host_path(
    user_key: str,
    conversation_id: int,
    virtual_path: str,
    *,
    write: bool = False,
) -> Path:
    """将受控虚拟路径解析到宿主目录，用于产物展示等后端操作。"""
    normalized = normalize_virtual_path(virtual_path)
    allowed = can_write(normalized) if write else can_read(normalized)
    if not allowed:
        raise ValueError(f"path is outside allowed sandbox roots: {normalized}")

    mappings = (
        (VIRTUAL_WORKSPACE_ROOT, user_workspace_dir(user_key)),
        (VIRTUAL_UPLOADS_ROOT, conversation_uploads_dir(user_key, conversation_id)),
        (VIRTUAL_OUTPUTS_ROOT, conversation_outputs_dir(user_key, conversation_id)),
        (VIRTUAL_SKILLS_ROOT, conversation_skills_dir(user_key, conversation_id)),
    )
    for virtual_root, host_root in mappings:
        if not is_same_or_child(normalized, virtual_root):
            continue
        relative = normalized[len(virtual_root) :].lstrip("/")
        root = host_root.resolve()
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("path traversal is not allowed") from exc
        return target
    raise ValueError(f"unsupported sandbox path: {normalized}")


def sync_readable_skills(
    user_key: str,
    conversation_id: int,
    skills: list[dict[str, Any]],
) -> None:
    """复制本轮已授权 Skill 到会话目录，随后由容器只读挂载。"""
    target_root = conversation_skills_dir(user_key, conversation_id)
    target_root.mkdir(parents=True, exist_ok=True)

    expected: set[str] = set()
    for resource in skills:
        config = resource.get("config") or {}
        prompt_path = str(config.get("prompt_path") or "").strip()
        if not prompt_path:
            continue
        source_dir = Path(prompt_path).expanduser().resolve().parent
        if not source_dir.is_dir():
            continue
        slug = source_dir.name
        expected.add(slug)
        target = target_root / slug
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source_dir, target, symlinks=False)

    for child in target_root.iterdir():
        if child.name not in expected:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
