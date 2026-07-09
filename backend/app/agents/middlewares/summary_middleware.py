from __future__ import annotations

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

from app.agents.buildin.chatbot.context import AgentContext
from app.llm import get_model, get_model_by_spec

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

_DEFAULT_FALLBACK_MESSAGE_COUNT = 15


def _get_approximate_token_counter(model: BaseChatModel) -> TokenCounter:
    if model._llm_type == "anthropic-chat":  # noqa: SLF001
        return partial(count_tokens_approximately, chars_per_token=3.3)
    return count_tokens_approximately


def _message_content_text(content: Any) -> str:
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


class SummaryMiddleware(AgentMiddleware):
    """Summarize long conversation history; tool output offload is handled elsewhere."""

    def before_model(self, state: AgentState[Any], runtime: Runtime) -> dict[str, Any] | None:
        return self._process_before_model(state, runtime)

    async def abefore_model(self, state: AgentState[Any], runtime: Runtime) -> dict[str, Any] | None:
        return await self._aprocess_before_model(state, runtime)

    def _process_before_model(
        self,
        state: AgentState[Any],
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        context = getattr(runtime, "context", None)
        if not isinstance(context, AgentContext):
            return None

        messages = list(state.get("messages") or [])
        if not messages:
            return None

        self._ensure_message_ids(messages)
        model = get_model_by_spec(context.model_spec) if context.model_spec else get_model(context.model_use)
        token_counter = _get_approximate_token_counter(model)
        total_tokens = token_counter(messages)
        if not self._should_summarize(context, messages, total_tokens):
            return None

        cutoff_index = self._determine_cutoff_index_for_summary(
            context=context,
            messages=messages,
            total_tokens=total_tokens,
            token_counter=token_counter,
        )
        if cutoff_index <= 0:
            return None

        system_messages = [message for message in messages if isinstance(message, SystemMessage)]
        conversation_messages = self._without_system_messages(messages)
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
        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *system_messages,
                *self._build_new_messages(summary),
                *preserved_messages,
            ]
        }

    async def _aprocess_before_model(
        self,
        state: AgentState[Any],
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        context = getattr(runtime, "context", None)
        if not isinstance(context, AgentContext):
            return None

        messages = list(state.get("messages") or [])
        if not messages:
            return None

        self._ensure_message_ids(messages)
        model = get_model_by_spec(context.model_spec) if context.model_spec else get_model(context.model_use)
        token_counter = _get_approximate_token_counter(model)
        total_tokens = token_counter(messages)
        if not self._should_summarize(context, messages, total_tokens):
            return None

        cutoff_index = self._determine_cutoff_index_for_summary(
            context=context,
            messages=messages,
            total_tokens=total_tokens,
            token_counter=token_counter,
        )
        if cutoff_index <= 0:
            return None

        system_messages = [message for message in messages if isinstance(message, SystemMessage)]
        conversation_messages = self._without_system_messages(messages)
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
        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *system_messages,
                *self._build_new_messages(summary),
                *preserved_messages,
            ]
        }

    def _determine_cutoff_index_for_summary(
        self,
        *,
        context: AgentContext,
        messages: list[AnyMessage],
        total_tokens: int,
        token_counter: TokenCounter,
    ) -> int:
        conversation_messages = self._without_system_messages(messages)
        trigger_value = self._token_trigger_value(context)
        if trigger_value is None:
            return self._determine_cutoff_index(
                conversation_messages,
                context.summary_keep_messages,
            )

        retention_limit = int(trigger_value * context.summary_max_retention_ratio)
        if total_tokens <= retention_limit:
            return 0
        return self._find_cutoff_by_token_limit(
            conversation_messages,
            max(1, retention_limit),
            token_counter,
        )

    def _should_summarize(
        self,
        context: AgentContext,
        messages: list[AnyMessage],
        total_tokens: int,
    ) -> bool:
        trigger_tokens = self._token_trigger_value(context)
        if trigger_tokens is not None and total_tokens >= trigger_tokens:
            return True
        return context.summary_trigger_messages > 0 and len(messages) >= context.summary_trigger_messages

    @staticmethod
    def _token_trigger_value(context: AgentContext) -> int | None:
        return context.summary_trigger_tokens if context.summary_trigger_tokens > 0 else None

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
        self,
        messages: list[AnyMessage],
        max_tokens: int,
        token_counter: TokenCounter,
    ) -> int:
        if not messages or token_counter(messages) <= max_tokens:
            return 0

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
        if not messages_to_summarize:
            return context.summary or "No previous conversation history."

        trimmed_messages = self._trim_messages_for_summary(
            messages_to_summarize,
            context=context,
            token_counter=token_counter,
        )
        if not trimmed_messages:
            return context.summary or "Previous conversation was too long to summarize."

        prompt_template = context.summary_prompt or DEFAULT_SUMMARY_PROMPT
        prompt = prompt_template.format(
            summary=context.summary or "None",
            messages=get_buffer_string(trimmed_messages),
        )
        try:
            response = model.invoke([HumanMessage(content=prompt)])
        except Exception as error:
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
        if not messages_to_summarize:
            return context.summary or "No previous conversation history."

        trimmed_messages = self._trim_messages_for_summary(
            messages_to_summarize,
            context=context,
            token_counter=token_counter,
        )
        if not trimmed_messages:
            return context.summary or "Previous conversation was too long to summarize."

        prompt_template = context.summary_prompt or DEFAULT_SUMMARY_PROMPT
        prompt = prompt_template.format(
            summary=context.summary or "None",
            messages=get_buffer_string(trimmed_messages),
        )
        try:
            response = await model.ainvoke([HumanMessage(content=prompt)])
        except Exception as error:
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
        for message in messages:
            if message.id is None:
                message.id = str(uuid.uuid4())

    @staticmethod
    def _partition_messages(
        conversation_messages: list[AnyMessage],
        cutoff_index: int,
    ) -> tuple[list[AnyMessage], list[AnyMessage]]:
        return conversation_messages[:cutoff_index], conversation_messages[cutoff_index:]
