from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from app.agents.skills.models import SkillMetadata, SkillRuntimeSnapshot
from app.agents.sandbox.paths import VIRTUAL_SKILLS_ROOT

logger = logging.getLogger(__name__)

SKILL_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def normalize_names(values: object) -> tuple[str, ...]:
    """Normalize a dependency list while preserving declaration order."""
    if not isinstance(values, (list, tuple, set)):
        return ()
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = str(value or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return tuple(result)


def build_skill_runtime_snapshot(resources: Iterable[dict]) -> SkillRuntimeSnapshot:
    """Build the immutable Skill catalog and recursively readable dependency closure."""
    metadata: dict[str, SkillMetadata] = {}
    selected: list[str] = []

    for resource in resources:
        slug = str(resource.get("name") or "").strip()
        if not SKILL_SLUG_PATTERN.fullmatch(slug):
            logger.warning("Ignore Skill with invalid runtime name: %s", slug)
            continue

        config = resource.get("config") or {}
        dependencies = config.get("dependencies") or {}
        prompt_path = str(config.get("prompt_path") or "").strip()
        if not prompt_path:
            logger.warning("Ignore Skill without prompt_path: %s", slug)
            continue

        metadata[slug] = SkillMetadata(
            slug=slug,
            name=str(resource.get("display_name") or slug).strip() or slug,
            description=str(resource.get("description") or "").strip(),
            prompt_path=prompt_path,
            tool_dependencies=normalize_names(dependencies.get("tools")),
            mcp_dependencies=normalize_names(dependencies.get("mcps")),
            skill_dependencies=normalize_names(dependencies.get("skills")),
        )
        selected.append(slug)

    readable: list[str] = []
    visited: set[str] = set()

    def visit(slug: str, stack: tuple[str, ...]) -> None:
        if slug in stack:
            logger.warning("Cycle detected in Skill dependencies: %s", " -> ".join((*stack, slug)))
            return
        if slug in visited:
            return
        item = metadata.get(slug)
        if item is None:
            logger.warning("Skill dependency is unavailable or unauthorized: %s", slug)
            return
        visited.add(slug)
        readable.append(slug)
        for dependency in item.skill_dependencies:
            visit(dependency, (*stack, slug))

    for slug in selected:
        visit(slug, ())

    return SkillRuntimeSnapshot(
        selected_slugs=tuple(selected),
        readable_slugs=tuple(readable),
        metadata=metadata,
    )


def skill_entry_virtual_path(slug: str) -> str:
    return f"{VIRTUAL_SKILLS_ROOT}/{slug}/SKILL.md"
