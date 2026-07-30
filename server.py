#!/usr/bin/env python3
"""
iOS / macOS Shortcuts MCP Server (zero third-party deps, stdio JSON-RPC).

Works with Grok Build, Codex CLI, Claude Desktop/Code, Cursor, Gemini /
Antigravity, and any MCP client that speaks stdio JSON-RPC.

Supports both:
  - Content-Length framed messages (MCP stdio transport)
  - Newline-delimited JSON (legacy / simple clients)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import traceback
from typing import Any, Dict, List, Optional

from shortcut_builder import (
    ACTION_MAPPINGS,
    TEMPLATES,
    build_shortcut_plist,
    get_template,
    inspect_shortcut_file,
    list_supported_actions,
    list_templates,
    sign_shortcut_file,
    validate_actions,
)

SERVER_NAME = "ios-shortcuts-mcp"
SERVER_VERSION = "2.0.0"
PROTOCOL_VERSION = "2024-11-05"

# Default artifact directory (overridable via env or tool args).
DEFAULT_OUTPUT_DIR = os.environ.get(
    "IOS_SHORTCUTS_MCP_DIST",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist"),
)


# ---------------------------------------------------------------------------
# Logging (stderr only — stdout is the MCP transport)
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    sys.stderr.write(f"[{SERVER_NAME}] {msg}\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "list_actions",
        "description": (
            "List supported high-level shortcut action types with parameter docs "
            "and examples. Call this before build_shortcut when unsure which "
            "action types exist."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional substring filter on type/summary/identifier",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 200)",
                },
            },
        },
    },
    {
        "name": "list_templates",
        "description": "List built-in shortcut recipe templates.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_template",
        "description": (
            "Return the full action recipe for a built-in template "
            "(e.g. hello_world, screenshot_ocr, shell_echo)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Template name from list_templates",
                }
            },
            "required": ["name"],
        },
    },
    {
        "name": "validate_recipe",
        "description": (
            "Dry-run compile an action recipe without writing files. "
            "Returns ok/errors/warnings and compiled action count."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "description": "Action recipe array (same shape as build_shortcut)",
                }
            },
            "required": ["actions"],
        },
    },
    {
        "name": "build_shortcut",
        "description": (
            "Create a macOS/iOS .shortcut binary from a high-level action recipe. "
            "Signs automatically via `shortcuts sign -m anyone` when available. "
            "Prefer list_actions / validate_recipe first for complex recipes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Shortcut display / file name",
                },
                "actions": {
                    "type": "array",
                    "description": (
                        "List of {type, params} action objects. "
                        "Examples: delay, open_app, open_url, speak_text, "
                        "set_volume, show_notification, take_screenshot, "
                        "ocr_extract_text, run_shell_script, get_contents_of_url, "
                        "conditional_start/else/end, set_variable, text, …"
                    ),
                },
                "output_dir": {
                    "type": "string",
                    "description": f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
                },
                "sign": {
                    "type": "boolean",
                    "description": "Auto-sign after build (default true)",
                },
                "sign_mode": {
                    "type": "string",
                    "description": "anyone | people-who-know-me (default anyone)",
                },
                "icon_color": {
                    "type": "string",
                    "description": (
                        "Icon color name: red, orange, yellow, green, teal, blue, "
                        "indigo, purple, pink, gray, dark_gray, taupe"
                    ),
                },
                "icon_glyph": {
                    "type": "integer",
                    "description": "Shortcuts glyph number (default 59793)",
                },
                "workflow_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "e.g. [\"NCWidget\", \"WatchKit\", \"ActionExtension\"]",
                },
            },
            "required": ["name", "actions"],
        },
    },
    {
        "name": "create_from_template",
        "description": (
            "Build (and optionally import) a shortcut from a built-in template. "
            "Convenience wrapper around get_template + build_shortcut."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "template": {
                    "type": "string",
                    "description": "Template name (see list_templates)",
                },
                "name": {
                    "type": "string",
                    "description": "Override shortcut name (default = template name)",
                },
                "output_dir": {"type": "string"},
                "import_after_build": {
                    "type": "boolean",
                    "description": "Open/import into Shortcuts library (default false)",
                },
                "icon_color": {"type": "string"},
            },
            "required": ["template"],
        },
    },
    {
        "name": "build_and_install",
        "description": (
            "One-shot: build + sign + import a shortcut recipe into the local "
            "macOS Shortcuts library."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "actions": {"type": "array"},
                "output_dir": {"type": "string"},
                "icon_color": {"type": "string"},
            },
            "required": ["name", "actions"],
        },
    },
    {
        "name": "sign_shortcut",
        "description": (
            "Sign an unsigned .shortcut file with macOS `shortcuts sign` "
            "for iOS 15+ / modern Shortcuts compatibility."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "input_path": {"type": "string"},
                "output_path": {"type": "string"},
                "mode": {
                    "type": "string",
                    "description": "anyone | people-who-know-me (default anyone)",
                },
            },
            "required": ["input_path", "output_path"],
        },
    },
    {
        "name": "inspect_shortcut",
        "description": (
            "Inspect a .shortcut file: format, action identifiers, icon, versions. "
            "Raw unsigned plists give full detail; signed packages report limited info."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to .shortcut file"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "import_shortcut",
        "description": (
            "Import/install a .shortcut file into the macOS Shortcuts library "
            "(opens the file with the system handler)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "shortcut_path": {"type": "string"},
            },
            "required": ["shortcut_path"],
        },
    },
    {
        "name": "view_shortcut",
        "description": "Open an installed shortcut by name in the Shortcuts app.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Installed shortcut name"}
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_shortcuts",
        "description": (
            "List installed Shortcuts on this Mac. Optionally filter by folder "
            "or show identifiers / folders only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder_name": {
                    "type": "string",
                    "description": "Folder name, or 'none' for unfiled",
                },
                "folders_only": {
                    "type": "boolean",
                    "description": "List folders instead of shortcuts",
                },
                "show_identifiers": {
                    "type": "boolean",
                    "description": "Include shortcut identifiers",
                },
            },
        },
    },
    {
        "name": "run_shortcut",
        "description": (
            "Run an installed shortcut by name. Supports optional text stdin, "
            "input file path, and output file path (macOS shortcuts CLI)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "input_text": {
                    "type": "string",
                    "description": "Text piped to the shortcut on stdin",
                },
                "input_path": {
                    "type": "string",
                    "description": "File path passed via --input-path",
                },
                "output_path": {
                    "type": "string",
                    "description": "Where to write shortcut output via --output-path",
                },
                "output_type": {
                    "type": "string",
                    "description": "UTI for output, e.g. public.plain-text",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "send_imessage",
        "description": (
            "Open an iMessage compose window for a recipient and reveal a file "
            "(e.g. .shortcut) in Finder so the user can attach and send it. "
            "Does NOT auto-send (safety)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": "Phone number or Apple ID email",
                },
                "file_path": {"type": "string"},
                "message": {
                    "type": "string",
                    "description": "Optional body hint (shown in tool response only)",
                },
            },
            "required": ["recipient", "file_path"],
        },
    },
    {
        "name": "doctor",
        "description": (
            "Environment health check: Python, macOS shortcuts CLI presence, "
            "sign capability, default dist dir, action/template counts."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _ok_json(payload: Any) -> dict:
    return _ok(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _err(text: str) -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": True,
    }


def _run(
    cmd: List[str],
    *,
    input_text: Optional[str] = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def handle_tool_call(tool_name: str, arguments: Optional[dict]) -> dict:
    args = arguments or {}
    try:
        if tool_name == "list_actions":
            items = list_supported_actions()
            query = (args.get("query") or "").strip().lower()
            if query:
                items = [
                    it
                    for it in items
                    if query in it["type"].lower()
                    or query in (it.get("summary") or "").lower()
                    or query in (it.get("identifier") or "").lower()
                ]
            limit = int(args.get("limit") or 200)
            return _ok_json(
                {
                    "count": len(items[:limit]),
                    "total_available": len(ACTION_MAPPINGS),
                    "actions": items[:limit],
                }
            )

        if tool_name == "list_templates":
            return _ok_json({"templates": list_templates()})

        if tool_name == "get_template":
            return _ok_json(get_template(args["name"]))

        if tool_name == "validate_recipe":
            return _ok_json(validate_actions(args.get("actions", [])))

        if tool_name == "build_shortcut":
            name = args["name"]
            actions = args.get("actions", [])
            output_dir = args.get("output_dir") or DEFAULT_OUTPUT_DIR
            sign = args.get("sign", True)
            if isinstance(sign, str):
                sign = sign.lower() in {"1", "true", "yes"}
            path = build_shortcut_plist(
                actions,
                name,
                output_dir,
                sign=bool(sign),
                sign_mode=args.get("sign_mode") or "anyone",
                icon_color=args.get("icon_color"),
                icon_glyph=args.get("icon_glyph"),
                workflow_types=args.get("workflow_types"),
            )
            signed = not path.endswith("_raw.shortcut")
            return _ok_json(
                {
                    "ok": True,
                    "name": name,
                    "path": path,
                    "signed": signed,
                    "action_count": len(actions),
                    "hint": (
                        "Use import_shortcut to install, or build_and_install next time."
                        if signed
                        else "Signing failed or skipped; path is unsigned raw plist."
                    ),
                }
            )

        if tool_name == "create_from_template":
            tpl = get_template(args["template"])
            name = args.get("name") or args["template"]
            output_dir = args.get("output_dir") or DEFAULT_OUTPUT_DIR
            path = build_shortcut_plist(
                tpl["actions"],
                name,
                output_dir,
                sign=True,
                icon_color=args.get("icon_color"),
            )
            imported = False
            if args.get("import_after_build"):
                _run(["open", path])
                imported = True
            return _ok_json(
                {
                    "ok": True,
                    "template": args["template"],
                    "name": name,
                    "path": path,
                    "imported": imported,
                    "description": tpl.get("description"),
                }
            )

        if tool_name == "build_and_install":
            name = args["name"]
            actions = args.get("actions", [])
            output_dir = args.get("output_dir") or DEFAULT_OUTPUT_DIR
            path = build_shortcut_plist(
                actions,
                name,
                output_dir,
                sign=True,
                icon_color=args.get("icon_color"),
            )
            res = _run(["open", path])
            return _ok_json(
                {
                    "ok": res.returncode == 0,
                    "name": name,
                    "path": path,
                    "import_triggered": res.returncode == 0,
                    "stderr": (res.stderr or "").strip() or None,
                }
            )

        if tool_name == "sign_shortcut":
            inp = os.path.abspath(args["input_path"])
            outp = os.path.abspath(args["output_path"])
            ok, msg = sign_shortcut_file(
                inp, outp, mode=args.get("mode") or "anyone"
            )
            if ok:
                return _ok_json({"ok": True, "path": msg})
            return _err(f"Signing error: {msg}")

        if tool_name == "inspect_shortcut":
            return _ok_json(inspect_shortcut_file(args["path"]))

        if tool_name == "import_shortcut":
            path = os.path.abspath(args["shortcut_path"])
            if not os.path.isfile(path):
                return _err(f"File not found: {path}")
            res = _run(["open", path])
            if res.returncode != 0:
                return _err(f"Import failed: {res.stderr or res.stdout}")
            return _ok_json(
                {
                    "ok": True,
                    "path": path,
                    "message": f"Triggered import for {path}",
                }
            )

        if tool_name == "view_shortcut":
            name = args["name"]
            res = _run(["shortcuts", "view", name])
            if res.returncode != 0:
                return _err(f"view failed: {res.stderr or res.stdout}")
            return _ok(f"Opened shortcut '{name}' in Shortcuts app.")

        if tool_name == "list_shortcuts":
            cmd = ["shortcuts", "list"]
            if args.get("folder_name"):
                cmd.extend(["--folder-name", args["folder_name"]])
            if args.get("folders_only"):
                cmd.append("--folders")
            if args.get("show_identifiers"):
                cmd.append("--show-identifiers")
            res = _run(cmd)
            if res.returncode != 0:
                return _err(f"Error listing shortcuts: {res.stderr or res.stdout}")
            lines = [ln for ln in (res.stdout or "").splitlines() if ln.strip()]
            return _ok_json({"count": len(lines), "shortcuts": lines})

        if tool_name == "run_shortcut":
            name = args["name"]
            cmd = ["shortcuts", "run", name]
            if args.get("input_path"):
                cmd.extend(["--input-path", os.path.abspath(args["input_path"])])
            if args.get("output_path"):
                cmd.extend(["--output-path", os.path.abspath(args["output_path"])])
            if args.get("output_type"):
                cmd.extend(["--output-type", args["output_type"]])
            res = _run(cmd, input_text=args.get("input_text"), timeout=300)
            payload = {
                "ok": res.returncode == 0,
                "name": name,
                "stdout": res.stdout or "",
                "stderr": res.stderr or "",
                "returncode": res.returncode,
            }
            if args.get("output_path") and os.path.isfile(args["output_path"]):
                payload["output_path"] = os.path.abspath(args["output_path"])
            if res.returncode != 0:
                return _err(json.dumps(payload, indent=2))
            return _ok_json(payload)

        if tool_name == "send_imessage":
            rec = args["recipient"]
            path = os.path.abspath(args["file_path"])
            if not os.path.isfile(path):
                return _err(f"File not found: {path}")
            msg = args.get("message") or "Shortcut file attached."
            # Safety: never auto-send; open compose + reveal file.
            _run(["open", f"imessage://{rec}"])
            _run(["open", "-R", path])
            return _ok_json(
                {
                    "ok": True,
                    "recipient": rec,
                    "file_path": path,
                    "message_hint": msg,
                    "note": (
                        "Opened Messages compose and revealed the file in Finder. "
                        "User must attach and send manually."
                    ),
                }
            )

        if tool_name == "doctor":
            shortcuts_path = None
            shortcuts_ok = False
            try:
                which = _run(["/usr/bin/which", "shortcuts"])
                shortcuts_path = (which.stdout or "").strip() or None
                help_res = _run(["shortcuts", "help"])
                shortcuts_ok = help_res.returncode == 0
            except Exception as exc:
                shortcuts_path = f"error: {exc}"

            return _ok_json(
                {
                    "server": SERVER_NAME,
                    "version": SERVER_VERSION,
                    "python": sys.version.split()[0],
                    "platform": sys.platform,
                    "shortcuts_cli": {
                        "path": shortcuts_path,
                        "available": shortcuts_ok,
                    },
                    "default_output_dir": DEFAULT_OUTPUT_DIR,
                    "action_types": len(ACTION_MAPPINGS),
                    "templates": len(TEMPLATES),
                    "tools": [t["name"] for t in TOOLS],
                    "env": {
                        "IOS_SHORTCUTS_MCP_DIST": os.environ.get(
                            "IOS_SHORTCUTS_MCP_DIST"
                        ),
                    },
                    "hints": [
                        "macOS Monterey+ required for `shortcuts` CLI",
                        "Signing uses `shortcuts sign -m anyone`",
                        "Grok: ~/.grok/config.toml [mcp_servers.ios-shortcuts]",
                        "Codex: ~/.codex/config.toml [mcp_servers.ios-shortcuts]",
                    ],
                }
            )

        return _err(f"Unknown tool: {tool_name}")

    except KeyError as exc:
        return _err(f"Missing / unknown key: {exc}")
    except FileNotFoundError as exc:
        return _err(f"File not found: {exc}")
    except subprocess.TimeoutExpired:
        return _err(f"Tool '{tool_name}' timed out")
    except Exception as exc:
        log(traceback.format_exc())
        return _err(f"Exception in {tool_name}: {exc}")


# ---------------------------------------------------------------------------
# MCP stdio transport (Content-Length + NDJSON)
# ---------------------------------------------------------------------------

def _write_message(payload: dict, *, framed: bool) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if framed:
        encoded = body.encode("utf-8")
        header = f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii")
        sys.stdout.buffer.write(header + encoded)
        sys.stdout.buffer.flush()
    else:
        sys.stdout.write(body + "\n")
        sys.stdout.flush()


def respond(response_obj: dict, *, framed: bool) -> None:
    _write_message(response_obj, framed=framed)


def _read_framed_message(first_line: str) -> Optional[dict]:
    """Parse Content-Length framed message starting with first header line."""
    headers = first_line.strip()
    # Read remaining headers
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        headers += "\n" + line.decode("ascii", errors="replace").strip()

    match = re.search(r"Content-Length:\s*(\d+)", headers, re.I)
    if not match:
        return None
    length = int(match.group(1))
    body = sys.stdin.buffer.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def read_request() -> Optional[tuple]:
    """
    Read one JSON-RPC request.
    Returns (request_dict, framed: bool) or None on EOF.
    """
    # Peek / read first line from binary to support both modes.
    # For framed mode, first line is "Content-Length: N".
    line_bytes = sys.stdin.buffer.readline()
    if not line_bytes:
        return None

    line = line_bytes.decode("utf-8", errors="replace")
    if not line.strip():
        # skip blank lines
        return read_request()

    if line.lower().startswith("content-length:"):
        req = _read_framed_message(line)
        if req is None:
            return None
        return req, True

    # NDJSON fallback
    try:
        return json.loads(line), False
    except json.JSONDecodeError:
        log(f"Ignoring non-JSON line: {line[:120]!r}")
        return read_request()


def handle_request(req: dict, *, framed: bool) -> None:
    msg_id = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}

    # Notifications (no id) — acknowledge silently where needed.
    if method == "notifications/initialized":
        return
    if method == "notifications/cancelled":
        return

    if method == "initialize":
        respond(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                    "instructions": (
                        "Build, sign, import, list, run, and inspect iOS/macOS "
                        "Shortcuts on this Mac. Prefer list_actions → validate_recipe "
                        "→ build_shortcut (or build_and_install). Use doctor for env checks."
                    ),
                },
            },
            framed=framed,
        )
        return

    if method == "tools/list":
        respond(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": TOOLS},
            },
            framed=framed,
        )
        return

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        result = handle_tool_call(tool_name, arguments)
        respond(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": result,
            },
            framed=framed,
        )
        return

    if method == "ping":
        respond({"jsonrpc": "2.0", "id": msg_id, "result": {}}, framed=framed)
        return

    if method == "resources/list":
        respond(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"resources": []},
            },
            framed=framed,
        )
        return

    if method == "prompts/list":
        respond(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "prompts": [
                        {
                            "name": "build_work_shortcut",
                            "description": (
                                "Guide for building a multi-step work check-in shortcut"
                            ),
                        },
                        {
                            "name": "discover_actions",
                            "description": "Discover available actions then build",
                        },
                    ]
                },
            },
            framed=framed,
        )
        return

    if method == "prompts/get":
        name = params.get("name")
        if name == "build_work_shortcut":
            text = (
                "1. Call list_actions with query for volume/screenshot/app.\n"
                "2. validate_recipe with your actions array.\n"
                "3. build_and_install with a clear Korean/English name.\n"
                "4. run_shortcut to smoke-test on macOS.\n"
            )
        else:
            text = (
                "Call list_actions, pick types, validate_recipe, then "
                "build_shortcut or build_and_install."
            )
        respond(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "description": name or "prompt",
                    "messages": [
                        {
                            "role": "user",
                            "content": {"type": "text", "text": text},
                        }
                    ],
                },
            },
            framed=framed,
        )
        return

    # Unknown method
    if msg_id is not None:
        respond(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                },
            },
            framed=framed,
        )


def main() -> None:
    log(f"starting {SERVER_NAME} v{SERVER_VERSION}")
    while True:
        try:
            got = read_request()
        except Exception:
            log(traceback.format_exc())
            continue
        if got is None:
            break
        req, framed = got
        try:
            handle_request(req, framed=framed)
        except Exception:
            log(traceback.format_exc())
            msg_id = req.get("id") if isinstance(req, dict) else None
            if msg_id is not None:
                respond(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {
                            "code": -32603,
                            "message": "Internal server error",
                        },
                    },
                    framed=framed,
                )


if __name__ == "__main__":
    main()
