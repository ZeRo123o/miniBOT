from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    """Immutable metadata used by one agent run."""

    slug: str
    name: str
    description: str
    prompt_path: str
    tool_dependencies: tuple[str, ...] = ()
    mcp_dependencies: tuple[str, ...] = ()
    skill_dependencies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkillRuntimeSnapshot:
    """Authorized Skill view captured before an agent run starts."""

    selected_slugs: tuple[str, ...] = ()
    readable_slugs: tuple[str, ...] = ()
    metadata: dict[str, SkillMetadata] = field(default_factory=dict)

    def get(self, slug: str) -> SkillMetadata | None:
        return self.metadata.get(slug)
