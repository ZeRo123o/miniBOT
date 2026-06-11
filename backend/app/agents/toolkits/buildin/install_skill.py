import asyncio
import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated, Any

from langchain.tools import InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.agents.toolkits.registry import tool
from app.core.config import get_settings
from app.db.repositories import PluginResourceRepository
from app.db.session import AsyncSessionLocal
from app.agents.toolkits.governance import fail_tool_call, finish_tool_call, start_tool_call

MAX_SKILL_FILES = 1000
MAX_SKILL_PROMPT_BYTES = 64 * 1024
SKILL_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class InstallSkillInput(BaseModel):
    """安装 Skill 的输入参数。"""

    source: str = Field(
        description=(
            "Skill 来源。支持 MINIBOT_RUNTIME_SKILL_IMPORTS_DIR 下的本地目录，"
            "或 owner/repo、完整 GitHub URL。"
        )
    )
    skill_names: list[str] | None = Field(
        default=None,
        description="Git 仓库中要安装的 Skill 目录名；仓库根目录本身是 Skill 时可省略。",
    )


def _runtime_context(runtime: ToolRuntime | None) -> Any:
    return runtime.context if runtime is not None else None


def _safe_user_segment(user_key: str) -> str:
    digest = hashlib.sha256(user_key.encode("utf-8")).hexdigest()[:12]
    return f"user-{digest}"


def _validate_skill_dir(source_dir: Path) -> tuple[str, str]:
    """校验 Skill 目录并返回 slug 与受限大小的 SKILL.md 内容。"""
    slug = source_dir.name.strip().lower()
    if len(slug) > 80 or not SKILL_SLUG_PATTERN.fullmatch(slug):
        raise ValueError(f"Skill slug '{slug}' 不合法，仅允许小写字母、数字和连字符")

    skill_file = source_dir / "SKILL.md"
    if not skill_file.is_file():
        raise ValueError(f"{source_dir} 中未找到 SKILL.md")

    entries = list(source_dir.rglob("*"))
    if any(item.is_symlink() for item in entries):
        raise ValueError("Skill 目录不允许包含符号链接")
    file_count = sum(1 for item in entries if item.is_file())
    if file_count > MAX_SKILL_FILES:
        raise ValueError(f"Skill 文件数超过限制，最多允许 {MAX_SKILL_FILES} 个文件")

    content = skill_file.read_bytes()
    if len(content) > MAX_SKILL_PROMPT_BYTES:
        raise ValueError(f"SKILL.md 超过 {MAX_SKILL_PROMPT_BYTES} 字节限制")
    return slug, content.decode("utf-8", errors="replace").strip()


def _normalize_github_source(source: str) -> str | None:
    normalized = source.strip().removesuffix(".git")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", normalized):
        return f"https://github.com/{normalized}.git"
    match = re.fullmatch(
        r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)",
        normalized,
    )
    if match:
        return f"https://github.com/{match.group(1)}/{match.group(2)}.git"
    return None


