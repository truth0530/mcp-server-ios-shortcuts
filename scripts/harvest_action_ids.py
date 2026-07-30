#!/usr/bin/env python3
"""
Harvest is.workflow.actions.* identifiers from the local macOS system.

Scans dyld shared cache slices with `strings` (no private API). Merges with
any existing data/apple_action_ids.txt and curated identifiers.

Usage:
  python3 scripts/harvest_action_ids.py
  python3 scripts/harvest_action_ids.py --timeout 90
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "apple_action_ids.txt")
PATTERN = re.compile(r"is\.workflow\.actions\.[A-Za-z0-9._-]+")

CACHE_DIRS = [
    "/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld",
    "/System/Library/dyld",
]


def find_cache_files() -> list:
    files = []
    for d in CACHE_DIRS:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.startswith("dyld_shared_cache_"):
                continue
            if "dylddata" in name or name.endswith(".map") or "aot" in name:
                continue
            if "readonly" in name or "linkedit" in name or "atlas" in name:
                continue
            path = os.path.join(d, name)
            if os.path.isfile(path):
                files.append(path)
    return files


def strings_scan(path: str, timeout: int) -> set:
    found = set()
    try:
        proc = subprocess.run(
            ["strings", "-a", path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        print("skip {0}: {1}".format(os.path.basename(path), exc), file=sys.stderr)
        return found
    for m in PATTERN.finditer(proc.stdout or ""):
        found.add(m.group(0))
    return found


def load_existing() -> set:
    ids = set()
    if os.path.isfile(OUT):
        with open(OUT, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    ids.add(line)
    return ids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=90, help="per-file strings timeout")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print counts only, do not write",
    )
    args = parser.parse_args()

    existing = load_existing()
    print("existing: {0}".format(len(existing)))

    files = find_cache_files()
    print("cache files: {0}".format(len(files)))
    harvested = set(existing)
    for path in files:
        print("scanning {0} …".format(os.path.basename(path)), flush=True)
        part = strings_scan(path, timeout=args.timeout)
        print("  +{0} (file total unique so far {1})".format(len(part), len(harvested | part)))
        harvested |= part

    # Merge curated
    sys.path.insert(0, ROOT)
    try:
        from action_catalog import CURATED_ALIASES

        for ident in CURATED_ALIASES.values():
            harvested.add(ident)
    except Exception as exc:
        print("curated merge skipped: {0}".format(exc), file=sys.stderr)

    ordered = sorted(harvested)
    print("total identifiers: {0}".format(len(ordered)))
    if args.dry_run:
        return 0

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(
            "# Harvested Apple Shortcuts action identifiers\n"
            "# Regenerate: python3 scripts/harvest_action_ids.py\n"
        )
        for ident in ordered:
            f.write(ident + "\n")
    print("wrote {0}".format(OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
