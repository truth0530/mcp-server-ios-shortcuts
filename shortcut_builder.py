#!/usr/bin/env python3
"""
iOS / macOS Shortcuts recipe → binary plist (.shortcut) builder.

Zero third-party deps. High-level action recipes are mapped to Apple
Workflow action identifiers and serialized as binary plists, then optionally
signed with the system `shortcuts sign` CLI.
"""

from __future__ import annotations

import os
import re
import uuid
import plistlib
import subprocess
from typing import Any, Dict, List, Optional, Tuple, Union

from action_catalog import (
    CURATED_ALIASES,
    catalog_stats,
    list_catalog_actions,
    preflight_platform,
    resolve_action_type,
    suggest_actions,
)
from magic_vars import (
    RecipeContext,
    collect_aliases,
    explain_magic_syntax,
    resolve_params,
    stamp_action_uuids,
    validate_magic_refs,
    workflow_actions_golden,
)
from wf_serialization import coerce_params

_ROOT = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Action catalog (compat + curated surface)
# ---------------------------------------------------------------------------

# Backward-compatible alias map used by older call sites / tests.
# Full Apple coverage lives in action_catalog + data/apple_action_ids.txt.
ACTION_MAPPINGS: Dict[str, str] = dict(CURATED_ALIASES)

# Condition enums used by is.workflow.actions.conditional
CONDITION_ENUMS: Dict[str, int] = {
    "equals": 4,
    "is": 4,
    "not_equals": 5,
    "is_not": 5,
    "contains": 99,
    "does_not_contain": 999,
    "begins_with": 8,
    "ends_with": 9,
    "greater_than": 2,
    "greater_or_equal": 3,
    "less_than": 0,
    "less_or_equal": 1,
    "has_value": 100,
    "does_not_have_value": 101,
    "is_between": 1003,
}

# Human-readable action docs for list_actions / agent discovery.
ACTION_DOCS: Dict[str, Dict[str, Any]] = {
    "delay": {
        "summary": "Wait N seconds",
        "params": {"seconds": "number (default 1)"},
        "example": {"type": "delay", "params": {"seconds": 3}},
    },
    "open_app": {
        "summary": "Open an app by bundle id / name",
        "params": {
            "bundle_id": "e.g. com.apple.mobilesafari",
            "app_name": "display name",
        },
        "example": {
            "type": "open_app",
            "params": {"bundle_id": "com.apple.MobileSMS", "app_name": "Messages"},
        },
    },
    "open_url": {
        "summary": "Open a URL in the default browser / handler",
        "params": {"url": "https://..."},
        "example": {"type": "open_url", "params": {"url": "https://x.ai"}},
    },
    "speak_text": {
        "summary": "Speak text aloud",
        "params": {"text": "string", "wait": "bool", "rate": "0.0–1.0"},
        "example": {"type": "speak_text", "params": {"text": "Done", "wait": True}},
    },
    "set_volume": {
        "summary": (
            "Set media volume to a literal 0.0–1.0. "
            "Do NOT restore volume from a named variable string — "
            "on iOS that often becomes '알 수 없는 동작' / unbound params."
        ),
        "params": {"volume": "float 0.0–1.0 (prefer literal; avoid variable names)"},
        "example": {"type": "set_volume", "params": {"volume": 1.0}},
    },
    "show_notification": {
        "summary": "Show a local notification",
        "params": {"title": "string", "body": "string"},
        "example": {
            "type": "show_notification",
            "params": {"title": "Herdr", "body": "Check-in complete"},
        },
    },
    "show_alert": {
        "summary": "Show an alert dialog",
        "params": {"title": "string", "message": "string", "show_cancel": "bool"},
        "example": {
            "type": "show_alert",
            "params": {"title": "Confirm", "message": "Continue?", "show_cancel": True},
        },
    },
    "show_result": {
        "summary": "Show result text to the user",
        "params": {"text": "string"},
        "example": {"type": "show_result", "params": {"text": "All done"}},
    },
    "ask": {
        "summary": "Ask the user for input",
        "params": {
            "prompt": "string",
            "default": "optional default answer",
            "input_type": "Text|Number|URL|Date (default Text)",
        },
        "example": {"type": "ask", "params": {"prompt": "Name?", "default": ""}},
    },
    "text": {
        "summary": "Emit a text value",
        "params": {"text": "string"},
        "example": {"type": "text", "params": {"text": "hello"}},
    },
    "set_variable": {
        "summary": "Store previous action output into a named variable",
        "params": {"var_name": "string"},
        "example": {"type": "set_variable", "params": {"var_name": "Result"}},
    },
    "get_variable": {
        "summary": "Retrieve a named variable",
        "params": {"var_name": "string"},
        "example": {"type": "get_variable", "params": {"var_name": "Result"}},
    },
    "set_clipboard": {
        "summary": "Copy input (or provided text) to clipboard",
        "params": {"text": "optional string to copy"},
        "example": {"type": "set_clipboard", "params": {"text": "copied"}},
    },
    "get_clipboard": {
        "summary": "Read the clipboard",
        "params": {},
        "example": {"type": "get_clipboard", "params": {}},
    },
    "get_contents_of_url": {
        "summary": "HTTP request (GET/POST/…) via Download URL",
        "params": {
            "url": "https://...",
            "method": "GET|POST|PUT|PATCH|DELETE",
            "headers": "object of header→value",
            "body": "optional string body",
            "body_type": "JSON|Form|File|string (default JSON when body present)",
        },
        "example": {
            "type": "get_contents_of_url",
            "params": {"url": "https://httpbin.org/get", "method": "GET"},
        },
    },
    "run_shell_script": {
        "summary": "Run a shell script (macOS)",
        "params": {
            "script": "shell source",
            "shell": "/bin/zsh|/bin/bash|…",
            "input_mode": "as arguments|to stdin|off",
        },
        "example": {
            "type": "run_shell_script",
            "params": {"script": "echo hello", "shell": "/bin/zsh"},
        },
    },
    "run_applescript": {
        "summary": "Run AppleScript (macOS)",
        "params": {"script": "AppleScript source"},
        "example": {
            "type": "run_applescript",
            "params": {"script": 'display notification "Hi" with title "Shortcuts"'},
        },
    },
    "run_shortcut": {
        "summary": "Run another shortcut by name",
        "params": {"name": "shortcut name", "show_while_running": "bool"},
        "example": {
            "type": "run_shortcut",
            "params": {"name": "My Other Shortcut", "show_while_running": False},
        },
    },
    "take_screenshot": {
        "summary": "Capture the screen",
        "params": {},
        "example": {"type": "take_screenshot", "params": {}},
    },
    "ocr_extract_text": {
        "summary": "Extract text from the image on the stack",
        "params": {},
        "example": {"type": "ocr_extract_text", "params": {}},
    },
    "send_message": {
        "summary": "Compose / send an iMessage / SMS",
        "params": {
            "recipients": "list of phone/email strings",
            "message": "body text",
            "show_compose": "bool (default true — safer)",
        },
        "example": {
            "type": "send_message",
            "params": {
                "recipients": ["+15551212"],
                "message": "On my way",
                "show_compose": True,
            },
        },
    },
    "conditional_start": {
        "summary": (
            "Start If block (pair with conditional_else / conditional_end). "
            "Prefer previous-action magic stack (no var_name). "
            "If var_name is set, compiler emits Get Variable then If "
            "(does NOT put WFInput Variable on the If — that breaks iOS)."
        ),
        "params": {
            "group_id": "uuid shared across the if/else/end trio",
            "condition": "equals|contains|greater_than|…",
            "value": "comparison value",
            "var_name": "optional named variable; expands to get_variable + If",
        },
        "example": {
            "type": "conditional_start",
            "params": {
                "group_id": "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
                "condition": "contains",
                "value": "OK",
            },
        },
    },
    "conditional_else": {
        "summary": "Else branch of an If block",
        "params": {"group_id": "same uuid as start/end"},
        "example": {
            "type": "conditional_else",
            "params": {"group_id": "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"},
        },
    },
    "conditional_end": {
        "summary": "End If block",
        "params": {"group_id": "same uuid as start"},
        "example": {
            "type": "conditional_end",
            "params": {"group_id": "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"},
        },
    },
    "comment": {
        "summary": "Add a comment (no runtime effect)",
        "params": {"text": "comment body"},
        "example": {"type": "comment", "params": {"text": "--- check-in block ---"}},
    },
    "exit_shortcut": {
        "summary": "Stop the shortcut immediately",
        "params": {},
        "example": {"type": "exit_shortcut", "params": {}},
    },
    "stop_and_output": {
        "summary": "Stop and pass current input as the shortcut output",
        "params": {},
        "example": {"type": "stop_and_output", "params": {}},
    },
    "replace_text": {
        "summary": "Find/replace in text on the stack",
        "params": {
            "find": "string",
            "replace": "string",
            "case_sensitive": "bool",
            "regular_expression": "bool",
        },
        "example": {
            "type": "replace_text",
            "params": {"find": "foo", "replace": "bar", "case_sensitive": False},
        },
    },
    "split_text": {
        "summary": "Split text into a list",
        "params": {"separator": "New Lines|Spaces|Custom", "custom": "if Custom"},
        "example": {"type": "split_text", "params": {"separator": "New Lines"}},
    },
    "combine_text": {
        "summary": "Join list items into text",
        "params": {"separator": "New Lines|Spaces|Custom", "custom": "if Custom"},
        "example": {"type": "combine_text", "params": {"separator": "New Lines"}},
    },
    "change_case": {
        "summary": "Change text case",
        "params": {"case": "UPPERCASE|lowercase|Capitalize Every Word|…"},
        "example": {"type": "change_case", "params": {"case": "UPPERCASE"}},
    },
    "list": {
        "summary": "Create a list from items",
        "params": {"items": ["a", "b", "c"]},
        "example": {"type": "list", "params": {"items": ["A", "B", "C"]}},
    },
    "dictionary": {
        "summary": "Create a dictionary",
        "params": {"items": {"key": "value"}},
        "example": {"type": "dictionary", "params": {"items": {"role": "admin"}}},
    },
    "set_focus": {
        "summary": "Set Focus / Do Not Disturb mode",
        "params": {"mode": "focus name, e.g. Do Not Disturb", "until": "Turned Off|…"},
        "example": {
            "type": "set_focus",
            "params": {"mode": "Do Not Disturb", "until": "Turned Off"},
        },
    },
    "get_battery": {
        "summary": "Get battery level (0–100)",
        "params": {},
        "example": {"type": "get_battery", "params": {}},
    },
    "get_device_details": {
        "summary": "Get device detail field",
        "params": {
            "detail": "Device Name|System Version|Battery Level|…"
        },
        "example": {
            "type": "get_device_details",
            "params": {"detail": "Device Name"},
        },
    },
}

