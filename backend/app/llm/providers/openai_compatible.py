from typing import Any

import httpx
from langchain_core.messages import AIMessage, BaseMessage


class OpenAICompatibleChatModel:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.2,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        if not self.api_key:
            raise ValueError("MINIBOT_OPENAI_API_KEY is required for OpenAI-compatible provider.")

        payload = {
            "model": self.model,
            "messages": [self._convert_message(message) for message in messages],
            "temperature": self.temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"].get("content") or ""
        return AIMessage(content=content, response_metadata={"model": self.model, "raw": data})

    def _convert_message(self, message: BaseMessage) -> dict[str, Any]:
        role = getattr(message, "type", "human")
        if role == "human":
            role = "user"
        elif role == "ai":
            role = "assistant"
        return {"role": role, "content": message.content}
