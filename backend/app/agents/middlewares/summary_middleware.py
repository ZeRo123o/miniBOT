from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Iterable
from functools import partial
from typing import Any, cast

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    MessageLikeRepresentation,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.utils import (
    count_tokens_approximately,
    get_buffer_string,
    trim_messages,
)
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime

from app.agents.backends.filesystem import (
    AgentFilesystemBackend,
    create_agent_filesystem_backend,
)
from app.agents.buildin.chatbot.context import AgentContext
from app.agents.backends.sandbox.paths import VIRTUAL_WORKSPACE_ROOT
from app.llm import get_model

TokenCounter = Callable[[Iterable[MessageLikeRepresentation]], int]

DEFAULT_SUMMARY_PROMPT = """<role>
Context Extraction Assistant
</role>

<primary_objective>
Your sole objective in this task is to extract the highest quality/most relevant
context from the conversation history below.
</primary_objective>

<objective_information>
You're nearing the total number of input tokens you can accept, so you must
extract the highest quality/most relevant pieces of information from your conversation
history. This context will then overwrite the conversation history presented below.
Because of this, ensure the context you extract is only the most important information
to your overall goal.
</objective_information>

<instructions>
The conversation history below will be replaced with the context you extract in
this step. Because of this, you must do your very best to extract and record all
of the most important context from the conversation history. You want to ensure
that you don't repeat any actions you've already completed, so the context you
extract from the conversation history should be focused on the most important
information to your overall goal.

If an existing summary is provided, merge it with the new history instead of
discarding it.
</instructions>

Existing summary:
{summary}

<messages>
Messages to summarize:
{messages}
</messages>"""

_DEFAULT_MESSAGES_TO_KEEP = 20
_DEFAULT_FALLBACK_MESSAGE_COUNT = 15
_OFFLOAD_DIR = ".minibot/summary_offload"
_TOOL_RESULT_SAVED_MARKER = "minibot_tool_result_saved"


def _get_approximate_token_counter(model: BaseChatModel) -> TokenCounter:
    """Tune the approximate token counter for providers with known token density."""
    if model._llm_type == "anthropic-chat":  # noqa: SLF001
        return partial(count_tokens_approximately, chars_per_token=3.3)
    return count_tokens_approximately


