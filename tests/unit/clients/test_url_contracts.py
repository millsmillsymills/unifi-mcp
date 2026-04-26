"""URL-contract tests for every API client (#108 item 1).

The existing per-client tests compute ``API_PREFIX`` from the same string
the production code uses, so a silent prefix rewrite (see #103) would not
fail any test. These tests pin the *expected* path prefix to a literal
that is NOT derived from the module. If a client starts hitting a
different path, one of these fails and the bug cannot ship silently.

The expected literals are chosen to match Ubiquiti's published
integration-API documentation at the time of writing:

* Network:      /proxy/network/api/s/{site}/
* Protect:      /proxy/protect/integration/v1/   (X-API-Key compatible)
* Site Manager: /v1/  (base host https://api.ui.com)

Note the asymmetry: Network uses plural ``integrations`` while Protect
uses singular ``integration``. Both are real Ubiquiti paths.
"""

from __future__ import annotations

import httpx
import respx

from unifi_mcp.clients.network import NetworkClient
from unifi_mcp.clients.protect import ProtectClient
from unifi_mcp.clients.site_manager import SITE_MANAGER_BASE_URL, SiteManagerClient


class TestNetworkURLContract:
    EXPECTED_PREFIX = "/proxy/network/api/s/default/"

    @respx.mock
    async def test_network_client_uses_published_prefix(self):
        base = "https://10.9.9.9:8443"
        client = NetworkClient(
            base_url=base,
            api_key="k",
            site="default",
            timeout=5,
            max_retries=1,
        )
        route = respx.get(url__startswith=f"{base}{self.EXPECTED_PREFIX}").mock(
            return_value=httpx.Response(200, json={"data": {}})
        )
        await client.get_health()
        assert route.called, (
            f"NetworkClient hit {respx.calls.last.request.url if respx.calls.call_count else '<no call>'} "
            f"but the documented integration-API path is {self.EXPECTED_PREFIX}."
        )
        await client.close()


class TestSiteManagerURLContract:
    EXPECTED_PREFIX = "/v1/"

    @respx.mock
    async def test_site_manager_client_uses_published_prefix(self):
        client = SiteManagerClient(api_key="k", timeout=5, max_retries=1)
        route = respx.get(url__startswith=f"{SITE_MANAGER_BASE_URL}{self.EXPECTED_PREFIX}").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        await client.list_hosts()
        assert route.called, (
            f"SiteManagerClient hit {respx.calls.last.request.url if respx.calls.call_count else '<no call>'} "
            f"but the documented Site Manager API path is {SITE_MANAGER_BASE_URL}{self.EXPECTED_PREFIX}."
        )
        await client.close()


class TestProtectURLContract:
    # Verified HTTP 200 against UCK-G2-Plus running Protect 7.0.107. The
    # X-API-Key scheme that the rest of the codebase uses is only accepted
    # under this prefix; the legacy /proxy/protect/api/ path requires the
    # session-cookie auth flow.
    EXPECTED_PREFIX = "/proxy/protect/integration/v1/"

    @respx.mock
    async def test_protect_client_uses_published_integration_prefix(self):
        base = "https://10.9.9.9:8443"
        client = ProtectClient(base_url=base, api_key="k", timeout=5, max_retries=1)
        route = respx.get(url__startswith=f"{base}{self.EXPECTED_PREFIX}").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.list_cameras()
        assert route.called, (
            f"ProtectClient hit {respx.calls.last.request.url if respx.calls.call_count else '<no call>'} "
            f"but X-API-Key auth only works under {self.EXPECTED_PREFIX}."
        )
        await client.close()
