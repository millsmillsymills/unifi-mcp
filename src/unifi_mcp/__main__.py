"""Entry point for running unifi-mcp as a module."""

from __future__ import annotations

from unifi_mcp.server import create_server


def main() -> None:
    """Start the UniFi MCP server."""
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
