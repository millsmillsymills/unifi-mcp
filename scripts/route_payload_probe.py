"""One-off probe: discover the create_route payload shape the controller accepts."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

from unifi_mcp.clients.network import NetworkClient


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


async def main() -> None:
    api_key = os.environ.get("UNIFI_NETWORK_API")
    if not api_key:
        print("UNIFI_NETWORK_API not set", file=sys.stderr)
        sys.exit(2)

    client = NetworkClient(
        base_url=f"https://{os.environ.get('UNIFI_NETWORK_HOST', '192.168.1.1')}:443",
        api_key=api_key,
        site=os.environ.get("UNIFI_NETWORK_SITE", "default"),
        verify_ssl=_bool_env("UNIFI_NETWORK_VERIFY_SSL"),
        timeout=15,
        max_retries=1,
    )

    suffix = uuid.uuid4().hex[:6]
    name = f"probe-route-{suffix}"

    candidates = [
        {
            "label": "type=static-route + prefixed",
            "data": {
                "name": name,
                "type": "static-route",
                "enabled": False,
                "static-route_network": "10.99.250.0/24",
                "static-route_distance": 1,
                "static-route_type": "nexthop-route",
                "static-route_nexthop": "192.168.1.1",
            },
        },
        {
            "label": "type=static-route + prefixed, no distance",
            "data": {
                "name": name,
                "type": "static-route",
                "enabled": False,
                "static-route_network": "10.99.250.0/24",
                "static-route_type": "nexthop-route",
                "static-route_nexthop": "192.168.1.1",
            },
        },
        {
            "label": "type=nexthop-route at top + prefixed",
            "data": {
                "name": name,
                "type": "nexthop-route",
                "enabled": False,
                "static-route_network": "10.99.250.0/24",
                "static-route_nexthop": "192.168.1.1",
            },
        },
    ]

    try:
        for i, cand in enumerate(candidates):
            try:
                result = await client.create_route(cand["data"])
                route_id = (result.get("data") or [{}])[0].get("_id")
                print(f"[{i}] {cand['label']}: ACCEPTED (id={route_id})")
                if route_id:
                    print(f"    payload was: {cand['data']}")
                    print("    read-back:")
                    rb = await client.get_route(route_id)
                    for k, v in (rb.get("data") or [{}])[0].items():
                        print(f"      {k}: {v}")
                    await client.delete_route(route_id)
                    print("    cleaned up.")
                    return
            except Exception as exc:
                print(f"[{i}] {cand['label']}: REJECTED — {exc}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
