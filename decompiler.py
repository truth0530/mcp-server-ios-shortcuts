#!/usr/bin/env python3
"""
Reverse decompiler: .shortcut (binary/XML plist) → high-level recipe JSON.

Supports:
  - Unsigned raw plists (always produced as *_raw.shortcut by this server)
  - Signed packages when a sibling *_raw.shortcut exists
  - Best-effort unwrap of WFTextTokenString / number wrappers for readability

Does *not* claim perfect round-trip for every App Intent payload, but
gives agents a structural recipe they can edit and re-build.
"""

from __future__ import annotations

import os
import plistlib
from typing import Any, Dict, List, Optional, Tuple

from action_catalog import (
    CURATED_ALIASES,
    identifier_to_auto_short,
    build_catalog_index,
)
from wf_serialization import unwrap_params


def _find_sibling_raw_path(path: str) -> Optional[str]:
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

# Reverse map: full identifier → preferred curated short name
_IDENT_TO_CURATED: Dict[str, str] = {}
for _short, _ident in CURATED_ALIASES.items():
    # Prefer first registered curated short
    _IDENT_TO_CURATED.setdefault(_ident, _short)

# Control-flow reverse mapping
_CONTROL_FLOW = {
    "is.workflow.actions.conditional": "conditional",
    "is.workflow.actions.repeat.count": "repeat",
    "is.workflow.actions.repeat.each": "repeat_each",
    "is.workflow.actions.choosefrommenu": "menu",
}


def _preferred_short(identifier: str) -> str:
    if identifier in _IDENT_TO_CURATED:
        return _IDENT_TO_CURATED[identifier]
    index = build_catalog_index()
    shorts = (index.get("shorts_for_id") or {}).get(identifier) or []
    curated = [s for s in shorts if s in CURATED_ALIASES]
    if curated:
        return curated[0]
    if shorts:
        return shorts[0]
    return identifier_to_auto_short(identifier)


def _load_plist_from_shortcut(path: str) -> Tuple[dict, Dict[str, Any]]:
    """Return (plist, meta) with resolution notes."""
    path = os.path.abspath(path)
    meta: Dict[str, Any] = {
        "requested_path": path,
        "source_path": path,
        "format": None,
    }
    if not os.path.isfile(path):
        raise FileNotFoundError(path)

    with open(path, "rb") as f:
        data = f.read()

    try:
        plist = plistlib.loads(data)
        meta["format"] = "plist"
        return plist, meta
    except Exception:
        pass

    raw = _find_sibling_raw_path(path)
    if raw and raw != path and os.path.isfile(raw):
        with open(raw, "rb") as f:
            raw_data = f.read()
        try:
            plist = plistlib.loads(raw_data)
            meta["format"] = "plist_via_raw_sibling"
            meta["source_path"] = raw
            meta["signed_path"] = path
            return plist, meta
        except Exception as exc:
            meta["raw_error"] = str(exc)

    raise ValueError(
        "Cannot decompile signed/opaque shortcut without a raw plist sibling. "
        "Rebuild with this server (keeps *_raw.shortcut) or supply an unsigned export. "
        "path={0}".format(path)
    )


