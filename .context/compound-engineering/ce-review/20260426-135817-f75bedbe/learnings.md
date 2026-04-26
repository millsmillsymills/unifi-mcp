## Institutional Learnings Search Results

### Search Context
- **Feature/Task**: PR #132 — switch ProtectClient to `/proxy/protect/integration/v1/` X-API-Key path (#103)
- **Keywords Used**: protect, integration/v1, X-API-Key, _path_prefix, validate_connection, bootstrap, events, nvr plural, deregistration, #87, #103, #104
- **Files Scanned**: `docs/plans/`, `src/unifi_mcp/clients/`, `src/unifi_mcp/server.py`, project memory
- **Relevant Matches**: 4 sources

---

### Relevant Learnings

#### 1. The exact bug this PR fixes is already fully documented in project memory

`/proxy/protect/api/` only accepts session-cookie auth; X-API-Key only works on `/proxy/protect/integration/v1/`. Verified against UCK-G2-Plus running Protect 7.0.107. The PR's path change is the correct and expected fix.

**File**: `.claude/projects/.../memory/project_protect_api_path_bug.md`

**Key Insight**: The memory note also warns that integration/v1 uses `nvrs` (plural) — not `nvr` — and that `bootstrap` and `events` have no integration/v1 equivalent. The current `protect.py` already reflects this (line 107: `await self.get("nvrs")`; docstring on `get_bootstrap` and `list_events` flags the 404 risk).

---

#### 2. Tool deregistration pattern (#87 / #103)

`src/unifi_mcp/server.py` (`_register_client`, `server_lifespan`) — when `validate_connection()` returns False, `server.disable(tags={api_name})` hides all tools for that API. The lifespan then emits a WARN with the exception class and message (implemented in #104 / PR #121). Any regression that causes `validate_connection` to return False silently removes all 15 Protect tools from the MCP tool list.

**Key Insight**: The validate_connection probe in `ProtectClient` calls `get_nvr()` → `GET nvrs`. If the path migration is incomplete (e.g. a test fixture still uses the old path, or `_path_prefix` is set after `super().__init__`), validation will fail and all Protect tools will disappear at startup with only a WARN log.

---

#### 3. HTML-body 401 is classified as UniFiAuthError, not a JSON decode error

`src/unifi_mcp/clients/base.py` `_parse_json()` (lines 219–233) — when the controller returns an HTML response (the UniFi OS portal SPA), it raises `UniFiAuthError` with a message that says "auth/path mismatch". This is the exact failure mode when hitting the wrong path prefix. The WARN diagnostic (#104) then surfaces `UniFiAuthError: Controller returned HTML...` in the startup log.

**Key Insight**: A wrong `_path_prefix` produces `UniFiAuthError` (not `UniFiNotFoundError`) at the validate_connection layer, so any test that asserts the exception type on a wrong-host scenario should expect `UniFiAuthError`.

---

#### 4. Plan-era path table is now stale

`docs/plans/2026-04-16-001-feat-unifi-mcp-server-plan.md` line 70 lists the Protect path as `/proxy/protect/api/` — the old cookie-auth path. This plan document predates the fix. It is not used at runtime, but reviewers reading it will see a contradiction with the now-correct `protect.py`.

**Key Insight**: The plan is frozen historical record, not live spec, so no action is required. But if the plan is ever regenerated or referenced, line 70 needs updating.

---

### Recommendations

- Confirm `_path_prefix` is set **before** `super().__init__()` is called in `ProtectClient.__init__` — the current code already does this correctly (line 39 before line 40).
- The `get_bootstrap` and `list_events` methods still exist on `ProtectClient` and will 404 on integration/v1. PR #132 should either remove them, stub them to raise `NotImplementedError`, or document the 404 explicitly in the tools that call them. The class docstring (lines 25–27) flags this but a caller who ignores docstrings will get an opaque `UniFiNotFoundError`.
- Hardware topology: Protect lives at `192.168.1.220`, not `192.168.1.1`. Any integration test or manual smoke test must set `UNIFI_PROTECT_HOST=192.168.1.220`.
- The memory note says "integration/v1 uses `nvrs` not `nvr`" — verify that the `update_nvr` write method (`PUT nvrs`) is also consistent (it is, line 185).
