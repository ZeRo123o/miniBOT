from __future__ import annotations

from typing import Any

import yaml


def parse_skill_frontmatter(content: str) -> dict[str, Any]:
    """解析 SKILL.md 顶部的 YAML frontmatter。"""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration:
        raise ValueError("SKILL.md frontmatter 缺少结束分隔符 ---") from None

    data = yaml.safe_load("\n".join(lines[1:end])) or {}
    if not isinstance(data, dict):
        raise ValueError("SKILL.md frontmatter 必须是对象")
    return data


def skill_dependency_names(metadata: dict[str, Any], kind: str) -> list[str]:
    """读取新版 dependencies 或兼容旧版扁平依赖字段。"""
    dependencies = metadata.get("dependencies") or {}
    nested = dependencies.get(kind) if isinstance(dependencies, dict) else None
    legacy_key = {
        "tools": "tool_dependencies",
        "mcps": "mcp_dependencies",
        "skills": "skill_dependencies",
    }[kind]
    values = nested if nested is not None else metadata.get(legacy_key)
    if not isinstance(values, list):
        return []
    return list(
        dict.fromkeys(
            str(value or "").strip()
            for value in values
            if str(value or "").strip()
        )
    )
