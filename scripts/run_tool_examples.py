"""Regenerate the tool examples report from configs/tool_questions.yaml.

Run from the project root:

    uv run python scripts/run_tool_examples.py

The scenarios and the analysis are written by hand in the configuration,
while this script executes the orchestration flow for real. That keeps the
report tied to current behaviour: a change to validation, to routing or to
a result schema turns up here on the next run, instead of leaving a hand
written example quietly wrong.

The first run requires OPENAI_API_KEY, since the model is asked both to
pick a tool and to read each result. Those answers are stored in
index/router_decisions.json and index/answers_cache.json, alongside the NVD
responses already in index/cve_cache.json. With all three committed the
report rebuilds from a fresh clone with no network and no key, and only the
Generated line differs between runs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from genai_security_assistant.config import Settings, load_yaml
from genai_security_assistant.models.orchestration import AssistantAnswer, RouteDecision
from genai_security_assistant.models.tools import ToolRequest, ToolSpec
from genai_security_assistant.orchestration.llm_router import build_llm_router
from genai_security_assistant.orchestration.pipeline import ToolAugmentedAnswerer


def json_type(spec: dict[str, Any]) -> str:
    """Describe one schema field's type in a few words."""
    if "enum" in spec:
        return " / ".join(f"`{value}`" for value in spec["enum"])
    if "anyOf" in spec:
        return " or ".join(json_type(option) for option in spec["anyOf"])
    if spec.get("type") == "array":
        return f"array of {json_type(spec.get('items', {}))}"
    return spec.get("type", "any")


def field_table(model: type[BaseModel]) -> list[str]:
    """Render a model's fields as a table."""
    schema = model.model_json_schema()
    required = set(schema.get("required", []))
    rows = ["| field | type | required |", "|---|---|---|"]
    for name, spec in schema["properties"].items():
        mark = "yes" if name in required else "no"
        rows.append(f"| `{name}` | {json_type(spec)} | {mark} |")
    return rows


def render_spec(spec: ToolSpec) -> list[str]:
    """Render everything one tool declares about itself."""
    lines = [
        f"### `{spec.name}` — {spec.tool_type} tool",
        "",
        f"**Purpose.** {spec.purpose}",
        "",
        f"**Source.** {spec.source}",
        "",
        "**When to call it**",
        "",
    ]
    lines += [f"- {item}" for item in spec.when_to_use]
    lines += ["", "**When not to call it**", ""]
    lines += [f"- {item}" for item in spec.when_not_to_use]
    lines += ["", "**Input contract**", ""]
    lines += field_table(spec.input_model)
    lines += ["", "Schema as the model receives it:", "", "```json"]
    lines += [json.dumps(spec.json_schema(), indent=2)]
    lines += ["```", "", "**Output contract**", ""]
    lines += field_table(spec.output_model)
    lines += [""]
    return lines


def run_example(
    answerer: ToolAugmentedAnswerer, example: dict[str, Any]
) -> AssistantAnswer:
    """Execute one example, through the router or straight at the tool."""
    if "tool" not in example:
        return answerer.answer(
            example["question"], confirm=example.get("confirm", False)
        )

    # No router proposes a write, so this one is called by hand. The
    # request still goes through the registry, so validation and the
    # confirmation gate apply exactly as they would otherwise.
    request = ToolRequest(
        tool_name=example["tool"],
        arguments=example.get("arguments", {}),
        confirmed=example.get("confirm", False),
        proposed_by="cli",
    )
    observation = answerer.registry.run(request)

    return AssistantAnswer(
        question=example["question"],
        decision=RouteDecision(
            route="tool",
            reason="Called directly: no router proposes a write.",
            decided_by="cli",
            tool_request=request,
        ),
        answer_text=answerer.explain(example["question"], observation),
        observation=observation,
    )


