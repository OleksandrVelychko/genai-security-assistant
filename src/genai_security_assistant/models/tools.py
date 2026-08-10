"""Data contracts for the external tool layer (HW5).

Declared here, filled in by the tools package, the same way
models/retrieval.py and models/generation.py work.

Four groups:
  ToolSpec        - what a tool declares about itself
  ToolRequest     - a proposed call, not yet validated
  ToolObservation - the result of one call, successful or not
  Input / Output  - one pair per tool: CveLookupInput / CveRecord,
                    SecurityFindingInput / FindingRecord
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ToolType = Literal["read", "write"]

# The router branches on these, so they are codes rather than sentences.
# not_found means the source has no such record; upstream_error means the
# source did not answer. Retrying helps with the second.
ToolErrorCode = Literal[
    "validation_error",
    "not_confirmed",
    "not_found",
    "upstream_error",
    "rate_limited",
    "unknown_tool",
]


class ToolSpec(BaseModel):
    """What one tool declares about itself.
    Feeds three consumers: the JSON schema shown to the model, the README
    section, and the generated report.
    """

    name: str
    tool_type: ToolType
    purpose: str
    source: str
    when_to_use: list[str]
    when_not_to_use: list[str]
    # Classes, not instances: the registry calls model_json_schema() on them.
    input_model: type[BaseModel]
    output_model: type[BaseModel]

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def json_schema(self) -> dict[str, Any]:
        """Return the input schema shown to the model for function calling."""
        return self.input_model.model_json_schema()


class ToolRequest(BaseModel):
    """A proposed tool call: which tool, with what arguments."""

    tool_name: str
    # dict, not a typed model: this comes from a router or an LLM and is
    # untrusted until validation converts it into the tool's input model.
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Set by the orchestration layer, never by the model. Keep it out of
    # any schema the model is shown, or it will confirm its own writes.
    confirmed: bool = False
    # "rule_router", "llm_router" or "cli". The report distinguishes a
    # tool the model chose from one a regex chose.
    proposed_by: str = "unknown"

    model_config = ConfigDict(extra="forbid")


class ToolObservation(BaseModel):
    """The result of one tool call, successful or not.
    One shape for both outcomes, so callers read .success instead of
    testing for an "error" key. Nothing here raises: a failed call has to
    stay reportable, like an ungrounded GroundedAnswer.
    """

    tool_name: str
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: ToolErrorCode | None = None
    error_message: str | None = None
    from_cache: bool = False
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def ok(
        cls, tool_name: str, data: dict[str, Any], from_cache: bool = False
    ) -> ToolObservation:
        """Build a successful observation."""
        return cls(tool_name=tool_name, success=True, data=data, from_cache=from_cache)

    @classmethod
    def fail(cls, tool_name: str, code: ToolErrorCode, message: str) -> ToolObservation:
        """Build a failed observation."""
        return cls(
            tool_name=tool_name,
            success=False,
            error_code=code,
            error_message=message,
        )


# CVE ids are CVE-YYYY-NNNN with four or more digits after the year.
CVE_ID_PATTERN = r"^CVE-\d{4}-\d{4,}$"
# The CVE program started in 1999.
CVE_FIRST_YEAR = 1999


class CveLookupInput(BaseModel):
    """Arguments for lookup_cve."""

    cve_id: str = Field(
        pattern=CVE_ID_PATTERN,
        max_length=30,
        description=(
            "CVE identifier in the form CVE-YYYY-NNNN, for example "
            "CVE-2023-29374. Four or more digits after the year."
        ),
    )

    # extra="forbid" is a control: an invented argument such
    # as "sql" or "limit" is rejected instead of silently ignored.
    model_config = ConfigDict(extra="forbid")

    @field_validator("cve_id")
    @classmethod
    def year_must_be_plausible(cls, value: str) -> str:
        """Reject ids whose year can't exist, such as CVE-0000-0001."""
        year = int(value.split("-")[1])
        current_year = datetime.now(timezone.utc).year
        if not CVE_FIRST_YEAR <= year <= current_year + 1:
            raise ValueError(
                f"CVE year {year} is out of range "
                f"({CVE_FIRST_YEAR}-{current_year + 1})."
            )
        return value


class CveRecord(BaseModel):
    """One CVE, flattened out of the NVD response.
    NVD nests these facts four levels deep and repeats the score under
    several CVSS versions, which wastes context and invites the model to
    read the wrong number.
    """

    cve_id: str
    published: datetime
    last_modified: datetime
    # "Analyzed", "Modified", "Awaiting Analysis", "Rejected". This is what
    # makes a CVE dynamic: a published record can be rescored or withdrawn.
    vuln_status: str
    description: str
    cvss_v31_score: float | None = Field(default=None, ge=0.0, le=10.0)
    cvss_v31_severity: str | None = None
    cvss_v31_vector: str | None = None
    cwe_ids: list[str] = Field(default_factory=list)
    reference_urls: list[str] = Field(default_factory=list)
    source: str = "NVD CVE API 2.0"
    source_url: str
    # Lets an answer state when the fact was true, the same way chunk
    # metadata carries retrieved_at.
    retrieved_at: datetime


FindingSeverity = Literal["low", "medium", "high", "critical"]


class SecurityFindingInput(BaseModel):
    """Arguments for record_security_finding."""

    title: str = Field(min_length=5, max_length=120)
    severity: FindingSeverity
    related_cve_id: str | None = Field(default=None, pattern=CVE_ID_PATTERN)
    summary: str = Field(min_length=10, max_length=1000)

    # No free-form payload, no path, no filename: a write tool's input
    # surface is its attack surface, so every field is bounded.
    model_config = ConfigDict(extra="forbid")


class FindingRecord(BaseModel):
    """One line of data/findings.jsonl."""

    # Derived from the content, not counted, so a retry after a timeout
    # appends nothing new.
    finding_id: str
    title: str
    severity: FindingSeverity
    related_cve_id: str | None = None
    summary: str
    recorded_at: datetime
    proposed_by: str
    confirmed: bool
