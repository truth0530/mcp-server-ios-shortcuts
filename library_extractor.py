#!/usr/bin/env python3
"""
Extract *external* (non-self-built) shortcut plists for the learning loop.

Sources (priority order):
  1. Apple Gallery / system .wflow samples (always readable, authored by Apple)
  2. User-supplied export directories
  3. ~/Library/Shortcuts/Shortcuts.sqlite (requires Full Disk Access / TCC)

Echo-chamber guard: files whose action UUIDs match this server's deterministic
uuid5 namespace are tagged source_class=self and excluded from trusted learning.
"""

from __future__ import annotations

import os
import plistlib
import sqlite3
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

from magic_vars import UUID_NS, step_uuid

# Known / historical Shortcuts DB locations
DEFAULT_SQLITE_CANDIDATES = [
    os.path.expanduser("~/Library/Shortcuts/Shortcuts.sqlite"),
    os.path.expanduser(
        "~/Library/Group Containers/group.is.workflow.shortcuts/"
        "Library/Application Support/Shortcuts/Shortcuts.sqlite"
    ),
    os.path.expanduser(
        "~/Library/Containers/com.apple.shortcuts/Data/Library/"
        "Shortcuts/Shortcuts.sqlite"
    ),
]

GALLERY_DIR = (
    "/System/Library/PrivateFrameworks/WorkflowKit.framework/"
    "Versions/A/Resources/Gallery.bundle/Contents/Resources"
)

DICTATION_WORKFLOWS_ROOT = (
    "/System/Library/PrivateFrameworks/SpeechObjects.framework/"
    "Versions/A/Frameworks/DictationServices.framework/"
    "Versions/A/Resources/Workflows"
)


def is_self_built_plist(plist: dict) -> bool:
    """
    Detect plists produced by this MCP server (deterministic UUIDs).
    Returns True if ≥50% of action UUIDs match our uuid5 scheme for indices 0..N.
    """
    actions = plist.get("WFWorkflowActions") or []
    if not actions:
        return False
    matches = 0
    total = 0
    for i, a in enumerate(actions):
        params = a.get("WFWorkflowActionParameters") or {}
        uid = params.get("UUID")
        if not uid:
            continue
        total += 1
        expected = step_uuid(i)
        # also accept part uuids
        if str(uid).upper() == expected.upper():
            matches += 1
            continue
        # intermediate parts
        try:
            u = uuid.UUID(str(uid))
            if u.version == 5 and str(u).upper().startswith(
                str(uuid.uuid5(UUID_NS, "ios-shortcuts-mcp/")).upper()[:8]
            ):
                # same namespace prefix heuristic
                ns_check = uuid.uuid5(UUID_NS, "ios-shortcuts-mcp/action/0")
                if u.hex[12:16] == ns_check.hex[12:16]:  # weak
                    pass
        except Exception:
            pass
        for part in range(0, 4):
            from magic_vars import part_uuid

            if str(uid).upper() == part_uuid(i, part).upper():
                matches += 1
                break
    if total == 0:
        return False
    return (matches / float(total)) >= 0.5


def load_plist_bytes(data: bytes) -> Optional[dict]:
    if not data:
        return None
    # strip signed wrapper: try direct plist
    try:
        return plistlib.loads(data)
    except Exception:
        pass
    # search for embedded bplist
    idx = data.find(b"bplist00")
    if idx >= 0:
        try:
            return plistlib.loads(data[idx:])
        except Exception:
            pass
    # XML plist
    idx = data.find(b"<?xml")
    if idx >= 0:
        try:
            return plistlib.loads(data[idx:])
        except Exception:
            pass
    return None


def load_workflow_file(path: str) -> Optional[dict]:
    try:
        with open(path, "rb") as f:
            return load_plist_bytes(f.read())
    except OSError:
        return None


def extract_gallery_wflows() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(GALLERY_DIR):
        return out
    for fn in sorted(os.listdir(GALLERY_DIR)):
        if not fn.endswith(".wflow"):
            continue
        path = os.path.join(GALLERY_DIR, fn)
        pl = load_workflow_file(path)
        if not pl or not pl.get("WFWorkflowActions"):
            continue
        out.append(
            {
                "name": fn.replace(".wflow", ""),
                "path": path,
                "plist": pl,
                "source_class": "external_apple",
                "source": "gallery:" + fn,
                "self_built": False,
            }
        )
    return out


