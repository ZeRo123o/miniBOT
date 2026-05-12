from app.graph.state import ChatState

DEFAULT_SYSTEM_PROMPT = "You are miniBOT, a modular assistant."


def build_resource_context(state: ChatState) -> str:
    mcps = [item.get("name", "") for item in state.get("mcps", [])]
    skills = [item.get("name", "") for item in state.get("skills", [])]
    subagents = [item.get("name", "") for item in state.get("subagents", [])]
    return (
        "当前启用资源：\n"
        f"- MCP: {mcps or '无'}\n"
        f"- Skill: {skills or '无'}\n"
        f"- Subagent: {subagents or '无'}"
    )


def build_system_prompt(state: ChatState, base_prompt: str = DEFAULT_SYSTEM_PROMPT) -> str:
    runtime = state.get("runtime", {})
    parts = [
        base_prompt,
        build_resource_context(state),
    ]
    if runtime.get("skill_prompt"):
        parts.append(runtime["skill_prompt"])
    return "\n\n".join(parts)
