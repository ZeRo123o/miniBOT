from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.skills.service import install_builtin_skill


def builtin_skills_root() -> Path:
    """Return the Skill source directory bundled with the application."""
    return Path(__file__).resolve().parent


def discover_builtin_skill_dirs() -> list[Path]:
    """Return direct child directories containing a built-in SKILL.md."""
    return [
        skill_file.parent
        for skill_file in sorted(builtin_skills_root().glob("*/SKILL.md"))
    ]


async def sync_builtin_skills(db: AsyncSession) -> None:
    """Install all bundled Skills and synchronize their PostgreSQL metadata."""
    for source_dir in discover_builtin_skill_dirs():
        await install_builtin_skill(db, source_dir)


__all__ = ["builtin_skills_root", "discover_builtin_skill_dirs", "sync_builtin_skills"]