# Built-in recipe templates for create_from_template.
TEMPLATES: Dict[str, Dict[str, Any]] = {
    "hello_world": {
        "description": "Show a notification and speak a greeting",
        "actions": [
            {"type": "show_notification", "params": {"title": "Hello", "body": "From Shortcuts MCP"}},
            {"type": "speak_text", "params": {"text": "Hello from Shortcuts MCP", "wait": True}},
        ],
    },
    "clipboard_to_notification": {
        "description": "Read clipboard, store as variable, show result via magic ref",
        "actions": [
            {"type": "get_clipboard", "params": {}, "as": "ClipOut"},
            {"type": "set_variable", "params": {"var_name": "Clip"}},
            {
                "type": "show_notification",
                "params": {
                    "title": "Clipboard",
                    "body": "Captured via magic alias ClipOut",
                },
            },
            {
                "type": "show_result",
                "params": {"text": {"$ref": "as:ClipOut"}},
            },
        ],
    },
    "magic_chain": {
        "description": "Demo action-output chaining with $ref and ${} interpolation",
        "actions": [
            {
                "type": "text",
                "params": {"text": "Agent"},
                "as": "Name",
            },
            {
                "type": "text",
                "params": {"text": "Hello ${as:Name} from Shortcuts MCP"},
                "as": "Greeting",
            },
            {
                "type": "show_notification",
                "params": {
                    "title": {"$ref": "as:Name"},
                    "body": {"$ref": "as:Greeting"},
                },
            },
            {
                "type": "speak_text",
                "params": {
                    "text": {"$action": 1},
                    "wait": True,
                },
            },
        ],
    },
    "volume_max_and_notify": {
        "description": "Set media volume to 100% and notify",
        "actions": [
            {"type": "set_volume", "params": {"volume": 1.0}},
            {
                "type": "show_notification",
                "params": {"title": "Volume", "body": "Set to 100%"},
            },
        ],
    },
    "screenshot_ocr": {
        "description": (
            "Screenshot → OCR → notify (adjacent magic stack; no crop, no volume restore)"
        ),
        "actions": [
            {"type": "take_screenshot", "params": {}, "as": "Shot"},
            {"type": "ocr_extract_text", "params": {}, "as": "OCR"},
            {
                "type": "show_notification",
                "params": {
                    "title": "OCR",
                    "body": {"$ref": "as:OCR"},
                },
            },
        ],
    },
    "screenshot_ocr_contains": {
        "description": (
            "Screenshot → OCR → If contains text → notify. "
            "No cropimage, no volume save/restore, no vibrate."
        ),
        "actions": [
            {"type": "open_app", "params": {"bundle_id": "com.example.app", "app_name": "Example App"}},
            {"type": "delay", "params": {"seconds": 3}},
            {"type": "take_screenshot", "params": {}},
            {"type": "ocr_extract_text", "params": {}},
            {
                "type": "conditional_start",
                "params": {
                    "group_id": "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB",
                    "condition": "contains",
                    "value": "OK",
                },
            },
            {
                "type": "speak_text",
                "params": {"text": "Target text found", "wait": True},
            },
            {
                "type": "show_notification",
                "params": {
                    "title": "OCR match",
                    "body": "Screenshot text contained the target phrase",
                },
            },
            {
                "type": "conditional_else",
                "params": {"group_id": "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"},
            },
            {
                "type": "speak_text",
                "params": {
                    "text": "Target text not found",
                    "wait": True,
                },
            },
            {
                "type": "show_notification",
                "params": {
                    "title": "OCR miss",
                    "body": "Screenshot text did not contain the target phrase",
                },
            },
            {
                "type": "conditional_end",
                "params": {"group_id": "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"},
            },
        ],
    },
    "open_url_and_wait": {
        "description": "Open a URL, wait 3s, notify done",
        "actions": [
            {"type": "open_url", "params": {"url": "https://x.ai"}},
            {"type": "delay", "params": {"seconds": 3}},
            {
                "type": "show_notification",
                "params": {"title": "URL", "body": "Opened and waited"},
            },
        ],
    },
    "shell_echo": {
        "description": "macOS: run a shell echo and show the result",
        "actions": [
            {
                "type": "run_shell_script",
                "params": {"script": "echo \"hello from shortcuts mcp\"", "shell": "/bin/zsh"},
            },
            {"type": "show_result", "params": {"text": ""}},
        ],
    },
    "morning_focus": {
        "description": "Enable Do Not Disturb style focus and notify",
        "actions": [
            {
                "type": "set_focus",
                "params": {"mode": "Do Not Disturb", "until": "Turned Off"},
            },
            {
                "type": "show_notification",
                "params": {"title": "Focus", "body": "Do Not Disturb enabled"},
            },
        ],
    },
    "http_get_sample": {
        "description": "GET httpbin.org/get and show body",
        "actions": [
            {
                "type": "get_contents_of_url",
                "params": {"url": "https://httpbin.org/get", "method": "GET"},
            },
            {"type": "show_result", "params": {"text": ""}},
        ],
    },
}

# Icon start colors (ARGB as unsigned 32-bit style ints used by Shortcuts).
ICON_COLORS: Dict[str, int] = {
    "red": 4282601983,
    "orange": 4251333119,
    "yellow": 4274264319,
    "green": 4292093695,
    "teal": 431817727,
    "blue": 3908262991,
    "indigo": 2071128575,
    "purple": 3679049983,
    "pink": 3980825855,
    "gray": 255,
    "dark_gray": 3031607807,
    "taupe": 2846468607,
}

DEFAULT_INPUT_CLASSES = [
    "WFAppStoreAppContentItem",
    "WFArticleContentItem",
    "WFContactContentItem",
    "WFDateContentItem",
    "WFEmailAddressContentItem",
    "WFFolderContentItem",
    "WFGenericFileContentItem",
    "WFImageContentItem",
    "WFiTunesProductContentItem",
    "WFLocationContentItem",
    "DCMapsLinkContentItem",
    "AVAssetContentItem",
    "PDFContentItem",
    "PHAssetContentItem",
    "WFPBRichTextContentItem",
    "WFSafariWebPageContentItem",
    "WFStringContentItem",
    "WFURLContentItem",
]

# Actions that execute code or leave the Shortcuts sandbox aggressively.
# Safe mode (server env IOS_SHORTCUTS_MCP_SAFE_MODE) rejects these.
DANGEROUS_ACTIONS = frozenset(
    {
        "run_shell_script",
        "run_applescript",
        "run_javascript_for_automation",
        "is.workflow.actions.runshellscript",
        "is.workflow.actions.applescript",
        "is.workflow.actions.runjsshortcut",
    }
)

# JSON Schema fragment for recipe action items (shared with MCP tool schemas).
ACTION_RECIPE_ITEM_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "description": "Short action name or is.workflow.actions.* identifier",
        },
        "action": {
            "type": "string",
            "description": "Alias for type",
        },
        "params": {
            "type": "object",
            "description": (
                "High-level parameters. Values may be magic refs: "
                "{$ref:{action_index:0}}, {$var:'X'}, or strings with "
                "${action:0}/${var:X}/${as:Alias}/${input}."
            ),
            "additionalProperties": True,
        },
        "arguments": {
            "type": "object",
            "description": "Alias for params",
            "additionalProperties": True,
        },
        "wf_params": {
            "type": "object",
            "description": "Raw Workflow parameter dict escape hatch",
            "additionalProperties": True,
        },
        "as": {
            "type": "string",
            "description": (
                "Optional output alias for this step. Later steps can use "
                "{$ref:'as:Name'} or ${as:Name}."
            ),
        },
    },
    "anyOf": [{"required": ["type"]}, {"required": ["action"]}],
    "additionalProperties": True,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_group_id() -> str:
    return str(uuid.uuid4()).upper()


def sanitize_filename(name: str) -> str:
    """Make a filesystem-safe file stem from a shortcut name."""
    if not isinstance(name, str):
        raise ValueError("Shortcut name must be a string")
    name = re.sub(r"[\x00-\x1f\x7f]+", "_", name)
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", name.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return (cleaned or "Untitled")[:120].rstrip(" .")


def create_action(action_type: str, params: Optional[dict] = None) -> dict:
    """Create a WF action dict. Resolves short names via full Apple catalog."""
    try:
        identifier, _meta = resolve_action_type(action_type)
    except KeyError:
        # Already a full identifier, or synthetic handled elsewhere
        if str(action_type).startswith("is.workflow.actions.") or str(
            action_type
        ).startswith("com."):
            identifier = action_type
        else:
            identifier = ACTION_MAPPINGS.get(action_type, action_type)
    return {
        "WFWorkflowActionIdentifier": identifier,
        "WFWorkflowActionParameters": params or {},
    }


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def _text_token_attachment(variable_name: str) -> dict:
    return {
        "Value": {"VariableName": variable_name, "Type": "Variable"},
        "WFSerializationType": "WFTextTokenAttachment",
    }


