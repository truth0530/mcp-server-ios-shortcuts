#!/usr/bin/env python3
"""
iOS / macOS Shortcuts MCP Server (zero third-party deps, stdio JSON-RPC).

Works with Grok Build, Codex CLI, Claude Desktop/Code, Cursor, Gemini /
Antigravity, and any stdio MCP client.

Supports both:
  - Content-Length framed messages (MCP stdio transport)
  - Newline-delimited JSON (legacy / simple clients)
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import traceback
from typing import Any, Dict, List, Optional, Sequence, Tuple

from shortcut_builder import (
    ACTION_MAPPINGS,
    ACTION_RECIPE_ITEM_SCHEMA,
    DANGEROUS_ACTIONS,
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
SERVER_VERSION = "2.2.0"
PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_PROTOCOL_VERSIONS = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
)


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


MAX_MESSAGE_BYTES = _positive_int_env(
    "IOS_SHORTCUTS_MCP_MAX_MESSAGE_BYTES",
    8 * 1024 * 1024,
)

# Default artifact directory (overridable via env or tool args).
DEFAULT_OUTPUT_DIR = os.path.abspath(
    os.environ.get(
        "IOS_SHORTCUTS_MCP_DIST",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist"),
    )
)

# When true, reject shell/AppleScript/JXA recipe actions and high-risk tools.
SAFE_MODE = _env_flag("IOS_SHORTCUTS_MCP_SAFE_MODE", False)

# Comma or os.pathsep-separated extra roots allowed for write paths.
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def _parse_allow_roots() -> List[str]:
    roots = [DEFAULT_OUTPUT_DIR, _REPO_ROOT]
    extra = os.environ.get("IOS_SHORTCUTS_MCP_ALLOW_ROOTS", "")
    if extra:
        parts = re.split(r"[{0},;]".format(re.escape(os.pathsep)), extra)
        for part in parts:
            part = part.strip()
            if part:
                roots.append(os.path.abspath(os.path.expanduser(part)))
    # De-dupe while preserving order
    seen = set()
    out: List[str] = []
    for r in roots:
        r = os.path.abspath(r)
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


ALLOW_ROOTS = _parse_allow_roots()


# ---------------------------------------------------------------------------
# Logging (stderr only — stdout is the MCP transport)
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    sys.stderr.write("[{0}] {1}\n".format(SERVER_NAME, msg))
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Path sandbox
# ---------------------------------------------------------------------------

def _is_under_roots(path: str, roots: Sequence[str]) -> bool:
    abs_path = os.path.abspath(path)
    for root in roots:
        root_abs = os.path.abspath(root)
        try:
            common = os.path.commonpath([abs_path, root_abs])
        except ValueError:
            continue
        if common == root_abs:
            return True
    return False


def resolve_write_path(path: str, *, label: str = "path") -> str:
    """Resolve and enforce write sandbox (ALLOW_ROOTS)."""
    if not path or not isinstance(path, str):
        raise PermissionError("{0} must be a non-empty string".format(label))
    abs_path = os.path.abspath(os.path.expanduser(path))
    if not _is_under_roots(abs_path, ALLOW_ROOTS):
        raise PermissionError(
            "{0} escapes allow roots: {1} (allowed: {2}). "
            "Set IOS_SHORTCUTS_MCP_ALLOW_ROOTS or use default dist.".format(
                label, abs_path, ", ".join(ALLOW_ROOTS)
            )
        )
    return abs_path


def resolve_write_dir(path: str, *, label: str = "output_dir") -> str:
    abs_path = resolve_write_path(path, label=label)
    os.makedirs(abs_path, exist_ok=True)
    return abs_path


def resolve_read_path(path: str, *, label: str = "path") -> str:
    """Read paths: must exist; any location allowed for inspect/import of user files."""
    if not path or not isinstance(path, str):
        raise FileNotFoundError("{0} must be a non-empty string".format(label))
    abs_path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(abs_path):
        raise FileNotFoundError("{0}: {1}".format(label, abs_path))
    return abs_path


# ---------------------------------------------------------------------------
# Shared schema fragments
# ---------------------------------------------------------------------------

ACTIONS_ARRAY_SCHEMA: Dict[str, Any] = {
    "type": "array",
    "description": "Recipe: list of {type, params} action objects",
    "minItems": 1,
    "items": ACTION_RECIPE_ITEM_SCHEMA,
}


def _ann(
    *,
    title: str,
    read_only: bool = False,
    destructive: bool = False,
    idempotent: bool = False,
    open_world: bool = False,
) -> Dict[str, Any]:
    return {
        "title": title,
        "readOnlyHint": read_only,
        "destructiveHint": destructive,
        "idempotentHint": idempotent,
        "openWorldHint": open_world,
    }


def _tool(
    name: str,
    description: str,
    properties: Dict[str, Any],
    required: Optional[List[str]] = None,
    *,
    annotations: Optional[Dict[str, Any]] = None,
    output_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    tool: Dict[str, Any] = {
        "name": name,
        "description": description,
        "inputSchema": schema,
    }
    if annotations:
        tool["annotations"] = annotations
    if output_schema:
        tool["outputSchema"] = output_schema
    return tool


GENERIC_OK_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
    },
    "additionalProperties": True,
}


TOOLS: List[Dict[str, Any]] = [
    _tool(
        "list_actions",
        "List supported high-level shortcut action types with parameter docs "
        "and examples. Call this before build_shortcut when unsure which "
        "action types exist.",
        {
            "query": {
                "type": "string",
                "description": "Optional substring filter on type/summary/identifier",
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 200, max 500)",
            },
        },
        annotations=_ann(title="List Actions", read_only=True, idempotent=True),
        output_schema=GENERIC_OK_SCHEMA,
    ),
    _tool(
        "list_templates",
        "List built-in shortcut recipe templates.",
        {},
        annotations=_ann(title="List Templates", read_only=True, idempotent=True),
    ),
    _tool(
        "get_template",
        "Return the full action recipe for a built-in template "
        "(e.g. hello_world, screenshot_ocr, shell_echo).",
        {
            "name": {
                "type": "string",
                "description": "Template name from list_templates",
            }
        },
        ["name"],
        annotations=_ann(title="Get Template", read_only=True, idempotent=True),
    ),
    _tool(
        "validate_recipe",
        "Dry-run compile an action recipe without writing files. "
        "Returns ok/errors/warnings/risks and compiled action count. "
        "Respects server safe_mode for dangerous actions.",
        {"actions": ACTIONS_ARRAY_SCHEMA},
        ["actions"],
        annotations=_ann(title="Validate Recipe", read_only=True, idempotent=True),
    ),
    _tool(
        "build_shortcut",
        "Create a macOS/iOS .shortcut binary from a high-level action recipe. "
        "Always writes *_raw.shortcut; signs to *.shortcut when possible. "
        "Returns raw_path, signed_path, path (best), actions_summary.",
        {
            "name": {
                "type": "string",
                "description": "Shortcut display / file name",
            },
            "actions": ACTIONS_ARRAY_SCHEMA,
            "output_dir": {
                "type": "string",
                "description": "Output directory under allow roots (default: dist)",
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
                "description": 'e.g. ["NCWidget", "WatchKit", "ActionExtension"]',
            },
        },
        ["name", "actions"],
        annotations=_ann(title="Build Shortcut", destructive=False, open_world=False),
    ),
    _tool(
        "create_from_template",
        "Build (and optionally import) a shortcut from a built-in template.",
        {
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
        ["template"],
        annotations=_ann(title="Create From Template"),
    ),
    _tool(
        "build_and_install",
        "One-shot: build + sign + prompt import into the local macOS Shortcuts library. "
        "Import is GUI-prompted (status import_prompted), not a confirmed install.",
        {
            "name": {"type": "string"},
            "actions": ACTIONS_ARRAY_SCHEMA,
            "output_dir": {"type": "string"},
            "icon_color": {"type": "string"},
        },
        ["name", "actions"],
        annotations=_ann(title="Build And Install", open_world=True),
    ),
    _tool(
        "sign_shortcut",
        "Sign an unsigned .shortcut file with macOS `shortcuts sign` "
        "for iOS 15+ / modern Shortcuts compatibility. output_path must be under allow roots.",
        {
            "input_path": {"type": "string"},
            "output_path": {"type": "string"},
            "mode": {
                "type": "string",
                "description": "anyone | people-who-know-me (default anyone)",
            },
        },
        ["input_path", "output_path"],
        annotations=_ann(title="Sign Shortcut"),
    ),
    _tool(
        "inspect_shortcut",
        "Inspect a .shortcut file. Signed packages auto-follow sibling *_raw.shortcut "
        "when present (produced by this server's builds).",
        {
            "path": {
                "type": "string",
                "description": "Path to .shortcut file",
            }
        },
        ["path"],
        annotations=_ann(title="Inspect Shortcut", read_only=True, idempotent=True),
    ),
    _tool(
        "import_shortcut",
        "Prompt import of a .shortcut into the macOS Shortcuts library "
        "(opens the file; user may still need to confirm in GUI).",
        {"shortcut_path": {"type": "string"}},
        ["shortcut_path"],
        annotations=_ann(title="Import Shortcut", open_world=True),
    ),
    _tool(
        "view_shortcut",
        "Open an installed shortcut by name in the Shortcuts app.",
        {
            "name": {
                "type": "string",
                "description": "Installed shortcut name",
            }
        },
        ["name"],
        annotations=_ann(title="View Shortcut", open_world=True),
    ),
    _tool(
        "list_shortcuts",
        "List installed Shortcuts on this Mac. Optionally filter by folder "
        "or show identifiers / folders only.",
        {
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
        annotations=_ann(title="List Shortcuts", read_only=True, idempotent=True),
    ),
    _tool(
        "run_shortcut",
        "Run an installed shortcut by name. Supports optional text stdin, "
        "input file path, and output file path (macOS shortcuts CLI). "
        "output_path must be under allow roots when provided.",
        {
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
        ["name"],
        annotations=_ann(
            title="Run Shortcut",
            destructive=True,
            open_world=True,
        ),
    ),
    _tool(
        "send_imessage",
        "Open an iMessage compose window for a recipient and reveal a file "
        "(e.g. .shortcut) in Finder so the user can attach and send it. "
        "Does NOT auto-send (safety). Blocked in safe_mode.",
        {
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
        ["recipient", "file_path"],
        annotations=_ann(
            title="Send iMessage (compose only)",
            destructive=False,
            open_world=True,
        ),
    ),
    _tool(
        "doctor",
        "Environment health check: Python, macOS shortcuts CLI, sign round-trip, "
        "allow roots, safe_mode, default dist writability.",
        {},
        annotations=_ann(title="Doctor", read_only=True, idempotent=True),
    ),
]


# ---------------------------------------------------------------------------
# Tool result helpers
# ---------------------------------------------------------------------------

def _ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _ok_json(payload: Any) -> dict:
    if isinstance(payload, dict) and "ok" not in payload:
        payload = dict(payload)
        payload["ok"] = True
    result = _ok(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    result["structuredContent"] = payload
    return result


def _err(
    text: str,
    *,
    code: str = "ERROR",
    details: Optional[dict] = None,
) -> dict:
    payload: Dict[str, Any] = {
        "ok": False,
        "code": code,
        "message": text,
    }
    if details is not None:
        payload["details"] = details
    return {
        "content": [{"type": "text", "text": text}],
        "isError": True,
        "structuredContent": payload,
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


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def handle_tool_call(tool_name: str, arguments: Optional[dict]) -> dict:
    if not isinstance(tool_name, str) or not tool_name:
        return _err("Tool name must be a non-empty string", code="INVALID_TOOL")
    if arguments is not None and not isinstance(arguments, dict):
        return _err("Tool arguments must be a JSON object", code="INVALID_PARAMS")
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
            limit = max(1, min(int(args.get("limit") or 200), 500))
            return _ok_json(
                {
                    "count": len(items[:limit]),
                    "total_available": len(ACTION_MAPPINGS),
                    "safe_mode": SAFE_MODE,
                    "dangerous_actions": sorted(DANGEROUS_ACTIONS),
                    "actions": items[:limit],
                }
            )

        if tool_name == "list_templates":
            return _ok_json(
                {
                    "templates": list_templates(),
                    "safe_mode": SAFE_MODE,
                }
            )

        if tool_name == "get_template":
            return _ok_json(get_template(args["name"]))

        if tool_name == "validate_recipe":
            result = validate_actions(
                args.get("actions", []),
                safe_mode=SAFE_MODE,
            )
            return _ok_json(result)

        if tool_name == "build_shortcut":
            name = args["name"]
            actions = args.get("actions", [])
            output_dir = resolve_write_dir(
                args.get("output_dir") or DEFAULT_OUTPUT_DIR,
                label="output_dir",
            )
            sign = _as_bool(args.get("sign", True), True)
            built = build_shortcut_plist(
                actions,
                name,
                output_dir,
                sign=sign,
                sign_mode=args.get("sign_mode") or "anyone",
                icon_color=args.get("icon_color"),
                icon_glyph=args.get("icon_glyph"),
                workflow_types=args.get("workflow_types"),
                safe_mode=SAFE_MODE,
            )
            built["hint"] = (
                "Import via import_shortcut / build_and_install. "
                "Inspect via inspect_shortcut on path or raw_path."
                if built.get("signed")
                else "Signing failed or skipped; use raw_path. See sign_error."
            )
            return _ok_json(built)

        if tool_name == "create_from_template":
            tpl = get_template(args["template"])
            name = args.get("name") or args["template"]
            output_dir = resolve_write_dir(
                args.get("output_dir") or DEFAULT_OUTPUT_DIR,
                label="output_dir",
            )
            built = build_shortcut_plist(
                tpl["actions"],
                name,
                output_dir,
                sign=True,
                icon_color=args.get("icon_color"),
                safe_mode=SAFE_MODE,
            )
            imported = False
            import_status = "not_requested"
            if args.get("import_after_build"):
                res = _run(["open", built["path"]])
                imported = res.returncode == 0
                import_status = "import_prompted" if imported else "import_failed"
            built.update(
                {
                    "template": args["template"],
                    "description": tpl.get("description"),
                    "imported": imported,
                    "import_status": import_status,
                }
            )
            return _ok_json(built)

        if tool_name == "build_and_install":
            name = args["name"]
            actions = args.get("actions", [])
            output_dir = resolve_write_dir(
                args.get("output_dir") or DEFAULT_OUTPUT_DIR,
                label="output_dir",
            )
            built = build_shortcut_plist(
                actions,
                name,
                output_dir,
                sign=True,
                icon_color=args.get("icon_color"),
                safe_mode=SAFE_MODE,
            )
            res = _run(["open", built["path"]])
            built.update(
                {
                    "import_triggered": res.returncode == 0,
                    "import_status": (
                        "import_prompted" if res.returncode == 0 else "import_failed"
                    ),
                    "stderr": (res.stderr or "").strip() or None,
                    "note": (
                        "macOS opened the .shortcut; user may still need to confirm "
                        "in the Shortcuts import UI."
                    ),
                }
            )
            return _ok_json(built)

        if tool_name == "sign_shortcut":
            inp = resolve_read_path(args["input_path"], label="input_path")
            outp = resolve_write_path(args["output_path"], label="output_path")
            ok, msg = sign_shortcut_file(
                inp, outp, mode=args.get("mode") or "anyone"
            )
            if ok:
                raw = None
                if inp.endswith("_raw.shortcut"):
                    raw = inp
                return _ok_json(
                    {
                        "path": msg,
                        "signed_path": msg,
                        "raw_path": raw,
                    }
                )
            return _err(
                "Signing error: {0}".format(msg),
                code="SIGN_FAILED",
                details={"input_path": inp, "output_path": outp},
            )

        if tool_name == "inspect_shortcut":
            path = resolve_read_path(args["path"], label="path")
            return _ok_json(inspect_shortcut_file(path))

        if tool_name == "import_shortcut":
            path = resolve_read_path(args["shortcut_path"], label="shortcut_path")
            res = _run(["open", path])
            if res.returncode != 0:
                return _err(
                    "Import failed: {0}".format(res.stderr or res.stdout),
                    code="IMPORT_FAILED",
                )
            return _ok_json(
                {
                    "path": path,
                    "import_status": "import_prompted",
                    "message": (
                        "Triggered import UI for {0}. Confirm in Shortcuts if prompted."
                    ).format(path),
                }
            )

        if tool_name == "view_shortcut":
            name = args["name"]
            res = _run(["shortcuts", "view", name])
            if res.returncode != 0:
                return _err(
                    "view failed: {0}".format(res.stderr or res.stdout),
                    code="VIEW_FAILED",
                )
            return _ok_json(
                {
                    "name": name,
                    "message": "Opened shortcut '{0}' in Shortcuts app.".format(name),
                }
            )

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
                return _err(
                    "Error listing shortcuts: {0}".format(res.stderr or res.stdout),
                    code="LIST_FAILED",
                )
            lines = [ln for ln in (res.stdout or "").splitlines() if ln.strip()]
            return _ok_json({"count": len(lines), "shortcuts": lines})

        if tool_name == "run_shortcut":
            if SAFE_MODE:
                return _err(
                    "run_shortcut is blocked in safe mode "
                    "(IOS_SHORTCUTS_MCP_SAFE_MODE=1)",
                    code="SAFE_MODE",
                )
            name = args["name"]
            cmd = ["shortcuts", "run", name]
            if args.get("input_path"):
                cmd.extend(
                    [
                        "--input-path",
                        resolve_read_path(args["input_path"], label="input_path"),
                    ]
                )
            if args.get("output_path"):
                outp = resolve_write_path(args["output_path"], label="output_path")
                parent = os.path.dirname(outp) or "."
                os.makedirs(parent, exist_ok=True)
                cmd.extend(["--output-path", outp])
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
                return _err(
                    json.dumps(payload, indent=2),
                    code="RUN_FAILED",
                    details=payload,
                )
            return _ok_json(payload)

        if tool_name == "send_imessage":
            if SAFE_MODE:
                return _err(
                    "send_imessage is blocked in safe mode "
                    "(IOS_SHORTCUTS_MCP_SAFE_MODE=1)",
                    code="SAFE_MODE",
                )
            rec = args["recipient"]
            if not isinstance(rec, str) or not rec.strip():
                return _err("recipient must be a non-empty string", code="INVALID_PARAMS")
            # Soft sanitize for URI (strip control chars)
            rec_clean = re.sub(r"[\x00-\x1f\x7f]", "", rec.strip())
            path = resolve_read_path(args["file_path"], label="file_path")
            msg = args.get("message") or "Shortcut file attached."
            _run(["open", "imessage://{0}".format(rec_clean)])
            _run(["open", "-R", path])
            return _ok_json(
                {
                    "recipient": rec_clean,
                    "file_path": path,
                    "message_hint": msg,
                    "note": (
                        "Opened Messages compose and revealed the file in Finder. "
                        "User must attach and send manually."
                    ),
                }
            )

        if tool_name == "doctor":
            return _ok_json(_run_doctor())

        return _err("Unknown tool: {0}".format(tool_name), code="UNKNOWN_TOOL")

    except PermissionError as exc:
        return _err(str(exc), code="PATH_SANDBOX")
    except KeyError as exc:
        return _err(
            "Missing / unknown key: {0}".format(exc),
            code="INVALID_PARAMS",
        )
    except FileNotFoundError as exc:
        return _err("File not found: {0}".format(exc), code="NOT_FOUND")
    except ValueError as exc:
        return _err(str(exc), code="VALIDATION_ERROR")
    except subprocess.TimeoutExpired:
        return _err(
            "Tool '{0}' timed out".format(tool_name),
            code="TIMEOUT",
        )
    except Exception as exc:
        log(traceback.format_exc())
        return _err(
            "Exception in {0}: {1}".format(tool_name, exc),
            code="INTERNAL",
        )


def _run_doctor() -> Dict[str, Any]:
    shortcuts_path = None
    shortcuts_ok = False
    try:
        which = _run(["/usr/bin/which", "shortcuts"])
        shortcuts_path = (which.stdout or "").strip() or None
        help_res = _run(["shortcuts", "help"])
        shortcuts_ok = help_res.returncode == 0
    except Exception as exc:
        shortcuts_path = "error: {0}".format(exc)

    dist_writable = False
    try:
        os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
        probe = os.path.join(DEFAULT_OUTPUT_DIR, ".doctor_write_probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok\n")
        os.remove(probe)
        dist_writable = True
    except OSError as exc:
        dist_writable = False
        dist_write_error = str(exc)
    else:
        dist_write_error = None

    sign_probe: Dict[str, Any] = {
        "attempted": False,
        "ok": False,
        "error": None,
        "raw_path": None,
        "signed_path": None,
    }
    if shortcuts_ok and dist_writable:
        sign_probe["attempted"] = True
        try:
            built = build_shortcut_plist(
                [
                    {
                        "type": "comment",
                        "params": {"text": "ios-shortcuts-mcp doctor probe"},
                    },
                    {
                        "type": "nothing",
                        "params": {},
                    },
                ],
                "DoctorProbe",
                DEFAULT_OUTPUT_DIR,
                sign=True,
                safe_mode=False,
            )
            sign_probe["raw_path"] = built.get("raw_path")
            sign_probe["signed_path"] = built.get("signed_path")
            sign_probe["ok"] = bool(built.get("signed"))
            if not built.get("signed"):
                sign_probe["error"] = built.get("sign_error") or "sign failed"
            # Prefer inspect on signed to verify raw sibling path
            if built.get("path"):
                insp = inspect_shortcut_file(built["path"])
                sign_probe["inspect_format"] = insp.get("format")
                sign_probe["inspect_action_count"] = insp.get("action_count")
        except Exception as exc:
            sign_probe["error"] = str(exc)

    mac_ver = None
    try:
        mac_ver = platform.mac_ver()[0] or None
    except Exception:
        pass

    healthy = bool(
        sys.platform == "darwin"
        and shortcuts_ok
        and dist_writable
        and (sign_probe["ok"] or not sign_probe["attempted"])
    )
    # If sign was attempted and failed, not fully healthy
    if sign_probe["attempted"] and not sign_probe["ok"]:
        healthy = False

    hints = [
        "macOS Monterey+ required for `shortcuts` CLI",
        "Signing uses `shortcuts sign -m anyone`",
        "Grok: ~/.grok/config.toml [mcp_servers.ios-shortcuts]",
        "Codex: ~/.codex/config.toml [mcp_servers.ios-shortcuts]",
        "Writes restricted to IOS_SHORTCUTS_MCP_ALLOW_ROOTS / default dist",
        "Set IOS_SHORTCUTS_MCP_SAFE_MODE=1 to block shell/JXA and run/send tools",
    ]
    if not shortcuts_ok:
        hints.insert(0, "Open the Shortcuts app once, then re-run doctor")
    if sign_probe["attempted"] and not sign_probe["ok"]:
        hints.insert(0, "Sign probe failed — check Shortcuts signing permissions")

    return {
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "healthy": healthy,
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "macos_version": mac_ver,
        "safe_mode": SAFE_MODE,
        "shortcuts_cli": {
            "path": shortcuts_path,
            "available": shortcuts_ok,
        },
        "sign_probe": sign_probe,
        "default_output_dir": DEFAULT_OUTPUT_DIR,
        "dist_writable": dist_writable,
        "dist_write_error": dist_write_error,
        "allow_roots": ALLOW_ROOTS,
        "action_types": len(ACTION_MAPPINGS),
        "templates": len(TEMPLATES),
        "dangerous_actions": sorted(DANGEROUS_ACTIONS),
        "tools": [t["name"] for t in TOOLS],
        "env": {
            "IOS_SHORTCUTS_MCP_DIST": os.environ.get("IOS_SHORTCUTS_MCP_DIST"),
            "IOS_SHORTCUTS_MCP_SAFE_MODE": os.environ.get("IOS_SHORTCUTS_MCP_SAFE_MODE"),
            "IOS_SHORTCUTS_MCP_ALLOW_ROOTS": os.environ.get(
                "IOS_SHORTCUTS_MCP_ALLOW_ROOTS"
            ),
            "IOS_SHORTCUTS_MCP_MAX_MESSAGE_BYTES": os.environ.get(
                "IOS_SHORTCUTS_MCP_MAX_MESSAGE_BYTES"
            ),
        },
        "hints": hints,
    }


# ---------------------------------------------------------------------------
# MCP stdio transport (Content-Length + NDJSON)
# ---------------------------------------------------------------------------

def _write_message(payload: dict, *, framed: bool) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if framed:
        encoded = body.encode("utf-8")
        header = "Content-Length: {0}\r\n\r\n".format(len(encoded)).encode("ascii")
        sys.stdout.buffer.write(header + encoded)
        sys.stdout.buffer.flush()
    else:
        sys.stdout.write(body + "\n")
        sys.stdout.flush()


def respond(response_obj: dict, *, framed: bool) -> None:
    _write_message(response_obj, framed=framed)


class RequestReadError(Exception):
    """A transport error that should become a JSON-RPC parse-error response."""

    def __init__(self, message: str, *, framed: bool, fatal: bool = False) -> None:
        super().__init__(message)
        self.framed = framed
        self.fatal = fatal


def _rpc_error(
    code: int,
    message: str,
    *,
    msg_id: Any = None,
    data: Optional[dict] = None,
) -> dict:
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": error}


def _read_framed_message(first_line: str) -> dict:
    """Parse Content-Length framed message starting with first header line."""
    headers = [first_line.strip()]
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            raise RequestReadError(
                "Unexpected EOF while reading headers",
                framed=True,
                fatal=True,
            )
        if line in (b"\r\n", b"\n"):
            break
        headers.append(line.decode("ascii", errors="replace").strip())

    match = re.search(r"^Content-Length:\s*(\d+)\s*$", "\n".join(headers), re.I | re.M)
    if not match:
        raise RequestReadError(
            "Missing or invalid Content-Length header",
            framed=True,
            fatal=True,
        )
    length = int(match.group(1))
    if length <= 0:
        raise RequestReadError("Content-Length must be greater than zero", framed=True)
    if length > MAX_MESSAGE_BYTES:
        raise RequestReadError(
            "Message exceeds {0} byte limit".format(MAX_MESSAGE_BYTES),
            framed=True,
            fatal=True,
        )
    body = sys.stdin.buffer.read(length)
    if len(body) != length:
        raise RequestReadError(
            "Unexpected EOF while reading message body",
            framed=True,
            fatal=True,
        )
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestReadError("Parse error: {0}".format(exc), framed=True) from exc


def read_request() -> Optional[Tuple[dict, bool]]:
    """
    Read one JSON-RPC request.
    Returns (request_dict, framed: bool) or None on EOF.
    """
    while True:
        line_bytes = sys.stdin.buffer.readline(MAX_MESSAGE_BYTES + 1)
        if not line_bytes:
            return None
        if len(line_bytes) > MAX_MESSAGE_BYTES:
            raise RequestReadError(
                "Message exceeds {0} byte limit".format(MAX_MESSAGE_BYTES),
                framed=False,
            )

        try:
            line = line_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RequestReadError(
                "Parse error: {0}".format(exc), framed=False
            ) from exc
        if not line.strip():
            continue
        if line.lower().startswith("content-length:"):
            return _read_framed_message(line), True
        try:
            return json.loads(line), False
        except json.JSONDecodeError as exc:
            raise RequestReadError(
                "Parse error: {0}".format(exc), framed=False
            ) from exc


def handle_request(req: dict, *, framed: bool) -> None:
    if not isinstance(req, dict):
        respond(_rpc_error(-32600, "Invalid Request"), framed=framed)
        return

    msg_id = req.get("id")
    method = req.get("method")
    is_notification = "id" not in req
    if req.get("jsonrpc") != "2.0" or not isinstance(method, str):
        if not is_notification:
            respond(
                _rpc_error(-32600, "Invalid Request", msg_id=msg_id),
                framed=framed,
            )
        return

    params = req.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        if not is_notification:
            respond(
                _rpc_error(
                    -32602,
                    "Invalid params: expected an object",
                    msg_id=msg_id,
                ),
                framed=framed,
            )
        return

    if method == "notifications/initialized":
        return
    if method == "notifications/cancelled":
        return
    if is_notification and method != "tools/call":
        return

    if method == "initialize":
        client_version = params.get("protocolVersion") or PROTOCOL_VERSION
        negotiated = (
            client_version
            if client_version in SUPPORTED_PROTOCOL_VERSIONS
            else PROTOCOL_VERSION
        )
        respond(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": negotiated,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "prompts": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                    "instructions": (
                        "Build, sign, import, list, run, and inspect iOS/macOS "
                        "Shortcuts on this Mac. Prefer list_actions → validate_recipe "
                        "→ build_shortcut (or build_and_install). Use doctor for env checks. "
                        "Builds always keep *_raw.shortcut for inspect. "
                        "Writes are sandboxed to allow roots; safe_mode blocks shell/JXA."
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
        if not isinstance(tool_name, str) or not isinstance(arguments, dict):
            if not is_notification:
                respond(
                    _rpc_error(
                        -32602,
                        "Invalid params: tools/call requires string name "
                        "and object arguments",
                        msg_id=msg_id,
                    ),
                    framed=framed,
                )
            return
        result = handle_tool_call(tool_name, arguments)
        if not is_notification:
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
                "result": {
                    "resources": [
                        {
                            "uri": "shortcut://catalog/actions",
                            "name": "Action catalog",
                            "description": "Supported high-level action types",
                            "mimeType": "application/json",
                        },
                        {
                            "uri": "shortcut://catalog/templates",
                            "name": "Template catalog",
                            "description": "Built-in recipe templates",
                            "mimeType": "application/json",
                        },
                    ]
                },
            },
            framed=framed,
        )
        return

    if method == "resources/read":
        uri = params.get("uri") or ""
        if uri == "shortcut://catalog/actions":
            body = json.dumps(
                {"actions": list_supported_actions()},
                ensure_ascii=False,
                indent=2,
            )
        elif uri == "shortcut://catalog/templates":
            body = json.dumps(
                {"templates": list_templates()},
                ensure_ascii=False,
                indent=2,
            )
        else:
            if not is_notification:
                respond(
                    _rpc_error(
                        -32602,
                        "Unknown resource uri: {0}".format(uri),
                        msg_id=msg_id,
                    ),
                    framed=framed,
                )
            return
        respond(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": body,
                        }
                    ]
                },
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
                            "arguments": [
                                {
                                    "name": "name",
                                    "description": "Shortcut name",
                                    "required": False,
                                },
                                {
                                    "name": "goal",
                                    "description": "What the shortcut should accomplish",
                                    "required": False,
                                },
                            ],
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
        pargs = params.get("arguments") or {}
        sc_name = pargs.get("name") or "WorkCheckIn"
        goal = pargs.get("goal") or "check-in flow with volume, app, wait, capture"
        if name == "build_work_shortcut":
            text = (
                "Goal: {goal}\n"
                "Suggested name: {sc_name}\n"
                "1. Call list_actions (query volume/screenshot/app) or read "
                "resource shortcut://catalog/actions.\n"
                "2. validate_recipe with your actions array.\n"
                "3. build_and_install (or build_shortcut) with name={sc_name}.\n"
                "4. inspect_shortcut on the returned path (uses raw sibling if signed).\n"
                "5. run_shortcut to smoke-test on macOS (disabled in safe_mode).\n"
            ).format(goal=goal, sc_name=sc_name)
        else:
            text = (
                "Call list_actions or resources/read shortcut://catalog/actions, "
                "pick types, validate_recipe, then build_shortcut or build_and_install. "
                "Prefer dual paths raw_path + signed_path in the tool result."
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

    if not is_notification:
        respond(
            _rpc_error(-32601, "Method not found: {0}".format(method), msg_id=msg_id),
            framed=framed,
        )


def main() -> None:
    log(
        "starting {0} v{1} safe_mode={2} dist={3}".format(
            SERVER_NAME, SERVER_VERSION, SAFE_MODE, DEFAULT_OUTPUT_DIR
        )
    )
    while True:
        try:
            got = read_request()
        except RequestReadError as exc:
            log(str(exc))
            respond(_rpc_error(-32700, str(exc)), framed=exc.framed)
            if exc.fatal:
                break
            continue
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
            if isinstance(req, dict) and "id" in req:
                respond(
                    _rpc_error(-32603, "Internal server error", msg_id=msg_id),
                    framed=framed,
                )


if __name__ == "__main__":
    main()
