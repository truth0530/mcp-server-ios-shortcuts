# 📱 iOS Shortcuts MCP Server

A Zero-Dependency Model Context Protocol (MCP) Server for macOS that empowers AI Coding Assistants (Gemini, Claude, Cursor, Antigravity) to build, sign, import, list, run, and send **iOS/macOS Shortcuts (`.shortcut` files)**.

---

## 🌟 Key Capabilities & Tools

This MCP server exposes **6 powerful tools** to any AI connected to it:

1. `build_shortcut`: Builds macOS/iOS binary `.shortcut` files from structured action recipes.
2. `sign_shortcut`: Signs un-signed `.shortcut` files using macOS native `shortcuts sign -m anyone` CLI for iOS 15+ compatibility.
3. `import_shortcut`: Installs a `.shortcut` file directly into the macOS Shortcuts library.
4. `list_shortcuts`: Lists all installed Shortcuts on the Mac.
5. `run_shortcut`: Executes an installed Shortcut on macOS.
6. `send_imessage`: Opens an iMessage compose window with the attached `.shortcut` file to send to any recipient.

---

## 🛠️ Requirements

- **macOS** (Monterey, Ventura, Sonoma, Sequoia or later)
- **Python 3.8+** (Uses standard library only; **No external `pip` dependencies required!**)

---

## ⚙️ Configuration for AI Assistants

### 1. Google Antigravity / agy CLI
Add the server entry to your MCP configuration (`~/.gemini/antigravity-cli/mcp/manifest.json` or `.gemini/mcp.json`):

```json
{
  "mcpServers": {
    "ios-shortcuts": {
      "command": "python3",
      "args": [
        "/Users/kwangsunglee/Projects/herdr-orchestrator/mcp-server-ios-shortcuts/server.py"
      ]
    }
  }
}
```

### 2. Claude Desktop App
Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ios-shortcuts": {
      "command": "python3",
      "args": [
        "/Users/kwangsunglee/Projects/herdr-orchestrator/mcp-server-ios-shortcuts/server.py"
      ]
    }
  }
}
```

### 3. Cursor IDE
In Cursor Settings → **Features** → **MCP Server**, add a new server:
- **Name**: `ios-shortcuts`
- **Type**: `stdio`
- **Command**: `python3 /Users/kwangsunglee/Projects/herdr-orchestrator/mcp-server-ios-shortcuts/server.py`

---

## 🧪 Testing the MCP Tools via AI

Once configured, any AI agent can respond to prompts like:

> *"Build an iOS shortcut named 'OffToWork' that sets media volume to 100%, opens Shiftee, waits 3 seconds, takes a screenshot, and speaks 'Check-in confirmed'."*

The AI will invoke `build_shortcut` -> `sign_shortcut` -> `import_shortcut` sequentially to deliver a ready-to-use Shortcut!
