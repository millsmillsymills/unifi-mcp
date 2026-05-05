# CLAUDE.md — Project Intelligence for unifi-mcp

## Project Overview

Production-grade Python MCP server for UniFi Site Manager, Network, and Protect APIs. Published to PyPI as `unifi-mcp`. Uses FastMCP framework with declarative read/write mode separation and graceful per-API degradation.

## Commands

```bash
# Install (development)
uv sync --extra dev

# Lint
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Type check
uv run mypy src/unifi_mcp/

# Test (unit only, excludes integration)
uv run pytest tests/unit/ -v

# Test with coverage
uv run pytest tests/unit/ --cov=unifi_mcp --cov-report=term-missing -m "not integration"

# Integration tests (requires live UniFi hardware)
uv run pytest tests/integration/ -v -m integration

# Security scan
uv run bandit -r src/unifi_mcp/ -c pyproject.toml

# Pre-commit hooks
uv run pre-commit run --all-files

# Build package
uv build
```

## Architecture

```
src/unifi_mcp/
├── __init__.py          # Package root, exports __version__
├── __main__.py          # Entry point: creates and runs server
├── server.py            # FastMCP server creation + lifespan
├── config.py            # Pydantic settings (env vars)
├── errors.py            # Exception hierarchy + error mapping
├── clients/             # API clients (httpx async)
│   ├── base.py          # BaseUniFiClient with retry/auth/error mapping
│   ├── network.py       # Network API client
│   ├── protect.py       # Protect API client
│   └── site_manager.py  # Site Manager API client
└── tools/               # MCP tool definitions
    ├── network/         # 24 read + 35 write tools (59 total)
    ├── protect/         # 11 read + 4 write tools (15 total, includes 2 media read tools)
    │                    # NOTE: 2 of 11 read tools (protect_get_bootstrap,
    │                    # protect_list_events) always return 404 against the
    │                    # integration API. Tracked in #130.
    └── site_manager/    # 3 read-only tools
```

## Conventions

- **Python >=3.11**, strict mypy, ruff for lint+format
- **Line length**: 120 characters
- **Tool naming**: `{api}_{verb}_{entity}` (e.g., `network_list_devices`, `protect_get_snapshot`)
- **Write tools**: Tagged with `{"write"}`, annotated with `readOnlyHint=False`. Disabled in readonly mode via `mcp.disable(tags={"write"})`
- **Defense-in-depth**: Write tools also check `config.is_readwrite` at runtime
- **Clients**: Use `httpx.AsyncClient` with `tenacity` retry (3 attempts, exponential backoff). API responses flow through as `dict[str, Any]` — there is no Pydantic validation layer between clients and tools.
- **Error mapping**: API errors -> typed exceptions -> `ToolError` with agent-readable messages
- **Tests**: Use `respx` for HTTP mocking, `pytest-asyncio` for async tests
- **No print statements**: Use `logging` module (enforced by ruff T20 rule)

## Key Patterns

### Mode Gating
```python
# Tools tagged with {"write"} are disabled in readonly mode
@mcp.tool(tags={"write"}, annotations={"readOnlyHint": False})
async def network_create_wlan(...): ...

# In server lifespan:
if not config.is_readwrite:
    mcp.disable(tags={"write"})
```

### Graceful Degradation
```python
# Only register tools for APIs with configured keys
if config.network_enabled:
    register_network_tools(mcp)
if config.protect_enabled:
    register_protect_tools(mcp)
```

## CI/CD

- **CI**: Runs on push to main and PRs. Lint (ruff) + typecheck (mypy) on Python 3.13; test (pytest) across Python 3.11-3.13
- **Release**: Triggered by `v*` tags. Builds with `uv build` (hatchling backend), publishes to TestPyPI then PyPI via trusted publishing
- **Security**: Weekly Bandit scans + dependency review on PRs
- **Dependabot**: Weekly updates for Python deps and GitHub Actions
