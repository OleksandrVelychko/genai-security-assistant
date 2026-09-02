"""The write half of the tool layer: recording a security finding.

Unlike a read tool, this one creates a persistent audit record, and so it
requires explicit confirmation before anything is written.

Each finding receives a deterministic identifier derived from its content.
The identifier makes the operation idempotent: submitting the same finding
again does not create a duplicate record. Instead, the previously stored
record is returned unchanged, including its original timestamp.

Records are appended to a local audit log, which preserves a stable history
of confirmed findings and keeps a regenerated report consistent with the
committed one.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from genai_security_assistant.config import Settings
from genai_security_assistant.models.tools import (
    FindingRecord,
    SecurityFindingInput,
    ToolObservation,
    ToolRequest,
    ToolSpec,
)
from genai_security_assistant.tools.base import BaseTool


def finding_id(arguments: SecurityFindingInput) -> str:
    """Fingerprint of what a finding says, not of when it was said."""
    payload = json.dumps(arguments.model_dump(), sort_keys=True).encode("utf-8")
    return "find_" + hashlib.sha256(payload).hexdigest()[:12]


class FindingsLog:
    """The findings file, appended to and read back by id."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def find(self, identifier: str) -> FindingRecord | None:
        """Return the record already stored under this id, if there is one."""
        if not self.path.exists():
            return None
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            stored = FindingRecord.model_validate_json(line)
            if stored.finding_id == identifier:
                return stored
        return None

    def append(self, record: FindingRecord) -> None:
        """Add one record to the end of the file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")


class RecordFindingTool(BaseTool):
    """Write one finding to the audit log, once it has been confirmed."""

    spec = ToolSpec(
        name="record_security_finding",
        tool_type="write",
        purpose=(
            "Append one security finding to the local audit log and return "
            "the stored record, including the identifier assigned to it."
        ),
        source="data/findings.jsonl",
        when_to_use=[
            "The user asks to log, record or file a finding they have "
            "described.",
            "A CVE lookup produced something the user wants kept.",
        ],
        when_not_to_use=[
            "The user is asking a question rather than asking for something "
            "to be written down.",
            "No human has confirmed the write. This tool refuses instead of "
            "asking, because the confirmation is not the model's to give.",
        ],
        input_model=SecurityFindingInput,
        output_model=FindingRecord,
    )

    def __init__(self, log: FindingsLog) -> None:
        self.log = log

    def execute(self, arguments: BaseModel, request: ToolRequest) -> ToolObservation:
        """Store the finding, or return the one already stored."""
        assert isinstance(arguments, SecurityFindingInput)
        identifier = finding_id(arguments)

        stored = self.log.find(identifier)
        if stored is not None:
            # A retry after a timeout looks exactly like this. Reporting the
            # original record, rather than writing a second one, is what
            # makes the call safe to repeat.
            return self._observe(stored, created=False)

        record = FindingRecord(
            finding_id=identifier,
            **arguments.model_dump(),
            recorded_at=datetime.now(timezone.utc),
            proposed_by=request.proposed_by,
            # Not read from the request: BaseTool refuses an unconfirmed
            # write before execute() is reached, so reaching here is the
            # confirmation.
            confirmed=True,
        )
        self.log.append(record)
        return self._observe(record, created=True)

    def _observe(self, record: FindingRecord, created: bool) -> ToolObservation:
        """Wrap a record, saying whether this call is what wrote it."""
        return ToolObservation.ok(
            self.spec.name, {**record.model_dump(mode="json"), "created": created}
        )


def build_record_finding_tool(settings: Settings | None = None) -> RecordFindingTool:
    """Build the tool from configs/base.yaml."""
    resolved = settings or Settings()
    return RecordFindingTool(log=FindingsLog(resolved.path("findings")))
