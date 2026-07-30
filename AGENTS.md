# Agent notes — ios-shortcuts MCP

## Purpose

Build, sign, import, list, run, and inspect macOS/iOS Shortcuts (`.shortcut`) via MCP tools. Zero pip deps. macOS only.

## Preferred workflow

1. `doctor` — confirm `shortcuts` CLI + server health  
2. `list_actions` / `list_templates` — discover primitives  
3. `validate_recipe` — catch bad types / unbalanced control flow  
4. `build_shortcut` or `build_and_install`  
5. `run_shortcut` — smoke test on this Mac  
6. `send_imessage` only when the user wants to ship a file to iPhone (manual send)

## Recipe rules

- Each action: `{ "type": "...", "params": { ... } }`  
- Control flow (`conditional_*`, `repeat_*`, `menu_*`) **must** be properly nested and share one `group_id` UUID per block
- Prefer short names (`open_app`, `speak_text`); full `is.workflow.actions.*` allowed  
- Escape hatch: `wf_params` for raw Workflow parameters  
- Messaging defaults to compose UI (`show_compose: true`) — do not force silent send  

## Client config

| Client | Config |
|--------|--------|
| Grok Build | `~/.grok/config.toml` → `[mcp_servers.ios-shortcuts]` or `grok mcp add` |
| Codex CLI | `~/.codex/config.toml` → `[mcp_servers.ios-shortcuts]` |
| Claude / Cursor | JSON `mcpServers.ios-shortcuts` command/args |

Snippets: `configs/grok.toml`, `configs/codex.toml`, `configs/mcp.json`.

## Safety

- `send_imessage` never auto-sends  
- Signing uses `shortcuts sign -m anyone` (shareable)  
- Do not exfiltrate user shortcut libraries or personal data  
