# iOS Shortcuts MCP Server

Zero-dependency **Model Context Protocol (MCP)** server for macOS that lets AI coding agents **build, sign, import, list, run, inspect, and share** iOS/macOS Shortcuts (`.shortcut` files).

**Supported clients:** Grok Build · Codex CLI · Claude Desktop / Claude Code · Cursor · Gemini / Antigravity · any stdio MCP client

| | |
|---|---|
| **Version** | 2.1.0 |
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
| `list_actions` | Discover supported action types + param docs |
| `list_templates` | Built-in recipe templates |
| `get_template` | Fetch a template’s full action list |
| `validate_recipe` | Dry-run compile (errors/warnings, no files) |
| `build_shortcut` | Build + auto-sign `.shortcut` from recipe |
| `create_from_template` | Build from a named template |
| `build_and_install` | Build + sign + import in one call |
| `sign_shortcut` | Sign with `shortcuts sign -m anyone` |
| `inspect_shortcut` | Summarize a `.shortcut` file |
| `import_shortcut` | Open/install into Shortcuts library |
| `view_shortcut` | Open an installed shortcut in the app |
| `list_shortcuts` | List installed shortcuts/folders/ids |
| `run_shortcut` | Run by name (stdin / input-path / output-path) |
| `send_imessage` | Open Messages compose + reveal file (no auto-send) |
| `doctor` | Environment health check |

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

**Signing:** unsigned binary plists are written as `Name_raw.shortcut`; successful `shortcuts sign -m anyone` produces `Name.shortcut` (iOS 15+ friendly “anyone” mode).

**Safety:** `send_imessage` never auto-sends — it only opens compose and reveals the file. `send_message` / `send_email` actions default to `show_compose: true`.

---

## Environment

| Variable | Meaning |
|----------|---------|
| `IOS_SHORTCUTS_MCP_DIST` | Default `output_dir` for builds (default: `<repo>/dist`) |
| `IOS_SHORTCUTS_MCP_MAX_MESSAGE_BYTES` | Maximum inbound MCP message size (default: 8 MiB) |

---

## Development

```bash
# Unit / smoke
python3 scripts/smoke_test.py

# Build a sample without MCP
python3 - <<'PY'
from shortcut_builder import build_shortcut_plist
path = build_shortcut_plist(
    [{"type": "show_notification", "params": {"title": "Hi", "body": "Test"}}],
    "SmokeNotify",
    "./dist",
)
print(path)
PY
```

### Protocol notes

- Primary transport: **MCP stdio** with `Content-Length` framing  
- Also accepts **newline-delimited JSON** for simple CLI debugging  
- `initialize` → `tools/list` → `tools/call`  
- Logs go to **stderr** only  

---

## Changelog (2.1.0)

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