def render_example(
    number: int, example: dict[str, Any], answer: AssistantAnswer
) -> list[str]:
    """Render one example in the shape the report asks for."""
    request = answer.decision.tool_request
    lines = [
        f"### {number}. {example['question']}",
        "",
        f"**User question:** {answer.question}",
        "",
        f"**Route:** `{answer.decision.route}` "
        f"({answer.decision.decided_by}) — {answer.decision.reason}",
        "",
    ]

    if request is None:
        lines += ["**Tool called:** none. The indexed documents answered.", ""]
    else:
        lines += [
            f"**Tool called:** `{request.tool_name}`",
            "",
            "**Input:**",
            "",
            "```json",
            json.dumps(request.arguments, indent=2, sort_keys=True),
            "```",
            "",
        ]

    if answer.observation is not None:
        observation = answer.observation
        if observation.success:
            body = json.dumps(observation.data, indent=2, sort_keys=True)
        else:
            body = json.dumps(
                {
                    "success": False,
                    "error_code": observation.error_code,
                    "error_message": observation.error_message,
                },
                indent=2,
            )
        lines += [
            "**Result:**",
            "",
            "```json",
            body,
            "```",
            "",
            f"Replayed from cache: `{observation.from_cache}`",
            "",
        ]

    if answer.grounded is not None:
        lines += ["**Result:** chunks retrieved from the indexed documents", ""]
        for chunk in answer.grounded.retrieved:
            lines.append(f"- `{chunk.chunk_id}` — score {chunk.score:.4f}")
        lines += ["", f"Grounded: {answer.grounded.is_grounded}", ""]

    lines += [
        "**Final answer:**",
        "",
        answer.answer_text,
        "",
        "**Why tool is better than retrieval:**",
        "",
        example["why"].strip(),
        "",
    ]
    return lines


def render_refusals(
    answerer: ToolAugmentedAnswerer, refusals: list[dict[str, Any]]
) -> list[str]:
    """Run each refused call and tabulate what came back."""
    lines = [
        "| what was proposed | arguments | code | message |",
        "|---|---|---|---|",
    ]
    for case in refusals:
        request = ToolRequest(
            tool_name=case["tool"],
            arguments=case.get("arguments", {}),
            confirmed=case.get("confirm", False),
            proposed_by="cli",
        )
        observation = answerer.registry.run(request)
        arguments = json.dumps(request.arguments, sort_keys=True)
        lines.append(
            f"| {case['description']} | `{arguments}` | "
            f"`{observation.error_code}` | {observation.error_message} |"
        )
    return lines


def proposal(decision: RouteDecision) -> str:
    """Name what a router proposed, in one cell."""
    if decision.tool_request is None:
        return "retrieval"
    return f"`{decision.tool_request.tool_name}`"


def render_router_comparison(
    answerer: ToolAugmentedAnswerer, settings: Settings, questions: list[str]
) -> list[str]:
    """Ask both routers the same questions and tabulate the two answers."""
    model_router = build_llm_router(settings, answerer.registry)

    lines = ["| question | rules propose | model proposes |", "|---|---|---|"]
    for question in questions:
        by_rules = answerer.router.route(question)
        by_model = model_router.route(question)
        # Pipes inside a question would end the cell early.
        cell = question.replace("|", "\\|")
        lines.append(f"| {cell} | {proposal(by_rules)} | {proposal(by_model)} |")
    return lines


def main() -> None:
    settings = Settings()
    config = load_yaml(settings.path("tool_questions"))
    examples = config["examples"]
    refusals = config.get("refusals", [])
    router_questions = config.get("router_questions") or [
        example["question"] for example in examples
    ]

    # The rule router, so the report is the deterministic pipeline. The
    # model-backed router appears further down, as a comparison.
    answerer = ToolAugmentedAnswerer.from_settings(settings)
    generation = settings.generation_config()

    lines = [
        "# External tool integration — examples",
        "",
        f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ}",
        f"Model: `{generation['model']}` · Router: `{answerer.router.name}`",
        "",
        "> This product uses the NVD API but is not endorsed or certified by",
        "> the NVD.",
        "",
        "Regenerate with `uv run python scripts/run_tool_examples.py`.",
        "The prose below is written by hand in `configs/tool_questions.yaml`",
        "and `configs/tool_conclusions.md`; every call, result and answer is",
        "produced by running the pipeline.",
        "",
        "## The tools",
        "",
    ]

    for spec in answerer.registry.specs():
        lines += render_spec(spec)

    lines += ["## Examples", ""]
    for number, example in enumerate(examples, start=1):
        lines += render_example(number, example, run_example(answerer, example))

    lines += [
        "## What the tool layer refuses",
        "",
        "Each row is a real call. None of them reached NVD or the log:",
        "validation runs before the source is touched.",
        "",
    ]
    lines += render_refusals(answerer, refusals)

    lines += [
        "",
        "## Which tool each router proposes",
        "",
        "The same questions, routed twice. Neither router executes anything",
        "here; only the proposal is shown.",
        "",
    ]
    lines += render_router_comparison(answerer, settings, router_questions)

    # The analysis is written by hand and folded in, so the report is one
    # file to read and configs/tool_conclusions.md stays the source.
    lines += ["", "## Notes", ""]
    lines += [settings.path("tool_conclusions").read_text(encoding="utf-8").strip()]
    lines += [""]

    destination = settings.path("tool_examples")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {destination}")


if __name__ == "__main__":
    main()
