"""Model-based tool selection for the orchestration layer.

The router shows the model the tool schemas the registry renders and asks
it to pick one, or none. Because those schemas and the runtime validation
come from the same ToolSpec, a proposal is checked against the contract it
was offered.

The module follows the client arrangement of generation/llm.py: a Protocol
states what the router needs, one client implements it, and a factory
builds that client from configs/base.yaml.

The model proposes a call and never executes one. Every proposal goes
through the same validation and dispatch as a proposal from router.py, and
a state-changing call still waits for explicit human confirmation.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from openai import OpenAI
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionFunctionToolParam,
    ChatCompletionMessageFunctionToolCall,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from openai.types.shared_params import FunctionDefinition

from genai_security_assistant.config import Settings, require_env
from genai_security_assistant.models.orchestration import RouteDecision, ToolChoice
from genai_security_assistant.models.tools import ToolRequest
from genai_security_assistant.orchestration.router_cache import CachedToolChooser
from genai_security_assistant.tools.registry import ToolRegistry

ROUTER_SYSTEM = """You route questions and requests for a GenAI \
application security assistant.

The assistant answers from an indexed set of OWASP documents about LLM and
AI agent security. Those documents are static, they describe classes of
risk rather than named vulnerabilities, and nothing in them changes after
they were indexed.

Call a read tool only when the documents cannot answer for one of those
reasons.

Not every input is a question. Asking for something to be recorded, logged
or filed is a request to act, and the documents cannot satisfy it at all:
route it to the tool that performs the action, not to one that looks
something up.

Do not answer or perform anything yourself. Either call one tool, or call
none."""

def as_tool_params(
    tools: list[dict[str, Any]],
) -> list[ChatCompletionFunctionToolParam]:
    """Convert the registry's plain dictionaries into SDK parameters.
    ToolRegistry renders dictionaries so that it does not depend on this
    SDK. This is the one place that boundary is crossed, and it names each
    field rather than casting, so a schema missing one fails here instead
    of inside the API call.
    """
    return [
        ChatCompletionFunctionToolParam(
            type="function",
            function=FunctionDefinition(
                name=tool["function"]["name"],
                description=tool["function"]["description"],
                parameters=tool["function"]["parameters"],
            ),
        )
        for tool in tools
    ]


class ToolChooser(Protocol):
    """What the router needs from a model."""

    model: str

    def choose(
        self, system: str, question: str, tools: list[dict[str, Any]]
    ) -> ToolChoice:
        """Return the call the model proposed, if it proposed one."""
        ...


class OpenAIToolChooser:
    """Tool selection through the OpenAI chat completions API."""

    name = "openai_chooser"

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key_env: str,
        temperature: float = 0,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self._client = OpenAI(api_key=require_env(api_key_env), base_url=base_url)

    def choose(
        self, system: str, question: str, tools: list[dict[str, Any]]
    ) -> ToolChoice:
        """Ask the model to pick a tool, or none."""
        response: ChatCompletion = self._client.chat.completions.create(
            model=self.model,
            messages=[
                ChatCompletionSystemMessageParam(role="system", content=system),
                ChatCompletionUserMessageParam(role="user", content=question),
            ],
            tools=as_tool_params(tools),
            # "auto" leaves room to choose nothing, which is the right
            # answer for most questions this assistant is asked.
            tool_choice="auto",
            temperature=self.temperature,
        )

        message = response.choices[0].message
        if not message.tool_calls:
            return ToolChoice()

        # One call, not several. A question needing two tools is a workflow,
        # and this router routes.
        call = message.tool_calls[0]

        # tool_calls is a union: a custom tool call carries no function to
        # read. This router offers function tools only, so anything else is
        # not a proposal it can act on.
        if not isinstance(call, ChatCompletionMessageFunctionToolCall):
            return ToolChoice()

        # The SDK documents this field as not always valid JSON, and as
        # able to name parameters no schema declared. Both are handled:
        # unreadable here, unknown fields by the tool's input model.
        written = call.function.arguments
        try:
            arguments = json.loads(written)
        except json.JSONDecodeError:
            return ToolChoice(
                tool_name=call.function.name,
                raw_arguments=written,
                unreadable=True,
            )

        return ToolChoice(
            tool_name=call.function.name,
            arguments=arguments,
            raw_arguments=written,
        )


class LlmRouter:
    """Route by asking the model which tool, if any, the question needs."""

    name = "llm_router"

    def __init__(self, chooser: ToolChooser, registry: ToolRegistry) -> None:
        self.chooser = chooser
        self.registry = registry

    def route(self, question: str) -> RouteDecision:
        """Decide where one question goes."""
        choice = self.chooser.choose(
            ROUTER_SYSTEM, question, self.registry.openai_tools()
        )

        if choice.tool_name is None:
            return RouteDecision(
                route="retrieval",
                reason="The model proposed no tool call.",
                decided_by=self.name,
            )

        if choice.unreadable:
            # Falling back rather than guessing. The reason is kept so the
            # report shows that this happened instead of hiding it.
            return RouteDecision(
                route="retrieval",
                reason=(
                    f"The model proposed {choice.tool_name} with arguments "
                    "that are not valid JSON."
                ),
                decided_by=self.name,
            )

        # A name the registry does not know is left alone here. Dispatch
        # already reports an unknown tool, and a second check would hide
        # from the report that a model invented one.
        return RouteDecision(
            route="tool",
            reason=f"The model proposed {choice.tool_name}.",
            decided_by=self.name,
            tool_request=ToolRequest(
                tool_name=choice.tool_name,
                arguments=choice.arguments,
                proposed_by=self.name,
            ),
        )


def build_llm_router(
    settings: Settings, registry: ToolRegistry, live: bool = False
) -> LlmRouter:
    """Build the model-backed router from configs/base.yaml."""
    config = settings.generation_config()
    use_cache = settings.generation.get("use_cached_answers", True)

    return LlmRouter(
        chooser=CachedToolChooser(
            path=settings.path("router_decisions"),
            model=config["model"],
            build_chooser=lambda: OpenAIToolChooser(
                model=config["model"],
                base_url=config["base_url"],
                api_key_env=config["api_key_env"],
                temperature=config.get("temperature", 0),
            ),
            read_cache=use_cache and not live,
        ),
        registry=registry,
    )
