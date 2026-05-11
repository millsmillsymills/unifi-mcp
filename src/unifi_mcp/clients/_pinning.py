"""Certificate-pinning transport for httpx async clients.

UniFi controllers ship self-signed certs, so chain verification can't be used
out of the box. Disabling verification (``verify=False``) bypasses identity
entirely — anyone in the network path can present any cert and harvest the
``X-API-Key`` header. Pinning the SHA-256 fingerprint of the leaf cert
restores identity verification without requiring users to install a custom CA:
the operator captures the fingerprint once with ``openssl s_client`` and the
client refuses to talk to any other cert.

The pin replaces chain + hostname verification — that's the whole point of
pinning self-signed certs — so the ``ssl.SSLContext`` we hand to httpx still
has ``check_hostname=False`` and ``verify_mode=CERT_NONE``. After the TLS
handshake completes, ``handle_async_request`` reads the leaf DER from the
httpcore ``ssl_object`` extension, hashes it, and compares against the
configured pin. A mismatch closes the connection and raises
``UniFiAuthError`` so the agent sees an actionable, status-coded failure
instead of a confused HTTP error later.
"""

from __future__ import annotations

import hashlib
import ssl
from typing import Any

import httpx

from unifi_mcp.errors import UniFiAuthError


def build_pinning_ssl_context() -> ssl.SSLContext:
    """Build an ``ssl.SSLContext`` suitable for use with cert pinning.

    Chain + hostname verification are disabled because the pin replaces them
    (the cert is self-signed and the hostname may be a raw IP). The context
    still negotiates TLS normally; only the trust decision is deferred to
    the post-handshake fingerprint check.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fingerprint_of(der_bytes: bytes) -> str:
    """Return canonical SHA-256 fingerprint (64 lowercase hex chars) of a DER cert."""
    return hashlib.sha256(der_bytes).hexdigest()


class CertPinningTransport(httpx.AsyncHTTPTransport):
    """httpx async transport that enforces a SHA-256 leaf-cert pin.

    After each handled request, the underlying httpcore network stream is
    queried for its ``ssl_object``; the peer's leaf DER is hashed and
    compared against the configured pin. A mismatch raises
    ``UniFiAuthError`` and the response is discarded.

    The check runs once per *response*, not once per *connection* — keep-alive
    means subsequent requests reuse the same socket, and re-checking is cheap
    relative to any cost of letting a swapped cert sneak through.
    """

    def __init__(self, expected_fingerprint: str, **kwargs: Any) -> None:
        kwargs.setdefault("verify", build_pinning_ssl_context())
        super().__init__(**kwargs)
        self._expected_fingerprint = expected_fingerprint.lower()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await super().handle_async_request(request)
        self._verify_pin(response)
        return response

    def _verify_pin(self, response: httpx.Response) -> None:
        """Hash the peer leaf cert and compare against the configured pin.

        Raises ``UniFiAuthError`` if the cert is missing (which would mean a
        plaintext connection got through somehow) or if its fingerprint
        doesn't match. The error message includes both fingerprints so the
        operator can either correct the pin or investigate the swap.
        """
        stream = response.extensions.get("network_stream")
        ssl_object = stream.get_extra_info("ssl_object") if stream is not None else None
        if ssl_object is None:
            raise UniFiAuthError(
                "cert pin configured but TLS layer exposed no ssl_object; "
                "refusing to send API key over an unverified connection",
                status_code=None,
            )
        der = ssl_object.getpeercert(binary_form=True)
        if not der:
            raise UniFiAuthError(
                "cert pin configured but peer presented no certificate; "
                "refusing to send API key over an unverified connection",
                status_code=None,
            )
        actual = fingerprint_of(der)
        if actual != self._expected_fingerprint:
            raise UniFiAuthError(
                f"TLS cert pin mismatch: expected sha256={self._expected_fingerprint}, "
                f"got sha256={actual}. Update UNIFI_*_CERT_FINGERPRINT or investigate "
                f"why the controller's cert changed.",
                status_code=None,
            )