def _message_content_text(content: Any) -> str:
    """Extract plain text from LangChain message content variants."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(part for part in parts if part)
    return "" if content is None else str(content)


def _format_offload_placeholder(
    *,
    file_path: str,
    tool_name: str,
    approx_tokens: int,
    content_sample: str,
    omitted_chars: int,
) -> str:
    """Format the compact ToolMessage content left in conversation history."""
    lines = [
        "[ToolResultOffloaded]",
        f"Tool: {tool_name}",
        f"Approx tokens: {approx_tokens}",
        f"Full output path: {file_path}",
        "Use sandbox_read_file to read the full content when needed.",
    ]
    if content_sample:
        lines.extend(["", "--- Content preview ---", content_sample])
    if omitted_chars > 0:
        lines.append(f"\n[Truncated {omitted_chars} chars. Read the full output from the saved file.]")
    return "\n".join(lines)


def _safe_tool_name(name: str | None) -> str:
    value = str(name or "unknown").strip()
    safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in value)
    return safe.strip("._-") or "tool-result"


def _build_offload_file_path(msg: ToolMessage, content: str) -> str:
    """Build a sandbox-readable path for offloaded tool output."""
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    return f"{VIRTUAL_WORKSPACE_ROOT}/{_OFFLOAD_DIR}/{_safe_tool_name(msg.name)}-{digest}.txt"


def _preview_content(content: str, lines_limit: int) -> tuple[str, int]:
    if lines_limit <= 0:
        return "", len(content)
    lines = content.splitlines()
    preview = "\n".join(line[:500] for line in lines[:lines_limit]).strip()
    omitted_chars = max(0, len(content) - len(preview))
    return preview, omitted_chars


class SummaryMiddleware(AgentMiddleware):
    """Summarize long state history and offload oversized ToolMessage results."""

    def before_model(self, state: AgentState[Any], runtime: Runtime) -> dict[str, Any] | None:
        # 同步 Agent 调用入口：所有实际逻辑收敛到同一个处理函数，避免两套分支漂移。
        return self._process_before_model(state, runtime)

    async def abefore_model(self, state: AgentState[Any], runtime: Runtime) -> dict[str, Any] | None:
        # 异步 Agent 调用入口：文件写入和摘要模型调用都走 async 版本，避免阻塞事件循环。
        return await self._aprocess_before_model(state, runtime)

    def _process_before_model(
        self,
        state: AgentState[Any],
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        # Step1 只处理 miniBOT 的 AgentContext；其他上下文不参与摘要与卸载。
        context = getattr(runtime, "context", None)
        if not isinstance(context, AgentContext):
            return None

        # Step2 读取 LangGraph state 中的历史消息；空历史无需处理。
        messages = list(state.get("messages") or [])
        if not messages:
            return None

        # Step3 补齐 message id，保证后续 RemoveMessage + add_messages reducer 可稳定工作。
        self._ensure_message_ids(messages)
        model = get_model(context.model_use)
        token_counter = _get_approximate_token_counter(model)
        total_tokens = token_counter(messages)
        if not self._should_summarize(context, messages, total_tokens):
            return None

        # Step4 触发后先卸载大 ToolMessage，降低工具结果对上下文窗口的占用。
        backend = create_agent_filesystem_backend(runtime)
        offloaded_messages, modified_messages = self._offload_tool_results(
            messages,
            backend=backend,
            preview_lines=context.summary_offload_preview_lines,
            threshold=context.summary_offload_threshold_tokens,
            token_counter=token_counter,
        )

        # Step5 卸载后重新估算 token；只有仍超过保留比例，才真正裁剪历史并摘要。
        current_tokens = token_counter(offloaded_messages)
        trigger_value = self._token_trigger_value(context)
        if trigger_value is None:
            # 没有 token 触发阈值时，按“保留最近 N 条消息”的策略寻找截断点。
            cutoff_index = self._determine_cutoff_index(
                self._without_system_messages(offloaded_messages),
                context.summary_keep_messages,
            )
        else:
            retention_limit = int(trigger_value * context.summary_max_retention_ratio)
            if current_tokens <= retention_limit:
                # 工具结果卸载后已经回到安全范围，只写回被替换的 ToolMessage，不做摘要。
                return {"messages": modified_messages} if modified_messages else None
            cutoff_index = self._find_cutoff_by_token_limit(
                self._without_system_messages(offloaded_messages),
                max(1, retention_limit),
                token_counter,
            )

        # Step6 拆分系统消息与纯对话消息；SystemMessage 始终保留，不参与摘要裁剪。
        system_messages = [msg for msg in offloaded_messages if isinstance(msg, SystemMessage)]
        conversation_messages = self._without_system_messages(offloaded_messages)
        if cutoff_index <= 0:
            # 截断点为 0 表示当前所有对话消息都要保留，不生成摘要。
            return {"messages": modified_messages} if modified_messages else None

        # Step7 将截断点之前的旧消息摘要化，截断点之后的近期消息原样保留。
        messages_to_summarize, preserved_messages = self._partition_messages(
            conversation_messages,
            cutoff_index,
        )
        summary = self._create_summary(
            messages_to_summarize,
            context=context,
            model=model,
            token_counter=token_counter,
        )
        context.summary = summary

        # Step8 用 RemoveMessage 清空旧 state，再写回系统消息、滚动摘要和近期消息。
        final_messages: list[AnyMessage] = [
            *system_messages,
            *self._build_new_messages(summary),
            *preserved_messages,
        ]
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *final_messages]}

    async def _aprocess_before_model(
        self,
        state: AgentState[Any],
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        # Step1 只处理 miniBOT 的 AgentContext；其他上下文不参与摘要与卸载。
        context = getattr(runtime, "context", None)
        if not isinstance(context, AgentContext):
            return None

        # Step2 读取 LangGraph state 中的历史消息；空历史无需处理。
        messages = list(state.get("messages") or [])
        if not messages:
            return None

        # Step3 补齐 message id，保证后续 RemoveMessage + add_messages reducer 可稳定工作。
        self._ensure_message_ids(messages)
        model = get_model(context.model_use)
        token_counter = _get_approximate_token_counter(model)
        total_tokens = token_counter(messages)
        if not self._should_summarize(context, messages, total_tokens):
            return None

        # Step4 异步卸载大 ToolMessage，降低工具结果对上下文窗口的占用。
        backend = create_agent_filesystem_backend(runtime)
        offloaded_messages, modified_messages = await self._aoffload_tool_results(
            messages,
            backend=backend,
            preview_lines=context.summary_offload_preview_lines,
            threshold=context.summary_offload_threshold_tokens,
            token_counter=token_counter,
        )

        # Step5 卸载后重新估算 token；只有仍超过保留比例，才真正裁剪历史并摘要。
        current_tokens = token_counter(offloaded_messages)
        trigger_value = self._token_trigger_value(context)
        if trigger_value is None:
            # 没有 token 触发阈值时，按“保留最近 N 条消息”的策略寻找截断点。
            cutoff_index = self._determine_cutoff_index(
                self._without_system_messages(offloaded_messages),
                context.summary_keep_messages,
            )
        else:
            retention_limit = int(trigger_value * context.summary_max_retention_ratio)
            if current_tokens <= retention_limit:
                # 工具结果卸载后已经回到安全范围，只写回被替换的 ToolMessage，不做摘要。
                return {"messages": modified_messages} if modified_messages else None
            cutoff_index = self._find_cutoff_by_token_limit(
                self._without_system_messages(offloaded_messages),
                max(1, retention_limit),
                token_counter,
            )

        # Step6 拆分系统消息与纯对话消息；SystemMessage 始终保留，不参与摘要裁剪。
        system_messages = [msg for msg in offloaded_messages if isinstance(msg, SystemMessage)]
        conversation_messages = self._without_system_messages(offloaded_messages)
        if cutoff_index <= 0:
            # 截断点为 0 表示当前所有对话消息都要保留，不生成摘要。
            return {"messages": modified_messages} if modified_messages else None

        # Step7 将截断点之前的旧消息摘要化，截断点之后的近期消息原样保留。
        messages_to_summarize, preserved_messages = self._partition_messages(
            conversation_messages,
            cutoff_index,
        )
        summary = await self._acreate_summary(
            messages_to_summarize,
            context=context,
            model=model,
            token_counter=token_counter,
        )
        context.summary = summary

        # Step8 用 RemoveMessage 清空旧 state，再写回系统消息、滚动摘要和近期消息。
        final_messages: list[AnyMessage] = [
            *system_messages,
            *self._build_new_messages(summary),
            *preserved_messages,
        ]
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *final_messages]}

    def _should_summarize(
        self,
        context: AgentContext,
        messages: list[AnyMessage],
        total_tokens: int,
    ) -> bool:
        # token 阈值优先；关闭 token 阈值时可退回到消息数量触发。
        trigger_tokens = self._token_trigger_value(context)
        if trigger_tokens is not None and total_tokens >= trigger_tokens:
            return True
        return context.summary_trigger_messages > 0 and len(messages) >= context.summary_trigger_messages

    @staticmethod
    def _token_trigger_value(context: AgentContext) -> int | None:
        # summary_trigger_tokens <= 0 表示关闭 token 触发，仅保留消息数量触发。
        return context.summary_trigger_tokens if context.summary_trigger_tokens > 0 else None


    def _offload_tool_result(
        self,
        message: ToolMessage,
        *,
        backend: AgentFilesystemBackend,
        preview_lines: int,
        threshold: int,
        token_counter: TokenCounter,
    ) -> ToolMessage | None:
        # 已经卸载过的 ToolMessage 不重复写文件，避免占位内容再次被当成原文保存。
        if getattr(message, "additional_kwargs", {}).get(_TOOL_RESULT_SAVED_MARKER) is True:
            return None

        # 只处理能提取出纯文本的工具结果；空内容没有卸载价值。
        content = _message_content_text(message.content)
        if not content.strip():
            return None

        # 工具结果未超过阈值时保留在消息里，避免无意义的小文件。
        approx_tokens = int(token_counter([message]))
        if approx_tokens <= threshold:
            return None

        # 文件名使用工具名 + 内容 hash，便于去重且不暴露完整查询内容。
        tool_name = message.name or "unknown"
        file_path = _build_offload_file_path(message, content)
        header = "\n".join(
            [
                "=== Tool Invocation ===",
                f"Tool: {tool_name}",
                f"Tool Call ID: {message.tool_call_id or ''}",
                "=" * 40,
                "",
            ]
        )
        write_result = backend.write(file_path, header + content)
        if write_result.error:
            # 卸载失败时保留原始 ToolMessage，避免因压缩辅助能力影响主流程。
            return None

        # 写入成功后，仅把预览和可读取路径留在消息历史里。
        preview, omitted_chars = _preview_content(content, preview_lines)
        additional_kwargs = dict(getattr(message, "additional_kwargs", {}) or {})
        additional_kwargs[_TOOL_RESULT_SAVED_MARKER] = True
        return message.model_copy(
            update={
                "content": _format_offload_placeholder(
                    file_path=file_path,
                    tool_name=tool_name,
                    approx_tokens=approx_tokens,
                    content_sample=preview,
                    omitted_chars=omitted_chars,
                ),
                "additional_kwargs": additional_kwargs,
            }
        )

    async def _aoffload_tool_result(
        self,
        message: ToolMessage,
        *,
        backend: AgentFilesystemBackend,
        preview_lines: int,
        threshold: int,
        token_counter: TokenCounter,
    ) -> ToolMessage | None:
        # 已经卸载过的 ToolMessage 不重复写文件，避免占位内容再次被当成原文保存。
        if getattr(message, "additional_kwargs", {}).get(_TOOL_RESULT_SAVED_MARKER) is True:
            return None

        # 只处理能提取出纯文本的工具结果；空内容没有卸载价值。
        content = _message_content_text(message.content)
        if not content.strip():
            return None

        # 工具结果未超过阈值时保留在消息里，避免无意义的小文件。
        approx_tokens = int(token_counter([message]))
        if approx_tokens <= threshold:
            return None

        # 文件名使用工具名 + 内容 hash，便于去重且不暴露完整查询内容。
        tool_name = message.name or "unknown"
        file_path = _build_offload_file_path(message, content)
        header = "\n".join(
            [
                "=== Tool Invocation ===",
                f"Tool: {tool_name}",
                f"Tool Call ID: {message.tool_call_id or ''}",
                "=" * 40,
                "",
            ]
        )
        write_result = await backend.awrite(file_path, header + content)
        if write_result.error:
            # 卸载失败时保留原始 ToolMessage，避免因压缩辅助能力影响主流程。
            return None

        # 写入成功后，仅把预览和可读取路径留在消息历史里。
        preview, omitted_chars = _preview_content(content, preview_lines)
        additional_kwargs = dict(getattr(message, "additional_kwargs", {}) or {})
        additional_kwargs[_TOOL_RESULT_SAVED_MARKER] = True
        return message.model_copy(
            update={
                "content": _format_offload_placeholder(
                    file_path=file_path,
                    tool_name=tool_name,
                    approx_tokens=approx_tokens,
                    content_sample=preview,
                    omitted_chars=omitted_chars,
                ),
                "additional_kwargs": additional_kwargs,
            }
        )

    def _offload_tool_results(
        self,
        messages: list[AnyMessage],
        *,
        backend: AgentFilesystemBackend | None,
        preview_lines: int,
        threshold: int,
        token_counter: TokenCounter,
    ) -> tuple[list[AnyMessage], list[AnyMessage]]:
        # 阈值关闭或文件 backend 不可用时，跳过卸载，保留原消息列表。
        if threshold <= 0 or backend is None:
            return messages, []

        sanitized_messages: list[AnyMessage] = []
        modified_messages: list[AnyMessage] = []
        for message in messages:
            if not isinstance(message, ToolMessage):
                sanitized_messages.append(message)
                continue
            # 每个 ToolMessage 独立判断是否需要卸载；未卸载则沿用原消息。
            replacement = self._offload_tool_result(
                message,
                backend=backend,
                preview_lines=preview_lines,
                threshold=threshold,
                token_counter=token_counter,
            )
            sanitized_messages.append(replacement or message)
            if replacement is not None:
                modified_messages.append(replacement)
        return sanitized_messages, modified_messages

    async def _aoffload_tool_results(
        self,
        messages: list[AnyMessage],
        *,
        backend: AgentFilesystemBackend | None,
        preview_lines: int,
        threshold: int,
        token_counter: TokenCounter,
    ) -> tuple[list[AnyMessage], list[AnyMessage]]:
        # 阈值关闭或文件 backend 不可用时，跳过卸载，保留原消息列表。
        if threshold <= 0 or backend is None:
            return messages, []

        sanitized_messages: list[AnyMessage] = []
        modified_messages: list[AnyMessage] = []
        for message in messages:
            if not isinstance(message, ToolMessage):
                sanitized_messages.append(message)
                continue
            # 每个 ToolMessage 独立异步判断是否需要卸载；未卸载则沿用原消息。
            replacement = await self._aoffload_tool_result(
                message,
                backend=backend,
                preview_lines=preview_lines,
                threshold=threshold,
                token_counter=token_counter,
            )
            sanitized_messages.append(replacement or message)
            if replacement is not None:
                modified_messages.append(replacement)
        return sanitized_messages, modified_messages

    @staticmethod
    def _without_system_messages(messages: list[AnyMessage]) -> list[AnyMessage]:
        return [message for message in messages if not isinstance(message, SystemMessage)]

    def _determine_cutoff_index(
        self,
        messages: list[AnyMessage],
        messages_to_keep: int,
    ) -> int:
        return self._find_safe_cutoff(messages, max(1, messages_to_keep))

    def _find_cutoff_by_token_limit(
        #二分查找安全截断下标
        self,
        messages: list[AnyMessage],
        max_tokens: int,
        token_counter: TokenCounter,
    ) -> int:
        # 消息本身已经在预算内时，不需要裁剪。
        if not messages or token_counter(messages) <= max_tokens:
            return 0

        # 二分查找最早可丢弃的位置，使保留段 messages[mid:] 不超过 token 预算。
        left, right = 0, len(messages)
        cutoff_candidate = len(messages)
        for _ in range(len(messages).bit_length() + 1):
            if left >= right:
                break
            mid = (left + right) // 2
            if token_counter(messages[mid:]) <= max_tokens:
                cutoff_candidate = mid
                right = mid
            else:
                left = mid + 1

        if cutoff_candidate == len(messages):
            cutoff_candidate = left
        return self._find_safe_cutoff_point(messages, cutoff_candidate)

    def _find_safe_cutoff(self, messages: list[AnyMessage], messages_to_keep: int) -> int:
        if len(messages) <= messages_to_keep:
            return 0
        return self._find_safe_cutoff_point(messages, len(messages) - messages_to_keep)

    @staticmethod
    def _find_safe_cutoff_point(messages: list[AnyMessage], cutoff_index: int) -> int:
        """Avoid splitting an AI tool call from its following ToolMessage results."""
        if cutoff_index >= len(messages) or not isinstance(messages[cutoff_index], ToolMessage):
            return cutoff_index

        # 如果截断点落在 ToolMessage 上，向前找到对应的 AIMessage，避免工具调用对被拆散。
        tool_call_ids: set[str] = set()
        idx = cutoff_index
        while idx < len(messages) and isinstance(messages[idx], ToolMessage):
            tool_msg = cast(ToolMessage, messages[idx])
            if tool_msg.tool_call_id:
                tool_call_ids.add(tool_msg.tool_call_id)
            idx += 1

        for index in range(cutoff_index - 1, -1, -1):
            message = messages[index]
            if isinstance(message, AIMessage) and message.tool_calls:
                ai_tool_call_ids = {item.get("id") for item in message.tool_calls if item.get("id")}
                if tool_call_ids & ai_tool_call_ids:
                    return index
        return idx

    def _create_summary(
        self,
        messages_to_summarize: list[AnyMessage],
        *,
        context: AgentContext,
        model: BaseChatModel,
        token_counter: TokenCounter,
    ) -> str:
        # 没有可摘要的旧消息时，沿用已有滚动摘要，避免覆盖为空。
        if not messages_to_summarize:
            return context.summary or "No previous conversation history."

        # 摘要模型只读取被裁剪段中的一部分，避免摘要请求自身过长。
        trimmed_messages = self._trim_messages_for_summary(
            messages_to_summarize,
            context=context,
            token_counter=token_counter,
        )
        if not trimmed_messages:
            return context.summary or "Previous conversation was too long to summarize."

        formatted_messages = get_buffer_string(trimmed_messages)
        prompt_template = context.summary_prompt or DEFAULT_SUMMARY_PROMPT
        prompt = prompt_template.format(
            summary=context.summary or "None",
            messages=formatted_messages,
        )
        try:
            response = model.invoke([HumanMessage(content=prompt)])
        except Exception as error:
            # 摘要失败时不阻断主流程：优先保留旧摘要，否则写入错误文本便于排查。
            return context.summary or f"Error generating summary: {error!s}"
        return _message_content_text(getattr(response, "content", "")).strip()

    async def _acreate_summary(
        self,
        messages_to_summarize: list[AnyMessage],
        *,
        context: AgentContext,
        model: BaseChatModel,
        token_counter: TokenCounter,
    ) -> str:
        # 没有可摘要的旧消息时，沿用已有滚动摘要，避免覆盖为空。
        if not messages_to_summarize:
            return context.summary or "No previous conversation history."

        # 摘要模型只读取被裁剪段中的一部分，避免摘要请求自身过长。
        trimmed_messages = self._trim_messages_for_summary(
            messages_to_summarize,
            context=context,
            token_counter=token_counter,
        )
        if not trimmed_messages:
            return context.summary or "Previous conversation was too long to summarize."

        formatted_messages = get_buffer_string(trimmed_messages)
        prompt_template = context.summary_prompt or DEFAULT_SUMMARY_PROMPT
        prompt = prompt_template.format(
            summary=context.summary or "None",
            messages=formatted_messages,
        )
        try:
            response = await model.ainvoke([HumanMessage(content=prompt)])
        except Exception as error:
            # 摘要失败时不阻断主流程：优先保留旧摘要，否则写入错误文本便于排查。
            return context.summary or f"Error generating summary: {error!s}"
        return _message_content_text(getattr(response, "content", "")).strip()

    def _trim_messages_for_summary(
        self,
        messages: list[AnyMessage],
        *,
        context: AgentContext,
        token_counter: TokenCounter,
    ) -> list[AnyMessage]:
        try:
            if context.summary_trim_tokens_to_summarize is None:
                return messages
            return cast(
                list[AnyMessage],
                trim_messages(
                    messages,
                    max_tokens=context.summary_trim_tokens_to_summarize,
                    token_counter=token_counter,
                    start_on="human",
                    strategy="last",
                    allow_partial=True,
                    include_system=True,
                ),
            )
        except Exception:
            return messages[-_DEFAULT_FALLBACK_MESSAGE_COUNT:]

    @staticmethod
    def _build_new_messages(summary: str) -> list[HumanMessage]:
        return [
            HumanMessage(
                id=str(uuid.uuid4()),
                content=f"Here is a summary of the conversation to date:\n\n{summary}",
                additional_kwargs={"lc_source": "summarization"},
            )
        ]

    @staticmethod
    def _ensure_message_ids(messages: list[AnyMessage]) -> None:
        # LangGraph 的消息 reducer 依赖 id 做替换/删除；缺失时补一个稳定的本轮 id。
        for message in messages:
            if message.id is None:
                message.id = str(uuid.uuid4())

    @staticmethod
    def _partition_messages(
        conversation_messages: list[AnyMessage],
        cutoff_index: int,
    ) -> tuple[list[AnyMessage], list[AnyMessage]]:
        return conversation_messages[:cutoff_index], conversation_messages[cutoff_index:]
