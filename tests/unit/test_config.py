"""Tests for UniFi MCP configuration."""

import logging

import pytest
from pydantic import ValidationError

from unifi_mcp.config import UniFiConfig, UniFiMode
from unifi_mcp.errors import (
    UniFiAuthError,
    UniFiConnectionError,
    UniFiError,
    UniFiNotFoundError,
    UniFiRateLimitError,
    UniFiReadOnlyError,
    handle_client_error,
)


class TestUniFiMode:
    def test_readonly_is_default(self):
        config = UniFiConfig(
            _env_file=None,
            unifi_network_api=None,
        )
        assert config.unifi_mode == UniFiMode.READONLY

    def test_readwrite_mode(self):
        config = UniFiConfig(
            _env_file=None,
            unifi_mode=UniFiMode.READWRITE,
        )
        assert config.unifi_mode == UniFiMode.READWRITE
        assert config.is_readwrite is True

    def test_readonly_mode_property(self):
        config = UniFiConfig(
            _env_file=None,
            unifi_mode=UniFiMode.READONLY,
        )
        assert config.is_readwrite is False

    def test_invalid_mode_raises_validation_error(self):
        with pytest.raises(ValidationError):
            UniFiConfig(_env_file=None, unifi_mode="invalid")


class TestAPIEnabled:
    def test_network_enabled_when_api_key_set(self):
        config = UniFiConfig(_env_file=None, unifi_network_api="test-key")
        assert config.network_enabled is True

    def test_network_disabled_when_no_api_key(self):
        config = UniFiConfig(_env_file=None, unifi_network_api=None)
        assert config.network_enabled is False

    def test_protect_enabled_when_api_key_set(self):
        config = UniFiConfig(_env_file=None, unifi_protect_api="test-key")
        assert config.protect_enabled is True

    def test_protect_disabled_when_no_api_key(self):
        config = UniFiConfig(_env_file=None, unifi_protect_api=None)
        assert config.protect_enabled is False

    def test_site_manager_enabled_when_api_key_set(self):
        config = UniFiConfig(_env_file=None, unifi_site_manager_api="test-key")
        assert config.site_manager_enabled is True

    def test_site_manager_disabled_when_no_api_key(self):
        config = UniFiConfig(_env_file=None, unifi_site_manager_api=None)
        assert config.site_manager_enabled is False


class TestDefaults:
    def test_default_network_host(self):
        config = UniFiConfig(_env_file=None)
        assert config.unifi_network_host == "192.168.1.1"

    def test_default_network_port(self):
        config = UniFiConfig(_env_file=None)
        assert config.unifi_network_port == 443

    def test_default_network_site(self):
        config = UniFiConfig(_env_file=None)
        assert config.unifi_network_site == "default"

    def test_protect_host_defaults_to_network_host(self):
        config = UniFiConfig(_env_file=None, unifi_network_host="10.0.0.1")
        assert config.unifi_protect_host == "10.0.0.1"

    def test_protect_host_independent_when_set(self):
        config = UniFiConfig(
            _env_file=None,
            unifi_network_host="10.0.0.1",
            unifi_protect_host="10.0.0.2",
        )
        assert config.unifi_protect_host == "10.0.0.2"

    def test_protect_host_default_logs_info_when_api_key_set(self, caplog):
        """When the Protect host default fires and Protect is enabled, emit an
        INFO log so the operator can catch the split-host misconfig.
        """
        with caplog.at_level(logging.INFO, logger="unifi_mcp.config"):
            config = UniFiConfig(
                _env_file=None,
                unifi_network_host="10.0.0.1",
                unifi_protect_api="k",
            )
        assert config.unifi_protect_host == "10.0.0.1"
        matching = [
            r for r in caplog.records if r.levelno == logging.INFO and "UNIFI_PROTECT_HOST not set" in r.getMessage()
        ]
        assert matching, f"expected INFO log about Protect host default; got {caplog.records!r}"
        assert "10.0.0.1" in matching[0].getMessage()

    def test_protect_host_default_silent_when_api_key_unset(self, caplog):
        """When Protect isn't configured, the host default must not log — the
        fallback is inconsequential because Protect tools won't register.
        """
        with caplog.at_level(logging.INFO, logger="unifi_mcp.config"):
            config = UniFiConfig(_env_file=None, unifi_network_host="10.0.0.1")
        assert config.unifi_protect_host == "10.0.0.1"
        assert not [r for r in caplog.records if "UNIFI_PROTECT_HOST not set" in r.getMessage()], (
            "host-default log should only fire when UNIFI_PROTECT_API is set"
        )

    def test_protect_host_default_silent_when_host_explicit(self, caplog):
        """When the operator set UNIFI_PROTECT_HOST explicitly, no default
        fires and no log is emitted even if the value happens to match the
        Network host.
        """
        with caplog.at_level(logging.INFO, logger="unifi_mcp.config"):
            UniFiConfig(
                _env_file=None,
                unifi_network_host="10.0.0.1",
                unifi_protect_host="10.0.0.1",
                unifi_protect_api="k",
            )
        assert not [r for r in caplog.records if "UNIFI_PROTECT_HOST not set" in r.getMessage()]

    def test_default_timeout(self):
        config = UniFiConfig(_env_file=None)
        assert config.unifi_request_timeout == 30

    def test_default_max_retries(self):
        config = UniFiConfig(_env_file=None)
        assert config.unifi_max_retries == 3

    def test_default_verify_ssl_false(self):
        config = UniFiConfig(_env_file=None)
        assert config.unifi_network_verify_ssl is False
        assert config.unifi_protect_verify_ssl is False


