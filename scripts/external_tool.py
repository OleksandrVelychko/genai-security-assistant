"""Call one tool, or ask a question and let the router decide.

Run from the project root:

    uv run python scripts/external_tool.py --schemas
    uv run python scripts/external_tool.py -t lookup_cve -a cve_id=CVE-2023-29374
    uv run python scripts/external_tool.py -q "What is the status of CVE-2025-68664?"
    uv run python scripts/external_tool.py -q "..." --llm-router
    uv run python scripts/external_tool.py -t record_security_finding \\
        -a title="..." -a severity=high -a summary="..." --confirm

Three modes
-----------
--schemas prints the contracts, exactly as a model would be shown them.

-t calls one tool directly and stops at the observation. No model is
involved, so this mode needs no OPENAI_API_KEY: it shows the integration
layer on its own, request through validation to normalized result.

-q sends a question through the orchestration layer, which routes it to a
tool or to the indexed documents and then produces an answer.

Caches and keys
---------------
NVD responses live in index/cve_cache.json and model output in
index/answers_cache.json and index/router_decisions.json. A question
already in those files runs with no network and no key. --live ignores
them and calls out for real, then overwrites the entry.

Confirmation
------------
A write tool refuses unless --confirm is given. The flag is the human in
the loop: neither the router nor the model can supply it.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from genai_security_assistant.config import Settings
from genai_security_assistant.models.orchestration import AssistantAnswer
from genai_security_assistant.models.tools import ToolObservation, ToolRequest
from genai_security_assistant.orchestration.pipeline import ToolAugmentedAnswerer
from genai_security_assistant.tools.registry import ToolRegistry, build_registry

LINE = "=" * 78


def parse_arguments(pairs: list[str]) -> dict[str, Any]:
    """Turn --arg field=value options into one arguments mapping.
    Everything arrives as a string. Pydantic coerces what it can and
    refuses the rest, which is the same treatment a model's arguments get.
    """
    arguments: dict[str, Any] = {}
    for pair in pairs:
        field, separator, value = pair.partition("=")
        if not separator or not field:
            raise SystemExit(
                f"--arg expects field=value, got {pair!r}. "
                "For example: --arg cve_id=CVE-2023-29374"
            )
        arguments[field] = value
    return arguments


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Call an external tool, or route a question to one."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--query", "-q", help="Question to route and answer.")
    mode.add_argument("--tool", "-t", help="Tool to call directly.")
    mode.add_argument(
        "--schemas",
        action="store_true",
        help="Print the tool contracts and stop.",
    )
    parser.add_argument(
        "--arg",
        "-a",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help="Argument for --tool. May be repeated.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Approve a write. Required by any tool that changes state.",
    )
    parser.add_argument(
        "--llm-router",
        action="store_true",
        help="Let the model choose the tool instead of the rules.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Ignore the caches and call out for real.",
    )
    return parser.parse_args()


def print_schemas(registry: ToolRegistry) -> None:
    """Print what each tool declares, then the schemas a model is shown."""
    for spec in registry.specs():
        print(LINE)
        print(f"{spec.name}  ({spec.tool_type} tool)")
        print(LINE)
        print(f"Purpose: {spec.purpose}")
        print(f"Source:  {spec.source}")
        print("Use when:")
        for item in spec.when_to_use:
            print(f"  - {item}")
        print("Do not use when:")
        for item in spec.when_not_to_use:
            print(f"  - {item}")
        print()

    print(LINE)
    print("Schemas as the model receives them")
    print(LINE)
    print(json.dumps(registry.openai_tools(), indent=2))


def print_request(request: ToolRequest, registry: ToolRegistry) -> None:
    """Print the proposal, before anything has validated it."""
    spec = next(
        (item for item in registry.specs() if item.name == request.tool_name), None
    )
    print(LINE)
    print("Tool request")
    print(LINE)
    print(f"tool:        {request.tool_name}")
    print(f"type:        {spec.tool_type if spec else 'unknown tool'}")
    print(f"proposed by: {request.proposed_by}")
    print(f"confirmed:   {request.confirmed}")
    print(f"arguments:   {json.dumps(request.arguments, sort_keys=True)}")


def print_observation(observation: ToolObservation) -> None:
    """Print what came back, successful or not."""
    print()
    print(LINE)
    print("Observation")
    print(LINE)
    print(f"success:  {observation.success}")
    if observation.success:
        print(f"cached:   {observation.from_cache}")
        print(json.dumps(observation.data, indent=2, sort_keys=True))
    else:
        print(f"code:     {observation.error_code}")
        print(f"message:  {observation.error_message}")


def print_answer(answer: AssistantAnswer) -> None:
    """Print the route taken, the evidence behind it, and the answer."""
    print(LINE)
    print(f"Question: {answer.question}")
    print(LINE)
    print(f"Route:    {answer.decision.route}")
    print(f"Decided:  {answer.decision.decided_by}")
    print(f"Because:  {answer.decision.reason}")

    if answer.decision.tool_request is not None:
        print(
            f"Proposed: {answer.decision.tool_request.tool_name} "
            f"{json.dumps(answer.decision.tool_request.arguments, sort_keys=True)}"
        )

    if answer.observation is not None:
        print_observation(answer.observation)

    if answer.grounded is not None:
        print()
        print("Retrieved chunks:")
        for chunk in answer.grounded.retrieved:
            print(f"  Top-{chunk.rank}: {chunk.chunk_id} | score {chunk.score:.4f}")
        print(f"Status:   {answer.grounded.status}")
        print(f"Grounded: {answer.grounded.is_grounded}")

    print()
    print(LINE)
    print("Answer")
    print(LINE)
    print(answer.answer_text)


def main() -> None:
    args = parse_args()
    settings = Settings()

    if args.schemas:
        print_schemas(build_registry(settings, live=args.live))
        return

    if args.tool:
        # No model is built on this path. The tool layer answers for
        # itself, which is what makes it testable without a key.
        registry = build_registry(settings, live=args.live)
        request = ToolRequest(
            tool_name=args.tool,
            arguments=parse_arguments(args.arg),
            confirmed=args.confirm,
            proposed_by="cli",
        )
        print_request(request, registry)
        print_observation(registry.run(request))
        return

    answerer = ToolAugmentedAnswerer.from_settings(
        settings, live=args.live, use_llm_router=args.llm_router
    )
    print_answer(answerer.answer(args.query, confirm=args.confirm))


if __name__ == "__main__":
    main()
