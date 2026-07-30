#!/usr/bin/env python3
"""
Build structured data/apple_action_catalog.json from:
  - data/apple_action_ids.txt (harvested identifiers)
  - curated aliases / categories / platform heuristics
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from action_catalog import (  # noqa: E402
    CURATED_ALIASES,
    categorize_identifier,
    identifier_to_auto_short,
)

IDS = os.path.join(ROOT, "data", "apple_action_ids.txt")
OUT = os.path.join(ROOT, "data", "apple_action_catalog.json")

# Heuristic platform tags (not Apple-official; best-effort preflight)
IOS_LEANING = (
    "takephoto",
    "selectphoto",
    "camera",
    "health",
    "workout",
    "mindfulness",
    "cellular",
    "cellulardata",
    "flashlight",
    "lowpowermode",
    "personalhotspot",
    "mobiledata",
    "ssid",
)
MACOS_LEANING = (
    "runshellscript",
    "applescript",
    "runjsshortcut",
    "runjavascript",
    "finder",
    "macos",
)


def platforms_for(ident: str) -> list:
    s = ident.lower()
    ios = True
    mac = True
    watch = True
    if any(k in s for k in IOS_LEANING):
        mac = False
    if any(k in s for k in MACOS_LEANING):
        ios = False
        watch = False
    out = []
    if ios:
        out.append("ios")
    if mac:
        out.append("macos")
    if watch and "shell" not in s and "applescript" not in s:
        out.append("watchos")
    return out or ["ios", "macos"]


def main() -> int:
    ids = []
    if os.path.isfile(IDS):
        with open(IDS, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    ids.append(line)
    for ident in CURATED_ALIASES.values():
        if ident not in ids:
            ids.append(ident)

    reverse_curated = {}
    for short, ident in CURATED_ALIASES.items():
        reverse_curated.setdefault(ident, []).append(short)

    actions = {}
    for ident in sorted(set(ids)):
        auto = identifier_to_auto_short(ident)
        shorts = list(reverse_curated.get(ident) or [])
        if auto not in shorts:
            shorts.append(auto)
        # dedupe preserve order
        seen = set()
        short_names = []
        for s in shorts:
            if s not in seen:
                seen.add(s)
                short_names.append(s)
        actions[ident] = {
            "short_names": short_names,
            "primary_short": short_names[0],
            "category": categorize_identifier(ident),
            "platforms": platforms_for(ident),
            "min_os": None,
            "curated": ident in reverse_curated,
            "serialization": "curated" if ident in reverse_curated else "generic",
            "verified_runtime": False,
        }

    # Mark a few known-good curated as verified when we E2E them
    for ident in (
        "is.workflow.actions.nothing",
        "is.workflow.actions.comment",
        "is.workflow.actions.notification",
        "is.workflow.actions.gettext",
        "is.workflow.actions.delay",
    ):
        if ident in actions:
            actions[ident]["verified_runtime"] = True

    doc = {
        "version": 1,
        "generator": "scripts/build_action_catalog_db.py",
        "identifier_count": len(actions),
        "curated_count": sum(1 for a in actions.values() if a["curated"]),
        "actions": actions,
        "notes": [
            "platforms/min_os are heuristic preflight hints, not Apple-official matrices",
            "serialization=generic requires WF keys and/or auto-coercion",
            "Refresh ids via harvest_action_ids.py then re-run this script",
        ],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(
        "wrote {0} ({1} actions, {2} curated)".format(
            OUT, doc["identifier_count"], doc["curated_count"]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
