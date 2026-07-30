# iOS Shortcuts MCP Server

Zero-dependency **Model Context Protocol (MCP)** server for macOS that lets AI coding agents **build, sign, import, list, run, inspect, and share** iOS/macOS Shortcuts (`.shortcut` files).

**Supported clients:** Grok Build · Codex CLI · Claude Desktop / Claude Code · Cursor · Gemini / Antigravity · any stdio MCP client

| | |
|---|---|
| **Version** | 2.7.0 |
| **Runtime** | Python 3.8+ (stdlib only — no `pip install`) |
| **OS** | macOS Monterey+ (`shortcuts` CLI) |
| **License** | MIT |

---

## Why this exists

Apple Shortcuts are powerful but tedious to author by hand. This server turns natural-language agent intent into signed `.shortcut` binaries via a structured action recipe:

```
list_actions → validate_recipe → build_shortcut → import_shortcut → run_shortcut
# or one-shot:
build_and_install
```

---

## Tools (v2)

| Tool | Purpose |
|------|---------|
| `list_actions` | Full Apple catalog (400+ ids) + curated aliases |
| `lookup_action` | Resolve short name / full identifier + suggestions |
| `decompile_shortcut` | `.shortcut` → editable recipe JSON (reverse path) |
| `learn_from_corpus` | Mine WF param keys from seeds/fixtures/files → learned maps |
| `get_learned_params` | short→WF map for one action |
| `list_learned_actions` | Top learned actions by sample count |
| `list_templates` | Built-in recipe templates |
| `get_template` | Fetch a template’s full action list |
| `validate_recipe` | Dry-run compile (semantic + control-flow + **magic refs**) |
| `explain_magic_vars` | Document `$ref` / `$var` / `${as:Name}` chaining syntax |
| `compile_recipe_preview` | Golden-normalized WF preview (no files) |
| `build_shortcut` | Build + auto-sign; returns `raw_path` + `signed_path` + summary |
| `create_from_template` | Build from a named template |
| `build_and_install` | Build + sign + **import prompt** (GUI, not confirmed install) |
| `sign_shortcut` | Sign with `shortcuts sign -m anyone` (write path sandboxed) |
| `inspect_shortcut` | Summarize `.shortcut`; auto-follows sibling `*_raw.shortcut` |
| `import_shortcut` | Prompt import into Shortcuts library |
| `view_shortcut` | Open an installed shortcut in the app |
| `list_shortcuts` | List installed shortcuts/folders/ids |
| `run_shortcut` | Run by name (blocked in safe mode) |
| `send_imessage` | Messages compose + reveal file (blocked in safe mode) |
| `doctor` | Health check + **sign round-trip** probe |

---

## Requirements

- **macOS** Monterey, Ventura, Sonoma, Sequoia, or later
- **Python 3.8+**
- System `shortcuts` CLI (`/usr/bin/shortcuts`) — ships with macOS

No virtualenv, no `requirements.txt`, no Node.

---

## Quick start

```bash
git clone https://github.com/truth0530/mcp-server-ios-shortcuts.git
cd mcp-server-ios-shortcuts

# Smoke test (no MCP client required)
python3 scripts/smoke_test.py

# Manual doctor via JSON-RPC (NDJSON)
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"doctor","arguments":{}}}' \
  | python3 server.py
```

Replace `REPO` below with the absolute path to this repo on your Mac.

---

## Configuration

### 1. Grok Build (xAI)

**CLI (recommended):**

```bash
grok mcp add ios-shortcuts -- python3 /absolute/path/to/mcp-server-ios-shortcuts/server.py
```

**Or edit `~/.grok/config.toml`:**

```toml
[mcp_servers.ios-shortcuts]
command = "python3"
args = ["/absolute/path/to/mcp-server-ios-shortcuts/server.py"]
enabled = true
startup_timeout_sec = 15
tool_timeout_sec = 300
```

Project-scoped (commit with the repo):

```toml
# .grok/config.toml
[mcp_servers.ios-shortcuts]
command = "python3"
args = ["./mcp-server-ios-shortcuts/server.py"]  # adjust relative path
enabled = true
```

Verify:

```bash
grok mcp list
grok mcp doctor ios-shortcuts
```

In a Grok session try: *“Call doctor on ios-shortcuts, then create_from_template hello_world and import it.”*

---

### 2. Codex CLI (OpenAI)

Edit `~/.codex/config.toml`:

