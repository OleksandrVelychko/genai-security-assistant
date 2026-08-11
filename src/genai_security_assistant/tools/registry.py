"""Registry of all tools available to the orchestration layer.

The registry maps tool names to executable implementations and renders the
schemas the model is shown.

Both the schema and the runtime argument validation are derived from the
same ToolSpec, which is what keeps a model-facing definition aligned with
what the application will actually execute. Nothing here can drift from the
tool it describes, because nothing here is written twice.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from genai_security_assistant.config import Settings
from genai_security_assistant.models.tools import (
    ToolObservation,
    ToolRequest,
    ToolSpec,
)
from genai_security_assistant.tools.base import Tool
from genai_security_assistant.tools.cve_lookup import build_cve_lookup_tool
from genai_security_assistant.tools.findings import build_record_finding_tool


def describe(spec: ToolSpec) -> str:
    """Render the text a model reads when deciding whether to call a tool.
    when_not_to_use earns its place here: without it a model reaches for
    the tool on questions the indexed documents already answer.
    """
    lines = [spec.purpose, "", "Use when:"]
    lines += [f"- {item}" for item in spec.when_to_use]
    lines += ["", "Do not use when:"]
    lines += [f"- {item}" for item in spec.when_not_to_use]
    return "\n".join(lines)


class ToolRegistry:
    """Tools by name, with dispatch and schema rendering."""

    def __init__(self, tools: Iterable[Tool]) -> None:
        self._tools = {tool.spec.name: tool for tool in tools}

    @property
    def names(self) -> list[str]:
        """Tool names, sorted, so schemas render in a stable order."""
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        """The declaration of every registered tool."""
        return [self._tools[name].spec for name in self.names]

    def run(self, request: ToolRequest) -> ToolObservation:
        """Dispatch a request to the tool it names.

        An unknown name is a failed observation rather than an exception:
        a model inventing a tool is something the report has to show.
        """
        tool = self._tools.get(request.tool_name)
        if tool is None:
            return ToolObservation.fail(
                request.tool_name,
                "unknown_tool",
                f"No tool named {request.tool_name!r}. "
                f"Available: {', '.join(self.names)}.",
            )
        return tool.run(request)

    def openai_tools(self) -> list[dict[str, Any]]:
        """The tools parameter for an OpenAI chat completion.

        The schema comes from the tool's input model, so a field the model
        is not offered is a field the tool would reject anyway. Confirmation
        is absent from every schema by construction: it lives on the
        request envelope, not in any tool's arguments.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": describe(spec),
                    "parameters": spec.json_schema(),
                },
            }
            for spec in self.specs()
        ]


def build_registry(
    settings: Settings | None = None, live: bool = False
) -> ToolRegistry:
    """Build every tool from configs/base.yaml."""
    resolved = settings or Settings()
    return ToolRegistry(
        [
            build_cve_lookup_tool(resolved, live=live),
            build_record_finding_tool(resolved),
        ]
    )
