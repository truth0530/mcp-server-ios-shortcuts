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

# ---------------------------------------------------------------------------
# Action catalog
# ---------------------------------------------------------------------------

# Canonical short names → Workflow action identifiers.
# Agents should prefer short names; full identifiers are also accepted.
ACTION_MAPPINGS: Dict[str, str] = {
    # Time / location
    "date": "is.workflow.actions.date",
    "adjust_date": "is.workflow.actions.adjustdate",
    "format_date": "is.workflow.actions.formatdate",
    "get_location": "is.workflow.actions.getcurrentlocation",
    "get_addresses": "is.workflow.actions.getaddressesfrominput",
    "get_maps_url": "is.workflow.actions.getmapslink",
    "get_halfway_point": "is.workflow.actions.gethalfwaypoint",
    "get_travel_time": "is.workflow.actions.gettraveltime",
    "open_in_maps": "is.workflow.actions.openinmaps",
    # Control flow
    "conditional": "is.workflow.actions.conditional",
    "repeat": "is.workflow.actions.repeat.count",
    "repeat_each": "is.workflow.actions.repeat.each",
    "choose_from_menu": "is.workflow.actions.choosefrommenu",
    "exit_shortcut": "is.workflow.actions.exit",
    "stop_and_output": "is.workflow.actions.output",
    "wait_to_return": "is.workflow.actions.waittoreturn",
    "nothing": "is.workflow.actions.nothing",
    "comment": "is.workflow.actions.comment",
    # Interaction
    "delay": "is.workflow.actions.delay",
    "ask": "is.workflow.actions.ask",
    "show_result": "is.workflow.actions.showresult",
    "show_alert": "is.workflow.actions.alert",
    "show_notification": "is.workflow.actions.notification",
    "choose_from_list": "is.workflow.actions.choosefromlist",
    "vibrate": "is.workflow.actions.vibrate",
    "play_sound": "is.workflow.actions.playsound",
    "speak_text": "is.workflow.actions.speaktext",
    "dictate_text": "is.workflow.actions.dictatetext",
    # Apps / system
    "open_app": "is.workflow.actions.openapp",
    "open_url": "is.workflow.actions.openurl",
    "search_web": "is.workflow.actions.searchweb",
    "run_shortcut": "is.workflow.actions.runworkflow",
    "get_my_shortcuts": "is.workflow.actions.getmyworkflows",
    "set_volume": "is.workflow.actions.setvolume",
    "get_volume": "is.workflow.actions.getvolume",
    "set_brightness": "is.workflow.actions.setbrightness",
    "get_brightness": "is.workflow.actions.getbrightness",
    "set_flashlight": "is.workflow.actions.flashlight",
    "set_low_power_mode": "is.workflow.actions.lowpowermode",
    "set_focus": "is.workflow.actions.dnd.set",
    "get_battery": "is.workflow.actions.getbatterylevel",
    "get_device_details": "is.workflow.actions.getdevicedetails",
    "get_network_details": "is.workflow.actions.getwifi",
    "set_wifi": "is.workflow.actions.wifi.set",
    "set_bluetooth": "is.workflow.actions.bluetooth.set",
    "set_airplane_mode": "is.workflow.actions.airplanemode.set",
    "set_cellular": "is.workflow.actions.cellulardata.set",
    "lock_screen": "is.workflow.actions.lockscreen",
    # Clipboard / text
    "get_clipboard": "is.workflow.actions.getclipboard",
    "set_clipboard": "is.workflow.actions.setclipboard",
    "text": "is.workflow.actions.gettext",
    "change_case": "is.workflow.actions.text.changecase",
    "split_text": "is.workflow.actions.text.split",
    "combine_text": "is.workflow.actions.text.combine",
    "replace_text": "is.workflow.actions.text.replace",
    "match_text": "is.workflow.actions.text.match",
    "get_text_from_input": "is.workflow.actions.detect.text",
    "count": "is.workflow.actions.count",
    "calculate": "is.workflow.actions.calculate",
    "format_number": "is.workflow.actions.format.number",
    "round_number": "is.workflow.actions.round",
    "base64_encode": "is.workflow.actions.base64encode",
    "url_encode": "is.workflow.actions.urlencode",
    "hash": "is.workflow.actions.hash",
    # Variables / data
    "set_variable": "is.workflow.actions.setvariable",
    "get_variable": "is.workflow.actions.getvariable",
    "add_to_variable": "is.workflow.actions.appendvariable",
    "dictionary": "is.workflow.actions.dictionary",
    "get_dictionary_value": "is.workflow.actions.getvalueforkey",
    "set_dictionary_value": "is.workflow.actions.setvalueforkey",
    "list": "is.workflow.actions.list",
    "get_item_from_list": "is.workflow.actions.getitemfromlist",
    "filter_files": "is.workflow.actions.filter.files",
    # Media / capture
    "take_screenshot": "is.workflow.actions.takescreenshot",
    "take_photo": "is.workflow.actions.takephoto",
    "select_photos": "is.workflow.actions.selectphoto",
    "crop_image": "is.workflow.actions.cropimage",
    "resize_image": "is.workflow.actions.image.resize",
    "rotate_image": "is.workflow.actions.imagerotate",
    "ocr_extract_text": "is.workflow.actions.extracttextfromimage",
    "make_pdf": "is.workflow.actions.makepdf",
    "encode_media": "is.workflow.actions.encodemedia",
    "play_music": "is.workflow.actions.playmusic",
    "pause_music": "is.workflow.actions.pausemusic",
    # Files / network
    "save_file": "is.workflow.actions.documentpicker.save",
    "get_file": "is.workflow.actions.documentpicker.open",
    "get_file_from_folder": "is.workflow.actions.file.get",
    "create_folder": "is.workflow.actions.file.createfolder",
    "rename_file": "is.workflow.actions.file.rename",
    "delete_files": "is.workflow.actions.file.delete",
    "get_contents_of_url": "is.workflow.actions.downloadurl",
    "get_headers_of_url": "is.workflow.actions.url.getheaders",
    "expand_url": "is.workflow.actions.url.expand",
    # Communication
    "send_message": "is.workflow.actions.sendmessage",
    "send_email": "is.workflow.actions.sendemail",
    "share": "is.workflow.actions.share",
    "airdrop": "is.workflow.actions.airdrop",
    # macOS scripting
    "run_shell_script": "is.workflow.actions.runshellscript",
    "run_applescript": "is.workflow.actions.applescript",
    "run_javascript_for_automation": "is.workflow.actions.runjsshortcut",
}

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
        "summary": "Set media volume (0.0–1.0) or a variable name",
        "params": {"volume": "float or variable name string"},
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
        "summary": "Start If block (pair with conditional_else / conditional_end)",
        "params": {
            "group_id": "uuid shared across the if/else/end trio",
            "condition": "equals|contains|greater_than|…",
            "value": "comparison value",
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
        "description": "Read clipboard and show it as a notification",
        "actions": [
            {"type": "get_clipboard", "params": {}},
            {"type": "set_variable", "params": {"var_name": "Clip"}},
            {
                "type": "show_notification",
                "params": {"title": "Clipboard", "body": "See content on stack / variable Clip"},
            },
            {"type": "get_variable", "params": {"var_name": "Clip"}},
            {"type": "show_result", "params": {"text": ""}},
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
        "description": "Take a screenshot, OCR it, show result",
        "actions": [
            {"type": "take_screenshot", "params": {}},
            {"type": "ocr_extract_text", "params": {}},
            {"type": "set_variable", "params": {"var_name": "OCR"}},
            {"type": "get_variable", "params": {"var_name": "OCR"}},
            {"type": "show_result", "params": {"text": ""}},
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


def list_supported_actions() -> List[Dict[str, Any]]:
    """Return a structured catalog for agent discovery."""
    items: List[Dict[str, Any]] = []
    # Synthetic control-flow helpers first
    synthetic = [
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
    ]
    seen = set()
    for name in synthetic + sorted(ACTION_MAPPINGS.keys()):
        if name in seen:
            continue
        seen.add(name)
        doc = ACTION_DOCS.get(name, {})
        items.append(
            {
                "type": name,
                "identifier": ACTION_MAPPINGS.get(name, name),
                "summary": doc.get("summary", ""),
                "params": doc.get("params", {}),
                "example": doc.get("example"),
            }
        )
    return items


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

def _compile_action(item: dict) -> List[dict]:
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
        return [create_action(atype, dict(item["wf_params"]))]

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

    if atype == "crop_image":
        return [
            create_action(
                "crop_image",
                {"WFCropImagePosition": args.get("position", "Custom")},
            )
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
        params = {}
        if args.get("text"):
            params["Text"] = args["text"]
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
            return [
                create_action("text", {"WFTextActionText": str(args["text"])}),
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

    # Generic fallback: treat `type` as short name or full identifier and
    # pass params through as WF parameters. Useful for advanced / newer actions.
    if atype in ACTION_MAPPINGS or atype.startswith("is.workflow.actions."):
        return [create_action(atype, args)]

    raise ValueError(
        f"Unknown action type '{atype}'. "
        f"Use list_actions, pass a full is.workflow.actions.* identifier, "
        f"or provide wf_params for a raw action."
    )


def validate_actions(actions_config: list) -> Dict[str, Any]:
    """Dry-run compile; returns {ok, actions_compiled, errors, warnings}."""
    errors: List[str] = []
    warnings: List[str] = []
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
        }

    for i, item in enumerate(actions_config):
        try:
            parts = _compile_action(item)
            compiled += len(parts)
            atype = (item or {}).get("type") or (item or {}).get("action")
            params = item.get("params") or item.get("arguments") or {}
            gid = params.get("group_id") if isinstance(params, dict) else None
            if atype in start_types:
                if not gid:
                    errors.append(f"actions[{i}] ({atype}): group_id is required")
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
                    errors.append(f"actions[{i}] ({atype}): group_id is required")
                elif not stack:
                    errors.append(f"actions[{i}] ({atype}): no open control-flow block")
                else:
                    expected_kind = "conditional" if atype == "conditional_else" else "menu"
                    current = stack[-1]
                    if current["kind"] != expected_kind or current["group_id"] != str(gid):
                        errors.append(
                            f"actions[{i}] ({atype}): expected open "
                            f"{current['kind']} group_id={current['group_id']}"
                        )
                    elif atype == "conditional_else" and current["has_else"]:
                        errors.append(
                            f"actions[{i}] ({atype}): duplicate else for group_id={gid}"
                        )
                    elif atype == "conditional_else":
                        current["has_else"] = True
            elif atype in end_types:
                if not gid:
                    errors.append(f"actions[{i}] ({atype}): group_id is required")
                elif not stack:
                    errors.append(f"actions[{i}] ({atype}): no open control-flow block")
                else:
                    current = stack[-1]
                    if (
                        current["kind"] != end_types[atype]
                        or current["group_id"] != str(gid)
                    ):
                        errors.append(
                            f"actions[{i}] ({atype}): expected end for "
                            f"{current['kind']} group_id={current['group_id']}"
                        )
                    else:
                        stack.pop()
        except Exception as exc:
            errors.append(f"actions[{i}]: {exc}")

    for group in reversed(stack):
        errors.append(
            f"actions[{group['index']}]: unclosed {group['kind']} "
            f"group_id={group['group_id']}"
        )

    return {
        "ok": len(errors) == 0,
        "actions_compiled": compiled,
        "errors": errors,
        "warnings": warnings,
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
) -> dict:
    """Compile recipe → in-memory shortcut plist dictionary (unsigned)."""
    validation = validate_actions(actions_config)
    if not validation["ok"]:
        raise ValueError(
            "Invalid action recipe:\n- " + "\n- ".join(validation["errors"])
        )

    wf_actions: List[dict] = []
    for item in actions_config:
        wf_actions.extend(_compile_action(item))

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


def inspect_shortcut_file(path: str) -> Dict[str, Any]:
    """Read a .shortcut (binary or XML plist) and summarize it."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)

    with open(path, "rb") as f:
        data = f.read()

    info: Dict[str, Any] = {
        "path": path,
        "size_bytes": len(data),
        "format": "unknown",
    }

    # Signed shortcuts may be wrapped; try plist first.
    try:
        plist = plistlib.loads(data)
        info["format"] = "plist"
    except Exception:
        # Signed package — report limited info.
        info["format"] = "signed_or_opaque"
        info["note"] = (
            "File is not a raw plist (likely signed). "
            "Import it into Shortcuts or re-build from recipe to inspect actions."
        )
        return info

    actions = plist.get("WFWorkflowActions") or []
    info["name"] = plist.get("WFWorkflowName")
    info["client_version"] = plist.get("WFWorkflowClientVersion")
    info["min_client_version"] = plist.get("WFWorkflowMinimumClientVersion")
    info["action_count"] = len(actions)
    info["actions"] = [
        {
            "identifier": a.get("WFWorkflowActionIdentifier"),
            "param_keys": sorted((a.get("WFWorkflowActionParameters") or {}).keys()),
        }
        for a in actions
    ]
    icon = plist.get("WFWorkflowIcon") or {}
    info["icon"] = {
        "glyph": icon.get("WFWorkflowIconGlyphNumber"),
        "color": icon.get("WFWorkflowIconStartColor"),
    }
    info["workflow_types"] = plist.get("WFWorkflowTypes")
    return info


def sign_shortcut_file(
    input_path: str,
    output_path: str,
    mode: str = "anyone",
) -> Tuple[bool, str]:
    """Sign with macOS `shortcuts sign`. Returns (ok, message)."""
    input_path = os.path.abspath(input_path)
    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    if mode not in {"anyone", "people-who-know-me"}:
        return False, f"Invalid sign mode '{mode}' (use anyone|people-who-know-me)"

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
) -> str:
    """
    Build a .shortcut file from a recipe.

    Returns the absolute path of the best available artifact:
    signed path if signing succeeded, otherwise the raw unsigned plist.
    """
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    stem = sanitize_filename(name)
    raw_path = os.path.join(output_dir, f"{stem}_raw.shortcut")
    signed_path = os.path.join(output_dir, f"{stem}.shortcut")

    shortcut_dict = build_shortcut_dict(
        actions_config,
        name=name,
        icon_color=icon_color,
        icon_glyph=icon_glyph,
        workflow_types=workflow_types,
    )

    with open(raw_path, "wb") as f:
        plistlib.dump(shortcut_dict, f, fmt=plistlib.FMT_BINARY)

    if sign:
        ok, msg = sign_shortcut_file(raw_path, signed_path, mode=sign_mode)
        if ok:
            return os.path.abspath(signed_path)
        # Fall through to raw; caller can inspect via build metadata.
        # Leave a sidecar note for debugging.
        note_path = os.path.join(output_dir, f"{stem}_sign_error.txt")
        try:
            with open(note_path, "w", encoding="utf-8") as nf:
                nf.write(msg + "\n")
        except OSError:
            pass

    return os.path.abspath(raw_path)