```toml
[mcp_servers.ios-shortcuts]
command = "python3"
args = ["/absolute/path/to/mcp-server-ios-shortcuts/server.py"]
startup_timeout_sec = 15
```

Optional per-tool approval overrides (example — tighten destructive tools if desired):

```toml
[mcp_servers.ios-shortcuts.tools.run_shortcut]
approval_mode = "approve"

[mcp_servers.ios-shortcuts.tools.build_and_install]
approval_mode = "approve"
```

Restart Codex (or reload MCP). Then: *“Use ios-shortcuts doctor, then list_templates.”*

---

### 3. Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ios-shortcuts": {
      "command": "python3",
      "args": [
        "/absolute/path/to/mcp-server-ios-shortcuts/server.py"
      ]
    }
  }
}
```

### 4. Claude Code

Project `.mcp.json` or user MCP config:

```json
{
  "mcpServers": {
    "ios-shortcuts": {
      "command": "python3",
      "args": [
        "/absolute/path/to/mcp-server-ios-shortcuts/server.py"
      ]
    }
  }
}
```

### 5. Cursor IDE

Settings → **Features** → **MCP** → add server:

- **Name:** `ios-shortcuts`
- **Type:** `stdio`
- **Command:** `python3`
- **Args:** `/absolute/path/to/mcp-server-ios-shortcuts/server.py`

Or project `.cursor/mcp.json` (same JSON shape as Claude).

### 6. Google Antigravity / Gemini CLI

`~/.gemini/antigravity-cli/mcp/manifest.json` or `.gemini/mcp.json`:

```json
{
  "mcpServers": {
    "ios-shortcuts": {
      "command": "python3",
      "args": [
        "/absolute/path/to/mcp-server-ios-shortcuts/server.py"
      ]
    }
  }
}
```

### Ready-made snippets

See [`configs/`](./configs/) for copy-paste fragments:

| File | Client |
|------|--------|
| `configs/grok.toml` | Grok Build |
| `configs/codex.toml` | Codex CLI |
| `configs/claude_desktop.json` | Claude Desktop |
| `configs/mcp.json` | Claude Code / Cursor / generic |

---

## Recipe format

```json
{
  "name": "OffToWork",
  "actions": [
    { "type": "set_volume", "params": { "volume": 1.0 } },
    {
      "type": "open_app",
      "params": {
        "bundle_id": "com.apple.MobileSMS",
        "app_name": "Messages"
      }
    },
    { "type": "delay", "params": { "seconds": 3 } },
    { "type": "take_screenshot", "params": {} },
    {
      "type": "speak_text",
      "params": { "text": "Check-in confirmed", "wait": true }
    }
  ],
  "icon_color": "blue"
}
```

### Action highlights

| Type | Notes |
|------|--------|
| `delay`, `speak_text`, `show_notification`, `show_alert`, `show_result`, `ask` | UX / timing |
| `open_app`, `open_url`, `run_shortcut` | Navigation |
| `set_volume`, `set_brightness`, `set_focus`, `set_wifi`, `set_bluetooth` | Device |
| `take_screenshot`, `take_photo`, `ocr_extract_text`, `crop_image` | Capture |
| `text`, `set_clipboard`, `get_clipboard`, `replace_text`, `split_text` | Text |
| `set_variable`, `get_variable`, `list`, `dictionary` | Data |
| `get_contents_of_url` | HTTP |
| `run_shell_script`, `run_applescript` | macOS scripting |
| `conditional_start` / `else` / `end` | If blocks (`group_id` required) |
| `repeat_start` / `end`, `menu_start` / `item` / `end` | Loops / menus |
| `is.workflow.actions.*` or `wf_params` | Escape hatch for raw WF actions |

Full catalog: call `list_actions`, or see [docs/ACTION_REFERENCE.md](./docs/ACTION_REFERENCE.md).

### Templates

| Name | Description |
|------|-------------|
| `hello_world` | Notify + speak |
| `clipboard_to_notification` | Clipboard → result |
| `volume_max_and_notify` | Volume 100% |
| `screenshot_ocr` | Screenshot → OCR → show |
| `open_url_and_wait` | Open URL, wait, notify |
| `shell_echo` | macOS shell sample |
| `morning_focus` | Focus / DND |
| `http_get_sample` | HTTP GET demo |

```text
create_from_template template=hello_world import_after_build=true
```

---

## Example agent prompts

> Build an iOS shortcut named `OffToWork` that sets media volume to 100%, opens Messages, waits 3 seconds, takes a screenshot, and speaks “Check-in confirmed”. Sign and import it.

> Use ios-shortcuts `doctor`, then `list_templates`, then `create_from_template` with `screenshot_ocr`.

> List installed shortcuts, run `hello_world` if present, and show stdout.

> Validate this recipe, fix any errors, then `build_and_install`.

---

## Architecture

```
server.py              # MCP stdio JSON-RPC (Content-Length + NDJSON)
shortcut_builder.py    # Recipe → binary plist + sign helpers
configs/               # Client config snippets
examples/              # Sample recipes (JSON)
docs/                  # Action reference
scripts/smoke_test.py  # Offline smoke tests
dist/                  # Build output (gitignored artifacts)
```

**Signing:** every build keeps `Name_raw.shortcut` (inspectable plist). Successful `shortcuts sign -m anyone` also writes `Name.shortcut`. Tool results expose both `raw_path` and `signed_path`; `path` is the best artifact for import.

**Safety:**
- Write paths sandboxed to allow roots (default: repo + `dist`)
- `IOS_SHORTCUTS_MCP_SAFE_MODE=1` blocks shell/AppleScript/JXA recipes and `run_shortcut` / `send_imessage`
- `send_imessage` never auto-sends; messaging actions default to compose UI
- Tool annotations (`readOnlyHint`, `destructiveHint`, `openWorldHint`) for client approval UX

**Resources:** `shortcut://catalog/actions`, `shortcut://catalog/templates`, `shortcut://docs/magic_vars`

