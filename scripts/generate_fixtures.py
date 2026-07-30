#!/usr/bin/env python3
"""Generate golden fixture JSON from fixtures/recipes/*.json."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shortcut_builder import build_golden_document  # noqa: E402

RECIPES = os.path.join(ROOT, "fixtures", "recipes")
GOLDEN = os.path.join(ROOT, "fixtures", "golden")


def main() -> int:
    os.makedirs(GOLDEN, exist_ok=True)
    if not os.path.isdir(RECIPES):
        print("No fixtures/recipes directory", file=sys.stderr)
        return 1

    count = 0
    for fn in sorted(os.listdir(RECIPES)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(RECIPES, fn)
        with open(path, encoding="utf-8") as f:
            recipe = json.load(f)
        name = recipe.get("name") or os.path.splitext(fn)[0]
        actions = recipe.get("actions")
        if not isinstance(actions, list):
            print("skip {0}: no actions".format(fn), file=sys.stderr)
            continue
        doc = build_golden_document(actions, name=name)
        # Drop bulky magic help from on-disk goldens (keep in API)
        doc.pop("magic", None)
        out = os.path.join(GOLDEN, fn)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print("wrote {0} ({1} actions)".format(out, doc["action_count"]))
        count += 1
    print("generated {0} golden fixture(s)".format(count))
    return 0 if count else 1


if __name__ == "__main__":
    raise SystemExit(main())