def list_supported_actions(
    *,
    query: Optional[str] = None,
    category: Optional[str] = None,
    curated_only: bool = False,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """
    Return the full Apple action catalog for agent discovery.

    Includes harvested system identifiers (~400+) plus curated aliases.
    """
    payload = list_catalog_actions(
        query=query,
        category=category,
        curated_only=curated_only,
        limit=limit,
    )
    items = payload.get("actions") or []
    # Merge hand-written docs + risk tags for curated types
    enriched: List[Dict[str, Any]] = []
    for it in items:
        name = it.get("type")
        doc = ACTION_DOCS.get(name, {}) if name else {}
        ident = it.get("identifier") or ""
        risk = it.get("risk") or "normal"
        if name in DANGEROUS_ACTIONS or str(ident).lower() in DANGEROUS_ACTIONS:
            risk = "dangerous"
        if doc:
            it = dict(it)
            if doc.get("summary"):
                it["summary"] = doc["summary"]
            if doc.get("params"):
                it["params"] = doc["params"]
            if doc.get("example") is not None:
                it["example"] = doc["example"]
        it["risk"] = risk
        enriched.append(it)
    return enriched


def list_templates() -> List[Dict[str, Any]]:
    return [
        {
            "name": name,
            "description": meta.get("description", ""),
            "action_count": len(meta.get("actions", [])),
        }
        for name, meta in sorted(TEMPLATES.items())
    ]


def get_template(name: str) -> Dict[str, Any]:
    if name not in TEMPLATES:
        known = ", ".join(sorted(TEMPLATES))
        raise KeyError(f"Unknown template '{name}'. Known: {known}")
    tpl = TEMPLATES[name]
    return {
        "name": name,
        "description": tpl.get("description", ""),
        "actions": tpl["actions"],
    }


# ---------------------------------------------------------------------------
# Action compilation
# ---------------------------------------------------------------------------

def _compile_action(item: dict, *, coerce_mode: str = "smart") -> List[dict]:
    """Compile one recipe step into one or more WF actions."""
    if not isinstance(item, dict):
        raise ValueError(f"Action must be an object, got {type(item).__name__}")

    atype = item.get("type") or item.get("action")
    if not atype:
        raise ValueError(f"Action missing 'type': {item!r}")

    # Allow callers to pass raw WF parameters under `wf_params` / `params`.
    args = dict(item.get("params") or item.get("arguments") or {})
    if "wf_params" in item:
        # Full escape hatch: raw Workflow parameters, still use identifier map.
        raw = dict(item["wf_params"])
        return [create_action(atype, coerce_params(raw, mode=coerce_mode))]

    # Modern App Intent / reverse-DNS action surface
    if atype in {"app_intent", "appintent", "run_app_intent"}:
        return _compile_app_intent(args, coerce_mode=coerce_mode)

    # ---- control flow (synthetic multi-part types) ----
    if atype == "conditional_start":
        cond_key = str(args.get("condition", "equals")).lower()
        cond_enum = CONDITION_ENUMS.get(cond_key, CONDITION_ENUMS["equals"])
        group_id = args.get("group_id") or new_group_id()
        params: Dict[str, Any] = {
            "GroupingIdentifier": group_id,
            "WFControlFlowMode": 0,
            "WFCondition": cond_enum,
        }
        if "value" in args:
            params["WFConditionalActionString"] = str(args["value"])
        if "number" in args:
            params["WFNumberValue"] = float(args["number"])

        # Empirical (iOS leave shortcut, 2026-08): putting WFInput={Type:Variable}
        # directly on is.workflow.actions.conditional often yields
        # 「알 수 없는 동작」 / unbound params. Prefer magic stack from the
        # previous action. When var_name is requested, expand to:
        #   Get Variable → If (no WFInput on If).
        var_name = args.get("var_name") or args.get("variable") or args.get("input_var")
        if var_name:
            return [
                create_action(
                    "get_variable",
                    {"WFVariable": _text_token_attachment(str(var_name))},
                ),
                create_action("conditional", params),
            ]
        if "WFInput" in args:
            # Escape hatch for ActionOutput attachments only; Variable form is discouraged.
            params["WFInput"] = args["WFInput"]

        return [create_action("conditional", params)]

    if atype == "conditional_else":
        return [
            create_action(
                "conditional",
                {
                    "GroupingIdentifier": args["group_id"],
                    "WFControlFlowMode": 1,
                },
            )
        ]

    if atype == "conditional_end":
        return [
            create_action(
                "conditional",
                {
                    "GroupingIdentifier": args["group_id"],
                    "WFControlFlowMode": 2,
                },
            )
        ]

    if atype == "repeat_start":
        group_id = args.get("group_id") or new_group_id()
        count = int(args.get("count", 1))
        return [
            create_action(
                "repeat",
                {
                    "GroupingIdentifier": group_id,
                    "WFControlFlowMode": 0,
                    "WFRepeatCount": count,
                },
            )
        ]

    if atype == "repeat_end":
        return [
            create_action(
                "repeat",
                {
                    "GroupingIdentifier": args["group_id"],
                    "WFControlFlowMode": 2,
                },
            )
        ]

    if atype == "repeat_each_start":
        group_id = args.get("group_id") or new_group_id()
        return [
            create_action(
                "repeat_each",
                {
                    "GroupingIdentifier": group_id,
                    "WFControlFlowMode": 0,
                },
            )
        ]

    if atype == "repeat_each_end":
        return [
            create_action(
                "repeat_each",
                {
                    "GroupingIdentifier": args["group_id"],
                    "WFControlFlowMode": 2,
                },
            )
        ]

    if atype == "menu_start":
        group_id = args.get("group_id") or new_group_id()
        prompt = args.get("prompt", "Choose")
        return [
            create_action(
                "choose_from_menu",
                {
                    "GroupingIdentifier": group_id,
                    "WFControlFlowMode": 0,
                    "WFMenuPrompt": prompt,
                    "WFMenuItems": list(args.get("items", [])),
                },
            )
        ]

    if atype == "menu_item":
        return [
            create_action(
                "choose_from_menu",
                {
                    "GroupingIdentifier": args["group_id"],
                    "WFControlFlowMode": 1,
                    "WFMenuItemTitle": args.get("title", "Item"),
                },
            )
        ]

    if atype == "menu_end":
        return [
            create_action(
                "choose_from_menu",
                {
                    "GroupingIdentifier": args["group_id"],
                    "WFControlFlowMode": 2,
                },
            )
        ]

    # ---- concrete actions ----
    if atype == "date":
        return [
            create_action(
                "date",
                {"WFDateActionMode": args.get("mode", "Current Date")},
            )
        ]

    if atype == "delay":
        return [create_action("delay", {"WFDelayTime": float(args.get("seconds", 1))})]

    if atype == "open_app":
        bundle_id = args.get("bundle_id") or args.get("bundleId") or "com.apple.Safari"
        app_name = args.get("app_name") or args.get("name") or bundle_id
        return [
            create_action(
                "open_app",
                {
                    "WFAppIdentifier": bundle_id,
                    "WFSelectedApp": {
                        "BundleIdentifier": bundle_id,
                        "Name": app_name,
                    },
                },
            )
        ]

    if atype == "open_url":
        return [create_action("open_url", {"WFInput": args.get("url", "")})]

    if atype == "take_screenshot":
        return [create_action("take_screenshot", {})]

    if atype == "take_photo":
        return [
            create_action(
                "take_photo",
                {
                    "WFPhotoCount": int(args.get("count", 1)),
                    "WFCameraCaptureDevice": args.get("camera", "Front"),
                },
            )
        ]

    if atype == "select_photos":
        return [
            create_action(
                "select_photos",
                {"WFSelectMultiplePhotos": _as_bool(args.get("multiple", True), True)},
            )
        ]

    if atype in {"crop_image", "image_crop"}:
        # Legacy is.workflow.actions.cropimage is broken on modern macOS
        # ("동작을 찾을 수 없습니다"). Prefer image.crop; allow explicit legacy.
        use_legacy = _as_bool(args.get("legacy_cropimage", False), False)
        pos = args.get("position", "Center")
        params: Dict[str, Any] = {}
        if use_legacy:
            params["WFCropImagePosition"] = str(pos)
            for src, dst in (
                ("width", "WFCropImageWidth"),
                ("height", "WFCropImageHeight"),
                ("x", "WFCropImageX"),
                ("y", "WFCropImageY"),
            ):
                if src in args:
                    params[dst] = float(args[src])
            return [
                {
                    "WFWorkflowActionIdentifier": "is.workflow.actions.cropimage",
                    "WFWorkflowActionParameters": params,
                }
            ]
        # Modern path
        params["WFImagePosition"] = str(pos)
        if "width" in args:
            params["WFImageWidth"] = float(args["width"])
        if "height" in args:
            params["WFImageHeight"] = float(args["height"])
        return [
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.image.crop",
                "WFWorkflowActionParameters": params,
            }
        ]

    if atype == "resize_image":
        params = {}
        if "width" in args:
            params["WFImageResizeWidth"] = float(args["width"])
        if "height" in args:
            params["WFImageResizeHeight"] = float(args["height"])
        return [create_action("resize_image", params)]

    if atype == "ocr_extract_text":
        return [create_action("ocr_extract_text", {})]

    if atype == "set_variable":
        name = args.get("var_name") or args.get("name")
        if not name:
            raise ValueError("set_variable requires params.var_name")
        return [create_action("set_variable", {"WFVariableName": name})]

    if atype == "get_variable":
        name = args.get("var_name") or args.get("name")
        if not name:
            raise ValueError("get_variable requires params.var_name")
        return [create_action("get_variable", {"WFVariable": _text_token_attachment(name)})]

    if atype == "add_to_variable":
        name = args.get("var_name") or args.get("name")
        if not name:
            raise ValueError("add_to_variable requires params.var_name")
        return [create_action("add_to_variable", {"WFVariableName": name})]

    if atype == "get_volume":
        return [create_action("get_volume", {})]

    if atype == "set_volume":
        vol = args.get("volume", 1.0)
        if isinstance(vol, dict):
            # Already-resolved magic ref / token attachment
            return [create_action("set_volume", {"WFVolume": vol})]
        if isinstance(vol, str):
            return [
                create_action(
                    "set_volume",
                    {"WFVolume": _text_token_attachment(vol)},
                )
            ]
        return [create_action("set_volume", {"WFVolume": float(vol)})]

    if atype == "set_brightness":
        return [
            create_action(
                "set_brightness",
                {"WFBrightness": float(args.get("brightness", 0.5))},
            )
        ]

    if atype == "speak_text":
        return [
            create_action(
                "speak_text",
                {
                    "WFSpeakTextText": args.get("text", ""),
                    "WFSpeakTextWait": _as_bool(args.get("wait", True), True),
                    "WFSpeakTextRate": float(args.get("rate", 0.45)),
                    "WFSpeakTextLanguage": args.get("language", "Default"),
                },
            )
        ]

    if atype == "show_notification":
        return [
            create_action(
                "show_notification",
                {
                    "WFNotificationActionTitle": args.get("title", ""),
                    "WFNotificationActionBody": args.get("body", args.get("text", "")),
                    "WFNotificationActionSound": _as_bool(args.get("sound", True), True),
                },
            )
        ]

    if atype == "show_alert":
        return [
            create_action(
                "show_alert",
                {
                    "WFAlertActionTitle": args.get("title", "Alert"),
                    "WFAlertActionMessage": args.get("message", args.get("text", "")),
                    "WFAlertActionCancelButtonShown": _as_bool(
                        args.get("show_cancel", False), False
                    ),
                },
            )
        ]

    if atype == "show_result":
        # Empty text → show whatever is on the magic variable stack.
        # Non-empty string or resolved magic-ref dict → explicit Text.
        params = {}
        text = args.get("text")
        if isinstance(text, dict) or (text is not None and str(text) != ""):
            params["Text"] = text
        return [create_action("show_result", params)]

    if atype == "ask":
        return [
            create_action(
                "ask",
                {
                    "WFAskActionPrompt": args.get("prompt", "Input"),
                    "WFAskActionDefaultAnswer": args.get("default", ""),
                    "WFInputType": args.get("input_type", "Text"),
                },
            )
        ]

    if atype == "vibrate":
        return [create_action("vibrate", {})]

    if atype == "play_sound":
        return [create_action("play_sound", {})]

    if atype == "comment":
        return [create_action("comment", {"WFCommentActionText": args.get("text", "")})]

    if atype == "text":
        return [create_action("text", {"WFTextActionText": args.get("text", "")})]

    if atype == "get_clipboard":
        return [create_action("get_clipboard", {})]

    if atype == "set_clipboard":
        params: Dict[str, Any] = {
            "WFLocalOnly": _as_bool(args.get("local_only", False), False),
            "WFExpirationDate": args.get("expiration", "Never"),
        }
        # If text provided, prepend a Text action so the stack has content.
        if args.get("text") is not None:
            text_val = args["text"]
            if not isinstance(text_val, dict):
                text_val = str(text_val)
            return [
                create_action("text", {"WFTextActionText": text_val}),
                create_action("set_clipboard", params),
            ]
        return [create_action("set_clipboard", params)]

    if atype == "change_case":
        return [
            create_action(
                "change_case",
                {"Show-text_case": True, "WFCaseType": args.get("case", "UPPERCASE")},
            )
        ]

    if atype == "replace_text":
        return [
            create_action(
                "replace_text",
                {
                    "WFReplaceTextFind": args.get("find", ""),
                    "WFReplaceTextReplace": args.get("replace", ""),
                    "WFReplaceTextCaseSensitive": _as_bool(
                        args.get("case_sensitive", True), True
                    ),
                    "WFReplaceTextRegularExpression": _as_bool(
                        args.get("regular_expression", False), False
                    ),
                },
            )
        ]

    if atype == "split_text":
        sep = args.get("separator", "New Lines")
        params = {"WFTextSeparator": sep}
        if sep == "Custom" and "custom" in args:
            params["WFTextCustomSeparator"] = args["custom"]
        return [create_action("split_text", params)]

    if atype == "combine_text":
        sep = args.get("separator", "New Lines")
        params = {"WFTextSeparator": sep}
        if sep == "Custom" and "custom" in args:
            params["WFTextCustomSeparator"] = args["custom"]
        return [create_action("combine_text", params)]

    if atype == "match_text":
        return [
            create_action(
                "match_text",
                {
                    "WFMatchTextPattern": args.get("pattern", ""),
                    "WFMatchTextCaseSensitive": _as_bool(
                        args.get("case_sensitive", True), True
                    ),
                },
            )
        ]

    if atype == "count":
        return [create_action("count", {"WFCountType": args.get("count_type", "Items")})]

    if atype == "calculate":
        return [
            create_action(
                "calculate",
                {
                    "WFMathOperation": args.get("operation", "+"),
                    "WFNumberOperand": float(args.get("operand", 0)),
                },
            )
        ]

    if atype == "base64_encode":
        return [
            create_action(
                "base64_encode",
                {
                    "WFEncodeMode": args.get("mode", "Encode"),
                    "WFBase64LineBreakMode": args.get("line_break", "None"),
                },
            )
        ]

    if atype == "url_encode":
        return [
            create_action(
                "url_encode",
                {"WFEncodeMode": args.get("mode", "Encode")},
            )
        ]

    if atype == "hash":
        return [create_action("hash", {"WFHashType": args.get("type", "MD5")})]

    if atype == "list":
        items = args.get("items", [])
        return [create_action("list", {"WFItems": list(items)})]

    if atype == "dictionary":
        items = args.get("items") or args.get("value") or {}
        # Shortcuts stores dict as array of key/value pairs in some versions;
        # the modern form accepts WFItems as a dict serialization.
        return [create_action("dictionary", {"WFItems": items})]

    if atype == "get_dictionary_value":
        return [
            create_action(
                "get_dictionary_value",
                {
                    "WFDictionaryKey": args.get("key", ""),
                    "WFGetDictionaryValueType": args.get("value_type", "Value"),
                },
            )
        ]

    if atype == "set_dictionary_value":
        return [
            create_action(
                "set_dictionary_value",
                {
                    "WFDictionaryKey": args.get("key", ""),
                    "WFDictionaryValue": args.get("value", ""),
                },
            )
        ]

    if atype == "get_item_from_list":
        return [
            create_action(
                "get_item_from_list",
                {
                    "WFItemSpecifier": args.get("specifier", "First Item"),
                    "WFItemIndex": args.get("index", 1),
                },
            )
        ]

    if atype == "get_contents_of_url":
        method = str(args.get("method", "GET")).upper()
        params: Dict[str, Any] = {
            "WFURL": args.get("url", ""),
            "WFHTTPMethod": method,
        }
        headers = args.get("headers") or {}
        if headers:
            params["WFHTTPHeaders"] = headers
        if method in {"POST", "PUT", "PATCH"} and args.get("body") is not None:
            body_type = args.get("body_type", "JSON")
            params["WFHTTPBodyType"] = body_type
            if body_type == "JSON":
                params["WFJSONValues"] = args["body"]
            else:
                params["WFRequestVariable"] = args["body"]
        return [create_action("get_contents_of_url", params)]

    if atype == "get_headers_of_url":
        return [create_action("get_headers_of_url", {"WFInput": args.get("url", "")})]

    if atype == "run_shell_script":
        return [
            create_action(
                "run_shell_script",
                {
                    "WFShellScript": args.get("script", args.get("source", "")),
                    "WFShellScriptShell": args.get("shell", "/bin/zsh"),
                    "WFInput": args.get("input_mode", "to stdin"),
                },
            )
        ]

    if atype == "run_applescript":
        return [
            create_action(
                "run_applescript",
                {"WFInput": args.get("script", args.get("source", ""))},
            )
        ]

    if atype == "run_shortcut":
        name = args.get("name") or args.get("shortcut_name")
        if not name:
            raise ValueError("run_shortcut requires params.name")
        return [
            create_action(
                "run_shortcut",
                {
                    "WFWorkflowName": name,
                    "WFShowWorkflow": _as_bool(args.get("show_while_running", False), False),
                },
            )
        ]

    if atype == "send_message":
        recipients = args.get("recipients") or args.get("recipient") or []
        if isinstance(recipients, str):
            recipients = [recipients]
        return [
            create_action(
                "send_message",
                {
                    "WFSendMessageActionRecipients": list(recipients),
                    "WFSendMessageContent": args.get("message", args.get("text", "")),
                    "ShowWhenRun": _as_bool(args.get("show_compose", True), True),
                },
            )
        ]

    if atype == "send_email":
        to = args.get("to") or args.get("recipients") or []
        if isinstance(to, str):
            to = [to]
        return [
            create_action(
                "send_email",
                {
                    "WFSendEmailActionToRecipients": list(to),
                    "WFSendEmailActionSubject": args.get("subject", ""),
                    "WFSendEmailActionBody": args.get("body", args.get("message", "")),
                    "ShowWhenRun": _as_bool(args.get("show_compose", True), True),
                },
            )
        ]

    if atype == "share":
        return [create_action("share", {})]

    if atype == "airdrop":
        return [create_action("airdrop", {})]

    if atype == "get_location":
        return [create_action("get_location", {})]

    if atype == "get_battery":
        return [create_action("get_battery", {})]

    if atype == "get_device_details":
        return [
            create_action(
                "get_device_details",
                {"WFDeviceDetail": args.get("detail", "Device Name")},
            )
        ]

    if atype == "get_network_details":
        return [
            create_action(
                "get_network_details",
                {"WFNetworkDetail": args.get("detail", "Network Name")},
            )
        ]

    if atype == "set_wifi":
        on = _as_bool(args.get("on", True), True)
        return [create_action("set_wifi", {"OnValue": on})]

    if atype == "set_bluetooth":
        on = _as_bool(args.get("on", True), True)
        return [create_action("set_bluetooth", {"OnValue": on})]

    if atype == "set_airplane_mode":
        on = _as_bool(args.get("on", True), True)
        return [create_action("set_airplane_mode", {"OnValue": on})]

    if atype == "set_cellular":
        on = _as_bool(args.get("on", True), True)
        return [create_action("set_cellular", {"OnValue": on})]

    if atype == "set_low_power_mode":
        on = _as_bool(args.get("on", True), True)
        return [create_action("set_low_power_mode", {"OnValue": on})]

    if atype == "set_flashlight":
        return [
            create_action(
                "set_flashlight",
                {"WFFlashlightSetting": args.get("setting", "On")},
            )
        ]

    if atype == "set_focus":
        # Focus / DND — field names vary slightly by OS version; this form
        # works on recent macOS/iOS Shortcuts builds.
        return [
            create_action(
                "set_focus",
                {
                    "FocusMode": args.get("mode", "Do Not Disturb"),
                    "UntilTurnedOff": True if args.get("until", "Turned Off") == "Turned Off" else False,
                },
            )
        ]

    if atype == "lock_screen":
        return [create_action("lock_screen", {})]

    if atype == "exit_shortcut":
        return [create_action("exit_shortcut", {})]

    if atype == "stop_and_output":
        return [create_action("stop_and_output", {})]

    if atype == "nothing":
        return [create_action("nothing", {})]

    if atype == "wait_to_return":
        return [create_action("wait_to_return", {})]

    if atype == "make_pdf":
        return [create_action("make_pdf", {})]

    if atype == "save_file":
        return [
            create_action(
                "save_file",
                {
                    "WFAskWhereToSave": _as_bool(args.get("ask_where", True), True),
                    "WFSaveFileOverwrite": _as_bool(args.get("overwrite", False), False),
                },
            )
        ]

    if atype == "create_folder":
        return [
            create_action(
                "create_folder",
                {"WFFileDestinationPath": args.get("path", args.get("name", "New Folder"))},
            )
        ]

    if atype == "rename_file":
        return [
            create_action(
                "rename_file",
                {"WFFileDestinationName": args.get("name", "Renamed")},
            )
        ]

    if atype == "search_web":
        return [
            create_action(
                "search_web",
                {
                    "WFSearchWebQuery": args.get("query", ""),
                    "WFSearchWebDestination": args.get("destination", "Safari"),
                },
            )
        ]

    # Generic path: full Apple catalog + any is.workflow.actions.* identifier.
    # Auto-coercion wraps plain strings/numbers into WF token/number states to
    # reduce Silent Corruption in Shortcuts UI for non-curated actions.
    try:
        ident, meta = resolve_action_type(atype)
    except KeyError as exc:
        suggestions = suggest_actions(str(atype), limit=5)
        hint = ""
        if suggestions:
            hint = " Suggestions: " + ", ".join(
                "{0} ({1})".format(s["type"], s["identifier"]) for s in suggestions
            )
        raise ValueError(
            "Unknown action type '{0}'. "
            "Use list_actions (full Apple catalog), pass a full "
            "is.workflow.actions.* identifier, app_intent, or wf_params.{1}".format(
                atype, hint
            )
        ) from exc

    # Prefer explicit wf-style keys; drop helper-only keys
    generic_params = dict(args)
    for drop in ("type", "action", "as"):
        generic_params.pop(drop, None)
    # Learned short→WF key maps (accepted/validated only by default)
    schema_by_key = {}
    try:
        from param_learning import (  # lazy: avoid import cycle
            apply_learned_param_map,
            get_param_schema,
        )

        generic_params, _map_notes = apply_learned_param_map(
            ident, generic_params, accepted_only=True
        )
        schema_by_key = get_param_schema(ident) or {}
    except Exception:
        pass
    # Curated identifiers still benefit from coercion when used via raw id
    mode = coerce_mode
    if meta.get("serialization") == "curated" and coerce_mode == "smart":
        mode = "smart"
    generic_params = coerce_params(
        generic_params, mode=mode, schema_by_key=schema_by_key
    )
    return [create_action(ident, generic_params)]


