"""Network API client for UniFi controllers."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from unifi_mcp.clients.base import BaseUniFiClient
from unifi_mcp.errors import UniFiError, UniFiNotFoundError

logger = logging.getLogger(__name__)


class NetworkClient(BaseUniFiClient):
    """Client for the UniFi Network API on a local controller.

    Communicates with the controller's proxy API at
    ``/proxy/network/api/s/{site}/``.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        site: str = "default",
        verify_ssl: bool = False,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self._path_prefix = f"/proxy/network/api/s/{site}/"
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            verify_ssl=verify_ssl,
            timeout=timeout,
            max_retries=max_retries,
        )

    # ── Read methods ───────────────────────────────────────────────────

    async def get_health(self) -> dict[str, Any]:
        """Get controller health status."""
        result: dict[str, Any] = await self.get("stat/health")
        return result

    async def list_events(self, limit: int = 100) -> dict[str, Any]:
        """List recent events / alarms.

        Uses ``stat/alarm`` — the legacy ``stat/event`` path returns 404 on
        current UniFi controllers.
        """
        result: dict[str, Any] = await self.get("stat/alarm", params={"_limit": limit})
        return result

    async def list_devices(self) -> dict[str, Any]:
        """List all adopted devices with full details."""
        result: dict[str, Any] = await self.get("stat/device")
        return result

    async def list_devices_basic(self) -> dict[str, Any]:
        """List all adopted devices with basic info only."""
        result: dict[str, Any] = await self.get("stat/device-basic")
        return result

    async def list_active_clients(self) -> dict[str, Any]:
        """List currently connected clients."""
        result: dict[str, Any] = await self.get("stat/sta")
        return result

    async def list_configured_clients(self) -> dict[str, Any]:
        """List all configured (known) clients."""
        result: dict[str, Any] = await self.get("rest/user")
        return result

    async def list_all_clients(self) -> dict[str, Any]:
        """List all clients (active and historical)."""
        result: dict[str, Any] = await self.get("stat/alluser", params={"type": "all", "conn": "all"})
        return result

    async def get_dpi_stats(self, dpi_type: str = "by_app") -> dict[str, Any]:
        """Get deep packet inspection statistics."""
        result: dict[str, Any] = await self.get("stat/dpi", params={"type": dpi_type})
        return result

    async def get_sysinfo(self) -> dict[str, Any]:
        """Get system information for the controller."""
        result: dict[str, Any] = await self.get("stat/sysinfo")
        return result

    async def list_wlans(self) -> dict[str, Any]:
        """List all WLAN configurations."""
        result: dict[str, Any] = await self.get("rest/wlanconf")
        return result

    async def get_wlan(self, wlan_id: str) -> dict[str, Any]:
        """Get a specific WLAN configuration."""
        result: dict[str, Any] = await self.get(f"rest/wlanconf/{wlan_id}")
        return result

    async def list_networks(self) -> dict[str, Any]:
        """List all network configurations."""
        result: dict[str, Any] = await self.get("rest/networkconf")
        return result

    async def get_network(self, network_id: str) -> dict[str, Any]:
        """Get a specific network configuration."""
        result: dict[str, Any] = await self.get(f"rest/networkconf/{network_id}")
        return result

    async def list_firewall_rules(self) -> dict[str, Any]:
        """List all firewall rules."""
        result: dict[str, Any] = await self.get("rest/firewallrule")
        return result

    async def get_firewall_rule(self, rule_id: str) -> dict[str, Any]:
        """Get a specific firewall rule."""
        result: dict[str, Any] = await self.get(f"rest/firewallrule/{rule_id}")
        return result

    async def list_firewall_groups(self) -> dict[str, Any]:
        """List all firewall groups."""
        result: dict[str, Any] = await self.get("rest/firewallgroup")
        return result

    async def get_firewall_group(self, group_id: str) -> dict[str, Any]:
        """Get a specific firewall group."""
        result: dict[str, Any] = await self.get(f"rest/firewallgroup/{group_id}")
        return result

    async def list_port_forwards(self) -> dict[str, Any]:
        """List all port forwarding rules."""
        result: dict[str, Any] = await self.get("rest/portforward")
        return result

    async def get_port_forward(self, pf_id: str) -> dict[str, Any]:
        """Get a specific port forwarding rule."""
        result: dict[str, Any] = await self.get(f"rest/portforward/{pf_id}")
        return result

    async def list_routes(self) -> dict[str, Any]:
        """List all static routes."""
        result: dict[str, Any] = await self.get("rest/routing")
        return result

    async def get_route(self, route_id: str) -> dict[str, Any]:
        """Get a specific static route."""
        result: dict[str, Any] = await self.get(f"rest/routing/{route_id}")
        return result

    async def get_settings(self) -> dict[str, Any]:
        """Get controller settings."""
        result: dict[str, Any] = await self.get("rest/setting")
        return result

    # ── Write methods: CRUD ────────────────────────────────────────────

    async def create_wlan(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new WLAN configuration."""
        result: dict[str, Any] = await self.post("rest/wlanconf", json=data)
        return result

    async def update_wlan(self, wlan_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing WLAN configuration."""
        result: dict[str, Any] = await self.put(f"rest/wlanconf/{wlan_id}", json=data)
        return result

    async def delete_wlan(self, wlan_id: str) -> dict[str, Any]:
        """Delete a WLAN configuration."""
        result: dict[str, Any] = await self.delete(f"rest/wlanconf/{wlan_id}")
        return result

    async def create_network(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new network configuration."""
        result: dict[str, Any] = await self.post("rest/networkconf", json=data)
        return result

    async def update_network(self, network_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing network configuration."""
        result: dict[str, Any] = await self.put(f"rest/networkconf/{network_id}", json=data)
        return result

    async def delete_network(self, network_id: str) -> dict[str, Any]:
        """Delete a network configuration."""
        result: dict[str, Any] = await self.delete(f"rest/networkconf/{network_id}")
        return result

    async def create_firewall_rule(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new firewall rule."""
        result: dict[str, Any] = await self.post("rest/firewallrule", json=data)
        return result

    async def update_firewall_rule(self, rule_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing firewall rule."""
        result: dict[str, Any] = await self.put(f"rest/firewallrule/{rule_id}", json=data)
        return result

    async def delete_firewall_rule(self, rule_id: str) -> dict[str, Any]:
        """Delete a firewall rule."""
        result: dict[str, Any] = await self.delete(f"rest/firewallrule/{rule_id}")
        return result

    async def create_firewall_group(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new firewall group."""
        result: dict[str, Any] = await self.post("rest/firewallgroup", json=data)
        return result

    async def update_firewall_group(self, group_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing firewall group."""
        result: dict[str, Any] = await self.put(f"rest/firewallgroup/{group_id}", json=data)
        return result

    async def delete_firewall_group(self, group_id: str) -> dict[str, Any]:
        """Delete a firewall group."""
        result: dict[str, Any] = await self.delete(f"rest/firewallgroup/{group_id}")
        return result

    async def create_port_forward(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new port forwarding rule."""
        result: dict[str, Any] = await self.post("rest/portforward", json=data)
        return result

    async def update_port_forward(self, pf_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing port forwarding rule."""
        result: dict[str, Any] = await self.put(f"rest/portforward/{pf_id}", json=data)
        return result

    async def delete_port_forward(self, pf_id: str) -> dict[str, Any]:
        """Delete a port forwarding rule."""
        result: dict[str, Any] = await self.delete(f"rest/portforward/{pf_id}")
        return result

    async def create_route(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new static route."""
        result: dict[str, Any] = await self.post("rest/routing", json=data)
        return result

    async def update_route(self, route_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing static route."""
        result: dict[str, Any] = await self.put(f"rest/routing/{route_id}", json=data)
        return result

    async def delete_route(self, route_id: str) -> dict[str, Any]:
        """Delete a static route."""
        result: dict[str, Any] = await self.delete(f"rest/routing/{route_id}")
        return result

    async def update_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        """Update controller settings."""
        result: dict[str, Any] = await self.put("rest/setting", json=data)
        return result

    # ── Write methods: commands ────────────────────────────────────────

    async def run_speedtest(self) -> dict[str, Any]:
        """Initiate a speed test on the controller."""
        result: dict[str, Any] = await self.post("cmd/devmgr", json={"cmd": "speedtest"})
        return result

    async def create_backup(self) -> dict[str, Any]:
        """Create a controller backup.

        UniFi's ``cmd/backup`` endpoint can take several minutes on controllers
        with non-trivial configuration (see #89). Bumps the per-request timeout
        to 5 minutes so the call doesn't surface a spurious ``UniFiTimeoutError``
        before the backup actually completes.
        """
        result: dict[str, Any] = await self.post("cmd/backup", json={"cmd": "backup"}, timeout=300.0)
        return result

    async def restart_device(self, mac: str) -> dict[str, Any]:
        """Restart an adopted device."""
        result: dict[str, Any] = await self.post("cmd/devmgr", json={"cmd": "restart", "mac": mac})
        return result

    async def adopt_device(self, mac: str) -> dict[str, Any]:
        """Adopt a new device."""
        result: dict[str, Any] = await self.post("cmd/devmgr", json={"cmd": "adopt", "mac": mac})
        return result

    async def locate_device(self, mac: str) -> dict[str, Any]:
        """Enable the locate LED on a device."""
        result: dict[str, Any] = await self.post("cmd/devmgr", json={"cmd": "set-locate", "mac": mac})
        return result

    async def unlocate_device(self, mac: str) -> dict[str, Any]:
        """Disable the locate LED on a device."""
        result: dict[str, Any] = await self.post("cmd/devmgr", json={"cmd": "unset-locate", "mac": mac})
        return result

    async def provision_device(self, mac: str) -> dict[str, Any]:
        """Force provision a device."""
        result: dict[str, Any] = await self.post("cmd/devmgr", json={"cmd": "force-provision", "mac": mac})
        return result

    async def upgrade_device(self, mac: str) -> dict[str, Any]:
        """Upgrade a device to the latest firmware."""
        result: dict[str, Any] = await self.post("cmd/devmgr", json={"cmd": "upgrade", "mac": mac})
        return result

    async def power_cycle_port(self, mac: str, port_idx: int) -> dict[str, Any]:
        """Power cycle a PoE port on a switch."""
        result: dict[str, Any] = await self.post(
            "cmd/devmgr", json={"cmd": "power-cycle", "mac": mac, "port_idx": port_idx}
        )
        return result

    async def _assert_client_known(self, mac: str) -> None:
        """Raise UniFiNotFoundError if ``mac`` isn't in the controller's client list.

        The legacy ``cmd/stamgr`` endpoints (block-sta, unblock-sta,
        authorize-guest, unauthorize-guest) return HTTP 200 with
        ``meta.rc == "ok"`` regardless of whether the MAC corresponds to a
        real client, so an agent can't distinguish a real action from a
        silent no-op on a typo. Pre-check against ``list_all_clients``
        (active + historical) to surface a typed 404-style error instead.
        See #96.
        """
        response = await self.list_all_clients()
        known = {entry.get("mac", "").lower() for entry in response.get("data", [])}
        if mac.lower() not in known:
            raise UniFiNotFoundError(f"Client with MAC {mac} not found")

    async def block_client(self, mac: str) -> dict[str, Any]:
        """Block a client from connecting.

        Raises ``UniFiNotFoundError`` (→ ``ToolError: Resource not found``)
        when ``mac`` is unknown to the controller, rather than silently
        succeeding on a typo. See #96.
        """
        await self._assert_client_known(mac)
        result: dict[str, Any] = await self.post("cmd/stamgr", json={"cmd": "block-sta", "mac": mac})
        return result

    async def unblock_client(self, mac: str) -> dict[str, Any]:
        """Unblock a previously blocked client.

        Raises ``UniFiNotFoundError`` when ``mac`` is unknown (see #96).
        """
        await self._assert_client_known(mac)
        result: dict[str, Any] = await self.post("cmd/stamgr", json={"cmd": "unblock-sta", "mac": mac})
        return result

    async def kick_client(self, mac: str) -> dict[str, Any]:
        """Disconnect (kick) a client.

        The controller already validates this endpoint (returns
        ``api.err.UnknownStation`` on missing MAC), so no pre-check.
        """
        result: dict[str, Any] = await self.post("cmd/stamgr", json={"cmd": "kick-sta", "mac": mac})
        return result

    async def authorize_guest(self, mac: str, minutes: int = 60) -> dict[str, Any]:
        """Authorize a guest client for a given duration.

        Raises ``UniFiNotFoundError`` when ``mac`` is unknown (see #96).
        """
        await self._assert_client_known(mac)
        result: dict[str, Any] = await self.post(
            "cmd/stamgr", json={"cmd": "authorize-guest", "mac": mac, "minutes": minutes}
        )
        return result

    async def unauthorize_guest(self, mac: str) -> dict[str, Any]:
        """Revoke guest authorization.

        Raises ``UniFiNotFoundError`` when ``mac`` is unknown (see #96).
        """
        await self._assert_client_known(mac)
        result: dict[str, Any] = await self.post("cmd/stamgr", json={"cmd": "unauthorize-guest", "mac": mac})
        return result

    async def archive_events(self) -> dict[str, Any]:
        """Archive all alarms/events."""
        result: dict[str, Any] = await self.post("cmd/evtmgr", json={"cmd": "archive-all-alarms"})
        return result

    async def reset_dpi(self) -> dict[str, Any]:
        """Reset DPI counters."""
        result: dict[str, Any] = await self.post("cmd/stat", json={"cmd": "reset-dpi"})
        return result

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def validate_connection(self) -> bool:
        """Validate connectivity by fetching system info."""
        try:
            await self.get_sysinfo()
        except (UniFiError, httpx.HTTPError):
            logger.debug("Network API connection validation failed", exc_info=True)
            return False
        else:
            return True
