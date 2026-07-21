"""子智能体委派中间件入口。

该模块是父聊天智能体接入子任务能力的唯一入口；具体的任务执行、图构建
和流式转发仍由 ``buildin.subagent`` 下的执行层负责，避免向父图暴露实现细节。
"""

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from app.agents.buildin.chatbot.context import AgentContext
from app.db.repositories import AgentRunRepository
from app.db.session import AsyncSessionLocal


@dataclass(frozen=True)
class SubAgentProfile:
    """一个内置子智能体的静态能力与提示词契约。"""

    name: str
    description: str
    system_prompt: str
    # 这里声明的是完整工具白名单，不是可由 Skill 或 Middleware 扩大的初始集合。
    tool_names: frozenset[str] = field(default_factory=frozenset)
    skill_slugs: frozenset[str] = field(default_factory=frozenset)
    model_use: str | None = None
    max_tool_calls: int = 6


BUILTIN_SUBAGENTS: dict[str, SubAgentProfile] = {
    "general": SubAgentProfile(
        name="general",
        description="处理独立推理、归纳或多步骤分析任务。",
        system_prompt="你是通用分析子智能体。只完成父智能体委派的具体任务，不与用户直接对话。",
    ),
    "planner": SubAgentProfile(
        name="planner",
        description="将复杂目标拆解为可执行步骤、依赖与验收标准。",
        system_prompt="你是任务规划子智能体。输出清晰、可执行、可验证的计划，不直接实施。",
    ),
    "researcher": SubAgentProfile(
        name="researcher",
        description="检索公开资料或知识库，提炼可追溯的事实与证据。",
        system_prompt="你是研究型子智能体。优先使用授权工具验证信息，区分事实与不确定项。",
        tool_names=frozenset({"tavily_search", "list_kbs", "query_kb"}),
        skill_slugs=frozenset({"web-research"}),
    ),
    "coder": SubAgentProfile(
        name="coder",
        description="只读分析代码、调用链与最小修改方案。",
        system_prompt="你是代码分析子智能体。只读调查，不修改文件、不执行宿主机命令。",
        tool_names=frozenset(
            {
                "sandbox_read_file",
                "sandbox_ls",
                "sandbox_grep",
                "sandbox_glob",
            }
        ),
    ),
}


@dataclass(kw_only=True)
class SubAgentContext(AgentContext):
    """隔离子图运行所需的最小上下文。"""

    subagent_type: str = ""
    # Runner 从受信任的静态 Profile 写入；Resolver 将其作为最终权限边界。
    allowed_tool_names: frozenset[str] = field(default_factory=frozenset)
    parent_tool_call_id: str = ""
    allow_subagents: bool = False


def make_parent_thread_id(conversation_id: int) -> str:
    return f"conversation:{conversation_id}"


def make_child_thread_id(parent_thread_id: str, subagent_type: str, tool_call_id: str) -> str:
    digest = hashlib.sha256(f"{parent_thread_id}:{subagent_type}:{tool_call_id}".encode("utf-8")).hexdigest()
    return f"subagent_{digest[:55]}"


def make_subagent_request_id(parent_run_id: str, child_thread_id: str, tool_call_id: str, subagent_type: str) -> str:
    digest = hashlib.sha256(f"{parent_run_id}:{child_thread_id}:{tool_call_id}:{subagent_type}".encode("utf-8")).hexdigest()
    return f"subagent:{digest[:48]}"


async def create_parent_run(*, user_id: str, conversation_id: int, thread_id: str, message: str) -> dict[str, Any]:
    """持久化本次聊天对应的父运行，供其所有子任务关联。"""
    run_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        item = await AgentRunRepository(db).create({"id": run_id, "conversation_id": conversation_id, "user_id": user_id, "thread_id": thread_id, "agent_id": "chatbot", "run_type": "chat", "request_id": f"chat:{run_id}", "checkpoint_thread_id": thread_id, "status": "running", "input_payload": {"message": message[:12000]}})
    return item.to_dict()


