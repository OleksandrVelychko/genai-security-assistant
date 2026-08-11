"""Unit tests for the CVE lookup tool and its normalization."""

from __future__ import annotations

from typing import Any

from genai_security_assistant.models.tools import CveRecord, ToolRequest
from genai_security_assistant.tools.cve_lookup import (
    CveLookupTool,
    normalize_cve,
    select_cvss,
)
from genai_security_assistant.tools.nvd_client import NvdError

TIMESTAMP = "2026-08-11T11:19:22.256"


def cvss_entry(
    score: float, entry_type: str, source: str, version: str = "3.1"
) -> dict[str, Any]:
    """One CVSS entry shaped the way NVD nests it."""
    return {
        "source": source,
        "type": entry_type,
        "cvssData": {
            "version": version,
            "baseScore": score,
            "baseSeverity": "HIGH",
            "vectorString": f"CVSS:{version}/AV:N/AC:L",
        },
    }


def make_payload(
    metrics: dict[str, Any] | None = None,
    weaknesses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A response body carrying one CVE and nothing that is not needed."""
    return {
        "timestamp": TIMESTAMP,
        "totalResults": 1,
        "vulnerabilities": [
            {
                "cve": {
                    "id": "CVE-2025-11111",
                    "published": "2025-01-02T00:00:00.000",
                    "lastModified": "2025-06-02T00:00:00.000",
                    "vulnStatus": "Analyzed",
                    "descriptions": [
                        {"lang": "es", "value": "no debe aparecer"},
                        {"lang": "en", "value": "A test vulnerability."},
                    ],
                    "metrics": metrics if metrics is not None else {},
                    "weaknesses": weaknesses if weaknesses is not None else [],
                    "references": [
                        {"url": "https://example.test/a"},
                        {"url": "https://example.test/a"},
                        {"url": "https://example.test/b"},
                    ],
                }
            }
        ],
    }


class StubNvdClient:
    """Returns a fixed body without touching the network."""

    name = "stub"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def fetch_cve(self, cve_id: str) -> dict[str, Any]:
        self.calls.append(cve_id)
        return self.payload


class ExplodingNvdClient:
    """Stands in for NVD in tests where nothing may reach it."""

    name = "exploding"

    def fetch_cve(self, cve_id: str) -> dict[str, Any]:
        raise AssertionError(f"the source was asked for {cve_id!r}")


class FailingNvdClient:
    """Fails the way the transport fails."""

    name = "failing"

    def __init__(self, error: NvdError) -> None:
        self.error = error

    def fetch_cve(self, cve_id: str) -> dict[str, Any]:
        raise self.error


def run(tool: CveLookupTool, **arguments: Any):
    """Call the tool the way the orchestration layer will."""
    return tool.run(ToolRequest(tool_name="lookup_cve", arguments=arguments))


def chosen_cvss(metrics: dict[str, Any]) -> dict[str, Any]:
    """select_cvss returns None when there is no score; these cases have one."""
    entry = select_cvss(metrics)
    assert entry is not None
    return entry


def normalized(payload: dict[str, Any]) -> CveRecord:
    """normalize_cve returns None for an empty body; these cases carry a CVE."""
    record = normalize_cve(payload)
    assert record is not None
    return record


# --- choosing which score to quote ---------------------------------------


def test_the_primary_score_wins_over_a_secondary_one():
    """The secondary entry is often listed first, so order cannot decide."""
    chosen = chosen_cvss(
        {
            "cvssMetricV31": [
                cvss_entry(9.3, "Secondary", "cna@example.test"),
                cvss_entry(8.2, "Primary", "nvd@nist.gov"),
            ]
        }
    )

    assert chosen["cvssData"]["baseScore"] == 8.2
    assert chosen["source"] == "nvd@nist.gov"


def test_a_secondary_score_is_used_when_no_primary_exists():
    chosen = chosen_cvss(
        {"cvssMetricV31": [cvss_entry(7.5, "Secondary", "cna@example.test")]}
    )

    assert chosen["cvssData"]["baseScore"] == 7.5


def test_the_newer_cvss_version_wins():
    """Versions are compared as numbers, so "10.0" cannot lose to "3.1"."""
    chosen = chosen_cvss(
        {
            "cvssMetricV31": [cvss_entry(8.2, "Primary", "nvd@nist.gov", "3.1")],
            "cvssMetricV40": [cvss_entry(6.1, "Primary", "nvd@nist.gov", "4.0")],
        }
    )

    assert chosen["cvssData"]["version"] == "4.0"


def test_a_decision_model_is_not_read_as_a_score():
    """metrics also carries ssvcV203, which has no baseScore at all."""
    assert select_cvss({"ssvcV203": [{"source": "cisa", "ssvcData": {}}]}) is None


def test_a_record_with_no_metrics_has_no_score():
    assert select_cvss({}) is None


# --- flattening the response ---------------------------------------------


def test_the_record_names_the_scorer_alongside_the_score():
    """A number without its source is the one an answer must not print."""
    record = normalized(
        make_payload(
            metrics={
                "cvssMetricV31": [
                    cvss_entry(9.3, "Secondary", "cna@example.test"),
                    cvss_entry(8.2, "Primary", "nvd@nist.gov"),
                ]
            }
        )
    )

    assert record.cvss_score == 8.2
    assert record.cvss_type == "Primary"
    assert record.cvss_source == "nvd@nist.gov"
    assert record.cvss_version == "3.1"


def test_only_the_english_description_is_kept():
    record = normalized(make_payload())

    assert record.description == "A test vulnerability."


def test_placeholder_weaknesses_are_dropped_and_repeats_collapse():
    """NVD writes NVD-CWE-noinfo when it has nothing to map, once per scorer."""
    record = normalized(
        make_payload(
            weaknesses=[
                {"description": [{"lang": "en", "value": "CWE-502"}]},
                {"description": [{"lang": "en", "value": "CWE-502"}]},
                {"description": [{"lang": "en", "value": "NVD-CWE-noinfo"}]},
            ]
        )
    )

    assert record.cwe_ids == ["CWE-502"]


def test_a_repeated_reference_is_listed_once():
    record = normalized(make_payload())

    assert record.reference_urls == [
        "https://example.test/a",
        "https://example.test/b",
    ]


def test_the_response_timestamp_is_kept_as_provenance():
    """Taken from the body, so a replayed call still says when it was true."""
    record = normalized(make_payload())

    assert record.retrieved_at.isoformat().startswith("2026-08-11T11:19:22")


def test_an_empty_response_is_not_a_record():
    """An unknown id comes back as 200 with nothing in it."""
    assert normalize_cve({"timestamp": TIMESTAMP, "vulnerabilities": []}) is None


# --- validation runs before the source is touched -------------------------


def test_a_malformed_id_never_reaches_the_source():
    observation = run(CveLookupTool(ExplodingNvdClient()), cve_id="CVE-23-29374")

    assert not observation.success
    assert observation.error_code == "validation_error"


def test_a_year_before_the_cve_program_never_reaches_the_source():
    observation = run(CveLookupTool(ExplodingNvdClient()), cve_id="CVE-1998-0001")

    assert observation.error_code == "validation_error"


def test_a_missing_id_never_reaches_the_source():
    observation = CveLookupTool(ExplodingNvdClient()).run(
        ToolRequest(tool_name="lookup_cve")
    )

    assert observation.error_code == "validation_error"


def test_an_argument_the_tool_does_not_declare_is_refused():
    """The tool takes an id and nothing else, so a query cannot be smuggled."""
    observation = run(
        CveLookupTool(ExplodingNvdClient()),
        cve_id="CVE-2025-11111",
        keyword="prompt injection",
    )

    assert observation.error_code == "validation_error"


# --- what comes back when the call happens --------------------------------


def test_a_valid_id_reaches_the_source_once():
    client = StubNvdClient(make_payload())

    observation = run(CveLookupTool(client), cve_id="CVE-2025-11111")

    assert observation.success
    assert client.calls == ["CVE-2025-11111"]


def test_an_empty_result_is_reported_as_not_found():
    client = StubNvdClient({"timestamp": TIMESTAMP, "vulnerabilities": []})

    observation = run(CveLookupTool(client), cve_id="CVE-2025-11111")

    assert observation.error_code == "not_found"


def test_a_transport_failure_keeps_its_code():
    """rate_limited means try later; it must not arrive as not_found."""
    client = FailingNvdClient(NvdError("rate_limited", "NVD refused for now."))

    observation = run(CveLookupTool(client), cve_id="CVE-2025-11111")

    assert observation.error_code == "rate_limited"
