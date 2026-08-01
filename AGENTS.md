# Agent notes — ios-shortcuts MCP (v2.9)

## Purpose

Build, sign, import, list, run, and inspect macOS/iOS Shortcuts (`.shortcut`) via MCP tools. Zero pip deps. macOS only.

## Preferred workflow

1. `doctor` — confirm CLI + **sign probe** + allow roots  
2. Prefer **curated** short names for production quality  
3. **Existing library shortcut (critical):**  
   - `export_library_shortcut` *or* user export to disk  
   - `extract_signed_shortcut` / `decompile_shortcut` (**AEA1 decrypt**)  
   - `clone_shortcut` to fork under a new name  
   - Diff real identifiers before inventing a “fix”  
4. For files you already have: `decompile_shortcut` → edit → `validate_recipe` → rebuild  
5. After library changes: `learn_from_corpus` / `extract_system_library`  
   - Needs **Full Disk Access** for Shortcuts.sqlite  
   - Never trust self-bootstrap unless debugging  
6. Generic short keys only if **accepted** map exists (`get_learned_params`)  
7. Remap → schema-aware coercion (enums plain; text may token-wrap)  
8. App Intents: `type: app_intent` with reverse-DNS `identifier`  
9. `validate_recipe` with `target_platform` (`ios`/`macos`)  
10. `build_shortcut` — keep `raw_path` for inspect/decompile/learn  
11. `run_shortcut` when installed (safe_mode blocks)

**Never** improve a real user shortcut by guessing IDs without extract.  
Docs: `docs/CLONE_AND_EXTRACT.md`

**Sign before shipping to the user**

```bash
shortcuts sign -m anyone -i Name_raw.shortcut -o Name.shortcut
```

Do **not** use `--mode` / `--input` / `--output` (agents have failed with “incorrect format”).  
Do **not** claim “개선 완료” with only `*_raw.shortcut` — iPhone needs the **signed** file.

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
- Details: `docs/MAGIC_VARIABLES.md` · **device traps:** `docs/RUNTIME_TRAPS.md`

### Hard lessons (do not regress)

| Trap | Rule |
|------|------|
| iOS volume restore | Literal `set_volume` only — **never** get_volume→var→set_volume |
| If / contains text | Previous action = text (OCR); **no** `WFInput` Variable on If |
| Screenshot | Next step must consume image (`ocr_extract_text` …) or UI sticks on 「이미지」 |
| Crop | Skip for full-frame OCR; bare crop → interactive Cancel/Done |
| Vibrate | iOS-only — omit for mac / dual target |
| Phone-only apps | `target_platform: "ios"`; Mac will ask to pick app |

Template for screenshot OCR demo: **`screenshot_ocr_contains`**.

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
