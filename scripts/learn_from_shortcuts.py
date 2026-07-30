#!/usr/bin/env python3
"""
Mine WF parameter shapes from seeds, templates, fixtures, and on-disk .shortcut files.

Writes data/learned_param_maps.json used by the generic compiler for short→WF
key remapping.

Usage:
  python3 scripts/learn_from_shortcuts.py
  python3 scripts/learn_from_shortcuts.py --roots ./dist:/path/to/exports
  python3 scripts/learn_from_shortcuts.py --json  # print summary JSON
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from param_learning import (  # noqa: E402
    default_learn_roots,
    learned_stats,
    run_learning,
    save_learned,
    top_learned_actions,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--roots",
        default="",
        help="Extra roots (pathsep :/,/;) for .shortcut discovery",
    )
    parser.add_argument("--no-seeds", action="store_true")
    parser.add_argument("--no-templates", action="store_true")
    parser.add_argument("--no-fixtures", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    roots = list(default_learn_roots())
    if args.roots:
        import re

        for part in re.split(r"[:;,]", args.roots):
            part = part.strip()
            if part:
                roots.append(part)

    doc = run_learning(
        roots=roots,
        include_seeds=not args.no_seeds,
        include_templates=not args.no_templates,
        include_fixtures=not args.no_fixtures,
    )
    path = save_learned(doc)
    # reload cache
    from param_learning import get_learned

    get_learned(force_reload=True)

    summary = {
        "wrote": path,
        "stats": learned_stats(),
        "top": top_learned_actions(15),
    }
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print("wrote", path)
        print(
            "identifiers={0} observed_actions={1} files={2} recipes={3}".format(
                summary["stats"]["identifier_count"],
                summary["stats"]["action_count_observed"],
                summary["stats"]["file_count"],
                summary["stats"]["recipe_count"],
            )
        )
        print("top actions:")
        for row in summary["top"][:10]:
            print(
                "  {0}: samples={1} keys={2} map={3}".format(
                    row["identifier"],
                    row["samples"],
                    row["keys"],
                    list((row.get("short_to_wf") or {}).items())[:4],
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