def _compile_app_intent(args: dict, *, coerce_mode: str = "smart") -> List[dict]:
    """
    Compile a modern App Intent style action.

    Accepted params:
      identifier / intent_identifier  — reverse-DNS action id (required)
      bundle_identifier               — optional app bundle
      parameters / params             — intent parameter payload
      wf_params                       — merged raw WF keys
    """
    ident = (
        args.get("identifier")
        or args.get("intent_identifier")
        or args.get("intent")
        or args.get("app_intent_identifier")
    )
    if not ident:
        raise ValueError(
            "app_intent requires params.identifier (reverse-DNS App Intent id)"
        )
    payload: Dict[str, Any] = {}
    nested = args.get("parameters") or args.get("params") or {}
    if isinstance(nested, dict):
        payload.update(nested)
    if isinstance(args.get("wf_params"), dict):
        payload.update(args["wf_params"])
    # Pass through other WF-looking keys from top-level params
    for k, v in args.items():
        if k in {
            "identifier",
            "intent_identifier",
            "intent",
            "app_intent_identifier",
            "parameters",
            "params",
            "wf_params",
            "bundle_identifier",
            "bundle_id",
        }:
            continue
        payload[k] = v
    bundle = args.get("bundle_identifier") or args.get("bundle_id")
    if bundle:
        payload.setdefault("AppIntentBundleIdentifier", bundle)
        payload.setdefault("WFAppIntentBundleIdentifier", bundle)
    # Common metadata keys used by various OS versions
    payload.setdefault("AppIntentIdentifier", ident)
    payload = coerce_params(payload, mode=coerce_mode)
    return [
        {
            "WFWorkflowActionIdentifier": str(ident),
            "WFWorkflowActionParameters": payload,
        }
    ]


