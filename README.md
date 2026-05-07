<p align="center">
  <img src="docs/assets/logo.png" alt="unifi-mcp logo" width="200" />
</p>

# unifi-mcp

Production-grade Python MCP server for UniFi Site Manager, Network, and Protect APIs.

## Status

**Under active development** — see [implementation plan](docs/plans/2026-04-16-001-feat-unifi-mcp-server-plan.md) for roadmap.

## Features

- **77 MCP tools** covering UniFi Network (59), Protect (15), and Site Manager (3) APIs
- **Read/write mode separation** — write tools invisible in readonly mode
- **Graceful per-API degradation** — only registers tools for configured APIs
- **Typed, linted, tested** — strict `ty`, `ruff`, `pytest` with CI across Python 3.11-3.13

## Quick Start

```bash
# Install from PyPI (once published)
uv pip install unifi-mcp

# Or install from source
git clone https://github.com/millsmillsymills/unifi-mcp.git
cd unifi-mcp
uv sync

# Configure
cp .env.example .env
# Edit .env with your UniFi API keys

# Run
unifi-mcp
```

## Configuration

See [.env.example](.env.example) for all configuration options.

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_MODE` | `readonly` | `readonly` or `readwrite` |
| `UNIFI_NETWORK_API` | — | Network API key |
| `UNIFI_PROTECT_API` | — | Protect API key |
| `UNIFI_SITE_MANAGER_API` | — | Site Manager cloud API key |

## Development

```bash
# Install with dev dependencies
uv sync --extra dev

# Lint and format
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Type check
uv run ty check src/unifi_mcp/

# Test
uv run pytest tests/unit/ -v

# Pre-commit hooks
uv run pre-commit install
```

## Known Issues

- **`protect_get_bootstrap` and `protect_list_events` always return 404** —
  [#130](https://github.com/millsmillsymills/unifi-mcp/issues/130). The
  Protect integration API at v1 does not expose `bootstrap` or `events`
  REST endpoints (verified against Protect 7.0.107). The tools are
  visible in the MCP tool list but every call returns
  `Resource not found: Entity 'endpoint' not found`. Decision on
  remove vs. WebSocket-based replacement tracked in #130.

- **Protect on a separate device requires explicit `UNIFI_PROTECT_HOST`** —
  [#107](https://github.com/millsmillsymills/unifi-mcp/issues/107). If your
  Protect NVR is on a different IP than your Network controller (common
  with UCK-G2-Plus + UDM/UCG setups), set `UNIFI_PROTECT_HOST` in `.env`.
  The default silently inherits `UNIFI_NETWORK_HOST`, which produces a
  startup WARN (`protect tools disabled`) and no `protect_*` entries in
  the tool list.

## License

Apache-2.0 — see [LICENSE](LICENSE).

## Trademarks

UniFi, UbiOS, and Ubiquiti are trademarks of Ubiquiti Inc. This project is an
independent, third-party MCP server and is not affiliated with, endorsed by, or
sponsored by Ubiquiti Inc. The repo logo (`docs/assets/logo.png`) is a stylized
8-bit derivative of Ubiquiti's UniFi access-point artwork, used here for
identification only.
