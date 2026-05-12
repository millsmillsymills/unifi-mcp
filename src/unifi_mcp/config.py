"""Configuration management for UniFi MCP server using pydantic-settings."""

from __future__ import annotations

import concurrent.futures
import enum
import ipaddress
import logging
import re
import socket

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# Cap DNS resolution so a bad host can't hang startup. Two seconds is enough
# for LAN lookups and short enough that a misconfigured host fails fast.
_DNS_LOOKUP_TIMEOUT_S = 2.0

# Canonical fingerprint form: 64 lowercase hex chars, no separators. The
# accepted input form additionally allows colon separators and any case.
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


def _normalize_fingerprint(raw: str) -> str:
    """Return canonical sha256 fingerprint (64 lowercase hex chars, no colons).

    Accepts the openssl output form (``aa:bb:...``) and the colon-stripped
    form, in any case. Raises ``ValueError`` for anything that doesn't
    contain exactly 64 hex digits.
    """
    stripped = raw.replace(":", "").strip().lower()
    if not _FINGERPRINT_RE.match(stripped):
        raise ValueError(
            f"expected sha256 fingerprint as 64 hex chars (colons optional, case-insensitive); got {raw!r}"
        )
    return stripped


class UniFiMode(enum.StrEnum):
    """Server operation mode."""

    READONLY = "readonly"
    READWRITE = "readwrite"


