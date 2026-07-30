#!/usr/bin/env python3
"""
Trusted learning loop (v2.7+).

Default: external-only corpus (Apple Gallery .wflow, system workflows,
optional Shortcuts.sqlite with Full Disk Access, user export roots).
Self-built dist/ seeds are OFF unless explicitly enabled.

After mining, reverse compile+sign validation accepts only working maps.

Usage:
  python3 scripts/learn_from_shortcuts.py
  python3 scripts/learn_from_shortcuts.py --roots ~/Desktop/exports
  python3 scripts/learn_from_shortcuts.py --allow-self-bootstrap  # debug only
  python3 scripts/learn_from_shortcuts.py --no-validate
  python3 scripts/learn_from_shortcuts.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from param_learning import (  # noqa: E402
    get_learned,
    learned_stats,
    run_learning,
    save_learned,
    top_learned_actions,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roots", default="", help="User export roots (:/;/,)")
    parser.add_argument("--db", default="", help="Path to Shortcuts.sqlite")
    parser.add_argument("--no-gallery", action="store_true")
    parser.add_argument("--no-dictation", action="store_true")
    parser.add_argument("--no-sqlite", action="store_true")
    parser.add_argument(
        "--allow-self-bootstrap",
        action="store_true",
        help="Also mine seed/template/fixture (UNTRUSTED; echo-chamber risk)",
    )
    parser.add_argument("--no-validate", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    roots = []
    if args.roots:
        for part in re.split(r"[:;,]", args.roots):
            if part.strip():
                roots.append(part.strip())

    doc = run_learning(
        export_roots=roots or None,
        include_gallery=not args.no_gallery,
        include_dictation=not args.no_dictation,
        include_sqlite=not args.no_sqlite,
        include_self_bootstrap=args.allow_self_bootstrap,
        include_seeds=args.allow_self_bootstrap,
        include_templates=args.allow_self_bootstrap,
        include_fixtures=args.allow_self_bootstrap,
        validate=not args.no_validate,
        db_path=args.db or None,
    )
    path = save_learned(doc)
    get_learned(force_reload=True)

    summary = {
        "wrote": path,
        "stats": learned_stats(),
        "top": top_learned_actions(15),
        "extractor": doc.get("extractor"),
        "validation": doc.get("validation_report"),
    }
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    else:
        print("wrote", path)
        st = summary["stats"]
        print(
            "trusted_ids={0} accepted_ids={1} trusted_obs={2} files={3}".format(
                st.get("trusted_identifier_count"),
                st.get("accepted_identifier_count"),
                st.get("trusted_action_count_observed"),
                st.get("file_count"),
            )
        )
        ex = summary.get("extractor") or {}
        meta = (ex.get("meta") or {}) if isinstance(ex, dict) else {}
        print(
            "sources gallery={0} dictation={1} sqlite={2} exports={3}".format(
                meta.get("gallery"),
                meta.get("dictation"),
                meta.get("sqlite"),
                meta.get("exports"),
            )
        )
        sq = meta.get("sqlite_status") or {}
        if sq.get("tcc_blocked"):
            print("WARNING: Shortcuts.sqlite blocked by TCC/Full Disk Access")
            print("  ", sq.get("hint"))
        vr = summary.get("validation") or {}
        print(
            "validation tested={0} accepted={1} rejected={2}".format(
                vr.get("tested"), vr.get("accepted"), vr.get("rejected")
            )
        )
        print("top trusted/accepted:")
        for row in summary["top"][:10]:
            print(
                "  {0}: trusted={1} accepted={2} map={3}".format(
                    row["identifier"],
                    row.get("samples_trusted"),
                    row.get("accepted"),
                    list((row.get("short_to_wf") or {}).items())[:3],
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
