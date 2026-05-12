"""Secret-redaction helper shared by clients (error bodies) and tools (responses).

`clients/base.py` calls this to scrub the JSON parsed from upstream 4xx
bodies before they reach the agent (#148). The tool layer calls it from
read-mode read tools so PSKs / RADIUS secrets / SSO tokens never leave
the server in cleartext (#146). Write tools deliberately do **not** scrub
because the controller needs the cleartext values for round-trip writes.
"""

from __future__ import annotations

from typing import Any

SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "x_passphrase",
        "x_password",
        "password",
        "passphrase",
        "radius_secret",
        "wpa_psk",
        "private_key",
        "ssotoken",
        "bearer",
        "token",
        "api_key",
        "apikey",
        "secret",
    }
)

REDACTED = "***REDACTED***"


def _is_sensitive_key(lowered: str) -> bool:
    if lowered in SENSITIVE_KEYS:
        return True
    return lowered.startswith("super_") and (lowered.endswith("_password") or lowered.endswith("_url"))


def redact_secrets(value: Any) -> Any:
    """Return a deep copy of ``value`` with sensitive keys replaced.

    Recursively walks dicts and lists. Dict-key match is case-insensitive.
    Also matches ``super_*_password`` and ``super_*_url`` callback keys
    that have historically leaked controller config. Non-container values
    pass through untouched. Input is not mutated.
    """
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, sub in value.items():
            key_str = str(key)
            if _is_sensitive_key(key_str.lower()):
                redacted[key_str] = REDACTED
            else:
                redacted[key_str] = redact_secrets(sub)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value
