"""NVIDIA NIM provider implementation."""

# 1. Standard library imports
from typing import AsyncIterator

# 2. Third-party imports
from openai import AsyncOpenAI

# 3. Local / internal imports
from nemo.ai.providers.base import AIProvider
from nemo.ai.schemas import ChatMessage, LLMResponse
from nemo.config.settings import get_settings

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
class NvidiaNimProvider(AIProvider):
    """NVIDIA NIM inference provider using OpenAI-compatible interface."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.nvidia_api_key
        self.base_url = base_url or settings.nvidia_base_url
        self.model = model or settings.nvidia_model

        if not self.api_key:
            raise ValueError("NVIDIA API key not configured. Check .env or settings.")

        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )

    async def generate(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        enable_thinking: bool = True,
    ) -> LLMResponse:
        """Call NVIDIA NIM chat completion endpoint."""
        formatted_msgs = [{"role": m.role, "content": m.content} for m in messages]
        extra_body = {}
        if enable_thinking:
            extra_body["chat_template_kwargs"] = {"enable_thinking": True}

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=formatted_msgs,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body if extra_body else None,
        )

        choice = response.choices[0]
        content = choice.message.content or ""
        usage_dict = {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            "total_tokens": response.usage.total_tokens if response.usage else 0,
        }

        return LLMResponse(
            content=content,
            model=response.model or self.model,
            usage=usage_dict,
            finish_reason=choice.finish_reason,
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream chunks from NVIDIA NIM."""
        formatted_msgs = [{"role": m.role, "content": m.content} for m in messages]
        stream_resp = await self.client.chat.completions.create(
            model=self.model,
            messages=formatted_msgs,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        async for chunk in stream_resp:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

# 6. Public exports
__all__ = ["NvidiaNimProvider"]