def extract_dictation_wflows() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(DICTATION_WORKFLOWS_ROOT):
        return out
    for root, _dirs, files in os.walk(DICTATION_WORKFLOWS_ROOT):
        for fn in files:
            if fn != "document.wflow" and not fn.endswith(".wflow"):
                continue
            path = os.path.join(root, fn)
            pl = load_workflow_file(path)
            if not pl or not pl.get("WFWorkflowActions"):
                continue
            name = os.path.basename(os.path.dirname(path))
            out.append(
                {
                    "name": name,
                    "path": path,
                    "plist": pl,
                    "source_class": "external_apple",
                    "source": "dictation:" + name,
                    "self_built": False,
                }
            )
    return out


def _looks_blob_column(col: str) -> bool:
    c = col.lower()
    return any(
        k in c
        for k in (
            "data",
            "blob",
            "workflow",
            "shortcut",
            "action",
            "record",
            "plist",
            "payload",
            "serialized",
        )
    )


def extract_from_sqlite(
    db_path: Optional[str] = None,
    *,
    max_rows: int = 500,
) -> Dict[str, Any]:
    """
    Best-effort Core Data / Shortcuts.sqlite extractor.

    Requires Full Disk Access for the terminal/agent process on modern macOS.
    Dynamically discovers BLOB columns that contain bplist workflow data.
    """
    result: Dict[str, Any] = {
        "ok": False,
        "db_path": None,
        "error": None,
        "tcc_blocked": False,
        "tables_scanned": [],
        "workflows": [],
        "hint": (
            "Grant Full Disk Access to your terminal (or this agent host) in "
            "System Settings → Privacy & Security → Full Disk Access, then retry."
        ),
    }

    candidates = []
    if db_path:
        candidates.append(os.path.expanduser(db_path))
    candidates.extend(DEFAULT_SQLITE_CANDIDATES)

    db_path_used = None
    for cand in candidates:
        if cand and os.path.isfile(cand):
            db_path_used = cand
            break
    if not db_path_used:
        # still try default path for clearer error
        db_path_used = DEFAULT_SQLITE_CANDIDATES[0]
    result["db_path"] = db_path_used

    try:
        # Open with URI readonly; may raise OperationalError under TCC
        uri = "file:{}?mode=ro".format(db_path_used)
        conn = sqlite3.connect(uri, uri=True, timeout=5)
    except Exception as exc:
        msg = str(exc).lower()
        result["error"] = str(exc)
        result["tcc_blocked"] = (
            "authorization" in msg
            or "not permitted" in msg
            or "unable to open" in msg
            or "operation not permitted" in msg
        )
        return result

    workflows: List[Dict[str, Any]] = []
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        result["tables_scanned"] = tables
        for table in tables:
            if table.startswith("sqlite_"):
                continue
            try:
                cols = [
                    r[1]
                    for r in conn.execute("PRAGMA table_info({})".format(table)).fetchall()
                ]
            except sqlite3.Error:
                continue
            blob_cols = [c for c in cols if _looks_blob_column(c)]
            if not blob_cols:
                # still probe all columns for bplist magic on a few rows
                blob_cols = list(cols)
            name_cols = [
                c
                for c in cols
                if c.lower() in {"zname", "name", "ztitle", "title", "zidentifier"}
            ]
            select_cols = list(dict.fromkeys(name_cols + blob_cols))
            if not select_cols:
                continue
            sql = "SELECT {} FROM {} LIMIT {}".format(
                ", ".join(select_cols), table, int(max_rows)
            )
            try:
                rows = conn.execute(sql).fetchall()
            except sqlite3.Error:
                continue
            for row in rows:
                row_map = dict(zip(select_cols, row))
                name = None
                for nc in name_cols:
                    if row_map.get(nc):
                        name = str(row_map[nc])
                        break
                for bc in blob_cols:
                    val = row_map.get(bc)
                    if not isinstance(val, (bytes, bytearray, memoryview)):
                        continue
                    data = bytes(val)
                    if b"bplist" not in data[:200] and b"WFWorkflowActions" not in data[:500]:
                        # still try load
                        if not data.startswith(b"bplist") and b"plist" not in data[:100]:
                            continue
                    pl = load_plist_bytes(data)
                    if not pl or not pl.get("WFWorkflowActions"):
                        continue
                    self_built = is_self_built_plist(pl)
                    workflows.append(
                        {
                            "name": name or pl.get("WFWorkflowName") or "unnamed",
                            "path": "{0}#{1}".format(db_path_used, table),
                            "plist": pl,
                            "source_class": "self" if self_built else "external_user",
                            "source": "sqlite:{0}:{1}".format(table, name or "?"),
                            "self_built": self_built,
                        }
                    )
        result["workflows"] = workflows
        result["ok"] = True
        result["count"] = len(workflows)
        result["external_count"] = sum(
            1 for w in workflows if w.get("source_class") != "self"
        )
    finally:
        conn.close()
    return result