### Magic variables (v2.3)

Chain prior step outputs into later params:

```json
[
  { "type": "text", "params": { "text": "Agent" }, "as": "Name" },
  {
    "type": "speak_text",
    "params": { "text": "Hello ${as:Name}", "wait": true }
  },
  {
    "type": "show_result",
    "params": { "text": { "$ref": "as:Name" } }
  }
]
```

See [docs/MAGIC_VARIABLES.md](./docs/MAGIC_VARIABLES.md). Template: `magic_chain`.

### Golden fixtures

```bash
python3 scripts/generate_fixtures.py   # rebuild fixtures/golden
python3 scripts/check_fixtures.py      # compare compiled output
```

---

## Environment

| Variable | Meaning |
|----------|---------|
| `IOS_SHORTCUTS_MCP_DIST` | Default `output_dir` for builds (default: `<repo>/dist`) |
| `IOS_SHORTCUTS_MCP_ALLOW_ROOTS` | Extra write roots (`:` / `,` / `;` separated) |
| `IOS_SHORTCUTS_MCP_SAFE_MODE` | `1` = block dangerous actions + run/send tools |
| `IOS_SHORTCUTS_MCP_MAX_MESSAGE_BYTES` | Max inbound MCP message size (default: 8 MiB) |

---

## Development

```bash
# Unit / smoke (14 tests) + golden fixtures
python3 scripts/smoke_test.py
python3 scripts/check_fixtures.py

# Build a sample without MCP
python3 - <<'PY'
from shortcut_builder import build_shortcut_plist
result = build_shortcut_plist(
    [{"type": "show_notification", "params": {"title": "Hi", "body": "Test"}}],
    "SmokeNotify",
    "./dist",
)
print(result["raw_path"], result.get("signed_path"), result["signed"])
PY
```

### Protocol notes

- Primary transport: **MCP stdio** with `Content-Length` framing  
- Also accepts **newline-delimited JSON** for simple CLI debugging  
- Tool results include `content` + `structuredContent` (errors use `code` + `message`)  
- Logs go to **stderr** only  

---

## Apple action coverage (v2.5)

| Layer | Reality check |
|-------|----------------|
| **Identifiers** | 400+ harvested + any unlisted `is.workflow.actions.*` / App Intent reverse-DNS |
| **Executable quality** | Curated ~100 with rich params; generic path uses **auto-coercion** (not full Apple schema parity) |
| **Reverse** | `decompile_shortcut` — modify/clone existing `.shortcut` via `*_raw` |
| **Platform** | `target_platform` preflight (ios/macos/watchos heuristics) |
| **Catalog DB** | `data/apple_action_catalog.json` (platforms, serialization, short_names) |

Refresh:

```bash
python3 scripts/harvest_action_ids.py
python3 scripts/build_action_catalog_db.py
python3 scripts/smoke_test.py
```

Details: [docs/ACTION_COVERAGE.md](./docs/ACTION_COVERAGE.md)

---

## Trusted learning loop (v2.7)

