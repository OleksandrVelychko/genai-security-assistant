"""Unit tests for the decisions triage makes from what it was told."""

from __future__ import annotations

from datetime import datetime, timezone

from genai_security_assistant.models.tools import CveRecord, ServiceExposure
from genai_security_assistant.orchestration.triage_rules import (
    DEFAULT_GUIDANCE,
    GUIDANCE_BY_CWE,
    build_finding,
    exposed_services,
    exposed_summary,
    exposure_of,
    finding_severity,
    guidance_question,
    is_below_fix,
    version_parts,
)

NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def service(
    installed: str,
    fixed: str | None = "1.0.0",
    service_id: str = "svc-one",
) -> ServiceExposure:
    return ServiceExposure(
        service_id=service_id,
        service_name="One service",
        component="langchain-core",
        installed_version=installed,
        fixed_version=fixed,
        environment="production",
        internet_facing=False,
    )


def cve(score: float | None = 8.2, cwe_ids: list[str] | None = None) -> CveRecord:
    return CveRecord(
        cve_id="CVE-2025-68664",
        published=NOW,
        last_modified=NOW,
        vuln_status="Analyzed",
        description="A serialization injection vulnerability.",
        cvss_score=score,
        cwe_ids=["CWE-502"] if cwe_ids is None else cwe_ids,
        source_url="https://nvd.nist.gov/vuln/detail/CVE-2025-68664",
        retrieved_at=NOW,
    )


# --- versions -------------------------------------------------------------


def test_versions_compare_as_numbers_where_text_would_disagree():
    """The case configs/asset_inventory.yaml carries on purpose."""
    assert version_parts("1.2.9") < version_parts("1.2.22")
    assert "1.2.9" > "1.2.22"


def test_a_suffix_after_the_digits_is_dropped():
    assert version_parts("2.0.0rc1") == (2, 0, 0)


def test_a_service_below_the_fix_is_exposed():
    assert is_below_fix(service("0.3.74", "0.3.81"))


def test_a_service_on_the_fix_is_not_exposed():
    assert not is_below_fix(service("0.3.81", "0.3.81"))


def test_a_service_past_the_fix_is_not_exposed():
    assert not is_below_fix(service("0.4.0", "0.3.81"))


def test_a_service_with_no_published_fix_is_exposed():
    """Nothing can be past a fix that does not exist."""
    assert is_below_fix(service("0.3.81", None))


# --- exposure -------------------------------------------------------------


def test_an_empty_inventory_result_means_not_affected():
    assert exposure_of([]) == "not_affected"


def test_every_service_on_the_fix_means_patched():
    assert exposure_of([service("1.0.0"), service("1.0.1")]) == "patched"


def test_one_service_below_the_fix_is_enough_to_be_exposed():
    services = [service("1.0.0", service_id="svc-one"),
                service("0.9.0", service_id="svc-two")]

    assert exposure_of(services) == "exposed"
    assert [row.service_id for row in exposed_services(services)] == ["svc-two"]


def test_the_summary_names_both_versions():
    text = exposed_summary([service("0.3.74", "0.3.81", "svc-chat-gateway")])

    assert "svc-chat-gateway" in text
    assert "0.3.74" in text
    assert "0.3.81" in text


# --- severity -------------------------------------------------------------


def test_cvss_bands_follow_the_specification():
    assert finding_severity(cve(9.3)) == "critical"
    assert finding_severity(cve(8.2)) == "high"
    assert finding_severity(cve(5.0)) == "medium"
    assert finding_severity(cve(2.0)) == "low"


def test_an_unscored_record_is_filed_rather_than_dropped():
    assert finding_severity(cve(None)) == "medium"


# --- the question the corpus is asked ------------------------------------


def test_a_mapped_weakness_gets_its_own_question():
    assert guidance_question(cve(cwe_ids=["CWE-502"])) == GUIDANCE_BY_CWE["CWE-502"]


def test_an_unmapped_weakness_falls_back_to_the_default():
    assert guidance_question(cve(cwe_ids=["CWE-1337"])) == DEFAULT_GUIDANCE


def test_a_record_with_no_weakness_falls_back_to_the_default():
    assert guidance_question(cve(cwe_ids=[])) == DEFAULT_GUIDANCE


def test_no_question_names_an_identifier():
    """The corpus mentions no CVE, so a question that did would mislead."""
    for question in [*GUIDANCE_BY_CWE.values(), DEFAULT_GUIDANCE]:
        assert "CVE-" not in question


# --- the finding a run would write ---------------------------------------


def test_the_finding_carries_the_record_and_the_service():
    finding = build_finding(
        cve(8.2), [service("0.3.74", "0.3.81", "svc-chat-gateway")]
    )

    assert finding.related_cve_id == "CVE-2025-68664"
    assert finding.severity == "high"
    assert "svc-chat-gateway" in finding.title
    assert "0.3.81" in finding.summary
