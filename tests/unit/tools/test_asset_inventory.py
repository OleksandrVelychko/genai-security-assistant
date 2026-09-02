"""Unit tests for the mock inventory tools."""

from __future__ import annotations

from genai_security_assistant.config import Settings
from genai_security_assistant.models.tools import ToolRequest
from genai_security_assistant.tools.asset_inventory import (
    AssetInventory,
    CheckAssetInventoryTool,
    GetServiceOwnerTool,
)


def inventory() -> AssetInventory:
    """The inventory the repository ships, so the tests read real fixtures."""
    return AssetInventory.from_path(Settings().path("asset_inventory"))


def check(cve_id: str):
    request = ToolRequest(
        tool_name="check_asset_inventory", arguments={"cve_id": cve_id}
    )
    return CheckAssetInventoryTool(inventory()).run(request)


def owner(service_id: str):
    request = ToolRequest(
        tool_name="get_service_owner", arguments={"service_id": service_id}
    )
    return GetServiceOwnerTool(inventory()).run(request)


# --- check_asset_inventory ------------------------------------------------


def test_a_known_cve_returns_the_services_running_the_component():
    observation = check("CVE-2025-68664")

    assert observation.success
    returned = {row["service_id"] for row in observation.data["services"]}
    assert returned == {"svc-chat-gateway", "svc-doc-indexer"}


def test_a_cve_nothing_runs_succeeds_with_an_empty_list():
    """not_affected is a conclusion the flow draws, so it needs an answer."""
    observation = check("CVE-2024-5565")

    assert observation.success
    assert observation.data["services"] == []


def test_a_lower_case_identifier_is_refused_the_way_lookup_cve_refuses_it():
    """One spelling per tool. Normalizing is the router's job, as in HW5."""
    observation = check("cve-2025-68664")

    assert not observation.success
    assert observation.error_code == "validation_error"


def test_the_inventory_itself_matches_either_spelling():
    """Below the tool, where nothing has normalized the identifier yet."""
    assert inventory().services_for("cve-2025-68664") != []


def test_a_malformed_identifier_never_reaches_the_file():
    observation = check("CVE-23-1")

    assert not observation.success
    assert observation.error_code == "validation_error"


def test_a_component_name_cannot_be_smuggled_in():
    request = ToolRequest(
        tool_name="check_asset_inventory",
        arguments={"cve_id": "CVE-2025-68664", "component": "langchain-core"},
    )

    observation = CheckAssetInventoryTool(inventory()).run(request)

    assert observation.error_code == "validation_error"


# --- get_service_owner ----------------------------------------------------


def test_a_known_service_returns_the_team_to_notify():
    observation = owner("svc-chat-gateway")

    assert observation.success
    assert observation.data["team"] == "Conversational AI"


def test_a_service_with_no_owner_is_a_gap_rather_than_an_answer():
    observation = owner("svc-nobody-owns-this")

    assert not observation.success
    assert observation.error_code == "not_found"


def test_a_service_id_outside_the_expected_shape_is_refused():
    """The id comes from the previous step's result, not from a free field."""
    observation = owner("../../etc/passwd")

    assert observation.error_code == "validation_error"


# --- the shipped fixture --------------------------------------------------


def test_every_service_in_the_inventory_has_an_owner():
    """identify_owner runs on whatever check_asset_inventory returned."""
    catalog = inventory()

    missing = [
        service_id
        for service_id in catalog.service_ids
        if catalog.owner_of(service_id) is None
    ]

    assert missing == []
