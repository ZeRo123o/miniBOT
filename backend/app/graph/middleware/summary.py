from collections.abc import Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.agent.context import AgentContext
from app.llm import get_model


class SummaryMiddleware(AgentMiddleware):
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """在模型调用前按 token 预算压缩过长历史，只保留摘要和最近若干条消息。"""
        context = request.runtime.context
        if not isinstance(context, AgentContext):
            return await handler(request)

        messages = list(request.messages)
        estimated_tokens = self._estimate_messages_tokens(messages)
        trigger_tokens = self._summary_trigger_tokens(context)
        if estimated_tokens < trigger_tokens:
            return await handler(request)

        keep_count = max(1, context.summary_keep_messages)
        old_messages = messages[:-keep_count]
        recent_messages = messages[-keep_count:]
        if not old_messages:
            return await handler(request)

        summary = await self._summarize_messages(old_messages, context)
        context.summary = summary

        compressed_messages: list[BaseMessage] = [
            SystemMessage(content=f"以下是较早对话的压缩摘要，用于延续上下文：\n{summary}"),
            *recent_messages,
        ]
        return await handler(request.override(messages=compressed_messages))

    def _summary_trigger_tokens(self, context: AgentContext) -> int:
        """计算上下文压缩触发 token 阈值，默认约为 128K 窗口的 70%。"""
        if context.summary_trigger_tokens > 0:
            return context.summary_trigger_tokens
        return int(context.summary_context_window_tokens * context.summary_trigger_ratio)

    def _estimate_messages_tokens(self, messages: list[BaseMessage]) -> int:
        """轻量估算消息 token 数；中文按字符估算，英文按约 4 字符 1 token 估算。"""
        return sum(self._estimate_text_tokens(str(message.content)) + 4 for message in messages)

    def _estimate_text_tokens(self, text: str) -> int:
        """估算单段文本 token 数，不引入 tokenizer 依赖。"""
        cjk_chars = 0
        non_cjk_chars = 0
        for char in text:
            if "\u4e00" <= char <= "\u9fff":
                cjk_chars += 1
            elif not char.isspace():
                non_cjk_chars += 1
        return cjk_chars + max(1, non_cjk_chars // 4)

    async def _summarize_messages(self, messages: list[BaseMessage], context: AgentContext) -> str:
        """调用当前模型把旧消息压缩成简洁摘要。"""
        text = self._format_messages(messages)
        if context.summary_max_chars > 0:
            text = text[-context.summary_max_chars :]

        prompt = (
            "请把以下历史对话压缩成一段简洁摘要，用于后续继续对话。\n"
            "必须保留：用户目标、已确认事实、关键约束、未完成事项、重要代码或配置决策。\n"
            "不要保留寒暄、重复内容和无关细节。\n\n"
            f"{text}"
        )
        model = get_model(context.model_use)
        response = await model.ainvoke([HumanMessage(content=prompt)])
        return str(response.content).strip()

    def _format_messages(self, messages: list[BaseMessage]) -> str:
        """把 LangChain 消息列表整理成可供摘要模型阅读的纯文本。"""
        lines = []
        for message in messages:
            role = self._message_role(message)
            content = str(message.content).strip()
            if content:
                lines.append(f"{role}: {content}")
        return "\n\n".join(lines)

    def _message_role(self, message: BaseMessage) -> str:
        """把消息类型转换为摘要文本中的角色名称。"""
        if isinstance(message, HumanMessage):
            return "user"
        if isinstance(message, AIMessage):
            return "assistant"
        if isinstance(message, SystemMessage):
            return "system"
        return getattr(message, "type", "message")
