#!/usr/bin/env python3
"""
Decompile-learning loop: mine WF parameter shapes from:
  1. Compiled curated / template / fixture recipes
  2. On-disk .shortcut files under configurable roots (dist, user paths)
  3. Optional iCloud / library export dirs

Produces data/learned_param_maps.json used by the generic compiler to:
  - map ergonomic short keys → WF… keys
  - prefer known value kinds (text token vs bare string)
  - surface confidence scores for agents

This is how we expand "executable quality" beyond hand-curated compilers
without claiming full Apple schema reverse-engineering.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from action_catalog import CURATED_ALIASES, identifier_to_auto_short
from wf_serialization import is_serialized_wf_value

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.join(_ROOT, "data")
_LEARNED_PATH = os.path.join(_DATA, "learned_param_maps.json")

# Seed recipes used when no external .shortcut corpus exists
_SEED_RECIPES: List[Dict[str, Any]] = [
    {
        "name": "seed_basics",
        "actions": [
            {"type": "comment", "params": {"text": "learn"}},
            {"type": "text", "params": {"text": "hello"}},
            {"type": "set_variable", "params": {"var_name": "X"}},
            {"type": "get_variable", "params": {"var_name": "X"}},
            {"type": "delay", "params": {"seconds": 1}},
            {"type": "set_volume", "params": {"volume": 0.5}},
            {"type": "speak_text", "params": {"text": "hi", "wait": True, "rate": 0.5}},
            {
                "type": "show_notification",
                "params": {"title": "T", "body": "B", "sound": True},
            },
            {"type": "show_alert", "params": {"title": "A", "message": "M"}},
            {"type": "show_result", "params": {"text": "R"}},
            {"type": "open_url", "params": {"url": "https://example.com"}},
            {
                "type": "open_app",
                "params": {
                    "bundle_id": "com.apple.Safari",
                    "app_name": "Safari",
                },
            },
            {"type": "get_clipboard", "params": {}},
            {"type": "set_clipboard", "params": {"text": "clip"}},
            {"type": "nothing", "params": {}},
            {"type": "exit_shortcut", "params": {}},
            {
                "type": "get_contents_of_url",
                "params": {"url": "https://httpbin.org/get", "method": "GET"},
            },
            {
                "type": "run_shell_script",
                "params": {"script": "echo hi", "shell": "/bin/zsh"},
            },
            {
                "type": "run_applescript",
                "params": {"script": 'return "ok"'},
            },
            {"type": "list", "params": {"items": ["a", "b"]}},
            {"type": "dictionary", "params": {"items": {"k": "v"}}},
            {"type": "count", "params": {"count_type": "Items"}},
            {"type": "calculate", "params": {"operation": "+", "operand": 1}},
            {"type": "change_case", "params": {"case": "UPPERCASE"}},
            {
                "type": "replace_text",
                "params": {"find": "a", "replace": "b", "case_sensitive": False},
            },
            {"type": "split_text", "params": {"separator": "New Lines"}},
            {"type": "combine_text", "params": {"separator": "New Lines"}},
            {"type": "take_screenshot", "params": {}},
            {"type": "ocr_extract_text", "params": {}},
            {"type": "get_battery", "params": {}},
            {
                "type": "get_device_details",
                "params": {"detail": "Device Name"},
            },
            {"type": "set_wifi", "params": {"on": True}},
            {"type": "set_bluetooth", "params": {"on": True}},
            {
                "type": "set_focus",
                "params": {"mode": "Do Not Disturb", "until": "Turned Off"},
            },
            {"type": "ask", "params": {"prompt": "?", "default": ""}},
            {"type": "vibrate", "params": {}},
            {"type": "play_sound", "params": {}},
            {
                "type": "send_message",
                "params": {
                    "recipients": ["+10000000000"],
                    "message": "hi",
                    "show_compose": True,
                },
            },
            {
                "type": "send_email",
                "params": {
                    "to": ["a@b.c"],
                    "subject": "s",
                    "body": "b",
                    "show_compose": True,
                },
            },
            {
                "type": "run_shortcut",
                "params": {"name": "Other", "show_while_running": False},
            },
        ],
    },
    {
        "name": "seed_control",
        "actions": [
            {"type": "text", "params": {"text": "ok"}},
            {
                "type": "conditional_start",
                "params": {
                    "group_id": "G1",
                    "condition": "contains",
                    "value": "ok",
                },
            },
            {"type": "show_notification", "params": {"title": "Y", "body": "yes"}},
            {"type": "conditional_else", "params": {"group_id": "G1"}},
            {"type": "show_notification", "params": {"title": "N", "body": "no"}},
            {"type": "conditional_end", "params": {"group_id": "G1"}},
            {
                "type": "repeat_start",
                "params": {"group_id": "R1", "count": 2},
            },
            {"type": "delay", "params": {"seconds": 0.1}},
            {"type": "repeat_end", "params": {"group_id": "R1"}},
        ],
    },
]


def _camel_to_snake(name: str) -> str:
    name = re.sub(r"^WF", "", name)
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def short_candidates_for_wf_key(key: str) -> List[str]:
    """Generate ergonomic short names from a WF parameter key."""
    if not key or key in {"UUID", "GroupingIdentifier", "WFControlFlowMode"}:
        return []
    snake = _camel_to_snake(key)
    parts = [p for p in snake.split("_") if p]
    out: List[str] = []
    if snake:
        out.append(snake)
    if parts:
        out.append(parts[-1])  # Text, Time, Name…
        if len(parts) >= 2:
            out.append("_".join(parts[-2:]))
    # common aliases
    aliases = {
        "speak_text_text": ["text"],
        "text_action_text": ["text"],
        "notification_action_title": ["title"],
        "notification_action_body": ["body"],
        "alert_action_title": ["title"],
        "alert_action_message": ["message", "body"],
        "delay_time": ["seconds", "delay"],
        "volume": ["volume"],
        "brightness": ["brightness"],
        "url": ["url"],
        "input": ["url", "input", "text"],
        "variable_name": ["var_name", "name"],
        "shell_script": ["script"],
        "app_identifier": ["bundle_id"],
        "http_method": ["method"],
        "repeat_count": ["count"],
    }
    for a in aliases.get(snake, []):
        out.append(a)
    # dedupe
    seen = set()
    uniq = []
    for x in out:
        if x and x not in seen and x not in {"wf", "action"}:
            seen.add(x)
            uniq.append(x)
    return uniq


def value_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        st = value.get("WFSerializationType")
        if st:
            return str(st)
        if "BundleIdentifier" in value:
            return "app_ref"
        return "dict"
    return type(value).__name__


def _empty_stats() -> Dict[str, Any]:
    return {
        "version": 1,
        "generated_at": None,
        "sources": [],
        "action_count_observed": 0,
        "file_count": 0,
        "recipe_count": 0,
        "actions": {},
        "notes": [
            "short_to_wf maps are frequency-ranked suggestions for the generic compiler",
            "confidence = key_freq / max_key_freq for that action",
            "Regenerate: python3 scripts/learn_from_shortcuts.py",
        ],
    }


def _ensure_action(store: dict, ident: str) -> dict:
    if ident not in store:
        store[ident] = {
            "identifier": ident,
            "short_names": [identifier_to_auto_short(ident)],
            "key_freq": {},
            "value_kinds": {},
            "short_to_wf": {},
            "wf_to_short": {},
            "samples": 0,
            "curated_alias": None,
        }
        # reverse curated
        for short, full in CURATED_ALIASES.items():
            if full == ident:
                store[ident]["curated_alias"] = short
                if short not in store[ident]["short_names"]:
                    store[ident]["short_names"].insert(0, short)
                break
    return store[ident]


def observe_wf_action(store: dict, action: dict) -> None:
    ident = action.get("WFWorkflowActionIdentifier")
    if not ident:
        return
    params = action.get("WFWorkflowActionParameters") or {}
    entry = _ensure_action(store, ident)
    entry["samples"] = int(entry.get("samples") or 0) + 1
    key_freq = entry.setdefault("key_freq", {})
    value_kinds = entry.setdefault("value_kinds", {})
    for k, v in params.items():
        if k == "UUID":
            continue
        key_freq[k] = int(key_freq.get(k, 0)) + 1
        kinds = value_kinds.setdefault(k, {})
        kind = value_kind(v)
        kinds[kind] = int(kinds.get(kind, 0)) + 1


def observe_plist_actions(store: dict, wf_actions: list) -> int:
    n = 0
    for a in wf_actions or []:
        if isinstance(a, dict):
            observe_wf_action(store, a)
            n += 1
    return n


def learn_from_compiled_recipe(
    store: dict,
    actions: list,
    *,
    source: str = "recipe",
) -> int:
    # Lazy import avoids cycle: shortcut_builder → param_learning → shortcut_builder
    from shortcut_builder import compile_recipe

    compiled = compile_recipe(actions, safe_mode=False, coerce_mode="off")
    return observe_plist_actions(store, compiled.get("wf_actions") or [])


def learn_from_shortcut_file(store: dict, path: str) -> int:
    """Decompile/load plist and observe raw WF actions when possible."""
    import plistlib

    path = os.path.abspath(path)
    # Prefer raw sibling
    candidates = [path]
    base = os.path.basename(path)
    if base.endswith(".shortcut") and not base.endswith("_raw.shortcut"):
        raw = os.path.join(
            os.path.dirname(path),
            base[: -len(".shortcut")] + "_raw.shortcut",
        )
        if os.path.isfile(raw):
            candidates.insert(0, raw)

    for cand in candidates:
        try:
            with open(cand, "rb") as f:
                data = f.read()
            plist = plistlib.loads(data)
            return observe_plist_actions(store, plist.get("WFWorkflowActions") or [])
        except Exception:
            continue

    # Fall back: decompile path may still yield curated-only view — skip for learning
    # (we need raw WF keys, not reverse-curated params)
    return 0


def discover_shortcut_files(roots: Iterable[str]) -> List[str]:
    found: List[str] = []
    for root in roots:
        root = os.path.expanduser(root)
        if not root or not os.path.exists(root):
            continue
        if os.path.isfile(root) and root.endswith(".shortcut"):
            found.append(os.path.abspath(root))
            continue
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            # skip huge / irrelevant trees
            if any(
                skip in dirpath
                for skip in (
                    "/node_modules",
                    "/.git",
                    "/DerivedData",
                    "/Caches",
                )
            ):
                continue
            for fn in filenames:
                if fn.endswith(".shortcut"):
                    found.append(os.path.join(dirpath, fn))
    # prefer raw files (richer for learning)
    found = sorted(set(found))
    return found


def default_learn_roots() -> List[str]:
    roots = [
        os.path.join(_ROOT, "dist"),
        os.path.join(_ROOT, "fixtures"),
        os.path.join(_ROOT, "examples"),
    ]
    env = os.environ.get("IOS_SHORTCUTS_MCP_LEARN_ROOTS", "")
    if env:
        for part in re.split(r"[:;,]", env):
            part = part.strip()
            if part:
                roots.append(part)
    return roots


def finalize_maps(store: dict) -> None:
    """Build short_to_wf / wf_to_short with conflict resolution by frequency."""
    for ident, entry in store.items():
        key_freq: Dict[str, int] = entry.get("key_freq") or {}
        if not key_freq:
            continue
        # candidate short -> list of (wf_key, freq)
        cand: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        for wf_key, freq in key_freq.items():
            for short in short_candidates_for_wf_key(wf_key):
                cand[short].append((wf_key, freq))

        short_to_wf: Dict[str, str] = {}
        wf_to_short: Dict[str, str] = {}
        # One short name may map to at most one WF key (highest freq).
        # One WF key may be targeted by many short aliases.
        assignments: List[Tuple[int, str, str]] = []
        for short, pairs in cand.items():
            pairs.sort(key=lambda x: -x[1])
            wf_key, freq = pairs[0]
            assignments.append((freq, short, wf_key))
        assignments.sort(key=lambda x: -x[0])

        taken_short: Set[str] = set()
        for freq, short, wf_key in assignments:
            if short in taken_short:
                continue
            # If this short is extremely ambiguous (multiple high-freq targets
            # within 10%), skip single-token generics unless unique.
            rivals = cand.get(short) or []
            if len(rivals) > 1 and len(short) <= 4:
                top = rivals[0][1]
                second = rivals[1][1]
                if second >= top * 0.9 and rivals[0][0] != wf_key:
                    continue
            short_to_wf[short] = wf_key
            taken_short.add(short)
            # Prefer shortest ergonomic alias as primary reverse map
            prev = wf_to_short.get(wf_key)
            if prev is None or len(short) < len(prev):
                wf_to_short[wf_key] = short

        # confidence
        max_f = max(key_freq.values()) if key_freq else 1
        entry["key_confidence"] = {
            k: round(float(v) / float(max_f), 3) for k, v in key_freq.items()
        }
        entry["short_to_wf"] = short_to_wf
        entry["wf_to_short"] = wf_to_short
        entry["primary_keys"] = [
            k
            for k, _ in sorted(key_freq.items(), key=lambda kv: -kv[1])
            if k != "UUID"
        ][:12]


def run_learning(
    *,
    roots: Optional[List[str]] = None,
    include_seeds: bool = True,
    include_templates: bool = True,
    include_fixtures: bool = True,
) -> Dict[str, Any]:
    doc = _empty_stats()
    store: Dict[str, Any] = {}
    sources: List[str] = []
    recipe_count = 0
    file_count = 0
    action_obs = 0

    if include_seeds:
        for seed in _SEED_RECIPES:
            n = learn_from_compiled_recipe(
                store, seed["actions"], source="seed:" + seed["name"]
            )
            action_obs += n
            recipe_count += 1
            sources.append("seed:" + seed["name"])

    if include_templates:
        from shortcut_builder import TEMPLATES

        for name, tpl in TEMPLATES.items():
            n = learn_from_compiled_recipe(
                store, tpl["actions"], source="template:" + name
            )
            action_obs += n
            recipe_count += 1
            sources.append("template:" + name)

    if include_fixtures:
        fix_dir = os.path.join(_ROOT, "fixtures", "recipes")
        if os.path.isdir(fix_dir):
            for fn in sorted(os.listdir(fix_dir)):
                if not fn.endswith(".json"):
                    continue
                path = os.path.join(fix_dir, fn)
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                actions = data.get("actions") or []
                n = learn_from_compiled_recipe(
                    store, actions, source="fixture:" + fn
                )
                action_obs += n
                recipe_count += 1
                sources.append("fixture:" + fn)

    roots = roots if roots is not None else default_learn_roots()
    files = discover_shortcut_files(roots)
    # Prefer *_raw.shortcut
    raw_first = [p for p in files if p.endswith("_raw.shortcut")]
    signed_only = [
        p
        for p in files
        if p.endswith(".shortcut") and not p.endswith("_raw.shortcut")
    ]
    ordered = raw_first + signed_only
    for path in ordered:
        n = learn_from_shortcut_file(store, path)
        if n:
            action_obs += n
            file_count += 1
            sources.append("file:" + path)

    finalize_maps(store)

    doc["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    doc["sources"] = sources
    doc["action_count_observed"] = action_obs
    doc["file_count"] = file_count
    doc["recipe_count"] = recipe_count
    doc["actions"] = store
    doc["identifier_count"] = len(store)
    return doc


def save_learned(doc: Dict[str, Any], path: str = _LEARNED_PATH) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def load_learned(path: str = _LEARNED_PATH) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return _empty_stats()
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return _empty_stats()


_LEARNED_CACHE: Optional[Dict[str, Any]] = None


def get_learned(force_reload: bool = False) -> Dict[str, Any]:
    global _LEARNED_CACHE
    if _LEARNED_CACHE is None or force_reload:
        _LEARNED_CACHE = load_learned()
    return _LEARNED_CACHE


def get_param_map(identifier: str) -> Dict[str, Any]:
    learned = get_learned()
    actions = learned.get("actions") or {}
    entry = actions.get(identifier)
    if not entry:
        # try resolve via auto short / curated
        for short, full in CURATED_ALIASES.items():
            if short == identifier or full == identifier:
                entry = actions.get(full)
                break
    return entry or {}


def apply_learned_param_map(
    identifier: str,
    params: dict,
    *,
    min_confidence: float = 0.0,
) -> Tuple[dict, List[str]]:
    """
    Remap ergonomic short keys to WF keys using learned maps.
    Returns (new_params, notes).
    """
    if not params:
        return {}, []
    entry = get_param_map(identifier)
    short_to_wf = (entry or {}).get("short_to_wf") or {}
    key_conf = (entry or {}).get("key_confidence") or {}
    if not short_to_wf:
        return dict(params), []

    out = dict(params)
    notes: List[str] = []
    # Only remap keys that are not already WF-style
    for short, wf_key in short_to_wf.items():
        if short not in out:
            continue
        if short.startswith("WF") or short == wf_key:
            continue
        conf = float(key_conf.get(wf_key, 1.0))
        if conf < min_confidence:
            continue
        if wf_key in out:
            # don't overwrite explicit WF key
            notes.append(
                "kept explicit {0}; ignored short {1}".format(wf_key, short)
            )
            continue
        out[wf_key] = out.pop(short)
        notes.append("mapped {0} → {1}".format(short, wf_key))
    return out, notes


def learned_stats() -> Dict[str, Any]:
    doc = get_learned()
    actions = doc.get("actions") or {}
    with_maps = sum(1 for a in actions.values() if a.get("short_to_wf"))
    return {
        "path": _LEARNED_PATH,
        "exists": os.path.isfile(_LEARNED_PATH),
        "generated_at": doc.get("generated_at"),
        "identifier_count": len(actions),
        "with_short_maps": with_maps,
        "action_count_observed": doc.get("action_count_observed"),
        "file_count": doc.get("file_count"),
        "recipe_count": doc.get("recipe_count"),
        "source_count": len(doc.get("sources") or []),
    }


def top_learned_actions(limit: int = 20) -> List[Dict[str, Any]]:
    doc = get_learned()
    rows = []
    for ident, entry in (doc.get("actions") or {}).items():
        rows.append(
            {
                "identifier": ident,
                "samples": entry.get("samples", 0),
                "keys": len(entry.get("key_freq") or {}),
                "short_to_wf": entry.get("short_to_wf") or {},
                "curated_alias": entry.get("curated_alias"),
                "primary_keys": entry.get("primary_keys") or [],
            }
        )
    rows.sort(key=lambda r: (-int(r["samples"]), r["identifier"]))
    return rows[:limit]
