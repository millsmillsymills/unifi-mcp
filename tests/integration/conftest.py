"""Shared fixtures for live-hardware integration tests.

All tests in this directory are tagged ``@pytest.mark.integration`` and
excluded from CI. Run them manually against a configured controller:

    uv run pytest tests/integration/ -v -m integration

Fixtures skip gracefully if the matching ``UNIFI_*_API`` env var is not set,
so a contributor with only Network credentials won't be forced to stub out
Protect / Site Manager.
"""

from __future__ import annotations

import os

import pytest

from unifi_mcp.clients.network import NetworkClient
from unifi_mcp.clients.protect import ProtectClient
from unifi_mcp.clients.site_manager import SiteManagerClient


def _network_host() -> str:
    return os.environ.get("UNIFI_NETWORK_HOST", "192.168.1.1")


def _network_port() -> int:
    return int(os.environ.get("UNIFI_NETWORK_PORT", "443"))


def _protect_host() -> str:
    return os.environ.get("UNIFI_PROTECT_HOST", _network_host())


def _protect_port() -> int:
    return int(os.environ.get("UNIFI_PROTECT_PORT", "443"))


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture
async def network_live_client():
    """Live NetworkClient. Skips if UNIFI_NETWORK_API is unset."""
    api_key = os.environ.get("UNIFI_NETWORK_API")
    if not api_key:
        pytest.skip("UNIFI_NETWORK_API not set; skipping live Network test")
    site = os.environ.get("UNIFI_NETWORK_SITE", "default")
    client = NetworkClient(
        base_url=f"https://{_network_host()}:{_network_port()}",
        api_key=api_key,
        site=site,
        verify_ssl=_bool_env("UNIFI_NETWORK_VERIFY_SSL"),
        timeout=int(os.environ.get("UNIFI_REQUEST_TIMEOUT", "30")),
        max_retries=int(os.environ.get("UNIFI_MAX_RETRIES", "3")),
    )
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture
async def protect_live_client():
    """Live ProtectClient. Skips if UNIFI_PROTECT_API is unset."""
    api_key = os.environ.get("UNIFI_PROTECT_API")
    if not api_key:
        pytest.skip("UNIFI_PROTECT_API not set; skipping live Protect test")
    client = ProtectClient(
        base_url=f"https://{_protect_host()}:{_protect_port()}",
        api_key=api_key,
        verify_ssl=_bool_env("UNIFI_PROTECT_VERIFY_SSL"),
        timeout=int(os.environ.get("UNIFI_REQUEST_TIMEOUT", "30")),
        max_retries=int(os.environ.get("UNIFI_MAX_RETRIES", "3")),
    )
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture
async def site_manager_live_client():
    """Live SiteManagerClient. Skips if UNIFI_SITE_MANAGER_API is unset."""
    api_key = os.environ.get("UNIFI_SITE_MANAGER_API")
    if not api_key:
        pytest.skip("UNIFI_SITE_MANAGER_API not set; skipping live Site Manager test")
    client = SiteManagerClient(
        api_key=api_key,
        timeout=int(os.environ.get("UNIFI_REQUEST_TIMEOUT", "30")),
        max_retries=int(os.environ.get("UNIFI_MAX_RETRIES", "3")),
    )
    try:
        yield client
    finally:
        await client.close()
