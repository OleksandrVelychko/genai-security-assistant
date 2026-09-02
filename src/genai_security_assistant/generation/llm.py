"""Chat models behind one interface.
Built the same way as retrieval/embeddings.py: a Protocol for what the
pipeline needs, one real client, and a factory that reads the config.
The Protocol lets tests pass in a fake client, so they never need an
API key.
"""

from __future__ import annotations

from typing import Any, Protocol

from openai import OpenAI
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

from genai_security_assistant.config import require_env


class ChatClient(Protocol):
    """What the answering pipeline needs from a chat model."""

    name: str
    model: str

    def complete(self, system: str, user: str) -> str:
        """Send one system and one user message. Return the text."""
        ...


class OpenAIChatClient:
    """OpenAI chat completions.
    Works with any OpenAI-compatible endpoint, such as OpenRouter.
    Only base_url and the key change.
    """

    name = "openai"

    def __init__(
            self,
            model: str,
            base_url: str,
            api_key_env: str,
            temperature: float = 0,
            max_output_tokens: int = 600,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self._client = OpenAI(api_key=require_env(api_key_env), base_url=base_url)

    def complete(self, system: str, user: str) -> str:
        """One call, one answer.
        Prompt v1 has no system message. An empty system turn is dropped
        rather than sent, because some endpoints reject it.
        """
        # Built with the message classes instead of plain dicts. A dict
        # literal is legal here and mypy accepts it, but the parameter
        # type is a union of six TypedDicts and PyCharm reads a literal
        # as dict[str, str]. The constructors say which member is meant.
        messages: list[ChatCompletionMessageParam] = []
        if system.strip():
            messages.append(
                ChatCompletionSystemMessageParam(role="system", content=system)
            )
        messages.append(ChatCompletionUserMessageParam(role="user", content=user))

        # create() has four overloads and the return type depends on
        # "stream". Without it the call returns ChatCompletion, but IDEs
        # often report the streaming union instead, and Stream has no
        # .choices. Saying the type here settles it.
        response: ChatCompletion = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            # max_tokens is deprecated in the SDK in favour of this.
            max_completion_tokens=self.max_output_tokens,
        )
        return (response.choices[0].message.content or "").strip()


def build_chat_client(config: dict[str, Any]) -> ChatClient:
    """Build the chat client named in configs/base.yaml.
    Takes the flat dict from Settings.generation_config(). This is the
    only place that checks a provider name.
    """
    provider = config["provider"]

    if provider == "openai":
        return OpenAIChatClient(
            model=config["model"],
            base_url=config["base_url"],
            api_key_env=config["api_key_env"],
            temperature=config.get("temperature", 0),
            max_output_tokens=config.get("max_output_tokens", 600),
        )

    raise ValueError(f"Unknown generation provider: {provider!r}. Expected 'openai'.")