def _decompile_control_flow(
    identifier: str,
    params: dict,
) -> Optional[Dict[str, Any]]:
    kind = _CONTROL_FLOW.get(identifier)
    if not kind:
        return None
    mode = params.get("WFControlFlowMode")
    group_id = params.get("GroupingIdentifier")
    base_params: Dict[str, Any] = {}
    if group_id:
        base_params["group_id"] = group_id

    if kind == "conditional":
        if mode == 0:
            base_params["condition"] = _condition_name(params.get("WFCondition"))
            if "WFConditionalActionString" in params:
                base_params["value"] = params.get("WFConditionalActionString")
            if "WFNumberValue" in params:
                base_params["number"] = params.get("WFNumberValue")
            return {"type": "conditional_start", "params": base_params}
        if mode == 1:
            return {"type": "conditional_else", "params": base_params}
        if mode == 2:
            return {"type": "conditional_end", "params": base_params}
    if kind == "repeat":
        if mode == 0:
            if "WFRepeatCount" in params:
                base_params["count"] = params.get("WFRepeatCount")
            return {"type": "repeat_start", "params": base_params}
        if mode == 2:
            return {"type": "repeat_end", "params": base_params}
    if kind == "repeat_each":
        if mode == 0:
            return {"type": "repeat_each_start", "params": base_params}
        if mode == 2:
            return {"type": "repeat_each_end", "params": base_params}
    if kind == "menu":
        if mode == 0:
            if "WFMenuPrompt" in params:
                base_params["prompt"] = params.get("WFMenuPrompt")
            if "WFMenuItems" in params:
                base_params["items"] = params.get("WFMenuItems")
            return {"type": "menu_start", "params": base_params}
        if mode == 1:
            if "WFMenuItemTitle" in params:
                base_params["title"] = params.get("WFMenuItemTitle")
            return {"type": "menu_item", "params": base_params}
        if mode == 2:
            return {"type": "menu_end", "params": base_params}
    # Fallback: emit generic with raw params
    return None


def _condition_name(enum_val: Any) -> str:
    mapping = {
        4: "equals",
        5: "not_equals",
        99: "contains",
        999: "does_not_contain",
        8: "begins_with",
        9: "ends_with",
        2: "greater_than",
        3: "greater_or_equal",
        0: "less_than",
        1: "less_or_equal",
        100: "has_value",
        101: "does_not_have_value",
    }
    try:
        return mapping.get(int(enum_val), "equals")
    except (TypeError, ValueError):
        return "equals"


def _curated_reverse(identifier: str, params: dict) -> Optional[Dict[str, Any]]:
    """Map known identifiers back to ergonomic curated params when possible."""
    p = unwrap_params(params)
    p.pop("UUID", None)

    if identifier == "is.workflow.actions.delay":
        return {
            "type": "delay",
            "params": {"seconds": p.get("WFDelayTime", 1)},
        }
    if identifier == "is.workflow.actions.speaktext":
        return {
            "type": "speak_text",
            "params": {
                "text": p.get("WFSpeakTextText", ""),
                "wait": p.get("WFSpeakTextWait", True),
                "rate": p.get("WFSpeakTextRate", 0.45),
                "language": p.get("WFSpeakTextLanguage", "Default"),
            },
        }
    if identifier == "is.workflow.actions.notification":
        return {
            "type": "show_notification",
            "params": {
                "title": p.get("WFNotificationActionTitle", ""),
                "body": p.get("WFNotificationActionBody", ""),
                "sound": p.get("WFNotificationActionSound", True),
            },
        }
    if identifier == "is.workflow.actions.gettext":
        return {"type": "text", "params": {"text": p.get("WFTextActionText", "")}}
    if identifier == "is.workflow.actions.comment":
        return {"type": "comment", "params": {"text": p.get("WFCommentActionText", "")}}
    if identifier == "is.workflow.actions.openurl":
        return {"type": "open_url", "params": {"url": p.get("WFInput", "")}}
    if identifier == "is.workflow.actions.setvolume":
        return {"type": "set_volume", "params": {"volume": p.get("WFVolume", 1.0)}}
    if identifier == "is.workflow.actions.setvariable":
        return {
            "type": "set_variable",
            "params": {"var_name": p.get("WFVariableName", "")},
        }
    if identifier == "is.workflow.actions.nothing":
        return {"type": "nothing", "params": {}}
    if identifier == "is.workflow.actions.showresult":
        return {"type": "show_result", "params": {"text": p.get("Text", "")}}
    if identifier == "is.workflow.actions.openapp":
        app = p.get("WFSelectedApp") or {}
        return {
            "type": "open_app",
            "params": {
                "bundle_id": p.get("WFAppIdentifier")
                or app.get("BundleIdentifier")
                or "",
                "app_name": app.get("Name") or "",
            },
        }
    if identifier == "is.workflow.actions.downloadurl":
        out = {"url": p.get("WFURL", ""), "method": p.get("WFHTTPMethod", "GET")}
        if p.get("WFHTTPHeaders"):
            out["headers"] = p["WFHTTPHeaders"]
        return {"type": "get_contents_of_url", "params": out}
    return None