class TestBaseURLs:
    def test_network_base_url(self):
        config = UniFiConfig(_env_file=None, unifi_network_host="10.0.0.1", unifi_network_port=8443)
        assert config.network_base_url == "https://10.0.0.1:8443"

    def test_protect_base_url(self):
        config = UniFiConfig(_env_file=None, unifi_protect_host="10.0.0.2", unifi_protect_port=7443)
        assert config.protect_base_url == "https://10.0.0.2:7443"


class TestFieldConstraints:
    def test_network_port_zero_raises_validation_error(self):
        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            UniFiConfig(_env_file=None, unifi_network_port=0)

    def test_network_port_above_max_raises_validation_error(self):
        with pytest.raises(ValidationError, match="less than or equal to 65535"):
            UniFiConfig(_env_file=None, unifi_network_port=65536)

    def test_protect_port_zero_raises_validation_error(self):
        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            UniFiConfig(_env_file=None, unifi_protect_port=0)

    def test_request_timeout_zero_raises_validation_error(self):
        with pytest.raises(ValidationError, match="greater than 0"):
            UniFiConfig(_env_file=None, unifi_request_timeout=0)

    def test_request_timeout_negative_raises_validation_error(self):
        with pytest.raises(ValidationError, match="greater than 0"):
            UniFiConfig(_env_file=None, unifi_request_timeout=-5)

    def test_max_retries_negative_raises_validation_error(self):
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            UniFiConfig(_env_file=None, unifi_max_retries=-1)

    def test_max_retries_zero_accepted(self):
        config = UniFiConfig(_env_file=None, unifi_max_retries=0)
        assert config.unifi_max_retries == 0


class TestHandleClientError:
    def test_auth_error_mapping(self):
        with pytest.raises(Exception, match="Authentication failed"):
            handle_client_error(UniFiAuthError("Invalid API key", status_code=401))

    def test_not_found_error_mapping(self):
        with pytest.raises(Exception, match="Resource not found"):
            handle_client_error(UniFiNotFoundError("Device xyz not found", status_code=404))

    def test_rate_limit_error_mapping(self):
        with pytest.raises(Exception, match="Rate limit exceeded"):
            handle_client_error(UniFiRateLimitError("Too many requests", status_code=429))

    def test_connection_error_mapping(self):
        with pytest.raises(Exception, match="Connection failed"):
            handle_client_error(UniFiConnectionError("Timeout"))

    def test_readonly_error_mapping(self):
        with pytest.raises(Exception, match="Write operation blocked"):
            handle_client_error(UniFiReadOnlyError("Cannot create WLAN"))

    def test_generic_unifi_error_mapping(self):
        with pytest.raises(Exception, match="UniFi API error"):
            handle_client_error(UniFiError("Something went wrong", status_code=500))

    def test_unexpected_error_mapping(self):
        with pytest.raises(Exception, match="Unexpected error"):
            handle_client_error(RuntimeError("Boom"))

    def test_cancelled_error_is_reraised_not_wrapped(self):
        """asyncio.CancelledError must propagate so FastMCP can honor
        cancellation. Wrapping it as ToolError would turn a cancel into
        a phantom tool failure.
        """
        import asyncio

        cancel = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError) as exc_info:
            handle_client_error(cancel)
        # The exact exception object should propagate, not a new one.
        assert exc_info.value is cancel
