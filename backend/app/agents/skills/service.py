from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.skills.parser import parse_skill_frontmatter, skill_dependency_names
from app.core.config import get_settings
from app.db.models import Skill
from app.repositories.skill_repository import SkillRepository

SKILL_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def normalize_string_list(values: list[str] | None) -> list[str]:
    """Normalize context and dependency lists while preserving declaration order."""
    return list(
        dict.fromkeys(
            value.strip()
            for value in values or []
            if isinstance(value, str) and value.strip()
        )
    )


def is_valid_skill_slug(value: Any) -> bool:
    return isinstance(value, str) and SKILL_SLUG_PATTERN.fullmatch(value) is not None


def runtime_skills_root() -> Path:
    root = Path(get_settings().runtime_skills_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_skill_dir(dir_path: str) -> Path:
    """Resolve a database path below the configured Skill root."""
    root = runtime_skills_root()
    target = (root / dir_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Skill dir_path escapes runtime root: {dir_path}") from exc
    return target


def hash_skill_directory(source_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in source_dir.rglob("*") if item.is_file()):
        digest.update(path.relative_to(source_dir).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def read_skill_definition(source_dir: Path) -> dict[str, Any]:
    """Validate SKILL.md and return the metadata persisted in PostgreSQL."""
    slug = source_dir.name.strip().lower()
    if not is_valid_skill_slug(slug):
        raise ValueError(f"Invalid Skill slug: {slug}")
    skill_file = source_dir / "SKILL.md"
    if not skill_file.is_file():
        raise ValueError(f"SKILL.md not found in {source_dir}")
    metadata = parse_skill_frontmatter(skill_file.read_text(encoding="utf-8"))
    name = str(metadata.get("name") or slug).strip()
    description = str(metadata.get("description") or "").strip()
    if not name or not description:
        raise ValueError(f"Skill {slug} must declare name and description")
    return {
        "slug": slug,
        "name": name,
        "description": description,
        "tool_dependencies": skill_dependency_names(metadata, "tools"),
        "mcp_dependencies": skill_dependency_names(metadata, "mcps"),
        "skill_dependencies": skill_dependency_names(metadata, "skills"),
        "version": str(metadata.get("version") or "1.0.0").strip(),
        "content_hash": hash_skill_directory(source_dir),
    }


async def install_builtin_skill(db: AsyncSession, source_dir: Path) -> Skill:
    """Copy one built-in Skill to the runtime root and synchronize its DB index."""
    definition = read_skill_definition(source_dir)
    slug = definition["slug"]
    target_dir = runtime_skills_root() / slug
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir, symlinks=False)

    repo = SkillRepository(db)
    item = await repo.get_by_slug(slug)
    if item is None:
        return await repo.create(
            **definition,
            dir_path=slug,
            is_builtin=True,
            created_by="system",
        )

    await repo.update_metadata(
        item,
        name=definition["name"],
        description=definition["description"],
        dir_path=slug,
        updated_by="system",
    )
    await repo.update_dependencies(
        item,
        tool_dependencies=definition["tool_dependencies"],
        mcp_dependencies=definition["mcp_dependencies"],
        skill_dependencies=definition["skill_dependencies"],
        updated_by="system",
    )
    return await repo.update_builtin_install(
        item,
        version=definition["version"],
        content_hash=definition["content_hash"],
        updated_by="system",
    )
