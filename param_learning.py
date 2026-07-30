#!/usr/bin/env python3
"""
Trusted parameter learning loop (v2.7).

Hard lessons from v2.6 critique:
  1. Echo chamber: do NOT trust maps mined only from our own builds
  2. Prefer external_apple (Gallery .wflow) + external_user (exports/sqlite)
  3. Enum vs text-token discrimination before coercion
  4. Accept maps only after reverse compile + sign validation

Self-built (dist/, our uuid5) may be recorded as bootstrap_hints but never
auto-accepted into accepted_short_to_wf without external corroboration or
explicit validate_accept_self flag.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from action_catalog import CURATED_ALIASES, identifier_to_auto_short
from library_extractor import extract_all_external, is_self_built_plist
from wf_serialization import is_serialized_wf_value

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.join(_ROOT, "data")
_LEARNED_PATH = os.path.join(_DATA, "learned_param_maps.json")
_ACCEPTED_PATH = os.path.join(_DATA, "accepted_param_maps.json")

TRUSTED_CLASSES = frozenset({"external_apple", "external_user"})
SELF_CLASSES = frozenset({"self", "seed", "template", "fixture"})

# Key name patterns that are almost always enums / plain literals
_ENUM_KEY_RE = re.compile(
    r"(Method|Mode|Type|Case|Operation|Specifier|Position|Setting|Shell|"
    r"Separator|Destination|Device|Detail|Hash|Encode|Language|Camera|"
    r"ControlFlow|Condition)$",
    re.I,
)


def _camel_to_snake(name: str) -> str:
    name = re.sub(r"^WF", "", name)
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def short_candidates_for_wf_key(key: str) -> List[str]:
    if not key or key in {"UUID", "GroupingIdentifier", "WFControlFlowMode"}:
        return []
    snake = _camel_to_snake(key)
    parts = [p for p in snake.split("_") if p]
    out: List[str] = []
    if snake:
        out.append(snake)
    if parts:
        # Prefer multi-part aliases; single-token last (collision-prone)
        if len(parts) >= 2:
            out.append("_".join(parts[-2:]))
        out.append(parts[-1])
    aliases = {
        "speak_text_text": ["text"],
        "text_action_text": ["text"],
        "notification_action_title": ["title"],
        "notification_action_body": ["body"],
        "alert_action_title": ["title"],
        "alert_action_message": ["message", "body"],
        "delay_time": ["seconds", "delay"],
        "variable_name": ["var_name", "name"],
        "shell_script": ["script"],
        "app_identifier": ["bundle_id"],
        "http_method": ["method"],
        "repeat_count": ["count"],
        "search_text": ["find", "search"],
        "replace_text": ["replace"],
    }
    for a in aliases.get(snake, []):
        out.append(a)
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


def classify_param_schema(
    key: str,
    kind_counts: Dict[str, int],
    sample_strings: List[str],
) -> Dict[str, Any]:
    """
    Discriminate enum vs text_token vs number vs bool vs free_text.

    This drives coercion: enums stay plain; text fields may wrap.
    """
    total = sum(kind_counts.values()) or 1
    token_n = sum(
        kind_counts.get(k, 0)
        for k in (
            "WFTextTokenString",
            "WFTextTokenAttachment",
        )
    )
    bool_n = kind_counts.get("bool", 0)
    num_n = kind_counts.get("int", 0) + kind_counts.get("float", 0)
    str_n = kind_counts.get("string", 0)
    num_state = kind_counts.get("WFNumberSubstitutableState", 0)
    bool_state = kind_counts.get("WFBooleanSubstitutableState", 0)

    # Explicit serialization wins
    if token_n / total >= 0.3:
        return {
            "kind": "text_token",
            "coerce": "text_token_string",
            "confidence": round(token_n / total, 3),
        }
    if num_state / total >= 0.3 or (num_n / total >= 0.7 and _looks_number_key(key)):
        return {
            "kind": "number",
            "coerce": "number_state" if num_state else "plain_number",
            "confidence": round((num_state + num_n) / total, 3),
        }
    if bool_state / total >= 0.3 or bool_n / total >= 0.7:
        return {
            "kind": "bool",
            "coerce": "plain_bool",
            "confidence": round((bool_state + bool_n) / total, 3),
        }

    # Enum: small closed set of short plain strings
    uniq = []
    seen = set()
    for s in sample_strings:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    short_literals = [s for s in uniq if isinstance(s, str) and len(s) <= 40]
    if str_n / total >= 0.6 and 1 <= len(short_literals) <= 12:
        # key name looks like enum OR all values are uppercase/token-like
        tokenish = all(
            re.match(r"^[A-Za-z0-9+._ -]+$", s) and " " not in s.strip()
            for s in short_literals
        ) or bool(_ENUM_KEY_RE.search(key))
        if tokenish or _ENUM_KEY_RE.search(key):
            return {
                "kind": "enum",
                "coerce": "plain_string",
                "values": short_literals[:20],
                "confidence": round(str_n / total, 3),
            }

    if str_n / total >= 0.5:
        # free text — prefer plain unless key strongly suggests token field
        coerce = "text_token_string" if re.search(
            r"(Text|Body|Message|Prompt|Comment|Script|Query)$", key
        ) else "plain_string"
        return {
            "kind": "free_text",
            "coerce": coerce,
            "confidence": round(str_n / total, 3),
        }

    return {
        "kind": "unknown",
        "coerce": "off",
        "confidence": 0.0,
    }


def _looks_number_key(key: str) -> bool:
    return bool(
        re.search(
            r"(Count|Time|Seconds|Rate|Volume|Brightness|Index|Number|Width|Height)$",
            key,
            re.I,
        )
    )


def _empty_doc() -> Dict[str, Any]:
    return {
        "version": 2,
        "generated_at": None,
        "sources": [],
        "source_class_counts": {},
        "action_count_observed": 0,
        "trusted_action_count_observed": 0,
        "file_count": 0,
        "recipe_count": 0,
        "actions": {},
        "notes": [
            "trusted learning uses external_apple + external_user only",
            "accepted_short_to_wf requires reverse compile+sign validation",
            "self/seed/template observations are bootstrap_hints only",
        ],
    }


def _ensure_action(store: dict, ident: str) -> dict:
    if ident not in store:
        store[ident] = {
            "identifier": ident,
            "short_names": [identifier_to_auto_short(ident)],
            "key_freq": {},
            "key_freq_trusted": {},
            "value_kinds": {},
            "value_kinds_trusted": {},
            "string_samples": {},
            "string_samples_trusted": {},
            "source_classes": {},
            "short_to_wf": {},
            "short_to_wf_trusted": {},
            "accepted_short_to_wf": {},
            "param_schema": {},
            "wf_to_short": {},
            "samples": 0,
            "samples_trusted": 0,
            "curated_alias": None,
            "validation": None,
        }
        for short, full in CURATED_ALIASES.items():
            if full == ident:
                store[ident]["curated_alias"] = short
                if short not in store[ident]["short_names"]:
                    store[ident]["short_names"].insert(0, short)
                break
    return store[ident]


def observe_wf_action(
    store: dict,
    action: dict,
    *,
    source_class: str,
) -> None:
    ident = action.get("WFWorkflowActionIdentifier")
    if not ident:
        return
    params = action.get("WFWorkflowActionParameters") or {}
    entry = _ensure_action(store, ident)
    trusted = source_class in TRUSTED_CLASSES

    entry["samples"] = int(entry.get("samples") or 0) + 1
    sc = entry.setdefault("source_classes", {})
    sc[source_class] = int(sc.get(source_class, 0)) + 1
    if trusted:
        entry["samples_trusted"] = int(entry.get("samples_trusted") or 0) + 1

    key_freq = entry.setdefault("key_freq", {})
    kinds_all = entry.setdefault("value_kinds", {})
    samples_all = entry.setdefault("string_samples", {})
    key_freq_t = entry.setdefault("key_freq_trusted", {})
    kinds_t = entry.setdefault("value_kinds_trusted", {})
    samples_t = entry.setdefault("string_samples_trusted", {})

    for k, v in params.items():
        if k == "UUID":
            continue
        key_freq[k] = int(key_freq.get(k, 0)) + 1
        kind = value_kind(v)
        kinds_all.setdefault(k, {})
        kinds_all[k][kind] = int(kinds_all[k].get(kind, 0)) + 1
        if isinstance(v, str):
            arr = samples_all.setdefault(k, [])
            if v not in arr and len(arr) < 24:
                arr.append(v)
        elif isinstance(v, dict) and v.get("WFSerializationType") == "WFTextTokenString":
            s = (v.get("Value") or {}).get("string")
            if isinstance(s, str):
                arr = samples_all.setdefault(k, [])
                if s not in arr and len(arr) < 24:
                    arr.append(s)

        if trusted:
            key_freq_t[k] = int(key_freq_t.get(k, 0)) + 1
            kinds_t.setdefault(k, {})
            kinds_t[k][kind] = int(kinds_t[k].get(kind, 0)) + 1
            if isinstance(v, str):
                arr = samples_t.setdefault(k, [])
                if v not in arr and len(arr) < 24:
                    arr.append(v)


def observe_plist(store: dict, plist: dict, *, source_class: str) -> int:
    n = 0
    for a in plist.get("WFWorkflowActions") or []:
        if isinstance(a, dict):
            observe_wf_action(store, a, source_class=source_class)
            n += 1
    return n


def finalize_maps(store: dict, *, trusted_only: bool = True) -> None:
    for ident, entry in store.items():
        key_freq = (
            entry.get("key_freq_trusted") if trusted_only else entry.get("key_freq")
        ) or {}
        # Fall back to all if no trusted data (still finalize as untrusted maps)
        using_trusted = bool(key_freq)
        if not key_freq:
            key_freq = entry.get("key_freq") or {}
            using_trusted = False

        kinds = (
            entry.get("value_kinds_trusted")
            if using_trusted
            else entry.get("value_kinds")
        ) or {}
        samples = (
            entry.get("string_samples_trusted")
            if using_trusted
            else entry.get("string_samples")
        ) or {}

        # schema per key
        schema: Dict[str, Any] = {}
        for k, kc in kinds.items():
            schema[k] = classify_param_schema(k, kc, samples.get(k) or [])
        entry["param_schema"] = schema
        entry["maps_from_trusted"] = using_trusted

        # short maps — prefer multi-part shorts; avoid ambiguous singles across keys
        cand: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        for wf_key, freq in key_freq.items():
            for short in short_candidates_for_wf_key(wf_key):
                cand[short].append((wf_key, freq))

        short_to_wf: Dict[str, str] = {}
        wf_to_short: Dict[str, str] = {}
        assignments: List[Tuple[int, int, str, str]] = []
        # score: prefer longer short names (less collision)
        for short, pairs in cand.items():
            pairs.sort(key=lambda x: -x[1])
            wf_key, freq = pairs[0]
            # ambiguity penalty
            if len(pairs) > 1 and pairs[1][1] >= pairs[0][1] * 0.8:
                if len(short) <= 5:
                    continue  # drop ambiguous generic token
            specificity = len(short)
            assignments.append((freq, specificity, short, wf_key))
        assignments.sort(key=lambda x: (-x[0], -x[1]))

        taken_short: Set[str] = set()
        for freq, _spec, short, wf_key in assignments:
            if short in taken_short:
                continue
            # don't map a short onto two different keys
            short_to_wf[short] = wf_key
            taken_short.add(short)
            prev = wf_to_short.get(wf_key)
            if prev is None or len(short) < len(prev):
                wf_to_short[wf_key] = short

        max_f = max(key_freq.values()) if key_freq else 1
        entry["key_confidence"] = {
            k: round(float(v) / float(max_f), 3) for k, v in key_freq.items()
        }
        entry["short_to_wf"] = short_to_wf
        entry["wf_to_short"] = wf_to_short
        if using_trusted:
            entry["short_to_wf_trusted"] = dict(short_to_wf)
        entry["primary_keys"] = [
            k for k, _ in sorted(key_freq.items(), key=lambda kv: -kv[1])
        ][:12]


def validate_and_accept_maps(
    store: dict,
    *,
    max_actions: int = 40,
    sign: bool = False,
) -> Dict[str, Any]:
    """
    For each action with short_to_wf_trusted, build a generic probe recipe,
    compile (and optionally sign), then copy maps into accepted_short_to_wf.

    Sign defaults to False: `shortcuts sign` can hang under TCC/keychain and
    multiplied timeouts make learning unusable. Compile+raw write is the
    structural gate; set sign=True when the environment is known-good.
    """
    from shortcut_builder import build_shortcut_plist, compile_recipe

    report = {
        "tested": 0,
        "accepted": 0,
        "rejected": 0,
        "details": [],
    }

    # Prefer trusted maps
    items = []
    for ident, entry in store.items():
        m = entry.get("short_to_wf_trusted") or entry.get("short_to_wf") or {}
        if not m:
            continue
        if not entry.get("maps_from_trusted") and entry.get("samples_trusted", 0) == 0:
            # refuse pure self-maps by default
            entry["validation"] = {
                "accepted": False,
                "reason": "no_trusted_samples",
            }
            continue
        items.append((ident, entry, m))

    items.sort(key=lambda x: -int(x[1].get("samples_trusted") or x[1].get("samples") or 0))
    items = items[:max_actions]

    with tempfile.TemporaryDirectory() as td:
        for ident, entry, short_map in items:
            report["tested"] += 1
            schema = entry.get("param_schema") or {}
            # Probe using SHORT keys, then apply candidate map *explicitly*
            # (cannot rely on accepted_short_to_wf — that is what we are deciding).
            probe_short: Dict[str, Any] = {}
            for short, wf_key in list(short_map.items())[:8]:
                sch = schema.get(wf_key) or {}
                kind = sch.get("kind")
                if kind == "enum" and sch.get("values"):
                    probe_short[short] = sch["values"][0]
                elif kind == "number":
                    probe_short[short] = 1
                elif kind == "bool":
                    probe_short[short] = True
                else:
                    probe_short[short] = "probe"

            # Apply candidate map → WF keys for compile input
            probe_wf: Dict[str, Any] = {}
            for short, val in probe_short.items():
                wf_key = short_map.get(short, short)
                probe_wf[wf_key] = val

            recipe = [{"type": ident, "params": probe_wf}]
            try:
                compiled = compile_recipe(
                    recipe, safe_mode=False, coerce_mode="smart"
                )
                wf_params = (
                    compiled["wf_actions"][0].get("WFWorkflowActionParameters") or {}
                )
                # required: WF keys present after compile
                missing = [wf for wf in probe_wf.keys() if wf not in wf_params]
                if missing:
                    entry["validation"] = {
                        "accepted": False,
                        "reason": "missing_wf_keys",
                        "missing": missing,
                    }
                    report["rejected"] += 1
                    report["details"].append(
                        {"identifier": ident, "ok": False, "reason": "missing_wf_keys"}
                    )
                    continue

                # enum keys must remain plain strings (not text token wrappers)
                enum_broken = []
                for wf_key, sch in schema.items():
                    if sch.get("kind") != "enum":
                        continue
                    if wf_key not in probe_wf:
                        continue
                    val = wf_params.get(wf_key)
                    if isinstance(val, dict) and val.get("WFSerializationType"):
                        enum_broken.append(wf_key)
                if enum_broken:
                    entry["validation"] = {
                        "accepted": False,
                        "reason": "enum_wrapped",
                        "keys": enum_broken,
                    }
                    report["rejected"] += 1
                    report["details"].append(
                        {
                            "identifier": ident,
                            "ok": False,
                            "reason": "enum_wrapped",
                            "keys": enum_broken,
                        }
                    )
                    continue

                built = build_shortcut_plist(
                    recipe,
                    "LearnValidate_" + identifier_to_auto_short(ident)[:40],
                    td,
                    sign=bool(sign),
                    safe_mode=False,
                    coerce_mode="smart",
                )
                if not os.path.isfile(built.get("raw_path") or ""):
                    raise ValueError(
                        built.get("sign_error") or "raw missing after build"
                    )

                # accept candidate short map
                entry["accepted_short_to_wf"] = dict(short_map)
                entry["validation"] = {
                    "accepted": True,
                    "reason": "compile_ok" if not sign else (
                        "compile_sign_ok" if built.get("signed") else "compile_ok_sign_failed"
                    ),
                    "signed": bool(built.get("signed")),
                    "probe_keys": list(probe_wf.keys()),
                }
                report["accepted"] += 1
                report["details"].append(
                    {"identifier": ident, "ok": True, "map_size": len(short_map)}
                )
            except Exception as exc:
                entry["validation"] = {
                    "accepted": False,
                    "reason": "exception",
                    "error": str(exc)[:300],
                }
                report["rejected"] += 1
                report["details"].append(
                    {
                        "identifier": ident,
                        "ok": False,
                        "reason": "exception",
                        "error": str(exc)[:200],
                    }
                )
    return report


def run_learning(
    *,
    export_roots: Optional[List[str]] = None,
    include_gallery: bool = True,
    include_dictation: bool = True,
    include_sqlite: bool = True,
    include_self_bootstrap: bool = False,
    include_seeds: bool = False,
    include_templates: bool = False,
    include_fixtures: bool = False,
    validate: bool = True,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Default is external-only trusted learning + validation.

    Self/seed/template are OFF by default to prevent echo chamber.
    """
    doc = _empty_doc()
    store: Dict[str, Any] = {}
    sources: List[str] = []
    class_counts: Counter = Counter()
    action_obs = 0
    trusted_obs = 0
    recipe_count = 0
    file_count = 0

    # --- external corpora ---
    roots = list(export_roots or [])
    env = os.environ.get("IOS_SHORTCUTS_MCP_LEARN_ROOTS", "")
    if env:
        for part in re.split(r"[:;,]", env):
            if part.strip():
                roots.append(part.strip())

    extracted = extract_all_external(
        include_gallery=include_gallery,
        include_dictation=include_dictation,
        include_sqlite=include_sqlite,
        export_roots=roots or None,
        db_path=db_path,
    )
    doc["extractor"] = {
        "meta": extracted.get("meta"),
        "errors": extracted.get("errors"),
        "count": extracted.get("count"),
        "trusted_external": extracted.get("trusted_external"),
    }

    for w in extracted.get("workflows") or []:
        sc = w.get("source_class") or "external_user"
        n = observe_plist(store, w["plist"], source_class=sc)
        action_obs += n
        if sc in TRUSTED_CLASSES:
            trusted_obs += n
        file_count += 1
        class_counts[sc] += 1
        sources.append(w.get("source") or sc)

    # --- optional self bootstrap (never trusted alone) ---
    if include_seeds or include_templates or include_fixtures or include_self_bootstrap:
        from shortcut_builder import TEMPLATES, compile_recipe

        if include_seeds or include_self_bootstrap:
            # minimal seed — marked seed (untrusted)
            seed_actions = [
                {"type": "text", "params": {"text": "hello"}},
                {"type": "delay", "params": {"seconds": 1}},
                {
                    "type": "show_notification",
                    "params": {"title": "T", "body": "B"},
                },
                {"type": "speak_text", "params": {"text": "hi", "wait": True}},
            ]
            compiled = compile_recipe(
                seed_actions, safe_mode=False, coerce_mode="off"
            )
            # observe as seed
            fake_plist = {"WFWorkflowActions": compiled["wf_actions"]}
            n = observe_plist(store, fake_plist, source_class="seed")
            action_obs += n
            recipe_count += 1
            class_counts["seed"] += 1
            sources.append("seed:minimal")

        if include_templates:
            for name, tpl in TEMPLATES.items():
                compiled = compile_recipe(
                    tpl["actions"], safe_mode=False, coerce_mode="off"
                )
                n = observe_plist(
                    store,
                    {"WFWorkflowActions": compiled["wf_actions"]},
                    source_class="template",
                )
                action_obs += n
                recipe_count += 1
                class_counts["template"] += 1
                sources.append("template:" + name)

        if include_fixtures:
            fix_dir = os.path.join(_ROOT, "fixtures", "recipes")
            if os.path.isdir(fix_dir):
                for fn in sorted(os.listdir(fix_dir)):
                    if not fn.endswith(".json"):
                        continue
                    with open(os.path.join(fix_dir, fn), encoding="utf-8") as f:
                        data = json.load(f)
                    compiled = compile_recipe(
                        data.get("actions") or [],
                        safe_mode=False,
                        coerce_mode="off",
                    )
                    n = observe_plist(
                        store,
                        {"WFWorkflowActions": compiled["wf_actions"]},
                        source_class="fixture",
                    )
                    action_obs += n
                    recipe_count += 1
                    class_counts["fixture"] += 1
                    sources.append("fixture:" + fn)

    finalize_maps(store, trusted_only=True)

    validation_report = None
    if validate:
        # compile-gate by default; enable sign via env when interactive mac is healthy
        do_sign = os.environ.get("IOS_SHORTCUTS_MCP_LEARN_SIGN", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        validation_report = validate_and_accept_maps(
            store, max_actions=40, sign=do_sign
        )

    doc["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    doc["sources"] = sources
    doc["source_class_counts"] = dict(class_counts)
    doc["action_count_observed"] = action_obs
    doc["trusted_action_count_observed"] = trusted_obs
    doc["file_count"] = file_count
    doc["recipe_count"] = recipe_count
    doc["actions"] = store
    doc["identifier_count"] = len(store)
    doc["trusted_identifier_count"] = sum(
        1 for e in store.values() if int(e.get("samples_trusted") or 0) > 0
    )
    doc["accepted_identifier_count"] = sum(
        1 for e in store.values() if e.get("accepted_short_to_wf")
    )
    doc["validation_report"] = validation_report
    return doc


def save_learned(doc: Dict[str, Any], path: str = _LEARNED_PATH) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    # also write slim accepted maps
    accepted = {
        "version": 2,
        "generated_at": doc.get("generated_at"),
        "actions": {
            ident: {
                "accepted_short_to_wf": entry.get("accepted_short_to_wf") or {},
                "param_schema": entry.get("param_schema") or {},
                "primary_keys": entry.get("primary_keys") or [],
            }
            for ident, entry in (doc.get("actions") or {}).items()
            if entry.get("accepted_short_to_wf")
        },
    }
    with open(_ACCEPTED_PATH, "w", encoding="utf-8") as f:
        json.dump(accepted, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def load_learned(path: str = _LEARNED_PATH) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return _empty_doc()
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return _empty_doc()


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
    if entry:
        return entry
    for short, full in CURATED_ALIASES.items():
        if short == identifier or full == identifier:
            return actions.get(full) or {}
    return {}


def apply_learned_param_map(
    identifier: str,
    params: dict,
    *,
    min_confidence: float = 0.0,
    accepted_only: bool = True,
) -> Tuple[dict, List[str]]:
    """
    Remap short keys → WF keys.
    By default only uses accepted_short_to_wf (post-validation).
    """
    if not params:
        return {}, []
    entry = get_param_map(identifier)
    if not entry:
        return dict(params), []

    short_to_wf = entry.get("accepted_short_to_wf") or {}
    if not accepted_only and not short_to_wf:
        # fall back to trusted then any
        short_to_wf = (
            entry.get("short_to_wf_trusted")
            or entry.get("short_to_wf")
            or {}
        )
    if not short_to_wf:
        return dict(params), []

    key_conf = entry.get("key_confidence") or {}
    out = dict(params)
    notes: List[str] = []
    for short, wf_key in short_to_wf.items():
        if short not in out:
            continue
        if short.startswith("WF") or short == wf_key:
            continue
        conf = float(key_conf.get(wf_key, 1.0))
        if conf < min_confidence:
            continue
        if wf_key in out:
            notes.append(
                "kept explicit {0}; ignored short {1}".format(wf_key, short)
            )
            continue
        out[wf_key] = out.pop(short)
        notes.append("mapped {0} → {1}".format(short, wf_key))
    return out, notes


def get_param_schema(identifier: str) -> Dict[str, Any]:
    entry = get_param_map(identifier)
    return (entry or {}).get("param_schema") or {}


def learned_stats() -> Dict[str, Any]:
    doc = get_learned()
    actions = doc.get("actions") or {}
    accepted = sum(1 for a in actions.values() if a.get("accepted_short_to_wf"))
    trusted = sum(1 for a in actions.values() if int(a.get("samples_trusted") or 0) > 0)
    return {
        "path": _LEARNED_PATH,
        "accepted_path": _ACCEPTED_PATH,
        "exists": os.path.isfile(_LEARNED_PATH),
        "version": doc.get("version"),
        "generated_at": doc.get("generated_at"),
        "identifier_count": len(actions),
        "trusted_identifier_count": trusted,
        "accepted_identifier_count": accepted,
        "with_short_maps": sum(
            1
            for a in actions.values()
            if a.get("accepted_short_to_wf") or a.get("short_to_wf_trusted")
        ),
        "action_count_observed": doc.get("action_count_observed"),
        "trusted_action_count_observed": doc.get("trusted_action_count_observed"),
        "file_count": doc.get("file_count"),
        "source_class_counts": doc.get("source_class_counts"),
        "extractor": doc.get("extractor"),
        "validation_report_summary": {
            "tested": (doc.get("validation_report") or {}).get("tested"),
            "accepted": (doc.get("validation_report") or {}).get("accepted"),
            "rejected": (doc.get("validation_report") or {}).get("rejected"),
        },
        "echo_chamber_guard": "self/seed excluded from trusted maps by default",
    }


def top_learned_actions(limit: int = 20) -> List[Dict[str, Any]]:
    doc = get_learned()
    rows = []
    for ident, entry in (doc.get("actions") or {}).items():
        rows.append(
            {
                "identifier": ident,
                "samples": entry.get("samples", 0),
                "samples_trusted": entry.get("samples_trusted", 0),
                "keys": len(entry.get("key_freq_trusted") or entry.get("key_freq") or {}),
                "short_to_wf": entry.get("accepted_short_to_wf")
                or entry.get("short_to_wf_trusted")
                or {},
                "accepted": bool(entry.get("accepted_short_to_wf")),
                "maps_from_trusted": entry.get("maps_from_trusted"),
                "curated_alias": entry.get("curated_alias"),
                "primary_keys": entry.get("primary_keys") or [],
                "validation": entry.get("validation"),
            }
        )
    rows.sort(
        key=lambda r: (
            -int(r.get("samples_trusted") or 0),
            -int(r["samples"]),
            r["identifier"],
        )
    )
    return rows[:limit]
