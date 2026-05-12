"""Unit tests for ``unifi_mcp._redaction.redact_secrets``."""

from __future__ import annotations

import pytest

from unifi_mcp._redaction import REDACTED, SENSITIVE_KEYS, redact_secrets


class TestRedactSecretsLeaf:
    def test_passes_through_non_containers(self):
        assert redact_secrets("plain") == "plain"
        assert redact_secrets(42) == 42
        assert redact_secrets(None) is None
        assert redact_secrets(True) is True

    def test_returns_redacted_for_sensitive_top_level_key(self):
        out = redact_secrets({"x_passphrase": "hunter2"})
        assert out == {"x_passphrase": REDACTED}

    def test_leaves_safe_keys_alone(self):
        payload = {"name": "guest", "enabled": True}
        assert redact_secrets(payload) == payload


class TestRedactSecretsRecursion:
    def test_redacts_nested_dict(self):
        payload = {"wlan": {"name": "g", "x_passphrase": "pw"}}
        assert redact_secrets(payload) == {"wlan": {"name": "g", "x_passphrase": REDACTED}}

    def test_redacts_inside_list_of_dicts(self):
        payload = {"data": [{"radius_secret": "s1"}, {"radius_secret": "s2"}]}
        out = redact_secrets(payload)
        assert out == {"data": [{"radius_secret": REDACTED}, {"radius_secret": REDACTED}]}

    def test_redacts_lists_of_lists(self):
        payload = [[{"token": "t"}], [{"name": "ok"}]]
        assert redact_secrets(payload) == [[{"token": REDACTED}], [{"name": "ok"}]]


class TestRedactSecretsKeyMatching:
    @pytest.mark.parametrize(
        "key",
        ["x_passphrase", "X_Passphrase", "X_PASSPHRASE", "Password", "PASSWORD"],
    )
    def test_case_insensitive_match(self, key):
        out = redact_secrets({key: "v"})
        assert out[key] == REDACTED

    @pytest.mark.parametrize(
        "key",
        [
            "super_smtp_password",
            "super_identity_password",
            "super_mgmt_url",
            "super_identity_url",
            "SUPER_SMTP_URL",
        ],
    )
    def test_super_wildcard_password_and_url(self, key):
        out = redact_secrets({key: "v"})
        assert out[key] == REDACTED

    def test_super_prefix_without_password_or_url_suffix_is_safe(self):
        out = redact_secrets({"super_mgmt_key": "v", "super_name": "g"})
        assert out == {"super_mgmt_key": "v", "super_name": "g"}

    def test_all_sensitive_keys_redacted(self):
        payload = {k: f"val-{k}" for k in SENSITIVE_KEYS}
        out = redact_secrets(payload)
        for k in SENSITIVE_KEYS:
            assert out[k] == REDACTED


class TestRedactSecretsProperties:
    def test_does_not_mutate_input(self):
        original = {"x_passphrase": "pw", "nested": {"token": "t"}}
        before = {"x_passphrase": "pw", "nested": {"token": "t"}}
        _ = redact_secrets(original)
        assert original == before

    def test_idempotent(self):
        payload = {"x_passphrase": "pw", "nested": {"token": "t", "name": "g"}}
        once = redact_secrets(payload)
        twice = redact_secrets(once)
        assert once == twice

    def test_realistic_wlan_list_payload(self):
        """Snapshot test against a realistic UniFi list_wlans shape."""
        payload = {
            "meta": {"rc": "ok"},
            "data": [
                {
                    "_id": "abc",
                    "name": "Home",
                    "enabled": True,
                    "security": "wpapsk",
                    "x_passphrase": "supersecret",
                    "wpa_mode": "wpa2",
                    "radius_secret": "radius-secret",
                    "guest_portal": {"x_password": "portal-pw"},
                },
                {
                    "_id": "def",
                    "name": "Guest",
                    "x_passphrase": "another",
                },
            ],
        }
        out = redact_secrets(payload)
        assert out["data"][0]["x_passphrase"] == REDACTED
        assert out["data"][0]["radius_secret"] == REDACTED
        assert out["data"][0]["guest_portal"]["x_password"] == REDACTED
        assert out["data"][1]["x_passphrase"] == REDACTED
        # Safe fields untouched
        assert out["data"][0]["name"] == "Home"
        assert out["data"][0]["security"] == "wpapsk"
        assert out["meta"] == {"rc": "ok"}
