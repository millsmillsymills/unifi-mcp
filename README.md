# unifi-mcp

Production-grade Python MCP server for UniFi Site Manager, Network, and Protect APIs.

## Status

**Under active development** — see [implementation plan](docs/plans/2026-04-16-001-feat-unifi-mcp-server-plan.md) for roadmap.

## Features

- **77 MCP tools** covering UniFi Network (59), Protect (15), and Site Manager (3) APIs
- **Read/write mode separation** — write tools invisible in readonly mode
- **Graceful per-API degradation** — only registers tools for configured APIs
- **Production-ready** — typed, tested, linted, published to PyPI

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
uv run mypy src/unifi_mcp/

# Test
uv run pytest tests/unit/ -v

# Pre-commit hooks
uv run pre-commit install
```

## License

Apache-2.0 — see [LICENSE](LICENSE).