class UniFiConfig(BaseSettings):
    """Configuration loaded from environment variables and .env file."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Mode
    unifi_mode: UniFiMode = UniFiMode.READONLY

    # Network API
    unifi_network_host: str = "192.168.1.1"
    unifi_network_port: int = Field(default=443, ge=1, le=65535)
    unifi_network_api: SecretStr | None = None
    unifi_network_site: str = "default"
    unifi_network_verify_ssl: bool = False
    unifi_network_cert_fingerprint: str | None = None

    # Protect API
    unifi_protect_host: str | None = None
    unifi_protect_port: int = Field(default=443, ge=1, le=65535)
    unifi_protect_api: SecretStr | None = None
    unifi_protect_verify_ssl: bool = False
    unifi_protect_cert_fingerprint: str | None = None

    # Site Manager API
    unifi_site_manager_api: SecretStr | None = None

    # General
    unifi_request_timeout: int = Field(default=30, gt=0)
    unifi_max_retries: int = Field(default=3, ge=0)
    # Cap raw-byte responses to keep a malicious or misconfigured request
    # from OOMing the server. Video exports and snapshots have very different
    # expected-size distributions (exports: tens to hundreds of MB; snapshots:
    # single MB), so they get independent caps.
    unifi_max_export_bytes: int = Field(default=500 * 1024 * 1024, gt=0)
    unifi_max_snapshot_bytes: int = Field(default=50 * 1024 * 1024, gt=0)

    @field_validator("unifi_network_cert_fingerprint", "unifi_protect_cert_fingerprint", mode="before")
    @classmethod
    def _validate_fingerprint(cls, value: object) -> str | None:
        """Reject malformed fingerprints at load time.

        Empty/blank strings normalize to ``None`` so an unset env var doesn't
        trip the validator. Non-string non-None values raise.
        """
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("fingerprint must be a string")
        if not value.strip():
            return None
        return _normalize_fingerprint(value)

    @model_validator(mode="after")
    def _default_protect_host(self) -> UniFiConfig:
        """Default Protect host to Network host when not explicitly set.

        WARNING: on deployments where Protect runs on a separate NVR (e.g.
        UCK-G2-Plus on a different IP from the gateway), leaving
        ``UNIFI_PROTECT_HOST`` unset points Protect at the wrong device.
        ``validate_connection`` then fails, and all Protect tools deregister
        at startup. See #104 for the lifespan-level diagnostic.

        When the fallback fires *and* a Protect API key is configured, emit
        an INFO log so the operator can see that the default was applied and
        decide whether it matches their topology.
        """
        if self.unifi_protect_host is None:
            if self.unifi_protect_api is not None:
                logger.info(
                    "UNIFI_PROTECT_HOST not set; defaulting to UNIFI_NETWORK_HOST=%s. "
                    "If Protect runs on a different device (e.g. a separate UCK NVR), "
                    "set UNIFI_PROTECT_HOST explicitly to avoid a silent "
                    "validate_connection failure.",
                    self.unifi_network_host,
                )
            self.unifi_protect_host = self.unifi_network_host
        return self

    @model_validator(mode="after")
    def _audit_tls_posture(self) -> UniFiConfig:
        """Warn at startup when an API key is sent over unverified TLS.

        Three log lines per affected service:

        1. Unconditional WARN when ``verify_ssl=False`` and no pin is set —
           the API key is shipped over a connection with no identity check.
        2. Additional WARN when the host resolves to a non-private IP — the
           MITM exposure isn't limited to a hostile LAN.
        3. Soft WARN if DNS resolution fails so we don't crash startup; the
           operator still gets a visible note that the safety check didn't run.

        Pinning (``*_cert_fingerprint``) suppresses both 1 and 2 because the
        pin provides identity even with chain/hostname verification disabled.
        Services without an API key are skipped — their tools never register,
        so the warning would be noise.
        """
        if self.unifi_network_api is not None:
            self._audit_service_tls(
                "Network",
                host=self.unifi_network_host,
                verify_ssl=self.unifi_network_verify_ssl,
                fingerprint=self.unifi_network_cert_fingerprint,
            )
        if self.unifi_protect_api is not None:
            self._audit_service_tls(
                "Protect",
                host=self.unifi_protect_host or self.unifi_network_host,
                verify_ssl=self.unifi_protect_verify_ssl,
                fingerprint=self.unifi_protect_cert_fingerprint,
            )
        return self

    @staticmethod
    def _audit_service_tls(service: str, *, host: str, verify_ssl: bool, fingerprint: str | None) -> None:
        """Emit the TLS-posture WARNs for one service. See ``_audit_tls_posture``."""
        if verify_ssl or fingerprint is not None:
            return
        logger.warning(
            "verify_ssl=False for %s; API key is sent over unverified TLS to %s",
            service,
            host,
        )
        try:
            resolved = _resolve_host(host)
        except (OSError, ValueError) as exc:
            logger.warning(
                "could not resolve %s host %r for TLS safety check (%s); skipping non-private check",
                service,
                host,
                exc,
            )
            return
        if not (resolved.is_private or resolved.is_loopback or resolved.is_link_local):
            logger.warning(
                "verify_ssl=False with non-private host %s (resolved to %s) for %s — "
                "X-API-Key exposed to MITM. Set UNIFI_%s_VERIFY_SSL=true or pin the "
                "cert via UNIFI_%s_CERT_FINGERPRINT.",
                host,
                resolved,
                service,
                service.upper(),
                service.upper(),
            )

    @property
    def writes_enabled(self) -> bool:
        """Whether write tools are enabled.

        True only when ``UNIFI_MODE=readwrite`` is set explicitly. The default
        ``readonly`` mode leaves the server in a safe, mutation-free posture.
        """
        return self.unifi_mode == UniFiMode.READWRITE

    @property
    def network_enabled(self) -> bool:
        """Whether Network API is configured."""
        return self.unifi_network_api is not None

    @property
    def protect_enabled(self) -> bool:
        """Whether Protect API is configured."""
        return self.unifi_protect_api is not None

    @property
    def site_manager_enabled(self) -> bool:
        """Whether Site Manager API is configured."""
        return self.unifi_site_manager_api is not None

    @property
    def network_base_url(self) -> str:
        """Base URL for Network API."""
        return f"https://{self.unifi_network_host}:{self.unifi_network_port}"

    @property
    def protect_base_url(self) -> str:
        """Base URL for Protect API."""
        host = self.unifi_protect_host or self.unifi_network_host
        return f"https://{host}:{self.unifi_protect_port}"


def _resolve_host(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Resolve ``host`` to an IP address with a bounded DNS timeout.

    Numeric hosts (IPv4 or IPv6 literals) short-circuit DNS entirely. For
    names, ``socket.gethostbyname`` runs on a worker thread bounded by
    ``_DNS_LOOKUP_TIMEOUT_S`` so a slow or unreachable resolver can't hang
    startup. Bounding via thread (rather than ``socket.setdefaulttimeout``)
    avoids mutating process-global socket state. Raises ``OSError`` (incl.
    ``socket.gaierror``) on lookup failure or timeout, or ``ValueError`` if
    the result isn't a valid IP literal.
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    with concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="unifi-dns") as pool:
        future = pool.submit(socket.gethostbyname, host)
        try:
            resolved = future.result(timeout=_DNS_LOOKUP_TIMEOUT_S)
        except concurrent.futures.TimeoutError as exc:
            raise OSError(f"DNS lookup for {host!r} exceeded {_DNS_LOOKUP_TIMEOUT_S}s timeout") from exc
    return ipaddress.ip_address(resolved)
