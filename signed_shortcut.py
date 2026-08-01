#!/usr/bin/env python3
"""
Signed .shortcut (AEA1) extract + library export + structural clone.

Hard-won lessons (2026-08 existing-shortcut work):
  1. macOS Shortcuts export produces AEA1-signed packages. Plain strings /
     bplist search finds only SigningCertificateChain — **not** WF actions.
  2. Decrypt with system ``aea decrypt`` + EC public key from the embedded
     SigningCertificateChain DER cert (profile hkdf_sha256_hmac__none__ecdsa_p256).
  3. Decrypted payload may be AA01… then an inner ``bplist00`` with WFWorkflowActions.
  4. Library export via File→Export is flaky with keystroke typing of Korean
     paths; use **clipboard paste** of pure ASCII path + English filename.
  5. Never ``rm`` the export folder after a successful .shortcut lands.

Agents **must** use this module to diagnose existing user shortcuts. Guessing
action IDs without extract wastes hours.
"""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import struct
import subprocess
import tempfile
import uuid
from copy import deepcopy
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple


class SignedShortcutError(RuntimeError):
    """Extract / export / clone failed with a recoverable reason."""


# ---------------------------------------------------------------------------
# AEA1 signed package → workflow plist
# ---------------------------------------------------------------------------


def _run(cmd: List[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def extract_signing_cert_der(data: bytes) -> bytes:
    """
    Parse AEA1 header + outer bplist SigningCertificateChain → first DER cert.
    Layout: b'AEA1' + 4 bytes + little-endian u32 size + bplist00…
    """
    if not data.startswith(b"AEA1"):
        raise SignedShortcutError("Not an AEA1 package (missing AEA1 magic)")
    if len(data) < 16:
        raise SignedShortcutError("AEA1 package too short")
    size = struct.unpack_from("<I", data, 8)[0]
    bpl = data[12 : 12 + size]
    if not bpl.startswith(b"bplist"):
        raise SignedShortcutError("AEA1 outer blob is not a bplist")
    try:
        outer = plistlib.loads(bpl)
    except Exception as exc:
        raise SignedShortcutError("Failed to parse signing plist: {0}".format(exc))
    chain = outer.get("SigningCertificateChain")
    if not chain:
        raise SignedShortcutError("No SigningCertificateChain in package")
    cert0 = chain[0]
    if not isinstance(cert0, (bytes, bytearray)):
        raise SignedShortcutError("Signing cert is not DER bytes")
    return bytes(cert0)


def aea_decrypt_to_bytes(path: str) -> bytes:
    """Decrypt AEA1 .shortcut to raw payload using /usr/bin/aea + leaf cert pubkey."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    if not os.path.isfile("/usr/bin/aea"):
        raise SignedShortcutError(
            "/usr/bin/aea not found — need macOS with Apple Encrypted Archive CLI"
        )
    if not os.path.isfile("/usr/bin/openssl"):
        raise SignedShortcutError("openssl required to export EC public key from cert")

    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(b"AEA1"):
        # Not signed — return as-is for caller to parse
        return data

    cert_der = extract_signing_cert_der(data)
    td = tempfile.mkdtemp(prefix="ios-shortcuts-aea-")
    try:
        der_path = os.path.join(td, "leaf.der")
        pub_path = os.path.join(td, "leaf.pub.pem")
        out_path = os.path.join(td, "dec.bin")
        with open(der_path, "wb") as f:
            f.write(cert_der)
        r = _run(
            [
                "openssl",
                "x509",
                "-inform",
                "DER",
                "-in",
                der_path,
                "-pubkey",
                "-noout",
            ]
        )
        if r.returncode != 0 or not (r.stdout or "").strip():
            raise SignedShortcutError(
                "openssl pubkey extract failed: {0}".format(
                    (r.stderr or r.stdout or "")[:300]
                )
            )
        with open(pub_path, "w", encoding="utf-8") as f:
            f.write(r.stdout)
        r2 = _run(
            [
                "aea",
                "decrypt",
                "-i",
                path,
                "-o",
                out_path,
                "-sign-pub",
                pub_path,
            ]
        )
        if r2.returncode != 0 or not os.path.isfile(out_path):
            raise SignedShortcutError(
                "aea decrypt failed: {0}".format((r2.stderr or r2.stdout or "")[:400])
            )
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(td, ignore_errors=True)


def _plist_from_payload(payload: bytes) -> dict:
    """Parse decrypted or raw bytes into a WF workflow dict."""
    if not payload:
        raise SignedShortcutError("Empty shortcut payload")

    # Direct bplist / XML
    for candidate in (payload,):
        try:
            obj = plistlib.loads(candidate)
            if isinstance(obj, dict) and "WFWorkflowActions" in obj:
                return obj
        except Exception:
            pass

    # Nested bplist00 (e.g. AA01… header then bplist)
    idx = payload.find(b"bplist00")
    if idx >= 0:
        try:
            obj = plistlib.loads(payload[idx:])
            if isinstance(obj, dict) and "WFWorkflowActions" in obj:
                return obj
            if isinstance(obj, dict):
                for v in obj.values():
                    if isinstance(v, dict) and "WFWorkflowActions" in v:
                        return v
                    if isinstance(v, (bytes, bytearray)) and bytes(v[:8]) == b"bplist00":
                        inner = plistlib.loads(bytes(v))
                        if isinstance(inner, dict) and "WFWorkflowActions" in inner:
                            return inner
        except Exception as exc:
            raise SignedShortcutError(
                "Found bplist00 but parse failed: {0}".format(exc)
            )

    idx = payload.find(b"<?xml")
    if idx >= 0:
        try:
            obj = plistlib.loads(payload[idx:])
            if isinstance(obj, dict) and "WFWorkflowActions" in obj:
                return obj
        except Exception:
            pass

    raise SignedShortcutError(
        "Could not locate WFWorkflowActions in payload ({0} bytes)".format(len(payload))
    )


def load_workflow_plist(path: str) -> Tuple[dict, Dict[str, Any]]:
    """
    Load a workflow plist from raw or AEA1-signed .shortcut.

    Returns (plist, meta).
    """
    path = os.path.abspath(path)
    meta: Dict[str, Any] = {
        "path": path,
        "format": None,
        "aea_decrypted": False,
        "action_count": 0,
    }
    with open(path, "rb") as f:
        data = f.read()

    if data.startswith(b"AEA1"):
        payload = aea_decrypt_to_bytes(path)
        meta["aea_decrypted"] = True
        meta["format"] = "aea1_decrypted"
        plist = _plist_from_payload(payload)
    else:
        try:
            plist = plistlib.loads(data)
            meta["format"] = "plist"
        except Exception:
            plist = _plist_from_payload(data)
            meta["format"] = "plist_embedded"

    if not isinstance(plist, dict) or "WFWorkflowActions" not in plist:
        raise SignedShortcutError("Not a Shortcuts workflow plist")
    meta["action_count"] = len(plist.get("WFWorkflowActions") or [])
    meta["name"] = plist.get("WFWorkflowName")
    meta["client_version"] = plist.get("WFWorkflowClientVersion")
    return plist, meta


def action_inventory(plist: dict) -> List[Dict[str, Any]]:
    """Compact list of identifiers + param keys for agent diagnosis."""
    out: List[Dict[str, Any]] = []
    for i, a in enumerate(plist.get("WFWorkflowActions") or []):
        if not isinstance(a, dict):
            continue
        params = dict(a.get("WFWorkflowActionParameters") or {})
        out.append(
            {
                "index": i,
                "identifier": a.get("WFWorkflowActionIdentifier"),
                "CustomOutputName": params.get("CustomOutputName"),
                "param_keys": sorted(
                    k for k in params.keys() if k not in ("UUID", "CustomOutputName")
                ),
            }
        )
    return out


def dangling_action_output_refs(plist: dict) -> List[Dict[str, str]]:
    """Return ActionOutput references whose producer UUID is absent."""
    actions = plist.get("WFWorkflowActions") or []
    producer_uuids = {
        (a.get("WFWorkflowActionParameters") or {}).get("UUID")
        for a in actions
        if isinstance(a, dict)
    }
    found: List[Dict[str, str]] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = "{0}.{1}".format(path, key) if path else str(key)
                if key == "OutputUUID" and isinstance(child, str):
                    if child not in producer_uuids:
                        found.append({"path": child_path, "uuid": child})
                else:
                    walk(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, "{0}[{1}]".format(path, index))

    walk(actions, "WFWorkflowActions")
    return found


# ---------------------------------------------------------------------------
# Structural clone (UUID / GroupingIdentifier remap)
# ---------------------------------------------------------------------------


def _new_uid() -> str:
    return str(uuid.uuid4()).upper()


def clone_workflow_plist(
    plist: dict,
    *,
    new_name: Optional[str] = None,
) -> dict:
    """
    Deep-copy a workflow, remapping action UUIDs and GroupingIdentifiers so
    ActionOutput links stay consistent. OutputNames are preserved.
    """
    clone = deepcopy(plist)
    actions = clone.get("WFWorkflowActions") or []
    if not isinstance(actions, list):
        raise SignedShortcutError("WFWorkflowActions missing")

    old_to_new: Dict[str, str] = {}
    group_map: Dict[str, str] = {}

    for a in actions:
        if not isinstance(a, dict):
            continue
        p = a.setdefault("WFWorkflowActionParameters", {})
        if not isinstance(p, dict):
            continue
        old = p.get("UUID")
        nu = _new_uid()
        if old:
            old_to_new[str(old)] = nu
        p["UUID"] = nu
        g = p.get("GroupingIdentifier")
        if g and str(g) not in group_map:
            group_map[str(g)] = _new_uid()

    def rewrite(o: Any) -> Any:
        if isinstance(o, dict):
            out: Dict[Any, Any] = {}
            for k, v in o.items():
                if k in ("OutputUUID", "UUID") and isinstance(v, str) and v in old_to_new:
                    out[k] = old_to_new[v]
                elif (
                    k == "GroupingIdentifier"
                    and isinstance(v, str)
                    and v in group_map
                ):
                    out[k] = group_map[v]
                else:
                    out[k] = rewrite(v)
            return out
        if isinstance(o, list):
            return [rewrite(x) for x in o]
        return o

    clone["WFWorkflowActions"] = rewrite(actions)
    if new_name:
        clone["WFWorkflowName"] = new_name
    dangling = dangling_action_output_refs(clone)
    if dangling:
        raise SignedShortcutError(
            "Clone contains dangling ActionOutput references: {0}".format(
                dangling[:5]
            )
        )
    return clone


def write_raw_shortcut(plist: dict, path: str) -> str:
    dangling = dangling_action_output_refs(plist)
    if dangling:
        raise SignedShortcutError(
            "Refusing to write workflow with dangling ActionOutput references: {0}".format(
                dangling[:5]
            )
        )
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        plistlib.dump(plist, f, fmt=plistlib.FMT_BINARY)
    return path


def sign_shortcut(raw_path: str, signed_path: str, mode: str = "anyone") -> str:
    """
    Sign an **unsigned binary plist** ``.shortcut`` / raw workflow.

    Critical CLI shape (macOS ``shortcuts`` — do **not** invent long flags)::

        shortcuts sign -m anyone -i INPUT_raw.shortcut -o OUTPUT.shortcut

    Wrong (seen failing in agents)::

        shortcuts sign --mode anyone --input … --output …
        → "The file couldn’t be opened because it isn’t in the correct format."

    Input must be a plain bplist (``bplist00`` / XML), **not** AEA1-signed data.
    """
    raw_path = os.path.abspath(raw_path)
    signed_path = os.path.abspath(signed_path)
    if not os.path.isfile(raw_path):
        raise SignedShortcutError("sign input missing: {0}".format(raw_path))
    with open(raw_path, "rb") as f:
        head = f.read(8)
    if head.startswith(b"AEA1"):
        raise SignedShortcutError(
            "sign input is already AEA1-signed; pass *_raw.shortcut (bplist), not signed"
        )
    if not (head.startswith(b"bplist") or head.startswith(b"<?xml")):
        # still try — some wrappers — but warn via error if CLI fails
        pass
    else:
        # Quick structural check
        try:
            with open(raw_path, "rb") as f:
                pl = plistlib.loads(f.read())
            if not isinstance(pl, dict) or "WFWorkflowActions" not in pl:
                raise SignedShortcutError(
                    "sign input bplist has no WFWorkflowActions: {0}".format(raw_path)
                )
            dang = dangling_action_output_refs(pl)
            if dang:
                raise SignedShortcutError(
                    "sign input has dangling ActionOutput refs: {0}".format(dang[:3])
                )
        except SignedShortcutError:
            raise
        except Exception as exc:
            raise SignedShortcutError(
                "sign input is not a loadable workflow plist: {0}".format(exc)
            )

    r = _run(
        [
            "shortcuts",
            "sign",
            "-m",
            mode,
            "-i",
            raw_path,
            "-o",
            signed_path,
        ],
        timeout=60,
    )
    if r.returncode != 0 or not os.path.isfile(signed_path):
        raise SignedShortcutError(
            "shortcuts sign failed (use: shortcuts sign -m anyone -i RAW -o SIGNED; "
            "not --mode/--input/--output): {0}".format(
                (r.stderr or r.stdout or "")[:400]
            )
        )
    with open(signed_path, "rb") as f:
        shead = f.read(4)
    if shead != b"AEA1":
        # some older outputs may differ; still return path
        pass
    return signed_path


def extract_and_clone(
    source_path: str,
    *,
    output_dir: str,
    new_name: str,
    sign: bool = True,
    sign_mode: str = "anyone",
) -> Dict[str, Any]:
    """
    Decrypt/extract source → write raw + optional signed clone under output_dir.
    """
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    plist, meta = load_workflow_plist(source_path)
    inv = action_inventory(plist)
    cloned = clone_workflow_plist(plist, new_name=new_name)
    safe = re.sub(r"[^\w.\-]+", "_", new_name, flags=re.UNICODE).strip("_") or "clone"
    raw_path = os.path.join(output_dir, "{0}_raw.shortcut".format(safe))
    signed_path = os.path.join(output_dir, "{0}.shortcut".format(safe))
    write_raw_shortcut(cloned, raw_path)
    # also write extracted original raw for inspection
    orig_raw = os.path.join(output_dir, "extracted_source_raw.shortcut")
    write_raw_shortcut(plist, orig_raw)
    result: Dict[str, Any] = {
        "ok": True,
        "source": source_path,
        "extract_meta": meta,
        "action_inventory": inv,
        "extracted_raw_path": orig_raw,
        "clone_name": new_name,
        "raw_path": raw_path,
        "signed_path": None,
        "signed": False,
    }
    if sign:
        sign_shortcut(raw_path, signed_path, mode=sign_mode)
        result["signed_path"] = signed_path
        result["signed"] = True
        result["path"] = signed_path
    else:
        result["path"] = raw_path
    return result


# ---------------------------------------------------------------------------
# Library export (macOS Shortcuts GUI — ASCII path + clipboard)
# ---------------------------------------------------------------------------


def export_library_shortcut(
    name: str,
    *,
    export_dir: Optional[str] = None,
    export_filename: str = "exported_shortcut",
    open_after: bool = False,
) -> Dict[str, Any]:
    """
    Export a named library shortcut via Shortcuts File→Export.

    Uses clipboard paste for path/filename (ASCII only recommended) to avoid
    Korean IME corruption that produced Macintosh HD save errors.
    """
    export_dir = os.path.abspath(
        export_dir
        or os.path.expanduser("~/Desktop/shortcut-export")
    )
    os.makedirs(export_dir, exist_ok=True)
    # Do NOT wipe existing .shortcut files in export_dir

    # Open the shortcut in Shortcuts
    r = _run(["shortcuts", "view", name], timeout=30)
    # view may return 0 even if UI only

    # Stage 1: open export, go to folder, paste path
    path_cmd = (
        "printf %s {0} | pbcopy && "
        "osascript <<'AS'\n"
        "tell application \"Shortcuts\" to activate\n"
        "delay 1.2\n"
        "tell application \"System Events\"\n"
        "  tell process \"Shortcuts\"\n"
        "    set frontmost to true\n"
        "    delay 0.8\n"
        "    click menu item \"내보내기…\" of menu 1 of menu bar item \"파일\" of menu bar 1\n"
        "    delay 2.0\n"
        "    keystroke \"g\" using {{command down, shift down}}\n"
        "    delay 1.0\n"
        "    keystroke \"v\" using {{command down}}\n"
        "    delay 0.4\n"
        "    keystroke return\n"
        "    delay 1.5\n"
        "  end tell\n"
        "end tell\n"
        "AS"
    ).format(repr(export_dir))
    # Safer: write tiny scripts
    td = tempfile.mkdtemp(prefix="ios-shortcuts-export-")
    try:
        path_file = os.path.join(td, "path.txt")
        name_file = os.path.join(td, "name.txt")
        with open(path_file, "w", encoding="utf-8") as f:
            f.write(export_dir)
        with open(name_file, "w", encoding="utf-8") as f:
            f.write(export_filename)

        script1 = os.path.join(td, "export1.scpt")
        # Use shell to pbcopy then osascript
        r1 = _run(
            [
                "bash",
                "-c",
                "pbcopy < {0} && osascript <<'APPLESCRIPT'\n"
                "tell application \"Shortcuts\" to activate\n"
                "delay 1.2\n"
                "tell application \"System Events\"\n"
                "  tell process \"Shortcuts\"\n"
                "    set frontmost to true\n"
                "    delay 0.8\n"
                "    click menu item \"내보내기…\" of menu 1 of menu bar item \"파일\" of menu bar 1\n"
                "    delay 2.0\n"
                "    keystroke \"g\" using {{command down, shift down}}\n"
                "    delay 1.0\n"
                "    keystroke \"v\" using {{command down}}\n"
                "    delay 0.4\n"
                "    keystroke return\n"
                "    delay 1.5\n"
                "  end tell\n"
                "end tell\n"
                "APPLESCRIPT".format(path_file),
            ],
            timeout=45,
        )
        r2 = _run(
            [
                "bash",
                "-c",
                "pbcopy < {0} && osascript <<'APPLESCRIPT'\n"
                "tell application \"System Events\"\n"
                "  tell process \"Shortcuts\"\n"
                "    set frontmost to true\n"
                "    delay 0.3\n"
                "    keystroke \"a\" using {{command down}}\n"
                "    delay 0.15\n"
                "    keystroke \"v\" using {{command down}}\n"
                "    delay 0.35\n"
                "    keystroke return\n"
                "    delay 2.0\n"
                "    try\n"
                "      keystroke return\n"
                "    end try\n"
                "    delay 1.0\n"
                "    try\n"
                "      click button \"대치\" of sheet 1 of window 1\n"
                "    end try\n"
                "    try\n"
                "      click button \"확인\" of sheet 1 of window 1\n"
                "    end try\n"
                "  end tell\n"
                "end tell\n"
                "APPLESCRIPT".format(name_file),
            ],
            timeout=45,
        )
    finally:
        shutil.rmtree(td, ignore_errors=True)

    # Discover new files
    found: List[str] = []
    for fn in os.listdir(export_dir):
        if fn.endswith(".shortcut") or fn.endswith(".shortcuts"):
            found.append(os.path.join(export_dir, fn))
    found.sort(key=lambda p: os.path.getmtime(p), reverse=True)

    result: Dict[str, Any] = {
        "ok": bool(found),
        "library_name": name,
        "export_dir": export_dir,
        "export_filename_requested": export_filename,
        "files": found,
        "primary": found[0] if found else None,
        "view_rc": r.returncode,
        "notes": [
            "Uses File→Export with clipboard paste (ASCII path).",
            "Requires Accessibility permission for System Events → Shortcuts.",
            "Does not delete existing .shortcut files in export_dir.",
        ],
    }
    if open_after and found:
        subprocess.Popen(  # noqa: S603
            ["open", "-R", found[0]],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    if not found:
        result["error"] = (
            "No .shortcut appeared in export_dir. Grant Accessibility, ensure "
            "the shortcut is open, retry, or drag from library into export_dir."
        )
    return result


def scrub_for_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): scrub_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_for_json(x) for x in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return "<bytes:{0}>".format(len(obj))
    return obj