def _semantic_check_action(
    index: int,
    atype: str,
    params: dict,
    *,
    safe_mode: bool,
) -> Tuple[List[str], List[str]]:
    """Return (errors, warnings) for semantic constraints on one action."""
    errors: List[str] = []
    warnings: List[str] = []
    prefix = "actions[{0}] ({1})".format(index, atype)
    atype_l = str(atype).lower()

    if atype in DANGEROUS_ACTIONS or atype_l in DANGEROUS_ACTIONS:
        if safe_mode:
            errors.append(
                "{0}: blocked in safe mode (shell/AppleScript/JXA)".format(prefix)
            )
        else:
            warnings.append(
                "{0}: dangerous action — executes local code when the shortcut runs".format(
                    prefix
                )
            )

    if atype in {"delay"}:
        seconds = params.get("seconds", 1)
        try:
            sec_f = float(seconds)
            if sec_f < 0:
                errors.append("{0}: seconds must be >= 0".format(prefix))
            elif sec_f > 3600:
                warnings.append("{0}: delay > 3600s is unusually long".format(prefix))
        except (TypeError, ValueError):
            errors.append("{0}: seconds must be a number".format(prefix))

    if atype in {"set_volume"}:
        vol = params.get("volume", 1.0)
        if isinstance(vol, dict):
            # Magic/ActionOutput ref — still risky for volume restore on device
            warnings.append(
                "{0}: set_volume from magic/variable attachment often breaks on iOS "
                "('알 수 없는 동작' / unbound 미디어 음량). Prefer a literal float "
                "0.0–1.0; avoid get_volume→set_variable→set_volume restore loops.".format(
                    prefix
                )
            )
        elif isinstance(vol, str):
            warnings.append(
                "{0}: set_volume(volume={1!r}) as a variable *name* serializes poorly "
                "on iOS and frequently becomes '알 수 없는 동작'. Use a literal float "
                "(e.g. 1.0) instead of volume restore.".format(prefix, vol)
            )
        else:
            try:
                v = float(vol)
                if v < 0.0 or v > 1.0:
                    errors.append("{0}: volume must be between 0.0 and 1.0".format(prefix))
            except (TypeError, ValueError):
                errors.append("{0}: volume must be a number".format(prefix))

    if atype in {"set_brightness"}:
        try:
            b = float(params.get("brightness", 0.5))
            if b < 0.0 or b > 1.0:
                errors.append("{0}: brightness must be between 0.0 and 1.0".format(prefix))
        except (TypeError, ValueError):
            errors.append("{0}: brightness must be a number".format(prefix))

    if atype in {
        "crop_image",
        "image_crop",
        "is.workflow.actions.cropimage",
        "is.workflow.actions.image.crop",
    }:
        if atype == "is.workflow.actions.cropimage" or params.get("legacy_cropimage"):
            warnings.append(
                "{0}: legacy is.workflow.actions.cropimage fails on modern macOS "
                "('동작을 찾을 수 없습니다'). On iOS it may work, but bare crop without "
                "dimensions often opens an interactive crop UI (취소/완료). "
                "Prefer skip crop for full-frame OCR, or crop_image→image.crop with size.".format(
                    prefix
                )
            )
        has_dims = any(
            k in params
            for k in (
                "width",
                "height",
                "x",
                "y",
                "WFCropImageWidth",
                "WFCropImageHeight",
                "WFImageWidth",
                "WFImageHeight",
            )
        )
        if not has_dims:
            warnings.append(
                "{0}: crop without width/height often presents an interactive "
                "「이미지」 sheet requiring Cancel/Done — bad for unattended flows. "
                "Skip crop (full-screen OCR) or supply dimensions.".format(prefix)
            )

    if atype in {"vibrate", "is.workflow.actions.vibrate"}:
        warnings.append(
            "{0}: vibrate is often iOS-only; on macOS the shortcut may fail with "
            "missing action. Omit for mac builds.".format(prefix)
        )

    if atype in {"take_screenshot", "is.workflow.actions.takescreenshot"}:
        warnings.append(
            "{0}: keep the next action an image consumer (ocr_extract_text / crop / "
            "resize). If the following step fails or is unbound, iOS shows a stuck "
            "「이미지」 popup requiring Cancel/Done.".format(prefix)
        )

    if atype in {"conditional_start"}:
        if params.get("var_name") or params.get("variable") or params.get("input_var"):
            warnings.append(
                "{0}: var_name expands to Get Variable → If (no WFInput on If). "
                "Prefer placing OCR/text as the previous action and omit var_name.".format(
                    prefix
                )
            )
        if "WFInput" in params:
            warnings.append(
                "{0}: WFInput Variable on conditional frequently breaks on iOS. "
                "Prefer magic stack from previous action; see docs/RUNTIME_TRAPS.md.".format(
                    prefix
                )
            )

    if atype in {"open_url"}:
        url = params.get("url")
        if isinstance(url, dict):
            pass  # magic ref — checked by validate_magic_refs
        elif not url or not str(url).strip():
            errors.append("{0}: params.url is required".format(prefix))
        elif not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", str(url)):
            warnings.append(
                "{0}: url has no scheme (expected https://, shortcuts://, …)".format(
                    prefix
                )
            )

    if atype in {"open_app"}:
        if not (params.get("bundle_id") or params.get("bundleId") or params.get("app_name") or params.get("name")):
            warnings.append(
                "{0}: prefer params.bundle_id + params.app_name for reliable open_app".format(
                    prefix
                )
            )

    if atype in {"speak_text"}:
        text = params.get("text", "")
        if not isinstance(text, dict) and not str(text).strip():
            warnings.append("{0}: empty speak text".format(prefix))

    if atype in {"show_notification"}:
        title = params.get("title", "")
        body = params.get("body", params.get("text", ""))
        title_empty = not isinstance(title, dict) and not str(title).strip()
        body_empty = not isinstance(body, dict) and not str(body).strip()
        if title_empty and body_empty:
            warnings.append("{0}: notification title/body both empty".format(prefix))

    if atype in {"set_variable", "get_variable", "add_to_variable"}:
        if not (params.get("var_name") or params.get("name")):
            errors.append("{0}: params.var_name is required".format(prefix))

    if atype in {"get_contents_of_url", "get_headers_of_url"}:
        url = params.get("url", "")
        if not isinstance(url, dict) and not str(url).strip():
            errors.append("{0}: params.url is required".format(prefix))

    if atype in {"run_shell_script", "run_applescript"}:
        script = params.get("script", params.get("source", ""))
        if not isinstance(script, dict) and not str(script).strip():
            errors.append("{0}: params.script is required".format(prefix))

    if atype in {"run_shortcut"}:
        if not (params.get("name") or params.get("shortcut_name")):
            errors.append("{0}: params.name is required".format(prefix))

    if atype in {"repeat_start"}:
        try:
            count = int(params.get("count", 1))
            if count < 1:
                errors.append("{0}: count must be >= 1".format(prefix))
            elif count > 1000:
                warnings.append("{0}: repeat count > 1000".format(prefix))
        except (TypeError, ValueError):
            errors.append("{0}: count must be an integer".format(prefix))

    if atype in {"send_message", "send_email"}:
        if params.get("show_compose") is False:
            warnings.append(
                "{0}: show_compose=false may send without UI confirmation".format(prefix)
            )

    return errors, warnings


