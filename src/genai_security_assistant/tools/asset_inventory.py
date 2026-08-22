"""check_asset_inventory and get_service_owner: the two internal sources.

Both stand in for systems this project doesn't have. The first answers
what an SBOM tool answers - which deployed services run a component one CVE
affects - and the second answers what a service catalog answers. The data
is fixed in configs/asset_inventory.yaml, which is what lets a traced run
reproduce.

Fixed data, not a fixed answer: both go through BaseTool, so the argument
validation and the observation shape are the ones a real integration would
use, and swapping the file for a client changes nothing above this module.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from genai_security_assistant.config import Settings, load_yaml
from genai_security_assistant.models.tools import (
    AssetInventoryInput,
    ServiceExposure,
    ServiceOwner,
    ServiceOwnerInput,
    ToolObservation,
    ToolRequest,
    ToolSpec,
)
from genai_security_assistant.tools.base import BaseTool, Tool


class AssetInventory:
    """The deployment facts in configs/asset_inventory.yaml."""

    def __init__(
        self,
        exposures: dict[str, list[ServiceExposure]],
        owners: dict[str, ServiceOwner],
    ) -> None:
        self._exposures = exposures
        self._owners = owners

    @classmethod
    def from_path(cls, path: Path) -> AssetInventory:
        """Read the inventory file, validating every row.
        Validated here rather than on use, so a typo in the file fails when
        the tools are built and not halfway through a traced run.
        """
        raw = load_yaml(path)
        return cls(
            exposures={
                cve_id.upper(): [
                    ServiceExposure.model_validate(row) for row in rows
                ]
                for cve_id, rows in (raw.get("exposures") or {}).items()
            },
            owners={
                service_id: ServiceOwner(service_id=service_id, **fields)
                for service_id, fields in (raw.get("owners") or {}).items()
            },
        )

    @property
    def service_ids(self) -> list[str]:
        """Every service the inventory can return, sorted, without repeats."""
        return sorted(
            {
                service.service_id
                for services in self._exposures.values()
                for service in services
            }
        )

    def services_for(self, cve_id: str) -> list[ServiceExposure]:
        """Services running a component this CVE affects, which may be none."""
        return self._exposures.get(cve_id.upper(), [])

    def owner_of(self, service_id: str) -> ServiceOwner | None:
        """The team accountable for one service, or None when none is recorded."""
        return self._owners.get(service_id)


class CheckAssetInventoryTool(BaseTool):
    """Read which deployed services one CVE reaches."""

    spec = ToolSpec(
        name="check_asset_inventory",
        tool_type="read",
        purpose=(
            "Return the deployed services running a component that one CVE "
            "affects, with the version installed and the version that fixes "
            "it."
        ),
        source="configs/asset_inventory.yaml (mock deployment inventory)",
        when_to_use=[
            "The question asks whether a named CVE affects this organization.",
            "A CVE record has been read and the next question is who runs the "
            "affected component.",
        ],
        when_not_to_use=[
            "The question is about a class of risk rather than one record.",
            "No CVE identifier is present. This tool matches on an id and "
            "cannot search by component name.",
        ],
        input_model=AssetInventoryInput,
        # The element type, not a wrapper: the report renders one row's
        # fields, and a list has none of its own.
        output_model=ServiceExposure,
    )

    def __init__(self, inventory: AssetInventory) -> None:
        self.inventory = inventory

    def execute(self, arguments: BaseModel, request: ToolRequest) -> ToolObservation:
        """Return every service this CVE reaches, which may be none."""
        assert isinstance(arguments, AssetInventoryInput)
        services = self.inventory.services_for(arguments.cve_id)

        # An empty list is an answer, not a failure: "nothing here runs it"
        # is what assess_exposure needs to conclude not_affected. not_found
        # would claim the inventory could not answer, which is different.
        return ToolObservation.ok(
            self.spec.name,
            {
                "cve_id": arguments.cve_id,
                "services": [
                    service.model_dump(mode="json") for service in services
                ],
            },
        )


class GetServiceOwnerTool(BaseTool):
    """Read who is accountable for one service."""

    spec = ToolSpec(
        name="get_service_owner",
        tool_type="read",
        purpose=(
            "Return the team accountable for one service, with the contact "
            "and the escalation channel to notify."
        ),
        source="configs/asset_inventory.yaml (mock service catalog)",
        when_to_use=[
            "A service has been found exposed and someone has to be told.",
            "The user asks who owns a service check_asset_inventory returned.",
        ],
        when_not_to_use=[
            "No service identifier is present. The identifier comes from "
            "check_asset_inventory, not from the user's wording.",
        ],
        input_model=ServiceOwnerInput,
        output_model=ServiceOwner,
    )

    def __init__(self, inventory: AssetInventory) -> None:
        self.inventory = inventory

    def execute(self, arguments: BaseModel, request: ToolRequest) -> ToolObservation:
        """Return the owner of the named service."""
        assert isinstance(arguments, ServiceOwnerInput)
        owner = self.inventory.owner_of(arguments.service_id)

        # not_found here, unlike in check_asset_inventory: a deployed service
        # nobody owns is a gap in the catalog, not a fact to report.
        if owner is None:
            return ToolObservation.fail(
                self.spec.name,
                "not_found",
                f"No owner is recorded for {arguments.service_id}.",
            )
        return ToolObservation.ok(self.spec.name, owner.model_dump(mode="json"))


def build_asset_inventory_tools(settings: Settings | None = None) -> list[Tool]:
    """Build both inventory tools from configs/base.yaml.
    Returned together because they read one file: it is parsed and validated
    once, at build time, and neither can be pointed at a different one.
    """
    resolved = settings or Settings()
    inventory = AssetInventory.from_path(resolved.path("asset_inventory"))
    return [CheckAssetInventoryTool(inventory), GetServiceOwnerTool(inventory)]
