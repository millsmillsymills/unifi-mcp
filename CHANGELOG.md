# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-05-06

### Changed

- **Breaking — every MCP tool is now exposed under the `unifi_*` namespace.**
  `network_*` tools are renamed to `unifi_network_*`, `protect_*` tools to
  `unifi_protect_*`, and `site_manager_*` tools to `unifi_site_manager_*`.
  Update any client configuration or scripts that reference tools by name.
  This is the consistency-check audit's PROTO-002 requirement; see #165.

### Added

- `SECURITY.md` describing the private-disclosure path (#157, #162).
- `tests/unit/test_logging.py` and a structured stderr JSON logger
  (`unifi_mcp._logging`) so MCP stdio traffic on stdout stays uncorrupted
  (#163, #164).
- `tools._common.JsonObject` type alias used on every UniFi-payload
  parameter (#166).
- Args/Returns docstring sections on every `@mcp.tool` (#167).
- `py.typed` PEP 561 marker so downstream type checkers consume the
  package's annotations (#172).

### Changed

- `UniFiConfig.is_readwrite` renamed to `writes_enabled` (#169).
- The project type checker is now `ty` instead of `mypy` (#173).
- `__main__` and `clients/__init__` import `from __future__ import
  annotations` for consistency with the rest of the package (#175).
- `.gitignore` carries a literal `*.pyc` entry alongside the existing
  `*.py[cod]` glob (#158).

## [0.1.0] - Initial release

- 84 MCP tools across UniFi Network, Protect, and Site Manager.
- Read-only / read-write mode separation, gated by `UNIFI_MODE`.
- Graceful per-API degradation when a key is missing or unreachable.
- Strict typing, ruff lint + format, full unit + opt-in integration suites.