def validate_actions(
    actions_config: list,
    *,
    safe_mode: bool = False,
    allow_empty: bool = False,
    target_platform: str = "macos",
    coerce_mode: str = "smart",
) -> Dict[str, Any]:
    """Dry-run compile; returns {ok, actions_compiled, errors, warnings, risks}."""
    errors: List[str] = []
    warnings: List[str] = []
    risks: List[str] = []
    compiled = 0
    stack: List[Dict[str, Any]] = []
    start_types = {
        "conditional_start": "conditional",
        "repeat_start": "repeat",
        "repeat_each_start": "repeat_each",
        "menu_start": "menu",
    }
    end_types = {
        "conditional_end": "conditional",
        "repeat_end": "repeat",
        "repeat_each_end": "repeat_each",
        "menu_end": "menu",
    }

    if not isinstance(actions_config, list):
        return {
            "ok": False,
            "actions_compiled": 0,
            "errors": ["'actions' must be a JSON array"],
            "warnings": [],
            "risks": [],
        }

    if len(actions_config) == 0 and not allow_empty:
        errors.append("'actions' must contain at least one action")

    aliases, alias_errors = collect_aliases(actions_config)
    errors.extend(alias_errors)
    magic_errors, magic_warnings = validate_magic_refs(
        actions_config, aliases=aliases
    )
    errors.extend(magic_errors)
    warnings.extend(magic_warnings)

    plat = preflight_platform(actions_config, target_platform=target_platform)
    errors.extend(plat.get("errors") or [])
    warnings.extend(plat.get("warnings") or [])

    for i, item in enumerate(actions_config):
        try:
            if not isinstance(item, dict):
                errors.append(
                    "actions[{0}]: must be an object with type/params".format(i)
                )
                continue
            atype = item.get("type") or item.get("action")
            params = item.get("params") or item.get("arguments") or {}
            if params is None:
                params = {}
            if not isinstance(params, dict):
                errors.append("actions[{0}]: params must be an object".format(i))
                params = {}

            # Semantic checks even if compile fails later
            if atype:
                sem_err, sem_warn = _semantic_check_action(
                    i, str(atype), params, safe_mode=safe_mode
                )
                errors.extend(sem_err)
                warnings.extend(sem_warn)
                if str(atype) in DANGEROUS_ACTIONS or str(atype).lower() in DANGEROUS_ACTIONS:
                    risks.append(str(atype))

            # Serialization quality hint for generic (non-curated) actions
            try:
                if atype and atype not in {
                    "app_intent",
                    "appintent",
                    "run_app_intent",
                    "conditional_start",
                    "conditional_else",
                    "conditional_end",
                    "repeat_start",
                    "repeat_end",
                    "repeat_each_start",
                    "repeat_each_end",
                    "menu_start",
                    "menu_item",
                    "menu_end",
                }:
                    _ident, _meta = resolve_action_type(str(atype))
                    if _meta.get("serialization") == "generic" and not item.get(
                        "wf_params"
                    ):
                        warnings.append(
                            "actions[{0}] ({1}): generic serialization — "
                            "auto-coercion applied; prefer curated type or "
                            "wf_params with real WF keys for production quality".format(
                                i, atype
                            )
                        )
            except KeyError:
                pass

            # Resolve magic refs for compile dry-run (same as real build)
            ctx = RecipeContext(
                step_count=len(actions_config),
                aliases=aliases,
                current_index=i,
            )
            try:
                resolved_item = dict(item)
                resolved_item["params"] = resolve_params(params, ctx)
                parts = _compile_action(resolved_item, coerce_mode=coerce_mode)
            except Exception:
                # Fall back to unresolved compile for non-ref recipes
                parts = _compile_action(item, coerce_mode=coerce_mode)
            compiled += len(parts)
            gid = params.get("group_id") if isinstance(params, dict) else None
            if atype in start_types:
                if not gid:
                    errors.append(
                        "actions[{0}] ({1}): group_id is required".format(i, atype)
                    )
                else:
                    stack.append(
                        {
                            "kind": start_types[atype],
                            "group_id": str(gid),
                            "index": i,
                            "has_else": False,
                        }
                    )
            elif atype in {"conditional_else", "menu_item"}:
                if not gid:
                    errors.append(
                        "actions[{0}] ({1}): group_id is required".format(i, atype)
                    )
                elif not stack:
                    errors.append(
                        "actions[{0}] ({1}): no open control-flow block".format(i, atype)
                    )
                else:
                    expected_kind = (
                        "conditional" if atype == "conditional_else" else "menu"
                    )
                    current = stack[-1]
                    if current["kind"] != expected_kind or current["group_id"] != str(
                        gid
                    ):
                        errors.append(
                            "actions[{0}] ({1}): expected open {2} group_id={3}".format(
                                i, atype, current["kind"], current["group_id"]
                            )
                        )
                    elif atype == "conditional_else" and current["has_else"]:
                        errors.append(
                            "actions[{0}] ({1}): duplicate else for group_id={2}".format(
                                i, atype, gid
                            )
                        )
                    elif atype == "conditional_else":
                        current["has_else"] = True
            elif atype in end_types:
                if not gid:
                    errors.append(
                        "actions[{0}] ({1}): group_id is required".format(i, atype)
                    )
                elif not stack:
                    errors.append(
                        "actions[{0}] ({1}): no open control-flow block".format(i, atype)
                    )
                else:
                    current = stack[-1]
                    if (
                        current["kind"] != end_types[atype]
                        or current["group_id"] != str(gid)
                    ):
                        errors.append(
                            "actions[{0}] ({1}): expected end for {2} group_id={3}".format(
                                i, atype, current["kind"], current["group_id"]
                            )
                        )
                    else:
                        stack.pop()
        except Exception as exc:
            errors.append("actions[{0}]: {1}".format(i, exc))

    for group in reversed(stack):
        errors.append(
            "actions[{0}]: unclosed {1} group_id={2}".format(
                group["index"], group["kind"], group["group_id"]
            )
        )

    # Sequence heuristics (leave-shortcut postmortem 2026-08)
    warnings.extend(_sequence_warnings(actions_config or []))

    return {
        "ok": len(errors) == 0,
        "actions_compiled": compiled,
        "errors": errors,
        "warnings": warnings,
        "risks": sorted(set(risks)),
    }


