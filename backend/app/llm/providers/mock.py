from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


class MockChatModel:
    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        last_user = next((message.content for message in reversed(messages) if isinstance(message, HumanMessage)), "")
        return AIMessage(content=f"收到：{last_user}\n\n当前使用 mock 模型。配置真实 provider 后会调用大模型。")
