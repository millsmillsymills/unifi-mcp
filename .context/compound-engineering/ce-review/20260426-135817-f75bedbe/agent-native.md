# Agent-Native Review — PR #132 (fix: switch ProtectClient to integration/v1 path)

**Reviewer:** agent-native  
**Run:** 20260426-135817-f75bedbe

## Tool surface parity: unchanged (high confidence)

The diff touches only `clients/protect.py`, test constants, and documentation. Every tool module under `src/unifi_mcp/tools/protect/` — `cameras.py`, `devices.py`, `events.py`, `media.py`, `nvr.py` — is unmodified. Tool names, docstrings, and parameter signatures are identical to pre-fix. An agent that learned this surface from a prior interaction will find it fully familiar.

## bootstrap/events agent-facing experience: better, but incomplete

Before this fix both tools were deregistered at startup. An agent received an MCP "unknown tool" error on any call — a signal indistinguishable from a misconfigured server, wrong endpoint, or missing API key.

After this fix both tools appear in the tool list and return a typed `ToolError`: `[HTTP 404] Resource not found: HTTP 404: Entity 'endpoint' not found`. The `[HTTP 404]` prefix (from `_status_tag` in `errors.py`) lets an agent branch on status code without parsing prose, and the error message is more specific about what is absent than "tool not found" was. This is a net improvement.

The remaining gap: neither `protect_get_bootstrap` nor `protect_list_events` mentions the known 404 in its docstring. The README known-issues section covers this for human readers, but an agent reads tool descriptions, not README prose. A one-line note in each docstring — e.g., "Note: returns 404 on the Protect integration API v1 until #130 ships a replacement" — would let an agent skip the call rather than discover the failure at runtime. This is worth adding in the #130 follow-up if not here.

## UI parity: 0/15 -> 10/15 working

The Protect web UI capabilities now covered by working tools: camera listing and detail, camera config, recording modes, smart detection settings, NVR read access, snapshot retrieval, video export, and accessory device listing (chimes, lights, sensors, viewers). The two remaining UI capabilities without working tools are live/historical events (`protect_list_events`) and system bootstrap (`protect_get_bootstrap`), both tracked in #130.

## protect_update_nvr: acceptable as-is

The inference that `PUT nvrs` mirrors `GET nvrs` (verified working) is the best available guess from the integration-API shape. The docstring declares the untested status. The write-mode gate limits exposure to deliberate readwrite deployments, and a failure will surface `[HTTP 404]` or `[HTTP 405]` with an actionable message through `handle_client_error`. Hiding the tool would reduce agent capability below what the API structure warrants. No change needed.

## Verdict

PASS for merging. One follow-up item for #130: add a "returns 404 until #130 resolves" note to the `protect_get_bootstrap` and `protect_list_events` docstrings so agents can reason about the limitation before calling.