def _sequence_warnings(actions_config: list) -> List[str]:
    """Cross-step traps that single-action checks miss."""
    out: List[str] = []
    types: List[str] = []
    for item in actions_config:
        if not isinstance(item, dict):
            types.append("")
            continue
        types.append(str(item.get("type") or item.get("action") or "").lower())

    def is_vol_set(t: str) -> bool:
        return t in {"set_volume", "is.workflow.actions.setvolume"}

    def is_vol_get(t: str) -> bool:
        return t in {"get_volume", "is.workflow.actions.getvolume"}

    def is_set_var(t: str) -> bool:
        return t in {"set_variable", "is.workflow.actions.setvariable"}

    def is_shot(t: str) -> bool:
        return t in {"take_screenshot", "is.workflow.actions.takescreenshot"}

    def is_image_consumer(t: str) -> bool:
        return t in {
            "ocr_extract_text",
            "is.workflow.actions.extracttextfromimage",
            "crop_image",
            "image_crop",
            "is.workflow.actions.cropimage",
            "is.workflow.actions.image.crop",
            "resize_image",
            "is.workflow.actions.image.resize",
            "rotate_image",
            "is.workflow.actions.imagerotate",
            "make_pdf",
            "is.workflow.actions.makepdf",
            "save_file",
            "is.workflow.actions.documentpicker.save",
            "set_variable",  # may store image
            "is.workflow.actions.setvariable",
        }

    for i in range(len(types) - 2):
        if is_vol_get(types[i]) and is_set_var(types[i + 1]) and is_vol_set(types[i + 2]):
            out.append(
                "actions[{0}..{1}]: get_volume→set_variable→set_volume restore loop "
                "often becomes '알 수 없는 동작' (미디어 음량) on iOS — omit volume "
                "save/restore for unattended shortcuts (docs/RUNTIME_TRAPS.md).".format(
                    i, i + 2
                )
            )

    for i, t in enumerate(types):
        if not is_shot(t):
            continue
        nxt = types[i + 1] if i + 1 < len(types) else ""
        if nxt and not is_image_consumer(nxt):
            out.append(
                "actions[{0}]: take_screenshot is followed by {1!r}, not an image "
                "consumer — iOS may show a stuck 「이미지」 popup. Put "
                "ocr_extract_text (or crop/resize) immediately after.".format(i, nxt)
            )

    return out


def actions_summary(actions_config: list) -> List[Dict[str, Any]]:
    """Lightweight summary of recipe steps for build/inspect responses."""
    out: List[Dict[str, Any]] = []
    for i, item in enumerate(actions_config or []):
        if not isinstance(item, dict):
            out.append({"index": i, "type": None, "error": "not an object"})
            continue
        atype = item.get("type") or item.get("action")
        params = item.get("params") or item.get("arguments") or {}
        keys = sorted(params.keys()) if isinstance(params, dict) else []
        out.append(
            {
                "index": i,
                "type": atype,
                "identifier": ACTION_MAPPINGS.get(str(atype), atype),
                "param_keys": keys,
                "risk": (
                    "dangerous"
                    if str(atype) in DANGEROUS_ACTIONS
                    else "normal"
                ),
            }
        )
    return out


def compile_recipe(
    actions_config: list,
    *,
    safe_mode: bool = False,
    target_platform: str = "macos",
    coerce_mode: str = "smart",
) -> Dict[str, Any]:
    """
    Compile a high-level recipe into WF actions with magic-var resolution
    and deterministic UUIDs.

    Returns:
      {
        "wf_actions": [...],
        "aliases": {...},
        "validation": {...},
        "golden_actions": [...],  # normalized for fixture compare
      }
    """
    validation = validate_actions(
        actions_config,
        safe_mode=safe_mode,
        target_platform=target_platform,
        coerce_mode=coerce_mode,
    )
    if not validation["ok"]:
        raise ValueError(
            "Invalid action recipe:\n- " + "\n- ".join(validation["errors"])
        )

    aliases, _ = collect_aliases(actions_config)
    n = len(actions_config or [])
    wf_actions: List[dict] = []

    for i, item in enumerate(actions_config or []):
        if not isinstance(item, dict):
            raise ValueError("actions[{0}] must be an object".format(i))
        params = item.get("params") or item.get("arguments") or {}
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise ValueError("actions[{0}].params must be an object".format(i))

        ctx = RecipeContext(step_count=n, aliases=aliases, current_index=i)
        resolved = dict(item)
        resolved["params"] = resolve_params(params, ctx)
        # Drop top-level 'as' before compile (not a WF field)
        resolved.pop("as", None)
        parts = _compile_action(resolved, coerce_mode=coerce_mode)
        parts = stamp_action_uuids(parts, step_index=i)
        wf_actions.extend(parts)

    return {
        "wf_actions": wf_actions,
        "aliases": aliases,
        "validation": validation,
        "golden_actions": workflow_actions_golden(wf_actions),
    }


def build_shortcut_dict(
    actions_config: list,
    name: str = "Untitled",
    *,
    icon_color: Optional[Union[str, int]] = None,
    icon_glyph: Optional[int] = None,
    workflow_types: Optional[List[str]] = None,
    client_version: str = "2600.0.1",
    min_client_version: int = 900,
    safe_mode: bool = False,
    target_platform: str = "macos",
    coerce_mode: str = "smart",
) -> dict:
    """Compile recipe → in-memory shortcut plist dictionary (unsigned)."""
    compiled = compile_recipe(
        actions_config,
        safe_mode=safe_mode,
        target_platform=target_platform,
        coerce_mode=coerce_mode,
    )
    wf_actions = compiled["wf_actions"]

    if isinstance(icon_color, str):
        color_val = ICON_COLORS.get(icon_color.lower(), ICON_COLORS["red"])
    elif isinstance(icon_color, int):
        color_val = icon_color
    else:
        color_val = ICON_COLORS["red"]

    glyph = int(icon_glyph) if icon_glyph is not None else 59793
    types = workflow_types or ["NCWidget", "WatchKit"]

    return {
        "WFWorkflowClientVersion": str(client_version),
        "WFWorkflowMinimumClientVersion": int(min_client_version),
        "WFWorkflowMinimumClientVersionString": str(min_client_version),
        "WFWorkflowIcon": {
            "WFWorkflowIconGlyphNumber": glyph,
            "WFWorkflowIconStartColor": color_val,
        },
        "WFWorkflowInputContentItemClasses": list(DEFAULT_INPUT_CLASSES),
        "WFWorkflowActions": wf_actions,
        "WFWorkflowTypes": list(types),
        # Optional metadata (ignored by older clients, useful for debugging)
        "WFWorkflowName": name,
    }


def build_golden_document(
    actions_config: list,
    *,
    name: str = "fixture",
    safe_mode: bool = False,
) -> Dict[str, Any]:
    """Build a JSON-serializable golden document for fixture storage."""
    compiled = compile_recipe(actions_config, safe_mode=safe_mode)
    return {
        "name": name,
        "version": 1,
        "action_count": len(compiled["wf_actions"]),
        "aliases": compiled["aliases"],
        "actions": compiled["golden_actions"],
        "magic": explain_magic_syntax(),
    }


def find_sibling_raw_path(path: str) -> Optional[str]:
    """
    Given Foo.shortcut, look for Foo_raw.shortcut beside it.
    Given Foo_raw.shortcut, return itself if it is a readable plist.
    """
    path = os.path.abspath(path)
    base = os.path.basename(path)
    directory = os.path.dirname(path)
    if base.endswith("_raw.shortcut"):
        return path if os.path.isfile(path) else None
    if base.endswith(".shortcut"):
        stem = base[: -len(".shortcut")]
        candidate = os.path.join(directory, "{0}_raw.shortcut".format(stem))
        if os.path.isfile(candidate):
            return candidate
    return None


def _summarize_plist(plist: dict, *, path: str, size: int) -> Dict[str, Any]:
    actions = plist.get("WFWorkflowActions") or []
    icon = plist.get("WFWorkflowIcon") or {}
    return {
        "path": path,
        "size_bytes": size,
        "format": "plist",
        "name": plist.get("WFWorkflowName"),
        "client_version": plist.get("WFWorkflowClientVersion"),
        "min_client_version": plist.get("WFWorkflowMinimumClientVersion"),
        "action_count": len(actions),
        "actions": [
            {
                "identifier": a.get("WFWorkflowActionIdentifier"),
                "param_keys": sorted(
                    (a.get("WFWorkflowActionParameters") or {}).keys()
                ),
            }
            for a in actions
        ],
        "icon": {
            "glyph": icon.get("WFWorkflowIconGlyphNumber"),
            "color": icon.get("WFWorkflowIconStartColor"),
        },
        "workflow_types": plist.get("WFWorkflowTypes"),
    }


def inspect_shortcut_file(path: str) -> Dict[str, Any]:
    """Read a .shortcut (binary or XML plist) and summarize it.

    Signed packages are opaque; when a sibling ``*_raw.shortcut`` exists
    (always produced by build_shortcut_plist), it is inspected automatically.
    """
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)

    with open(path, "rb") as f:
        data = f.read()

    info: Dict[str, Any] = {
        "path": path,
        "size_bytes": len(data),
        "format": "unknown",
        "raw_path": None,
        "signed_path": path if not path.endswith("_raw.shortcut") else None,
    }

    try:
        plist = plistlib.loads(data)
        summary = _summarize_plist(plist, path=path, size=len(data))
        summary["raw_path"] = path if path.endswith("_raw.shortcut") else path
        summary["signed_path"] = info["signed_path"]
        return summary
    except Exception:
        pass

    # Signed / opaque — try sibling raw produced by our builder.
    raw = find_sibling_raw_path(path)
    info["format"] = "signed_or_opaque"
    info["raw_path"] = raw
    if raw and raw != path:
        try:
            with open(raw, "rb") as rf:
                raw_data = rf.read()
            plist = plistlib.loads(raw_data)
            summary = _summarize_plist(plist, path=raw, size=len(raw_data))
            summary["format"] = "plist_via_raw_sibling"
            summary["signed_path"] = path
            summary["raw_path"] = raw
            summary["inspected_from"] = raw
            summary["requested_path"] = path
            summary["signed_size_bytes"] = len(data)
            return summary
        except Exception as exc:
            info["raw_inspect_error"] = str(exc)

    info["note"] = (
        "File is not a raw plist (likely signed). "
        "Re-build with this server to keep a sibling *_raw.shortcut for inspect, "
        "or pass the unsigned raw path explicitly."
    )
    return info


