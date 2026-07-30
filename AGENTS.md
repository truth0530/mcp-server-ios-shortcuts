# Agent notes — ios-shortcuts MCP (v2.4)

## Purpose

Build, sign, import, list, run, and inspect macOS/iOS Shortcuts (`.shortcut`) via MCP tools. Zero pip deps. macOS only.

## Preferred workflow

1. `doctor` — confirm CLI + **sign probe** + allow roots  
2. `list_actions` / `lookup_action` — full Apple catalog (400+ ids) + curated aliases  
3. Prefer curated short names; else full `is.workflow.actions.*` + `WF…` / `wf_params`  
4. `explain_magic_vars` when chaining outputs between steps  
5. `validate_recipe` — control-flow + semantic + **magic refs** + safe_mode  
6. Optional `compile_recipe_preview` to inspect golden-normalized WF actions  
7. `build_shortcut` or `build_and_install`  
8. Prefer `inspect_shortcut` on returned `path` (auto-uses `raw_path` sibling)  
9. `run_shortcut` smoke test (disabled when `SAFE_MODE=1`)  
10. `send_imessage` only when shipping a file to iPhone (manual send; blocked in safe mode)

## Build result shape

```json
{
  "ok": true,
  "path": "/…/Name.shortcut",
  "raw_path": "/…/Name_raw.shortcut",
  "signed_path": "/…/Name.shortcut",
  "signed": true,
  "actions_summary": [{ "index": 0, "type": "delay", "…": "…" }],
  "warnings": [],
  "risks": []
}
```

Import tools report `import_status: "import_prompted"` — GUI confirm may still be required.

## Recipe rules

- Each action: `{ "type": "...", "params": { ... } }` (min 1 action)  
- Optional `"as": "Alias"` tags the step output for later `${as:Alias}` / `{$ref:"as:Alias"}`  
- Magic refs: `{$ref:{action_index:0}}`, `{$var:"X"}`, `{$action:0}`, `{$input:true}`, or `"Hello ${as:Name}"`  
- **No forward refs** — only earlier steps  
- Control flow (`conditional_*`, `repeat_*`, `menu_*`) **must** nest correctly and share one `group_id` per block  
- Semantic checks: `volume`/`brightness` ∈ [0,1], `delay.seconds` ≥ 0, URLs required for HTTP/open_url, etc.  
- Prefer short names (`open_app`, `speak_text`); full `is.workflow.actions.*` allowed  
- Escape hatch: `wf_params` for raw Workflow parameters  
- Messaging defaults to compose UI (`show_compose: true`)  
- Details: `docs/MAGIC_VARIABLES.md`

## Client config

| Client | Config |
|--------|--------|
| Grok Build | `~/.grok/config.toml` → `[mcp_servers.ios-shortcuts]` or `grok mcp add` |
| Codex CLI | `~/.codex/config.toml` → `[mcp_servers.ios-shortcuts]` |
| Claude / Cursor | JSON `mcpServers.ios-shortcuts` command/args |

Snippets: `configs/grok.toml`, `configs/codex.toml`, `configs/mcp.json`.

Use **absolute paths** to `server.py` (do not rely on `${workspaceFolder}`).

## Safety

| Control | Behavior |
|---------|----------|
| Write sandbox | Only `dist`, repo root, and `IOS_SHORTCUTS_MCP_ALLOW_ROOTS` |
| `IOS_SHORTCUTS_MCP_SAFE_MODE=1` | Blocks shell/AppleScript/JXA recipes; blocks `run_shortcut` / `send_imessage` |
| `send_imessage` | Compose + Finder reveal only — never auto-send |
| Errors | `structuredContent.code` e.g. `PATH_SANDBOX`, `VALIDATION_ERROR`, `SAFE_MODE` |

Do not exfiltrate user shortcut libraries or personal data.
