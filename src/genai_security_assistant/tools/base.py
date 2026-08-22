"""What every tool in this package looks like from the outside.
Validation lives here rather than in each tool. A tool can't forget to
check its arguments, and a write tool can't forget to check confirmation,
because neither gets to run before this class has done both.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ValidationError

from genai_security_assistant.models.tools import (
    ToolObservation,
    ToolRequest,
    ToolSpec,
)


class Tool(Protocol):
    """What the registry and the orchestration layer need from a tool."""

    spec: ToolSpec

    def run(self, request: ToolRequest) -> ToolObservation:
        """Validate the request and execute it. Never raises."""
        ...


def _first_error(error: ValidationError) -> str:
    """Turn a pydantic failure into one sentence a model can act on."""
    first = error.errors()[0]
    field = ".".join(str(part) for part in first["loc"]) or "arguments"
    return f"{field}: {first['msg']}"


class BaseTool:
    """Validation, then execution. Subclasses implement execute() only."""

    spec: ToolSpec

    def run(self, request: ToolRequest) -> ToolObservation:
        """Validate the request and execute it."""
        # Checked before the arguments, so write proposed without
        # confirmation is refused.
        if self.spec.tool_type == "write" and not request.confirmed:
            return ToolObservation.fail(
                self.spec.name,
                "not_confirmed",
                f"{self.spec.name} changes state and needs confirmation.",
            )

        try:
            arguments = self.spec.input_model.model_validate(request.arguments)
        except ValidationError as error:
            return ToolObservation.fail(
                self.spec.name, "validation_error", _first_error(error)
            )

        return self.execute(arguments, request)

    def execute(self, arguments: BaseModel, request: ToolRequest) -> ToolObservation:
        """Run the validated call. Implemented by each tool."""
        raise NotImplementedError
