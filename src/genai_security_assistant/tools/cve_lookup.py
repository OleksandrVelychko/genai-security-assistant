"""lookup_cve: one CVE record, read from the NVD API and flattened.

The tool takes an identifier and nothing else. NVD also offers a keyword
search, and it's deliberately not exposed: a free-text parameter filled
in by a model is a query the model wrote, and this layer does not run
queries the model wrote.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from genai_security_assistant.config import Settings
from genai_security_assistant.models.tools import (
    CveLookupInput,
    CveRecord,
    ToolObservation,
    ToolRequest,
    ToolSpec,
)
from genai_security_assistant.tools.base import BaseTool
from genai_security_assistant.tools.cve_cache import CachedNvdClient
from genai_security_assistant.tools.nvd_client import (
    NvdClient,
    NvdError,
    build_nvd_client,
)

DETAIL_URL = "https://nvd.nist.gov/vuln/detail/{cve_id}"


def _version_key(version: str) -> tuple[int, ...]:
    """Turn "3.1" into (3, 1) so versions compare as numbers, not strings."""
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return (0,)


def select_cvss(metrics: dict[str, Any]) -> dict[str, Any] | None:
    """Pick the CVSS entry an answer should quote.
    Returns the whole entry, not just the score, because the answer has to
    name the scorer alongside the number.
    """
    # Only keys beginning with cvssMetric hold a CVSS score. metrics also
    # carries ssvcV203, which is CISA's decision model and has no baseScore.
    entries = [
        entry
        for key, group in metrics.items()
        if key.startswith("cvssMetric")
        for entry in group
    ]
    if not entries:
        return None

    # NVD's own analysis is "Primary", a CNA's is "Secondary". The two
    # scorers often disagree, and the secondary entry is not always last,
    # so the first entry is the wrong one to take. Records with no Primary
    # exist, which makes the fallback required rather than a nicety.
    primary = [entry for entry in entries if entry.get("type") == "Primary"]
    candidates = primary or entries

    # Highest version wins, so a v4.0 score would be preferred over v3.1
    # without this function needing to know the key name NVD gives it.
    return max(
        candidates,
        key=lambda entry: _version_key(entry.get("cvssData", {}).get("version", "0")),
    )


def _english(entries: list[dict[str, Any]]) -> str:
    """Join the English values of an NVD description list."""
    return " ".join(
        entry["value"] for entry in entries if entry.get("lang") == "en"
    ).strip()


def _cwe_ids(weaknesses: list[dict[str, Any]]) -> list[str]:
    """Collect real CWE identifiers, in order, without repeats.
    NVD fills this field with NVD-CWE-noinfo and NVD-CWE-Other when it has
    nothing to map, and lists the same CWE once per scorer.
    """
    found = [
        description["value"]
        for weakness in weaknesses
        for description in weakness.get("description", [])
        if description.get("value", "").startswith("CWE-")
    ]
    return list(dict.fromkeys(found))


def normalize_cve(payload: dict[str, Any]) -> CveRecord | None:
    """Flatten one NVD response into a CveRecord, or None when it holds no CVE.
    An unknown identifier is not an error: NVD answers 200 with an empty
    vulnerabilities list, and that body is cached like any other.
    """
    vulnerabilities = payload.get("vulnerabilities") or []
    if not vulnerabilities:
        return None

    cve = vulnerabilities[0]["cve"]
    chosen = select_cvss(cve.get("metrics", {})) or {}
    cvss = chosen.get("cvssData", {})

    return CveRecord(
        cve_id=cve["id"],
        published=cve["published"],
        last_modified=cve["lastModified"],
        vuln_status=cve["vulnStatus"],
        description=_english(cve.get("descriptions", [])),
        cvss_score=cvss.get("baseScore"),
        cvss_severity=cvss.get("baseSeverity"),
        cvss_vector=cvss.get("vectorString"),
        cvss_version=cvss.get("version"),
        cvss_source=chosen.get("source"),
        cvss_type=chosen.get("type"),
        cwe_ids=_cwe_ids(cve.get("weaknesses", [])),
        reference_urls=list(
            dict.fromkeys(
                reference["url"] for reference in cve.get("references", [])
            )
        ),
        source_url=DETAIL_URL.format(cve_id=cve["id"]),
        # NVD stamps every response with the moment it was produced. Taking
        # it from the body rather than the clock keeps a replayed call
        # honest about when the fact was true.
        retrieved_at=payload["timestamp"],
    )


class CveLookupTool(BaseTool):
    """Read one CVE record from NVD."""

    spec = ToolSpec(
        name="lookup_cve",
        tool_type="read",
        purpose=(
            "Return the current NVD record for one CVE identifier: status, "
            "description, CVSS score with its scorer, CWE ids and references."
        ),
        source="NVD CVE API 2.0",
        when_to_use=[
            "The question names a CVE identifier.",
            "The user asks whether a vulnerability is still current, has "
            "been rescored, or has been withdrawn.",
            "The user asks for the severity or CWE mapping of a known CVE.",
        ],
        when_not_to_use=[
            "The question is about a class of risk rather than one record: "
            "the indexed OWASP documents answer those.",
            "The user wants mitigations or guidance rather than a record.",
            "No identifier is present. This tool looks up an id and cannot "
            "search by keyword.",
        ],
        input_model=CveLookupInput,
        output_model=CveRecord,
    )

    def __init__(self, client: NvdClient) -> None:
        self.client = client

    def execute(self, arguments: BaseModel, request: ToolRequest) -> ToolObservation:
        """Fetch the record named by the validated arguments."""
        assert isinstance(arguments, CveLookupInput)

        try:
            payload = self.client.fetch_cve(arguments.cve_id)
        except NvdError as error:
            return ToolObservation.fail(self.spec.name, error.code, error.message)

        record = normalize_cve(payload)
        if record is None:
            return ToolObservation.fail(
                self.spec.name,
                "not_found",
                f"NVD holds no record for {arguments.cve_id}.",
            )

        return ToolObservation.ok(
            self.spec.name,
            record.model_dump(mode="json"),
            # Only the cache sets this; a bare client has no such attribute.
            from_cache=getattr(self.client, "last_was_cached", False),
        )


def build_cve_lookup_tool(
    settings: Settings | None = None, live: bool = False
) -> CveLookupTool:
    """Build the tool from configs/base.yaml, reading the cache unless live."""
    resolved = settings or Settings()
    nvd_config = resolved.nvd_config()
    use_cache = resolved.tools.get("use_cached_responses", True)

    return CveLookupTool(
        client=CachedNvdClient(
            path=resolved.path("cve_cache"),
            # Closes over the plain dict, not over Settings: the config is
            # read once, at build time, not whenever the client is needed.
            build_client=lambda: build_nvd_client(nvd_config),
            read_cache=use_cache and not live,
        )
    )
