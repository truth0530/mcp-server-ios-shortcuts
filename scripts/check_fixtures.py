#!/usr/bin/env python3
"""Compare compiled recipes against fixtures/golden/*.json."""

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
    if not os.path.isdir(RECIPES) or not os.path.isdir(GOLDEN):
        print("fixtures/recipes or fixtures/golden missing", file=sys.stderr)
        return 1

    failed = 0
    checked = 0
    for fn in sorted(os.listdir(RECIPES)):
        if not fn.endswith(".json"):
            continue
        recipe_path = os.path.join(RECIPES, fn)
        golden_path = os.path.join(GOLDEN, fn)
        if not os.path.isfile(golden_path):
            print("FAIL {0}: missing golden {1}".format(fn, golden_path))
            failed += 1
            continue
        with open(recipe_path, encoding="utf-8") as f:
            recipe = json.load(f)
        with open(golden_path, encoding="utf-8") as f:
            expected = json.load(f)
        name = recipe.get("name") or os.path.splitext(fn)[0]
        actual = build_golden_document(recipe["actions"], name=name)
        actual.pop("magic", None)
        # Compare stable fields
        for key in ("name", "version", "action_count", "aliases", "actions"):
            if actual.get(key) != expected.get(key):
                print("FAIL {0}: mismatch on '{1}'".format(fn, key))
                print("  expected: {0}".format(json.dumps(expected.get(key), ensure_ascii=False)[:400]))
                print("  actual:   {0}".format(json.dumps(actual.get(key), ensure_ascii=False)[:400]))
                failed += 1
                break
        else:
            print("OK   {0}".format(fn))
            checked += 1

    if failed:
        print("\n{0} fixture check(s) failed ({1} ok)".format(failed, checked))
        print("Re-generate with: python3 scripts/generate_fixtures.py")
        return 1
    print("\nAll {0} golden fixtures match.".format(checked))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
