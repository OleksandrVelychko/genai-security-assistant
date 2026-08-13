"""The NVD CVE API behind one interface.

Built like generation/llm.py: a Protocol for what the tool layer needs,
one real client, and a factory that reads the config. The Protocol is what
lets the cache and the tests stand in for the network.

This module is transport only. It returns the response body as it came, or
raises. Deciding what a body means is the tool's job, not the client's.

Use of this API is subject to the NVD Terms of Use
(https://nvd.nist.gov/developers/terms-of-use). The notice they ask for is
displayed in README.md and at the top of outputs/tool_examples.md.
"""

from __future__ import annotations

import os
import time
from typing import Any, Protocol

import httpx

from genai_security_assistant.models.tools import ToolErrorCode


class NvdError(Exception):
    """A call to NVD that produced no body."""

    def __init__(self, code: ToolErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NvdClient(Protocol):
    """What the CVE tool needs from NVD."""

    name: str

    def fetch_cve(self, cve_id: str) -> dict[str, Any]:
        """Return the raw response body for one CVE id.
        Raises NvdError when nothing came back.
        """
        ...


class HttpNvdClient:
    """NVD CVE API 2.0 over HTTP."""

    name = "nvd_http"

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout_seconds: float = 20.0,
        min_interval_seconds: float = 6.0,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        # Without a key the allowance is 5 requests per rolling 30 seconds.
        # A key raises it to 50, so the wait is not needed.
        self.min_interval_seconds = 0.0 if api_key else min_interval_seconds
        self._last_request_at: float | None = None

    def _wait_turn(self) -> None:
        """Sleep until the next request is allowed."""
        if self._last_request_at is None or self.min_interval_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)

    def fetch_cve(self, cve_id: str) -> dict[str, Any]:
        """Return the raw NVD body for one CVE id."""
        # The id is validated by CveLookupInput before it gets here, so it
        # cannot carry anything but CVE-YYYY-NNNN. params= keeps it encoded
        # even so, rather than pasted into the URL.
        headers = {"apiKey": self.api_key} if self.api_key else {}

        self._wait_turn()
        try:
            response = httpx.get(
                self.base_url,
                params={"cveId": cve_id},
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except httpx.RequestError as error:
            raise NvdError("upstream_error", f"NVD unreachable: {error}") from error
        finally:
            self._last_request_at = time.monotonic()

        # 403 and 429 both mean "not now" rather than "never", so they get
        # their own code: the caller may retry, and the report should not
        # count them as a missing record.
        if response.status_code in (403, 429):
            raise NvdError(
                "rate_limited", f"NVD refused for now: {response.status_code}."
            )
        if response.status_code == 404:
            raise NvdError("not_found", f"NVD has no record for {cve_id}.")
        if response.status_code != 200:
            raise NvdError("upstream_error", f"NVD returned {response.status_code}.")

        try:
            return response.json()
        except ValueError as error:
            raise NvdError(
                "upstream_error", "NVD returned a body that is not JSON."
            ) from error

def build_nvd_client(config: dict[str, Any]) -> NvdClient:
    """Build the NVD client described by configs/base.yaml."""
    api_key_env = config.get("api_key_env", "NVD_API_KEY")
    return HttpNvdClient(
        base_url=config["base_url"],
        # Optional, unlike the OpenAI key: NVD serves anonymous callers at
        # a lower rate, so require_env would refuse a run that works.
        api_key=os.environ.get(api_key_env) or None,
        timeout_seconds=config.get("timeout_seconds", 20.0),
        min_interval_seconds=config.get("min_interval_seconds", 6.0),
    )
