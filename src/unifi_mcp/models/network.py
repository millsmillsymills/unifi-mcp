"""Pydantic models for UniFi Network API responses."""

from __future__ import annotations

from unifi_mcp.models.common import UniFiBaseModel


class NetworkDevice(UniFiBaseModel):
    """An adopted network device (AP, switch, gateway, etc.)."""

    _id: str | None = None
    mac: str | None = None
    model: str | None = None
    type: str | None = None
    name: str | None = None
    ip: str | None = None
    state: int | None = None
    adopted: bool | None = None
    version: str | None = None
    uptime: int | None = None


class NetworkClient(UniFiBaseModel):
    """A network client (wired or wireless)."""

    _id: str | None = None
    mac: str | None = None
    hostname: str | None = None
    ip: str | None = None
    name: str | None = None
    oui: str | None = None
    network: str | None = None
    is_wired: bool | None = None
    is_guest: bool | None = None
    tx_bytes: int | None = None
    rx_bytes: int | None = None
    uptime: int | None = None


class WlanConfig(UniFiBaseModel):
    """A WLAN (wireless network) configuration."""

    _id: str | None = None
    name: str | None = None
    enabled: bool | None = None
    security: str | None = None
    wpa_mode: str | None = None
    is_guest: bool | None = None


class FirewallRule(UniFiBaseModel):
    """A firewall rule."""

    _id: str | None = None
    name: str | None = None
    enabled: bool | None = None
    ruleset: str | None = None
    action: str | None = None
    src_address: str | None = None
    dst_address: str | None = None
    protocol: str | None = None


class FirewallGroup(UniFiBaseModel):
    """A firewall address or port group."""

    _id: str | None = None
    name: str | None = None
    group_type: str | None = None
    group_members: list[str] | None = None


class NetworkConfig(UniFiBaseModel):
    """A network (VLAN/subnet) configuration."""

    _id: str | None = None
    name: str | None = None
    purpose: str | None = None
    subnet: str | None = None
    vlan: int | None = None
    enabled: bool | None = None
    dhcpd_enabled: bool | None = None


class PortForwardRule(UniFiBaseModel):
    """A port forwarding rule."""

    _id: str | None = None
    name: str | None = None
    enabled: bool | None = None
    src: str | None = None
    dst_port: str | None = None
    fwd: str | None = None
    fwd_port: str | None = None
    proto: str | None = None


class StaticRoute(UniFiBaseModel):
    """A static route configuration."""

    _id: str | None = None
    name: str | None = None
    enabled: bool | None = None
    type: str | None = None
    network: str | None = None
    gateway_ip: str | None = None
    interface: str | None = None