async def create_or_get_child_run(*, parent_run_id: str, parent_thread_id: str, child_thread_id: str, conversation_id: int, user_id: str, subagent_type: str, tool_call_id: str, description: str, continuing: bool) -> tuple[dict[str, Any], bool]:
    """创建幂等子运行，并校验指定的续跑线程。"""
    request_id = make_subagent_request_id(parent_run_id, child_thread_id, tool_call_id, subagent_type)
    async with AsyncSessionLocal() as db:
        repository = AgentRunRepository(db)
        existing = await repository.get_by_request_id(request_id)
        if existing is not None:
            return existing.to_dict(), False
        if continuing:
            previous = await repository.get_latest_subagent_for_thread(thread_id=child_thread_id, user_id=user_id)
            if previous is None or previous.conversation_id != conversation_id:
                raise ValueError("The requested subagent thread is not available in this conversation.")
            if previous.agent_id != subagent_type:
                raise ValueError("The requested subagent thread belongs to a different subagent type.")
        item = await repository.create({"id": str(uuid.uuid4()), "conversation_id": conversation_id, "user_id": user_id, "thread_id": child_thread_id, "agent_id": subagent_type, "parent_agent_run_id": parent_run_id, "run_type": "subagent", "request_id": request_id, "checkpoint_thread_id": child_thread_id, "status": "running", "input_payload": {"description": description, "tool_call_id": tool_call_id, "subagent_type": subagent_type, "parent_thread_id": parent_thread_id, "child_thread_id": child_thread_id, "continuing": continuing}})
    return item.to_dict(), True


async def finish_run(run_id: str, *, status: str, result_payload: dict[str, Any] | None = None, error: Exception | None = None) -> dict[str, Any]:
    """使用独立数据库会话写入终态，避免并行任务共享会话。"""
    async with AsyncSessionLocal() as db:
        item = await AgentRunRepository(db).set_terminal_status(run_id, status=status, result_payload=result_payload, error_type=type(error).__name__ if error else None, error_message=str(error) if error else None)
    return item.to_dict()


class SubAgentMiddleware(AgentMiddleware):
    """向父智能体暴露私有 ``task`` 工具及其委派策略。"""

    def __init__(self) -> None:
        super().__init__()
        self.profiles = BUILTIN_SUBAGENTS
        # 延迟导入：task 执行器会反向依赖本模块中定义的上下文与契约。
        from app.agents.buildin.subagent.tools import build_task_tool

        self.tools = [build_task_tool(self.profiles)]

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        context = request.runtime.context
        if isinstance(context, AgentContext) and context.allow_subagents:
            request = request.override(
                system_message=_append_system_message(request.system_message, self._prompt())
            )
        return await handler(request)

    def _prompt(self) -> str:
        profiles = "\n".join(
            f"- {name}: {profile.description}" for name, profile in self.profiles.items()
        )
        return f"""
你可以在任务复杂时调用 task 工具委派子智能体。

适合调用 task 的情况：
- 需要多步骤研究或跨文件分析
- 需要先探索再总结
- 可以拆成独立子问题，结果仍需由你综合

不要调用 task 的情况：
- 简单问答
- 单次工具调用即可完成
- 用户只要求简短解释

可用子智能体：
{profiles}

每个 task 必须包含明确目标、必要上下文和期望输出。子智能体返回后，必须由你整合结果，而非原样复述。""".strip()


def _append_system_message(message: SystemMessage | None, section: str) -> SystemMessage:
    """仅追加一次任务策略，同时保留结构化 system message 内容。"""
    normalized = section.strip()
    if not normalized:
        return message or SystemMessage(content="")
    existing_text = _message_text(message)
    if normalized in existing_text:
        return message or SystemMessage(content=normalized)
    existing_blocks = list(message.content_blocks) if message else []
    return SystemMessage(content=[*existing_blocks, {"type": "text", "text": normalized}])


def _message_text(message: object) -> str:
    if message is None:
        return ""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content)