Echo-chamber fix: learn from **Apple Gallery / system / user exports / SQLite**, not from our own dist.

```bash
python3 scripts/learn_from_shortcuts.py
# Full Disk Access required for ~/Library/Shortcuts/Shortcuts.sqlite
python3 scripts/learn_from_shortcuts.py --roots "$HOME/Desktop/shortcut-exports"
```

- `accepted_short_to_wf` only after reverse compile validation
- Enum params stay plain strings; text fields may become WFTextTokenString
- MCP: `learn_from_corpus` · `extract_system_library` · `get_learned_params`

Env: `IOS_SHORTCUTS_MCP_LEARN_ROOTS`, `IOS_SHORTCUTS_MCP_LEARN_SIGN=1` (optional sign gate)

---

## Changelog

### 2.7.0

- **Echo-chamber guard**: trusted maps only from external_apple / external_user
- **SQLite extractor** for Shortcuts.sqlite when Full Disk Access allows
- **Gallery/system .wflow** as authentic Apple corpus
- **Enum vs TextToken** discriminator (enums never WFTextTokenString-wrapped)
- **Accept filter**: reverse compile before accepted_short_to_wf
- `extract_system_library` tool + TCC status reporting

### 2.6.0

- **Learning loop**: compile/decompile mining → `learned_param_maps.json`
- Generic path applies learned **short→WF** remaps (text/wait/seconds/…)
- Tools: `learn_from_corpus`, `get_learned_params`, `list_learned_actions`
- Script: `scripts/learn_from_shortcuts.py`
- Expand corpus via user `.shortcut` exports under learn roots

### 2.5.0

- **Decompiler**: `decompile_shortcut` (recipe reverse path for modify/clone)
- **Smart WF auto-coercion**: plain strings/numbers → WFTextTokenString / WFNumberSubstitutableState on generic path
- **Structured catalog DB** with platform tags + short-name collision disambiguation
- **App Intent** surface: `type: app_intent` + reverse-DNS identifiers
- **Platform preflight** on validate/build (`target_platform`)
- **E2E**: decompile round-trip always; `shortcuts run` when library import succeeds
- Honest docs: identifier cover ≠ silent-corruption-free generic params

### 2.4.0

- Full Apple action identifier catalog (harvested from macOS) + generic compile path
- `lookup_action`, expanded `list_actions` (`category`, `curated_only`)
- `action_catalog.py`, harvest script, ACTION_COVERAGE docs
- Honest split: identifier coverage vs curated param schemas

### 2.3.0

- Magic variables / action chaining: `$ref`, `$var`, `$action`, `$input`, `${…}` interpolation, step `as` aliases
- Deterministic action UUIDs (`uuid5`) for stable refs + fixtures
- Golden fixture suite (`fixtures/recipes` → `fixtures/golden`) with generate/check scripts
- Tools: `explain_magic_vars`, `compile_recipe_preview`
- Template `magic_chain`; resource `shortcut://docs/magic_vars`
- Smoke tests expanded to 14 cases

### 2.2.0

- Dual artifacts: always keep `*_raw.shortcut`; return `raw_path` + `signed_path`
- `inspect_shortcut` auto-follows raw sibling for signed packages
- Semantic validation (ranges, required fields, empty recipes) + risks list
- Write-path sandbox (`ALLOW_ROOTS`) and `SAFE_MODE`
- MCP tool annotations + stricter `actions` JSON Schema
- Structured error payloads (`code`, `message`, `details`)
- `doctor` sign round-trip probe, macOS version, dist writability
- Resources for action/template catalogs; richer prompts
- Smoke tests expanded to 12 cases

### 2.1.0

- Standards-compliant JSON-RPC parse, invalid-request, invalid-params, and method errors
- Recoverable NDJSON / `Content-Length` parsing with an 8 MiB safety limit
- Notifications never produce responses
- Structured tool results alongside text content for modern MCP clients
- Strict stack-based control-flow validation (nesting, type, order, `group_id`)
- Safer shortcut filenames and expanded transport / validation regression tests

### 2.0.0

- Grok Build + Codex CLI first-class config docs and snippets  
- 15 tools (was 6): templates, validate, inspect, view, doctor, build_and_install, …  
- Expanded action catalog (HTTP, shell, AppleScript, focus, clipboard, control flow, …)  
- Content-Length framing + NDJSON  
- Recipe validation, icon colors, safer messaging defaults  
- Smoke test script and example recipes  

---

## License

MIT — see [LICENSE](./LICENSE).