def extract_file_exports(
    roots: Iterable[str],
    *,
    exclude_self_built: bool = True,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for root in roots:
        root = os.path.expanduser(root)
        if not root or not os.path.exists(root):
            continue
        paths: List[str] = []
        if os.path.isfile(root):
            paths = [root]
        else:
            for dirpath, _dn, filenames in os.walk(root):
                if any(s in dirpath for s in ("/.git", "/node_modules", "/Caches")):
                    continue
                for fn in filenames:
                    if fn.endswith((".shortcut", ".wflow", ".plist")):
                        paths.append(os.path.join(dirpath, fn))
        for path in paths:
            pl = load_workflow_file(path)
            if not pl or not pl.get("WFWorkflowActions"):
                continue
            self_built = is_self_built_plist(pl)
            if exclude_self_built and self_built:
                continue
            # dist/ without self uuid still treated carefully
            source_class = "self" if self_built else "external_user"
            if "/Gallery.bundle/" in path or path.endswith(".wflow"):
                if "WorkflowKit" in path or "DictationServices" in path:
                    source_class = "external_apple"
            out.append(
                {
                    "name": os.path.basename(path),
                    "path": path,
                    "plist": pl,
                    "source_class": source_class,
                    "source": "file:" + path,
                    "self_built": self_built,
                }
            )
    return out


def extract_all_external(
    *,
    include_gallery: bool = True,
    include_dictation: bool = True,
    include_sqlite: bool = True,
    export_roots: Optional[List[str]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Aggregate external corpora for trusted learning."""
    workflows: List[Dict[str, Any]] = []
    errors: List[str] = []
    meta: Dict[str, Any] = {
        "gallery": 0,
        "dictation": 0,
        "sqlite": 0,
        "exports": 0,
        "sqlite_status": None,
    }

    if include_gallery:
        g = extract_gallery_wflows()
        workflows.extend(g)
        meta["gallery"] = len(g)

    if include_dictation:
        d = extract_dictation_wflows()
        workflows.extend(d)
        meta["dictation"] = len(d)

    if include_sqlite:
        sq = extract_from_sqlite(db_path)
        meta["sqlite_status"] = {
            "ok": sq.get("ok"),
            "tcc_blocked": sq.get("tcc_blocked"),
            "error": sq.get("error"),
            "db_path": sq.get("db_path"),
            "count": sq.get("count"),
            "external_count": sq.get("external_count"),
            "hint": sq.get("hint"),
        }
        if sq.get("ok"):
            for w in sq.get("workflows") or []:
                if w.get("self_built"):
                    continue
                workflows.append(w)
            meta["sqlite"] = meta["sqlite_status"]["external_count"]
        else:
            errors.append(
                "sqlite: {0}".format(sq.get("error") or "unavailable")
            )

    if export_roots:
        ex = extract_file_exports(export_roots, exclude_self_built=True)
        workflows.extend(ex)
        meta["exports"] = len(ex)

    # Deduplicate by action fingerprint
    seen = set()
    unique: List[Dict[str, Any]] = []
    for w in workflows:
        acts = (w.get("plist") or {}).get("WFWorkflowActions") or []
        fp = tuple(
            (
                a.get("WFWorkflowActionIdentifier"),
                tuple(
                    sorted(
                        (k, type(v).__name__)
                        for k, v in (a.get("WFWorkflowActionParameters") or {}).items()
                        if k != "UUID"
                    )
                ),
            )
            for a in acts
        )
        if fp in seen:
            continue
        seen.add(fp)
        unique.append(w)

    return {
        "ok": True,
        "workflows": unique,
        "count": len(unique),
        "meta": meta,
        "errors": errors,
        "trusted_external": sum(
            1
            for w in unique
            if w.get("source_class") in {"external_apple", "external_user"}
        ),
    }
