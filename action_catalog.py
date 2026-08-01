#!/usr/bin/env python3
"""
Comprehensive Apple Shortcuts action catalog.

Sources:
  1. data/apple_action_ids.txt — harvested is.workflow.actions.* identifiers
     (from macOS system frameworks / dyld shared cache)
  2. CURATED_ALIASES — ergonomic short names with preferred compilers
  3. Runtime: any is.workflow.actions.* / com.apple.* action identifier is
     accepted even if not yet harvested (forward-compatible).

Policy:
  - Every known Apple identifier is listable and buildable via generic path.
  - Curated short names keep high-quality parameter shaping.
  - Unknown short names fail validation; unknown full identifiers warn + allow.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_IDS_PATH = os.path.join(_DATA_DIR, "apple_action_ids.txt")
_CATALOG_DB_PATH = os.path.join(_DATA_DIR, "apple_action_catalog.json")
_META_PATH = os.path.join(_DATA_DIR, "apple_action_meta.json")

# Explicit short-name → full identifier (high-quality curated surface).
# Kept in sync with special-case compilers in shortcut_builder when possible.
CURATED_ALIASES: Dict[str, str] = {
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
    # Media
    "take_screenshot": "is.workflow.actions.takescreenshot",
    "take_photo": "is.workflow.actions.takephoto",
    "select_photos": "is.workflow.actions.selectphoto",
    # legacy cropimage is broken on modern macOS — keep image.crop as crop_image
    "crop_image": "is.workflow.actions.image.crop",
    "image_crop": "is.workflow.actions.image.crop",
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
    # Scripting
    "run_shell_script": "is.workflow.actions.runshellscript",
    "run_applescript": "is.workflow.actions.applescript",
    "run_javascript_for_automation": "is.workflow.actions.runjsshortcut",
}

# Synthetic multi-part helpers (not real WF identifiers alone).
SYNTHETIC_TYPES = frozenset(
    {
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
    }
)

# Category heuristics from identifier suffix.
_CATEGORY_RULES: List[Tuple[str, str]] = [
    (r"^(text|detect\.text|changecase|split|combine|replace|match)", "text"),
    (r"^(file|documentpicker|folder)", "files"),
    (r"^(image|photo|camera|gif|video|media|encodemedia|makepdf)", "media"),
    (r"^(music|playlist|playmusic|pausemusic|spotify|applemusic)", "music"),
    (r"^(url|downloadurl|getheaders|expand|rss|webpage)", "web"),
    (r"^(wifi|bluetooth|cellulardata|airplanemode|lowpower|dnd|focus|brightness|volume|flashlight|battery|device|lockscreen|appearance)", "device"),
    (r"^(location|maps|address|travel|weather)", "location"),
    (r"^(calendar|event|reminder|alarm|date|adjustdate|formatdate)", "calendar"),
    (r"^(contact|phone|message|email|mail|airdrop|share)", "communication"),
    (r"^(note|appendnote|evernote)", "notes"),
    (r"^(script|shell|applescript|javascript|runjs)", "scripting"),
    (r"^(variable|dictionary|list|count|calculate|number|math|hash|base64)", "data"),
    (r"^(conditional|repeat|choosefrommenu|exit|output|nothing|comment|wait)", "control"),
    (r"^(notification|alert|showresult|ask|speak|dictate|vibrate|playsound)", "interaction"),
    (r"^(openapp|runworkflow|getmyworkflows|openurl|searchweb)", "apps"),
    (r"^(filter|properties|get)", "items"),
    (r"^(health|workout|mindfulness)", "health"),
    (r"^(home|homekit)", "home"),
    (r"^(dropbox|trello|wordpress|tumblr)", "services"),
]


def _identifier_suffix(ident: str) -> str:
    if ident.startswith("is.workflow.actions."):
        return ident[len("is.workflow.actions.") :]
    return ident


def identifier_to_auto_short(ident: str) -> str:
    """
    is.workflow.actions.speaktext → speaktext
    is.workflow.actions.text.split → text_split
    is.workflow.actions.dnd.set → dnd_set
    """
    suffix = _identifier_suffix(ident)
    short = suffix.replace(".", "_")
    short = re.sub(r"[^a-zA-Z0-9_]+", "_", short)
    short = re.sub(r"_+", "_", short).strip("_").lower()
    return short or "action"


def categorize_identifier(ident: str) -> str:
    suffix = _identifier_suffix(ident).lower()
    for pattern, cat in _CATEGORY_RULES:
        if re.search(pattern, suffix):
            return cat
    return "other"


@lru_cache(maxsize=1)
def load_harvested_ids() -> Tuple[str, ...]:
    ids: List[str] = []
    if os.path.isfile(_IDS_PATH):
        with open(_IDS_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    ids.append(line)
    # Always include curated identifiers
    for ident in CURATED_ALIASES.values():
        if ident not in ids:
            ids.append(ident)
    return tuple(sorted(set(ids)))


@lru_cache(maxsize=1)
def load_optional_meta() -> Dict[str, Any]:
    if os.path.isfile(_META_PATH):
        try:
            with open(_META_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


@lru_cache(maxsize=1)
def load_catalog_db() -> Dict[str, Any]:
    """Structured catalog DB (platforms, serialization, short_names)."""
    if os.path.isfile(_CATALOG_DB_PATH):
        try:
            with open(_CATALOG_DB_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def is_full_identifier(name: str) -> bool:
    if not isinstance(name, str):
        return False
    if name.startswith("is.workflow.actions."):
        return True
    # App intents / third-party style
    if name.startswith("com.") and ".action" in name.lower():
        return True
    if re.match(r"^[a-z0-9-]+\.[a-z0-9.-]+\.[a-z0-9.-]+$", name, re.I):
        # reverse-DNS with ≥3 segments — treat as possible full identifier
        if name.count(".") >= 2 and not name.startswith("is.workflow.actions."):
            # Only allow if looks action-like
            return "action" in name.lower() or name.startswith("com.apple.")
    return False


def _disambiguated_short(ident: str, base: str, taken: Dict[str, str]) -> str:
    """
    Avoid short-name collisions: if base is taken by another identifier,
    fall back to full underscored suffix, then numeric suffix.
    """
    if base not in taken or taken[base] == ident:
        return base
    alt = identifier_to_auto_short(ident)
    # denser form keeping dots as underscores already
    if alt not in taken or taken[alt] == ident:
        return alt
    # include more of the reverse-dns tail
    dense = ident.replace("is.workflow.actions.", "").replace(".", "_")
    if dense not in taken or taken[dense] == ident:
        return dense
    n = 2
    while True:
        candidate = "{0}_{1}".format(dense, n)
        if candidate not in taken or taken[candidate] == ident:
            return candidate
        n += 1


@lru_cache(maxsize=1)
def build_catalog_index() -> Dict[str, Any]:
    """
    Returns:
      {
        "by_id": { identifier: entry },
        "by_short": { short: identifier },
        "shorts_for_id": { identifier: [short, ...] },
        "collisions_resolved": [...],
      }
    """
    harvested = list(load_harvested_ids())
    meta = load_optional_meta()
    db = load_catalog_db()
    db_actions = db.get("actions") or {}
    by_id: Dict[str, Dict[str, Any]] = {}
    by_short: Dict[str, str] = {}
    shorts_for_id: Dict[str, List[str]] = {}
    collisions_resolved: List[Dict[str, str]] = []

    def register_short(short: str, ident: str, *, curated: bool = False) -> str:
        if not short:
            return short
        existing = by_short.get(short)
        if existing and existing != ident:
            if curated:
                # curated wins: reassign previous owner to disambiguated name
                old = existing
                new_short = _disambiguated_short(old, short + "_alt", by_short)
                by_short[new_short] = old
                lst = shorts_for_id.setdefault(old, [])
                if short in lst:
                    lst[lst.index(short)] = new_short
                else:
                    lst.append(new_short)
                collisions_resolved.append(
                    {
                        "short": short,
                        "winner": ident,
                        "displaced": old,
                        "displaced_short": new_short,
                    }
                )
            else:
                short = _disambiguated_short(ident, short, by_short)
                if short in by_short and by_short[short] != ident:
                    return short
                collisions_resolved.append(
                    {
                        "short": short,
                        "identifier": ident,
                        "note": "auto-disambiguated",
                    }
                )
        by_short[short] = ident
        shorts_for_id.setdefault(ident, [])
        if short not in shorts_for_id[ident]:
            shorts_for_id[ident].append(short)
        return short

    # 1) harvested IDs — prefer structured DB entries when present
    for ident in harvested:
        db_entry = db_actions.get(ident) or {}
        entry_meta = (meta.get("actions") or {}).get(ident) or {}
        by_id[ident] = {
            "identifier": ident,
            "short_names": [],
            "category": db_entry.get("category")
            or entry_meta.get("category")
            or categorize_identifier(ident),
            "summary": entry_meta.get("summary") or "",
            "params": entry_meta.get("params") or {},
            "example": entry_meta.get("example"),
            "curated": bool(db_entry.get("curated")),
            "harvested": True,
            "risk": entry_meta.get("risk") or "normal",
            "verified": bool(
                db_entry.get("verified_runtime") or entry_meta.get("verified", False)
            ),
            "platforms": db_entry.get("platforms")
            or ["ios", "macos", "watchos"],
            "min_os": db_entry.get("min_os"),
            "serialization": db_entry.get("serialization") or "generic",
        }
        for sn in db_entry.get("short_names") or [identifier_to_auto_short(ident)]:
            register_short(sn, ident, curated=False)

    # 2) curated aliases override / enrich
    for short, ident in CURATED_ALIASES.items():
        if ident not in by_id:
            db_entry = db_actions.get(ident) or {}
            by_id[ident] = {
                "identifier": ident,
                "short_names": [],
                "category": db_entry.get("category") or categorize_identifier(ident),
                "summary": "",
                "params": {},
                "example": None,
                "curated": True,
                "harvested": False,
                "risk": "normal",
                "verified": True,
                "platforms": db_entry.get("platforms") or ["ios", "macos", "watchos"],
                "min_os": db_entry.get("min_os"),
                "serialization": "curated",
            }
        else:
            by_id[ident]["curated"] = True
            by_id[ident]["verified"] = True
            by_id[ident]["serialization"] = "curated"
        register_short(short, ident, curated=True)

    # Fill short_names lists (curated first)
    for ident, shorts in shorts_for_id.items():
        if ident in by_id:
            curated_first = [s for s in shorts if s in CURATED_ALIASES]
            rest = [s for s in shorts if s not in CURATED_ALIASES]
            by_id[ident]["short_names"] = curated_first + rest

    return {
        "by_id": by_id,
        "by_short": by_short,
        "shorts_for_id": shorts_for_id,
        "collisions_resolved": collisions_resolved,
    }


def preflight_platform(
    actions_config: list,
    *,
    target_platform: str = "macos",
) -> Dict[str, Any]:
    """
    Warn/error when recipe uses actions tagged incompatible with target platform.
    target_platform: ios | macos | watchos
    """
    target = (target_platform or "macos").strip().lower()
    if target in {"mac", "osx"}:
        target = "macos"
    if target in {"iphone", "ipad"}:
        target = "ios"
    index = build_catalog_index()
    errors: List[str] = []
    warnings: List[str] = []
    for i, item in enumerate(actions_config or []):
        if not isinstance(item, dict):
            continue
        atype = item.get("type") or item.get("action")
        if not atype:
            continue
        try:
            ident, meta = resolve_action_type(str(atype))
        except KeyError:
            continue
        if meta.get("synthetic"):
            continue
        platforms = meta.get("platforms") or (
            (index["by_id"].get(ident) or {}).get("platforms")
        )
        if not platforms:
            continue
        platforms_l = [str(p).lower() for p in platforms]
        if target not in platforms_l:
            msg = (
                "actions[{0}] ({1} → {2}): not tagged for platform '{3}' "
                "(supports: {4})"
            ).format(i, atype, ident, target, ", ".join(platforms_l))
            # macOS scripting on iOS is an error; mild mismatches warn
            if target == "ios" and any(
                x in ident for x in ("shell", "applescript", "runjsshortcut")
            ):
                errors.append(msg)
            else:
                warnings.append(msg)
    return {
        "ok": len(errors) == 0,
        "target_platform": target,
        "errors": errors,
        "warnings": warnings,
    }


def resolve_action_type(type_name: str) -> Tuple[str, Dict[str, Any]]:
    """
    Resolve short name or full identifier → (identifier, meta).

    Raises KeyError if short name unknown and not a full identifier.
    """
    if type_name in SYNTHETIC_TYPES:
        return type_name, {
            "identifier": type_name,
            "synthetic": True,
            "category": "control",
            "curated": True,
        }

    index = build_catalog_index()
    if type_name in index["by_short"]:
        ident = index["by_short"][type_name]
        return ident, index["by_id"].get(ident, {"identifier": ident})

    if type_name in index["by_id"]:
        return type_name, index["by_id"][type_name]

    if is_full_identifier(type_name) or type_name.startswith("is.workflow.actions."):
        # Forward-compatible: accept unlisted full identifiers
        return type_name, {
            "identifier": type_name,
            "short_names": [identifier_to_auto_short(type_name)],
            "category": categorize_identifier(type_name),
            "summary": "",
            "params": {},
            "curated": False,
            "harvested": False,
            "unlisted": True,
            "risk": "normal",
            "verified": False,
        }

    # Suggest close matches
    suggestions = suggest_actions(type_name, limit=5)
    hint = ""
    if suggestions:
        hint = " Did you mean: " + ", ".join(
            s.get("type") or s.get("identifier") for s in suggestions
        )
    raise KeyError("Unknown action type '{0}'.{1}".format(type_name, hint))


def suggest_actions(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    q = (query or "").strip().lower()
    if not q:
        return []
    index = build_catalog_index()
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for ident, entry in index["by_id"].items():
        hay = " ".join(
            [
                ident,
                " ".join(entry.get("short_names") or []),
                entry.get("summary") or "",
                entry.get("category") or "",
            ]
        ).lower()
        score = 0
        if q == ident.lower():
            score = 100
        elif any(q == s.lower() for s in entry.get("short_names") or []):
            score = 95
        elif q in hay:
            score = 50 + (10 if hay.startswith(q) else 0)
        elif all(part in hay for part in q.replace(".", " ").replace("_", " ").split()):
            score = 30
        if score:
            primary = (entry.get("short_names") or [identifier_to_auto_short(ident)])[0]
            scored.append(
                (
                    score,
                    {
                        "type": primary,
                        "identifier": ident,
                        "category": entry.get("category"),
                        "curated": entry.get("curated"),
                        "score": score,
                    },
                )
            )
    scored.sort(key=lambda x: (-x[0], x[1]["identifier"]))
    return [item for _, item in scored[:limit]]


def list_catalog_actions(
    *,
    query: Optional[str] = None,
    category: Optional[str] = None,
    curated_only: bool = False,
    limit: int = 500,
    include_unlisted_note: bool = True,
) -> Dict[str, Any]:
    index = build_catalog_index()
    items: List[Dict[str, Any]] = []

    # Synthetic first
    for name in sorted(SYNTHETIC_TYPES):
        items.append(
            {
                "type": name,
                "identifier": name,
                "summary": "Synthetic control-flow helper (compiles to WF conditional/repeat/menu)",
                "params": {"group_id": "required for multi-part blocks"},
                "category": "control",
                "curated": True,
                "risk": "normal",
                "verified": True,
                "short_names": [name],
            }
        )

    for ident in sorted(index["by_id"].keys()):
        entry = index["by_id"][ident]
        if curated_only and not entry.get("curated"):
            continue
        if category and entry.get("category") != category:
            continue
        shorts = entry.get("short_names") or [identifier_to_auto_short(ident)]
        primary = shorts[0]
        row = {
            "type": primary,
            "identifier": ident,
            "summary": entry.get("summary")
            or "Apple Shortcuts action ({0})".format(ident),
            "params": entry.get("params") or {},
            "example": entry.get("example"),
            "category": entry.get("category"),
            "curated": bool(entry.get("curated")),
            "verified": bool(entry.get("verified")),
            "harvested": bool(entry.get("harvested")),
            "risk": entry.get("risk") or "normal",
            "short_names": shorts,
        }
        if query:
            q = query.lower()
            blob = " ".join(
                [
                    row["type"],
                    row["identifier"],
                    row["summary"],
                    row["category"] or "",
                    " ".join(shorts),
                ]
            ).lower()
            if q not in blob:
                continue
        items.append(row)

    total = len(items)
    items = items[: max(1, min(int(limit), 2000))]
    return {
        "count": len(items),
        "total_available": total,
        "catalog_identifiers": len(index["by_id"]),
        "curated_aliases": len(CURATED_ALIASES),
        "categories": sorted(
            {e.get("category") or "other" for e in index["by_id"].values()}
            | {"control"}
        ),
        "note": (
            "Any is.workflow.actions.* identifier is buildable even if not listed; "
            "pass type as full identifier with params/wf_params."
            if include_unlisted_note
            else None
        ),
        "actions": items,
    }


def catalog_stats() -> Dict[str, Any]:
    index = build_catalog_index()
    curated = sum(1 for e in index["by_id"].values() if e.get("curated"))
    generic = sum(
        1
        for e in index["by_id"].values()
        if (e.get("serialization") or "generic") == "generic"
    )
    by_cat: Dict[str, int] = {}
    for e in index["by_id"].values():
        c = e.get("category") or "other"
        by_cat[c] = by_cat.get(c, 0) + 1
    db = load_catalog_db()
    return {
        "identifiers": len(index["by_id"]),
        "short_names": len(index["by_short"]),
        "curated_aliases": len(CURATED_ALIASES),
        "curated_identifiers": curated,
        "generic_serialization": generic,
        "synthetic_types": len(SYNTHETIC_TYPES),
        "collisions_resolved": len(index.get("collisions_resolved") or []),
        "categories": dict(sorted(by_cat.items(), key=lambda kv: (-kv[1], kv[0]))),
        "coverage_policy": (
            "Identifiers: harvested + unlisted is.workflow.actions.* accepted. "
            "Executable quality: curated serialization path is reliable; "
            "generic path uses auto-coercion (not full Apple schema parity). "
            "App Intents: use type=app_intent or full reverse-DNS identifier."
        ),
        "data_file": _IDS_PATH,
        "catalog_db": _CATALOG_DB_PATH if os.path.isfile(_CATALOG_DB_PATH) else None,
        "catalog_db_version": db.get("version"),
    }


def all_known_short_names() -> Set[str]:
    index = build_catalog_index()
    return set(index["by_short"].keys()) | set(SYNTHETIC_TYPES)


def all_known_identifiers() -> Set[str]:
    return set(build_catalog_index()["by_id"].keys())
