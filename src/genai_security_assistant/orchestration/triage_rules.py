"""The decisions triage makes without calling anything (HW6).

Every function here reads values two tool calls already produced and
returns what follows from them. Same arguments, same answer: nothing
here reaches the registry, the corpus or the current date, so a branch
can be tested without building a single tool.

build_finding drafts a finding and stops. The identifier and the
timestamp belong to the write tool, which assigns them only after a
human has confirmed the write.
"""

from __future__ import annotations

from itertools import takewhile

from genai_security_assistant.models.tools import (
    CveRecord,
    FindingSeverity,
    SecurityFindingInput,
    ServiceExposure,
)

# The question the corpus is asked once a service is found exposed, chosen
# by the weakness NVD mapped the record to. An entry earns its place only
# by being answered and grounded; the scores behind these are in
# configs/agent_conclusions.md. Re-measure one with:
#   uv run python scripts/rag_answer.py -q "..."
GUIDANCE_BY_CWE = {
    # Deserialization of untrusted data. The corpus covers no serialization
    # format, so the question asks about handling hostile input instead.
    "CWE-502": (
        "How should an AI agent handle untrusted input that it parses or "
        "loads, and what limits the damage when that input is hostile?"
    ),
    # Path traversal while loading a prompt. Asking how to validate a path
    # was refused: the corpus prescribes controls rather than defect checks,
    # so this asks for the control it does prescribe.
    "CWE-22": (
        "How should an LLM application limit the permissions of an "
        "extension that reads external resources on a user's behalf?"
    ),
}

# Asked when no entry matches, and aimed at LLM06: whatever the flaw turns
# out to be, the corpus can answer what limits a compromised component.
DEFAULT_GUIDANCE = (
    "What controls limit what a compromised component of an LLM application "
    "can do?"
)


def _leading_number(part: str) -> int:
    """Read the digits at the start of one version part."""
    return int("".join(takewhile(str.isdigit, part)) or "0")


def version_parts(version: str) -> tuple[int, ...]:
    """Split a dotted version so it compares as numbers, not as text.
    "1.2.9" sorts above "1.2.22" as a string, which would report an exposed
    service as patched. Anything after the leading digits of a part is
    dropped, which PEP 440 does not do and these fixtures never need.
    """
    return tuple(_leading_number(part) for part in version.split("."))


def is_below_fix(service: ServiceExposure) -> bool:
    """Say whether one service still runs a version the fix hasn't reached.
    A service with no fixed_version counts as exposed: no fix is published,
    so nothing it runs can be past one.
    """
    if service.fixed_version is None:
        return True
    installed = version_parts(service.installed_version)
    return installed < version_parts(service.fixed_version)


def exposed_services(services: list[ServiceExposure]) -> list[ServiceExposure]:
    """The services the fix hasn't reached, in the order they were returned."""
    return [service for service in services if is_below_fix(service)]


def exposure_of(services: list[ServiceExposure]) -> str:
    """Decide what the inventory result means for this organization.
    An empty list is not_affected rather than an error: the inventory
    answered, and what it answered was nothing.
    """
    if not services:
        return "not_affected"
    if exposed_services(services):
        return "exposed"
    return "patched"


def finding_severity(record: CveRecord) -> FindingSeverity:
    """Map a CVSS base score onto the severity a finding accepts.
    Bands are the qualitative scale in the CVSS v3.1 specification, section
    5: https://www.first.org/cvss/v3.1/specification-document
    """
    score = record.cvss_score
    # An unscored record still has to be filed as something. medium, so it
    # is neither hidden below a triage threshold nor treated as urgent.
    if score is None:
        return "medium"
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    return "low"


def exposed_summary(services: list[ServiceExposure]) -> str:
    """Name every service still below the fix, with both versions."""
    described = [
        f"{service.service_id} runs {service.component} "
        f"{service.installed_version}, fixed in {service.fixed_version}"
        for service in exposed_services(services)
    ]
    return "; ".join(described)


def guidance_question(record: CveRecord) -> str:
    """The question the corpus is asked about this class of flaw.
    Built from the weakness rather than from the identifier: no document in
    the corpus mentions any CVE, and a question that did would retrieve on
    the surrounding words alone.
    """
    for cwe_id in record.cwe_ids:
        if cwe_id in GUIDANCE_BY_CWE:
            return GUIDANCE_BY_CWE[cwe_id]
    return DEFAULT_GUIDANCE


def build_finding(
    record: CveRecord, services: list[ServiceExposure]
) -> SecurityFindingInput:
    """Draft the finding an exposed assessment justifies. Writes nothing."""
    exposed = exposed_services(services)
    return SecurityFindingInput(
        title=f"{record.cve_id} affects {exposed[0].service_id}",
        severity=finding_severity(record),
        related_cve_id=record.cve_id,
        summary=exposed_summary(services),
    )
