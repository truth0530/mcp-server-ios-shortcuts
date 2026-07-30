#!/usr/bin/env python3
"""
Smart WF serialization / auto-coercion layer.

Apple Shortcuts parameters are often *not* bare JSON scalars. Many fields
expect wrapper dictionaries such as:

  WFTextTokenString / WFTextTokenAttachment
  WFNumberSubstitutableState
  WFBooleanSubstitutableState (bool often still plain)

This module coerces plain LLM-friendly values into safer WF-shaped values
for the **generic** compiler path, reducing "Silent Corruption" where a
plist builds and signs but the Shortcuts UI shows empty parameters.

Curated action compilers may still emit bare values that are known-good
for those specific keys.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set

# Already-serialized markers
_SERIALIZATION_KEYS = frozenset(
    {
        "WFSerializationType",
        "Value",
        "attachmentsByRange",
    }
)

# Parameter key heuristics → coercion kind
_TEXT_KEY_RE = re.compile(
    r"(text|title|body|prompt|message|name|query|comment|note|subject|"
    r"caption|header|footer|label|description|url|path|script|source|"
    r"string|content|input|output|filename|folder)$",
    re.I,
)
_NUMBER_KEY_RE = re.compile(
    r"(count|time|seconds|rate|volume|brightness|index|number|value|"
    r"width|height|delay|duration|offset|limit|quantity|price|amount|"
    r"latitude|longitude|altitude|speed|level)$",
    re.I,
)
_BOOL_KEY_RE = re.compile(
    r"(wait|enabled|show|hide|on|off|toggle|allow|include|exclude|"
    r"multiple|overwrite|case.?sensitive|regular.?expression|sound|"
    r"local.?only|ask|open|close)$",
    re.I,
)

# Keys that should stay plain even on generic path (UUID, enums, modes)
_PLAIN_KEYS = frozenset(
    {
        "UUID",
        "GroupingIdentifier",
        "WFControlFlowMode",
        "WFCondition",
        "WFHTTPMethod",
        "WFCaseType",
        "WFInputType",
        "WFHashType",
        "WFEncodeMode",
        "WFAppIdentifier",
        "WFDeviceDetail",
        "WFNetworkDetail",
        "WFMathOperation",
        "WFItemSpecifier",
        "WFCropImagePosition",
        "WFFlashlightSetting",
        "WFDateActionMode",
        "FocusMode",
        "OnValue",
        "ShowWhenRun",
        "Show-text_case",
    }
)


def is_serialized_wf_value(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("WFSerializationType"):
        return True
    # SelectedApp-style nested dicts are intentional structures
    if "BundleIdentifier" in value or "Name" in value and "BundleIdentifier" in value:
        return True
    return False


def text_token_string(text: str) -> dict:
    return {
        "Value": {
            "string": text,
            "attachmentsByRange": {},
        },
        "WFSerializationType": "WFTextTokenString",
    }


def number_substitutable(value: float) -> dict:
    return {
        "Value": value,
        "WFSerializationType": "WFNumberSubstitutableState",
    }


def boolean_substitutable(value: bool) -> dict:
    return {
        "Value": bool(value),
        "WFSerializationType": "WFBooleanSubstitutableState",
    }


def _looks_text_key(key: str) -> bool:
    if key in _PLAIN_KEYS:
        return False
    if key.startswith("WF") and _TEXT_KEY_RE.search(key):
        return True
    if _TEXT_KEY_RE.search(key):
        return True
    # Common explicit keys
    return key in {
        "WFSpeakTextText",
        "WFTextActionText",
        "WFNotificationActionTitle",
        "WFNotificationActionBody",
        "WFAlertActionTitle",
        "WFAlertActionMessage",
        "WFAskActionPrompt",
        "WFCommentActionText",
        "WFURL",
        "WFInput",
        "WFShellScript",
        "Text",
    }


def _looks_number_key(key: str) -> bool:
    if key in _PLAIN_KEYS:
        return False
    return bool(_NUMBER_KEY_RE.search(key)) or key in {
        "WFDelayTime",
        "WFVolume",
        "WFBrightness",
        "WFSpeakTextRate",
        "WFRepeatCount",
        "WFNumberValue",
        "WFNumberOperand",
        "WFPhotoCount",
        "WFItemIndex",
    }


def _looks_bool_key(key: str) -> bool:
    if key in _PLAIN_KEYS:
        return key in {"ShowWhenRun", "OnValue", "UntilTurnedOff"}
    return bool(_BOOL_KEY_RE.search(key)) or key in {
        "WFSpeakTextWait",
        "WFNotificationActionSound",
        "WFAlertActionCancelButtonShown",
        "WFSelectMultiplePhotos",
        "WFAskWhereToSave",
        "WFSaveFileOverwrite",
        "WFShowWorkflow",
        "WFReplaceTextCaseSensitive",
        "WFReplaceTextRegularExpression",
        "WFMatchTextCaseSensitive",
        "WFLocalOnly",
    }


def coerce_value(key: str, value: Any, *, mode: str = "smart") -> Any:
    """
    Coerce a single parameter value.

    mode:
      - off: identity
      - smart: wrap plain scalars when key heuristics match (default)
      - aggressive: wrap all plain strings as WFTextTokenString and
        all numbers as WFNumberSubstitutableState
    """
    if mode in (None, "off", "none", False):
        return value
    if value is None:
        return value
    if is_serialized_wf_value(value):
        return value
    # Magic-ref leftovers should already be resolved before this stage
    if isinstance(value, dict):
        return {k: coerce_value(k, v, mode=mode) for k, v in value.items()}
    if isinstance(value, list):
        return [coerce_value(key, v, mode=mode) for v in value]

    aggressive = mode in ("aggressive", "strict", "full")

    if isinstance(value, bool):
        if aggressive and _looks_bool_key(key):
            return boolean_substitutable(value)
        return value

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if aggressive or _looks_number_key(key):
            # Integers used as enums (WFControlFlowMode etc.) stay plain
            if key in _PLAIN_KEYS:
                return value
            return number_substitutable(float(value))
        return value

    if isinstance(value, str):
        if key in _PLAIN_KEYS:
            return value
        if aggressive or _looks_text_key(key):
            # Empty string: still wrap so UI has a token field
            return text_token_string(value)
        return value

    return value


def coerce_params(params: Optional[dict], *, mode: str = "smart") -> dict:
    if not params:
        return {}
    if mode in (None, "off", "none", False):
        return dict(params)
    out: Dict[str, Any] = {}
    for k, v in params.items():
        out[k] = coerce_value(str(k), v, mode=mode)
    return out


def unwrap_value(value: Any) -> Any:
    """Best-effort reverse of coercion for decompiler readability."""
    if not isinstance(value, dict):
        return value
    st = value.get("WFSerializationType")
    if st == "WFTextTokenString":
        inner = value.get("Value") or {}
        if isinstance(inner, dict) and not inner.get("attachmentsByRange"):
            return inner.get("string", value)
        # Has attachments — keep structured
        return value
    if st == "WFTextTokenAttachment":
        return value  # keep structure (variable / action output)
    if st in {"WFNumberSubstitutableState", "WFBooleanSubstitutableState"}:
        if "Value" in value and not isinstance(value["Value"], dict):
            return value["Value"]
    return value


def unwrap_params(params: Optional[dict]) -> dict:
    if not params:
        return {}
    return {k: unwrap_value(v) for k, v in params.items()}
