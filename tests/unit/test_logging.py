"""Tests for unifi_mcp._logging."""

from __future__ import annotations

import json
import logging
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from unifi_mcp._logging import JSONFormatter, configure_logging


@pytest.fixture(autouse=True)
def _reset_root_logger() -> Iterator[None]:
    saved_handlers = list(logging.root.handlers)
    saved_level = logging.root.level
    saved_fastmcp_handlers = list(logging.getLogger("fastmcp").handlers)
    saved_fastmcp_propagate = logging.getLogger("fastmcp").propagate
    yield
    logging.root.handlers = saved_handlers
    logging.root.setLevel(saved_level)
    fastmcp = logging.getLogger("fastmcp")
    fastmcp.handlers = saved_fastmcp_handlers
    fastmcp.propagate = saved_fastmcp_propagate


def _format_record(**kwargs: object) -> dict[str, object]:
    record = logging.LogRecord(
        name=str(kwargs.get("name", "unifi_mcp.test")),
        level=int(kwargs.get("level", logging.INFO)),
        pathname=str(kwargs.get("pathname", "test.py")),
        lineno=int(kwargs.get("lineno", 1)),
        msg=str(kwargs.get("msg", "hello")),
        args=kwargs.get("args"),
        exc_info=kwargs.get("exc_info"),
    )
    extra = kwargs.get("extra")
    if isinstance(extra, dict):
        for k, v in extra.items():
            setattr(record, k, v)
    return json.loads(JSONFormatter().format(record))


def test_format_emits_required_fields() -> None:
    payload = _format_record()
    assert payload["level"] == "INFO"
    assert payload["logger"] == "unifi_mcp.test"
    assert payload["message"] == "hello"
    assert "timestamp" in payload


def test_format_renders_args_into_message() -> None:
    payload = _format_record(msg="user %s", args=("alice",))
    assert payload["message"] == "user alice"


def test_format_includes_extra_fields() -> None:
    payload = _format_record(extra={"request_id": "abc-123"})
    assert payload["request_id"] == "abc-123"


def test_format_extras_cannot_overwrite_canonical_fields() -> None:
    payload = _format_record(
        extra={"level": "BOGUS", "timestamp": "1970-01-01", "logger": "fake", "message": "fake"},
    )
    assert payload["level"] == "INFO"
    assert payload["logger"] == "unifi_mcp.test"
    assert payload["message"] == "hello"
    assert payload["timestamp"] != "1970-01-01"


def test_format_serializes_exception() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()
    payload = _format_record(level=logging.ERROR, msg="failure", exc_info=exc_info)
    assert "exc_info" in payload
    assert "ValueError" in str(payload["exc_info"])


def test_format_handles_non_json_serializable_extras() -> None:
    payload = _format_record(extra={"items": {1, 2, 3}})
    assert "items" in payload


def test_format_skips_underscore_prefixed_attrs() -> None:
    payload = _format_record(extra={"_private": "secret"})
    assert "_private" not in payload


def test_configure_logging_installs_stderr_handler() -> None:
    configure_logging("DEBUG")
    assert logging.root.level == logging.DEBUG
    assert len(logging.root.handlers) == 1
    handler = logging.root.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.stream is sys.stderr
    assert isinstance(handler.formatter, JSONFormatter)


def test_configure_logging_is_idempotent() -> None:
    configure_logging("DEBUG")
    first_handler = logging.root.handlers[0]
    configure_logging("DEBUG")
    assert len(logging.root.handlers) == 1
    assert logging.root.handlers[0] is not first_handler


def test_configure_logging_default_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNIFI_LOG_LEVEL", raising=False)
    configure_logging()
    assert logging.root.level == logging.INFO


def test_configure_logging_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFI_LOG_LEVEL", "warning")
    configure_logging()
    assert logging.root.level == logging.WARNING


def test_configure_logging_arg_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFI_LOG_LEVEL", "WARNING")
    configure_logging("DEBUG")
    assert logging.root.level == logging.DEBUG


def test_configure_logging_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFI_LOG_LEVEL", "  warning  ")
    configure_logging()
    assert logging.root.level == logging.WARNING


def test_configure_logging_falls_back_on_invalid_level(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("UNIFI_LOG_LEVEL", "BOGUS")
    configure_logging()
    assert logging.root.level == logging.INFO
    err = capsys.readouterr().err
    assert "BOGUS" in err
    assert "INFO" in err


def test_configure_logging_redirects_fastmcp_logger() -> None:
    fastmcp = logging.getLogger("fastmcp")
    fastmcp.addHandler(logging.NullHandler())
    fastmcp.propagate = False
    configure_logging("INFO")
    assert fastmcp.handlers == []
    assert fastmcp.propagate is True