def decompile_action(action: dict) -> Dict[str, Any]:
    identifier = action.get("WFWorkflowActionIdentifier") or ""
    params = dict(action.get("WFWorkflowActionParameters") or {})

    # App Intent-ish: reverse-DNS not under is.workflow.actions
    if identifier and not identifier.startswith("is.workflow.actions."):
        clean = unwrap_params(params)
        clean.pop("UUID", None)
        return {
            "type": "app_intent",
            "params": {
                "identifier": identifier,
                "parameters": clean,
            },
        }

    cf = _decompile_control_flow(identifier, params)
    if cf:
        return cf

    curated = _curated_reverse(identifier, params)
    if curated:
        return curated

    clean = unwrap_params(params)
    clean.pop("UUID", None)
    short = _preferred_short(identifier)
    return {
        "type": short if short else identifier,
        "params": clean,
        "wf_identifier": identifier,
    }


def decompile_shortcut(
    path: str,
    *,
    prefer_curated: bool = True,
) -> Dict[str, Any]:
    """
    Decompile a .shortcut file into a recipe-shaped document.

    Returns:
      {
        ok, path, source_path, format, name, actions, action_count,
        workflow_types, icon, warnings, raw_actions?
      }
    """
    plist, meta = _load_plist_from_shortcut(path)
    wf_actions = plist.get("WFWorkflowActions") or []
    actions: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for i, raw in enumerate(wf_actions):
        try:
            step = decompile_action(raw)
            if not prefer_curated and step.get("wf_identifier"):
                # force full identifier surface
                step = {
                    "type": raw.get("WFWorkflowActionIdentifier"),
                    "params": unwrap_params(
                        dict(raw.get("WFWorkflowActionParameters") or {})
                    ),
                }
                step["params"].pop("UUID", None)
            actions.append(step)
        except Exception as exc:
            warnings.append("action[{0}]: {1}".format(i, exc))
            actions.append(
                {
                    "type": raw.get("WFWorkflowActionIdentifier") or "unknown",
                    "params": dict(raw.get("WFWorkflowActionParameters") or {}),
                    "decompile_error": str(exc),
                }
            )

    icon = plist.get("WFWorkflowIcon") or {}
    return {
        "ok": True,
        "path": meta.get("requested_path"),
        "source_path": meta.get("source_path"),
        "format": meta.get("format"),
        "name": plist.get("WFWorkflowName"),
        "client_version": plist.get("WFWorkflowClientVersion"),
        "min_client_version": plist.get("WFWorkflowMinimumClientVersion"),
        "workflow_types": plist.get("WFWorkflowTypes"),
        "icon": {
            "glyph": icon.get("WFWorkflowIconGlyphNumber"),
            "color": icon.get("WFWorkflowIconStartColor"),
        },
        "action_count": len(actions),
        "actions": actions,
        "warnings": warnings,
        "note": (
            "Decompiled recipe is best-effort. Re-validate with validate_recipe "
            "before rebuild. App Intent payloads may need manual param fixes."
        ),
    }


def decompile_to_recipe(path: str) -> Dict[str, Any]:
    """Alias returning only name + actions (agent-friendly)."""
    full = decompile_shortcut(path)
    return {
        "ok": full.get("ok"),
        "name": full.get("name") or "Decompiled",
        "actions": full.get("actions") or [],
        "source_path": full.get("source_path"),
        "format": full.get("format"),
        "warnings": full.get("warnings") or [],
        "meta": {
            "action_count": full.get("action_count"),
            "client_version": full.get("client_version"),
            "workflow_types": full.get("workflow_types"),
        },
    }