def _clone_repository(url: str, target_dir: Path) -> None:
    result = subprocess.run(
        ["git", "clone", "--depth", "1", url, str(target_dir)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "Git 仓库克隆失败")


def _resolve_local_source(source: str) -> Path:
    """只允许从配置的导入目录读取本地 Skill，避免任意文件系统访问。"""
    imports_root = Path(get_settings().runtime_skill_imports_dir).expanduser().resolve()
    candidate = Path(source).expanduser().resolve()
    try:
        candidate.relative_to(imports_root)
    except ValueError as exc:
        raise ValueError(f"本地 Skill 只能来自目录: {imports_root}") from exc
    if not candidate.is_dir():
        raise ValueError(f"Skill 来源目录不存在: {candidate}")
    return candidate


def _find_skill_sources(repo_dir: Path, skill_names: list[str] | None) -> list[Path]:
    """按名称定位仓库中的 Skill 目录；根目录含 SKILL.md 时允许直接安装。"""
    if (repo_dir / "SKILL.md").is_file() and not skill_names:
        return [repo_dir]
    if not skill_names:
        raise ValueError("仓库根目录不是 Skill，请通过 skill_names 指定要安装的 Skill")

    ordered_names = list(
        dict.fromkeys(str(name).strip() for name in skill_names if str(name).strip())
    )
    requested = set(ordered_names)
    found: dict[str, Path] = {}
    for skill_file in repo_dir.rglob("SKILL.md"):
        parent = skill_file.parent
        if parent.name in requested and parent.name not in found:
            found[parent.name] = parent
    missing = sorted(requested - set(found))
    if missing:
        raise ValueError(f"未找到 Skill: {', '.join(missing)}")
    return [found[name] for name in ordered_names]


def _next_target_dir(root: Path, slug: str) -> Path:
    target = root / slug
    suffix = 2
    while target.exists():
        target = root / f"{slug}-{suffix}"
        suffix += 1
    return target


async def _register_installed_skill(
    *,
    source_dir: Path,
    source: str,
    user_key: str,
) -> dict[str, Any]:
    """复制 Skill 文件并注册为当前用户拥有的启用资源。"""
    slug, instructions = _validate_skill_dir(source_dir)
    settings = get_settings()
    user_root = (
        Path(settings.runtime_skills_dir).expanduser().resolve()
        / _safe_user_segment(user_key)
    )
    user_root.mkdir(parents=True, exist_ok=True)
    target_dir = _next_target_dir(user_root, slug)
    shutil.copytree(source_dir, target_dir)

    runtime_name = f"{_safe_user_segment(user_key)}-{target_dir.name}"
    async with AsyncSessionLocal() as db:
        resource = await PluginResourceRepository(db).upsert(
            {
                "kind": "skill",
                "name": runtime_name,
                "display_name": target_dir.name,
                "description": f"由用户 {user_key} 安装的 Skill",
                "enabled": True,
                "config": {
                    "prompt_path": str(target_dir / "SKILL.md"),
                    "instructions": instructions,
                    "source": source,
                    "owner_user_key": user_key,
                    "dependencies": {"mcps": [], "skills": [], "tools": []},
                },
            }
        )

        return resource.to_dict()


async def _prepare_and_install(
    source: str,
    skill_names: list[str] | None,
    user_key: str,
) -> list[dict[str, Any]]:
    github_url = _normalize_github_source(source)
    if github_url:
        with tempfile.TemporaryDirectory(prefix="minibot-skill-") as temp_dir:
            repo_dir = Path(temp_dir) / "repo"
            await asyncio.to_thread(_clone_repository, github_url, repo_dir)
            sources = _find_skill_sources(repo_dir, skill_names)
            return [
                await _register_installed_skill(
                    source_dir=item,
                    source=source,
                    user_key=user_key,
                )
                for item in sources
            ]

    local_source = _resolve_local_source(source)
    return [
        await _register_installed_skill(
            source_dir=local_source,
            source=source,
            user_key=user_key,
        )
    ]


@tool(
    category="buildin",
    tags=["skill", "安装"],
    display_name="安装技能",
    args_schema=InstallSkillInput,
)
async def install_skill(
    source: str,
    skill_names: list[str] | None = None,
    runtime: ToolRuntime | None = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """安装 Skill，并立即作为当前用户的启用扩展参与运行。"""
    context = _runtime_context(runtime)
    user_key = str(getattr(context, "user_key", "") or "").strip()
    event = start_tool_call(
        context,
        tool_name="install_skill",
        payload={"source": source, "skill_names": skill_names or []},
    )
    if not user_key:
        error = "无法获取当前用户信息"
        fail_tool_call(event, error)
        return Command(
            update={"messages": [ToolMessage(content=f"错误：{error}", tool_call_id=tool_call_id)]}
        )

    try:
        resources = await _prepare_and_install(source.strip(), skill_names, user_key)
    except Exception as error:
        fail_tool_call(event, error)
        return Command(
            update={
                "messages": [
                    ToolMessage(content=f"Skill 安装失败：{error}", tool_call_id=tool_call_id)
                ]
            }
        )

    if context is not None and isinstance(getattr(context, "skills", None), list):
        existing = {item.get("name") for item in context.skills}
        context.skills.extend(item for item in resources if item.get("name") not in existing)

    installed_names = [item["name"] for item in resources]
    finish_tool_call(event, installed_skills=installed_names)
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=f"成功安装并激活 Skill: {', '.join(installed_names)}",
                    tool_call_id=tool_call_id,
                )
            ]
        }
    )
