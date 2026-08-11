"""Unit tests for the routing decision cache."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from genai_security_assistant.models.orchestration import ToolChoice
from genai_security_assistant.orchestration.router_cache import CachedToolChooser

MODEL = "test-model"
SYSTEM = "route this"
TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {"name": "lookup_cve"}}
]


class RecordingChooser:
    """Stands in for the model and remembers what it was asked."""

    model = MODEL

    def __init__(self) -> None:
        self.calls: list[str] = []

    def choose(
        self, system: str, question: str, tools: list[dict[str, Any]]
    ) -> ToolChoice:
        self.calls.append(question)
        return ToolChoice(tool_name="lookup_cve", arguments={"cve_id": question})


def exploding_factory():
    """A chooser factory for tests where nothing may reach the model."""
    raise AssertionError("the model was built, but nothing was missing")


def cache(path: Path, factory: Any, read_cache: bool = True) -> CachedToolChooser:
    return CachedToolChooser(path, MODEL, factory, read_cache=read_cache)


def test_nothing_is_built_when_the_file_is_absent(tmp_path: Path):
    """Building the real chooser needs an API key, so construction must not."""
    cache(tmp_path / "decisions.json", exploding_factory)


def test_the_first_call_asks_the_model_and_writes_the_file(tmp_path: Path):
    path = tmp_path / "decisions.json"
    chooser = RecordingChooser()

    choice = cache(path, lambda: chooser).choose(SYSTEM, "CVE-2025-68664", TOOLS)

    assert choice.tool_name == "lookup_cve"
    assert chooser.calls == ["CVE-2025-68664"]
    assert path.exists()


def test_a_later_run_reads_from_disk_with_no_model(tmp_path: Path):
    """The claim the reports rest on: regenerating them needs no API key."""
    path = tmp_path / "decisions.json"
    first = cache(path, lambda: RecordingChooser())
    expected = first.choose(SYSTEM, "CVE-2025-68664", TOOLS)

    second = cache(path, exploding_factory)
    replayed = second.choose(SYSTEM, "CVE-2025-68664", TOOLS)

    assert replayed == expected
    assert second.last_was_cached is True


def test_a_different_question_is_a_different_entry(tmp_path: Path):
    chooser = RecordingChooser()
    stored = cache(tmp_path / "decisions.json", lambda: chooser)

    stored.choose(SYSTEM, "CVE-2025-68664", TOOLS)
    stored.choose(SYSTEM, "CVE-2026-34070", TOOLS)

    assert chooser.calls == ["CVE-2025-68664", "CVE-2026-34070"]


def test_changed_schemas_are_not_answered_from_the_old_decision(tmp_path: Path):
    """A tool that now declares something else is a different question."""
    path = tmp_path / "decisions.json"
    chooser = RecordingChooser()
    stored = cache(path, lambda: chooser)

    stored.choose(SYSTEM, "CVE-2025-68664", TOOLS)
    stored.choose(
        SYSTEM,
        "CVE-2025-68664",
        [{"type": "function", "function": {"name": "lookup_cve", "strict": True}}],
    )

    assert len(chooser.calls) == 2


def test_a_changed_system_message_is_not_answered_from_the_old_decision(
    tmp_path: Path,
):
    chooser = RecordingChooser()
    stored = cache(tmp_path / "decisions.json", lambda: chooser)

    stored.choose(SYSTEM, "CVE-2025-68664", TOOLS)
    stored.choose("route this differently", "CVE-2025-68664", TOOLS)

    assert len(chooser.calls) == 2


def test_live_mode_asks_again_and_overwrites(tmp_path: Path):
    path = tmp_path / "decisions.json"
    cache(path, lambda: RecordingChooser()).choose(SYSTEM, "q", TOOLS)

    chooser = RecordingChooser()
    cache(path, lambda: chooser, read_cache=False).choose(SYSTEM, "q", TOOLS)

    assert chooser.calls == ["q"]