def sign_shortcut_file(
    input_path: str,
    output_path: str,
    mode: str = "anyone",
) -> Tuple[bool, str]:
    """Sign with macOS `shortcuts sign`. Returns (ok, message)."""
    input_path = os.path.abspath(input_path)
    output_path = os.path.abspath(output_path)
    parent = os.path.dirname(output_path) or "."
    os.makedirs(parent, exist_ok=True)

    if mode not in {"anyone", "people-who-know-me"}:
        return False, "Invalid sign mode '{0}' (use anyone|people-who-know-me)".format(
            mode
        )

    try:
        res = subprocess.run(
            [
                "shortcuts",
                "sign",
                "-m",
                mode,
                "-i",
                input_path,
                "-o",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        return False, "macOS `shortcuts` CLI not found (requires macOS Monterey+)"
    except subprocess.TimeoutExpired:
        return False, "shortcuts sign timed out"

    if res.returncode == 0 and os.path.isfile(output_path):
        return True, output_path
    err = (res.stderr or res.stdout or "unknown error").strip()
    return False, err


def build_shortcut_plist(
    actions_config: list,
    name: str,
    output_dir: str = "./dist",
    *,
    sign: bool = True,
    sign_mode: str = "anyone",
    icon_color: Optional[Union[str, int]] = None,
    icon_glyph: Optional[int] = None,
    workflow_types: Optional[List[str]] = None,
    safe_mode: bool = False,
    target_platform: str = "macos",
    coerce_mode: str = "smart",
) -> Dict[str, Any]:
    """
    Build a .shortcut file from a recipe.

    Always writes ``{stem}_raw.shortcut``. When signing succeeds, also writes
    ``{stem}.shortcut``. Returns a result dict (not only a path):

    ``path`` is the best artifact for import (signed if available, else raw).
    """
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    stem = sanitize_filename(name)
    raw_path = os.path.join(output_dir, "{0}_raw.shortcut".format(stem))
    signed_path = os.path.join(output_dir, "{0}.shortcut".format(stem))

    validation = validate_actions(
        actions_config,
        safe_mode=safe_mode,
        target_platform=target_platform,
        coerce_mode=coerce_mode,
    )
    if not validation["ok"]:
        raise ValueError(
            "Invalid action recipe:\n- " + "\n- ".join(validation["errors"])
        )

    shortcut_dict = build_shortcut_dict(
        actions_config,
        name=name,
        icon_color=icon_color,
        icon_glyph=icon_glyph,
        workflow_types=workflow_types,
        safe_mode=safe_mode,
        target_platform=target_platform,
        coerce_mode=coerce_mode,
    )

    with open(raw_path, "wb") as f:
        plistlib.dump(shortcut_dict, f, fmt=plistlib.FMT_BINARY)

    signed_ok = False
    sign_error = None
    final_signed: Optional[str] = None
    if sign:
        ok, msg = sign_shortcut_file(raw_path, signed_path, mode=sign_mode)
        if ok:
            signed_ok = True
            final_signed = os.path.abspath(signed_path)
        else:
            sign_error = msg
            note_path = os.path.join(output_dir, "{0}_sign_error.txt".format(stem))
            try:
                with open(note_path, "w", encoding="utf-8") as nf:
                    nf.write(msg + "\n")
            except OSError:
                pass

    best = final_signed or os.path.abspath(raw_path)
    return {
        "ok": True,
        "name": name,
        "stem": stem,
        "raw_path": os.path.abspath(raw_path),
        "signed_path": final_signed,
        "path": best,
        "signed": signed_ok,
        "sign_error": sign_error,
        "action_count": len(actions_config or []),
        "actions_summary": actions_summary(actions_config),
        "warnings": validation.get("warnings") or [],
        "risks": validation.get("risks") or [],
        "aliases": {
            str(item.get("as")): idx
            for idx, item in enumerate(actions_config or [])
            if isinstance(item, dict) and item.get("as")
        },
    }


def compare_shortcut_recipes(
    path_a: Optional[str] = None,
    path_b: Optional[str] = None,
    recipe_a: Optional[list] = None,
    recipe_b: Optional[list] = None,
) -> Dict[str, Any]:
    """Compare two shortcuts or action recipes step-by-step and highlight parameter diffs/unbound warnings."""
    from decompiler import decompile_shortcut

    def _resolve_actions(path: Optional[str], rec: Optional[list]) -> Tuple[list, Dict[str, Any]]:
        if rec and isinstance(rec, list):
            return rec, {"source": "in_memory_recipe", "action_count": len(rec)}
        if path and isinstance(path, str):
            dec = decompile_shortcut(path)
            return dec.get("actions") or [], dec
        raise ValueError("Must provide path_a/recipe_a or path_b/recipe_b")

    actions_a, meta_a = _resolve_actions(path_a, recipe_a)
    actions_b, meta_b = _resolve_actions(path_b, recipe_b)

    val_a = validate_actions(actions_a, allow_empty=True)
    val_b = validate_actions(actions_b, allow_empty=True)

    max_len = max(len(actions_a), len(actions_b))
    step_diffs = []
    param_diffs = []

    for i in range(max_len):
        act_a = actions_a[i] if i < len(actions_a) else None
        act_b = actions_b[i] if i < len(actions_b) else None

        type_a = (act_a.get("type") or act_a.get("wf_identifier")) if isinstance(act_a, dict) else None
        type_b = (act_b.get("type") or act_b.get("wf_identifier")) if isinstance(act_b, dict) else None

        params_a = (act_a.get("params") or {}) if isinstance(act_a, dict) else {}
        params_b = (act_b.get("params") or {}) if isinstance(act_b, dict) else {}

        diff_keys = set(params_a.keys()) ^ set(params_b.keys())
        mismatched_vals = {
            k: {"a": params_a.get(k), "b": params_b.get(k)}
            for k in set(params_a.keys()) & set(params_b.keys())
            if params_a.get(k) != params_b.get(k)
        }

        diff_info = {
            "index": i,
            "type_a": type_a,
            "type_b": type_b,
            "params_a": params_a,
            "params_b": params_b,
            "type_match": type_a == type_b,
            "param_diff_keys": sorted(list(diff_keys)),
            "param_value_mismatches": mismatched_vals,
        }
        step_diffs.append(diff_info)
        if diff_keys or mismatched_vals or type_a != type_b:
            param_diffs.append(diff_info)

    recommendations = []
    if val_a.get("warnings"):
        for w in val_a["warnings"]:
            # Surface device-trap warnings (crop interactive UI, volume, etc.)
            if any(
                needle in w
                for needle in (
                    "Shortcuts app will prompt",
                    "Custom",
                    "interactive",
                    "이미지",
                    "알 수 없는",
                    "restore loop",
                    "crop without",
                )
            ):
                recommendations.append("Shortcut A Warning: {0}".format(w))

    return {
        "ok": True,
        "shortcut_a": {
            "path": path_a,
            "action_count": len(actions_a),
            "warnings": val_a.get("warnings") or [],
            "errors": val_a.get("errors") or [],
        },
        "shortcut_b": {
            "path": path_b,
            "action_count": len(actions_b),
            "warnings": val_b.get("warnings") or [],
            "errors": val_b.get("errors") or [],
        },
        "step_count_max": max_len,
        "different_action_count": len(param_diffs),
        "param_diffs": param_diffs,
        "recommendations": recommendations,
    }


def bind_recipe_params(
    path: Optional[str] = None,
    actions: Optional[list] = None,
    param_updates: Optional[list] = None,
    name: str = "improved_fixed",
    output_dir: Optional[str] = None,
    sign: bool = True,
    sign_mode: str = "anyone",
) -> Dict[str, Any]:
    """Bind or update parameter values for specific actions in a shortcut file or recipe."""
    from decompiler import decompile_shortcut

    if not output_dir:
        output_dir = os.path.join(_ROOT, "dist")

    if actions and isinstance(actions, list):
        target_actions = [dict(a) for a in actions]
    elif path and isinstance(path, str):
        dec = decompile_shortcut(path)
        target_actions = dec.get("actions") or []
    else:
        raise ValueError("Must provide either 'path' or 'actions'")

    if not param_updates or not isinstance(param_updates, list):
        param_updates = []

    applied_count = 0
    for update in param_updates:
        if not isinstance(update, dict):
            continue
        idx = update.get("action_index")
        atype = update.get("action_type")
        new_params = update.get("params") or {}
        if not isinstance(new_params, dict):
            continue

        for i, act in enumerate(target_actions):
            if not isinstance(act, dict):
                continue
            cur_type = act.get("type") or act.get("wf_identifier")
            if idx is not None and i == idx:
                act.setdefault("params", {}).update(new_params)
                applied_count += 1
            elif idx is None and atype and cur_type == atype:
                act.setdefault("params", {}).update(new_params)
                applied_count += 1

    built = build_shortcut_plist(
        target_actions,
        name=name,
        output_dir=output_dir,
        sign=sign,
        sign_mode=sign_mode,
    )
    built["applied_param_updates"] = applied_count
    built["updated_actions"] = target_actions
    return built
