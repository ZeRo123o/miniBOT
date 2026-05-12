from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import PluginResourceRepository


async def resolve_resources_by_name(
    db: AsyncSession,
    *,
    kind: str,
    names: list[str],
) -> list[dict]:
    repo = PluginResourceRepository(db)
    resolved = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        item = await repo.get_by_name(kind, name)
        if item and item.enabled:
            resolved.append(item.to_dict())
    return resolved


async def seed_builtin_resources(db: AsyncSession) -> None:
    repo = PluginResourceRepository(db)
    samples = [
        {
            "kind": "mcp",
            "name": "filesystem",
            "display_name": "Filesystem MCP",
            "description": "Example MCP server placeholder.",
            "config": {"transport": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]},
        },
        {
            "kind": "skill",
            "name": "reporter",
            "display_name": "Reporter Skill",
            "description": "Draft structured reports from gathered context.",
            "config": {"prompt_path": "skills/reporter/SKILL.md", "dependencies": {"mcps": [], "skills": []}},
        },
        {
            "kind": "subagent",
            "name": "researcher",
            "display_name": "Researcher Subagent",
            "description": "A focused helper for research and source synthesis.",
            "config": {"system_prompt": "You are a concise research subagent.", "tools": []},
        },
    ]
    for item in samples:
        await repo.upsert({"enabled": True, **item})
