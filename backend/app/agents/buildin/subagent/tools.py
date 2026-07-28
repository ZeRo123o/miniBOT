import asyncio
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.middlewares.subagent_middleware import (
    SubAgentProfile,
    resolve_subagent_profile,
)
from app.agents.buildin.subagent.runner import SubAgentRunner
from app.agents.middlewares.subagent_middleware import create_or_get_child_run, finish_run, make_child_thread_id
from app.agents.toolkits.governance import (
    emit_runtime_event,
    fail_tool_call,
    finish_tool_call,
    start_tool_call,
)


TASK_DESCRIPTION = """
Delegate a complex, independently solvable subtask to a specialized subagent.

Independent subtasks may be called in parallel. Omit thread_id to create a new isolated
subagent thread. Pass a thread_id returned by an earlier task only to continue that task.
Do not call the same thread_id in parallel.
""".strip()

TASK_DESCRIPTION_ARG = "A short title or summary for the delegated task."
TASK_PROMPT_ARG = "The detailed task prompt sent to the subagent."
SUBAGENT_TYPE_ARG = "The subagent profile name to use."
EXPECTED_OUTPUT_ARG = "Optional format or content expectations."
THREAD_ID_ARG = "Optional child thread ID returned by an earlier task; omit for a new task."


def build_task_tool(profiles: dict[str, SubAgentProfile]) -> StructuredTool:
    """创建由中间件管理、支持子运行追踪的任务工具。"""

    def task(
        description: Annotated[str, TASK_DESCRIPTION_ARG],
        prompt: Annotated[str, TASK_PROMPT_ARG],
        runtime: ToolRuntime,
        subagent_type: Annotated[str, SUBAGENT_TYPE_ARG] = "general-purpose",
        expected_output: Annotated[str, EXPECTED_OUTPUT_ARG] = "",
        thread_id: Annotated[str | None, THREAD_ID_ARG] = None,
    ) -> str:
        return "task supports async invocation only."

    async def atask(
        description: Annotated[str, TASK_DESCRIPTION_ARG],
        prompt: Annotated[str, TASK_PROMPT_ARG],
        runtime: ToolRuntime,
        subagent_type: Annotated[str, SUBAGENT_TYPE_ARG] = "general-purpose",
        expected_output: Annotated[str, EXPECTED_OUTPUT_ARG] = "",
        thread_id: Annotated[str | None, THREAD_ID_ARG] = None,
    ) -> Command | str:
        """Run one isolated child graph and merge its terminal state into the parent graph."""
        context = runtime.context
        tool_call_id = _tool_call_id(runtime)
        event = start_tool_call(
            context,
            tool_name="task",
            payload={"description": description[:200], "subagent_type": subagent_type},
            tool_call_id=tool_call_id,
        )
        run: dict[str, Any] | None = None
        child_thread_id = ""

        try:
            if not isinstance(context, AgentContext):
                raise ValueError("task requires AgentContext runtime")
            _validate_subagent_limits(context, prompt)
            profile = resolve_subagent_profile(profiles, subagent_type)
            if profile is None:
                allowed = ", ".join(sorted(profiles))
                raise ValueError(f"unknown subagent_type: {subagent_type}; allowed: {allowed}")
            if not context.run_id or not context.thread_id:
                raise ValueError("task requires a persisted parent run and logical thread ID")

            # This increment happens before the first await, so concurrent tool coroutines cannot
            # all pass the per-parent task limit before claiming a slot.
            context.subagent_task_count += 1
            requested_thread_id = str(thread_id or "").strip()
            continuing = bool(requested_thread_id)
            child_thread_id = requested_thread_id or make_child_thread_id(
                context.thread_id,
                profile.name,
                tool_call_id,
            )
            run, is_new_run = await create_or_get_child_run(
                parent_run_id=context.run_id,
                parent_thread_id=context.thread_id,
                child_thread_id=child_thread_id,
                conversation_id=int(context.conversation_id or 0),
                user_id=context.user_id,
                subagent_type=profile.name,
                tool_call_id=tool_call_id,
                description=description,
                continuing=continuing,
            )
            emit_runtime_event(
                context,
                {
                    "type": "subagent_status",
                    "status": "running",
                    "subagent_type": profile.name,
                    "child_thread_id": child_thread_id,
                    "run_id": run["id"],
                    "tool_call_id": tool_call_id,
                },
            )
            if not is_new_run:
                content = str((run.get("result_payload") or {}).get("content") or "")
                existing_state = _state_run(run, profile.name, description, child_thread_id)
                emit_runtime_event(
                    context,
                    {"type": "subagent_status", "tool_call_id": tool_call_id, **existing_state},
                )
                return _task_command(
                    runtime,
                    content=_format_task_result(profile.name, description, content, False, run, child_thread_id),
                    subagent_run=existing_state,
                    artifacts=list((run.get("result_payload") or {}).get("artifacts") or []),
                )

            # 子图的文本仅走 subagent_token；运行期间不允许混入主回答 token。
            context.active_subagent_run_count += 1
            try:
                result = await SubAgentRunner().run(
                    parent_context=context,
                    profile=profile,
                    prompt=prompt[: context.subagent_prompt_max_chars],
                    expected_output=expected_output,
                    uploads=_state_uploads(runtime),
                    files=_state_files(runtime),
                    child_thread_id=child_thread_id,
                    child_run_id=str(run["id"]),
                    parent_tool_call_id=tool_call_id,
                )
            finally:
                context.active_subagent_run_count = max(0, context.active_subagent_run_count - 1)
            content = str(result.get("content") or "")
            truncated = len(content) > context.subagent_result_max_chars
            if truncated:
                content = f"{content[: context.subagent_result_max_chars]}\n\n[Subagent result truncated]"
            artifacts = list(result.get("artifacts") or [])
            run = await finish_run(
                str(run["id"]),
                status="completed",
                result_payload={"content": content, "artifacts": artifacts, "truncated": truncated},
            )
            state_run = _state_run(run, profile.name, description, child_thread_id, truncated=truncated)
            emit_runtime_event(
                context,
                {"type": "subagent_status", "status": "completed", "tool_call_id": tool_call_id, **state_run},
            )
            finish_tool_call(
                event,
                subagent_type=profile.name,
                child_thread_id=child_thread_id,
                child_tool_event_count=len(result.get("tool_events") or []),
                child_tool_calls=result.get("tool_events") or [],
            )
            return _task_command(
                runtime,
                content=_format_task_result(profile.name, description, content, truncated, run, child_thread_id),
                subagent_run=state_run,
                artifacts=artifacts,
            )
        except asyncio.CancelledError:
            if run is not None:
                await finish_run(str(run["id"]), status="cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            fail_tool_call(event, exc)
            if run is not None:
                run = await finish_run(str(run["id"]), status="failed", error=exc)
            failed_run = _state_run(
                run or {"id": f"subagent:{tool_call_id}:{subagent_type}", "status": "failed"},
                subagent_type,
                description,
                child_thread_id or f"subagent:{tool_call_id}:{subagent_type}",
                error=str(exc),
            )
            if isinstance(context, AgentContext):
                emit_runtime_event(
                    context,
                    {"type": "subagent_status", "status": "failed", "tool_call_id": tool_call_id, **failed_run},
                )
            return _task_command(
                runtime,
                content=f"Subagent thread ID: {failed_run['child_thread_id']}\n\nError: {exc}",
                subagent_run=failed_run,
                artifacts=[],
            )

    return StructuredTool.from_function(
        name="task",
        func=task,
        coroutine=atask,
        description=TASK_DESCRIPTION,
        infer_schema=True,
    )


def _validate_subagent_limits(context: AgentContext, prompt: str) -> None:
    if not context.allow_subagents:
        raise ValueError("subagent delegation is disabled in this context")
    if context.subagent_depth >= 1:
        raise ValueError("nested subagent delegation is not allowed")
    if context.subagent_task_count >= context.max_subagent_tasks_per_run:
        raise ValueError("subagent task limit reached for this run")
    if len(prompt) > context.subagent_prompt_max_chars:
        raise ValueError(f"task prompt exceeds {context.subagent_prompt_max_chars} characters")


def _state_uploads(runtime: ToolRuntime | None) -> list[dict[str, Any]]:
    state = getattr(runtime, "state", None)
    value = state.get("uploads") if isinstance(state, dict) else None
    return value if isinstance(value, list) else []


def _state_files(runtime: ToolRuntime | None) -> dict:
    state = getattr(runtime, "state", None)
    value = state.get("files") if isinstance(state, dict) else None
    return value if isinstance(value, dict) else {}


def _tool_call_id(runtime: ToolRuntime | None) -> str:
    return str(getattr(runtime, "tool_call_id", "") or "unknown")


def _state_run(
    run: dict[str, Any],
    subagent_type: str,
    description: str,
    child_thread_id: str,
    *,
    truncated: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    result = run.get("result_payload") or {}
    return {
        "id": run.get("id"),
        "subagent_type": subagent_type,
        "child_thread_id": child_thread_id,
        "description": description,
        "status": run.get("status", "failed" if error else "unknown"),
        "truncated": truncated or bool(result.get("truncated")),
        "artifacts": list(result.get("artifacts") or []),
        "result_preview": str(result.get("content") or "")[:500],
        "error": error or run.get("error_message"),
    }


def _task_command(
    runtime: ToolRuntime | None,
    *,
    content: str,
    subagent_run: dict[str, Any],
    artifacts: list[str],
) -> Command | str:
    tool_call_id = _tool_call_id(runtime)
    if tool_call_id == "unknown":
        return content
    update: dict[str, Any] = {
        "messages": [ToolMessage(content=content, tool_call_id=tool_call_id)],
        "subagent_runs": [subagent_run],
    }
    if artifacts:
        update["artifacts"] = artifacts
    return Command(update=update)


def _format_task_result(
    subagent_type: str,
    description: str,
    content: str,
    truncated: bool,
    run: dict[str, Any],
    child_thread_id: str,
) -> str:
    suffix = "\n\nNote: the result was truncated; use only the visible part." if truncated else ""
    return (
        f"Subagent run ID: {run.get('id')}\n"
        f"Subagent thread ID: {child_thread_id}\n"
        f"Subagent: {subagent_type}\n"
        f"Task: {description}\n\n{content}{suffix}"
    )
