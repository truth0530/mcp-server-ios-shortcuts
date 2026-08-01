# Clone & extract existing Shortcuts (v2.9+)

**Why this exists:** Improving a real user shortcut without reading its binary wastes
hours. Guessed identifiers (`cropimage`, `WFSpeakTextText`, wrong app bundle IDs)
look plausible but **do not match** hand-built library files.

## Agent rule

Before “fix” / “improve” any **existing** library shortcut:

1. **Export** it (tool or GUI) → `.shortcut` on disk  
2. **Extract** (AEA decrypt if signed) → action inventory  
3. **Clone** or **decompile** → edit from **real** identifiers/params  
4. Only then rebuild/sign  

Do **not** invent action graphs from UI screenshots alone when a file can be extracted.

## Tools

| Tool | Purpose |
|------|---------|
| `export_library_shortcut` | Library name → File→Export (clipboard ASCII path) |
| `extract_signed_shortcut` | AEA1 decrypt + inventory + `extracted_source_raw.shortcut` |
| `clone_shortcut` | Extract + UUID remap + raw/signed copy under new name |
| `decompile_shortcut` | Recipe JSON (now uses AEA path automatically) |

## AEA1 decrypt (technical)

Library exports are **Apple Encrypted Archive** (`AEA1` magic), not plain bplists.

1. Outer auth blob = bplist with `SigningCertificateChain` (DER certs)  
2. `openssl x509 -inform DER -pubkey` on leaf cert  
3. `/usr/bin/aea decrypt -i file.shortcut -o out.bin -sign-pub leaf.pub.pem`  
4. Inner payload: often `AA01…` then `bplist00` with `WFWorkflowActions`  

Implemented in `signed_shortcut.py` (`load_workflow_plist`, `aea_decrypt_to_bytes`).

## Export pitfalls (macOS GUI)

| Mistake | Result |
|---------|--------|
| Keystroke Korean path/filename | Path corruption → “Macintosh HD에 저장할 수 없습니다” |
| `rm export_dir/*` after success | **Deletes the original export** (never do this) |
| Expect plain `strings` on signed file | No `is.workflow.actions.*` visible (encrypted) |

**Do:** clipboard-paste pure ASCII directory + English stem (`exported_shortcut`).  
**Default dir:** `~/Desktop/shortcut-export`

## Clone semantics

- Deep-copies all actions and parameters  
- Remaps every action `UUID` and `GroupingIdentifier`  
- Rewrites nested `OutputUUID` references so magic links stay valid  
- Preserves `OutputName` strings (e.g. `이미지의 텍스트`)  

## Lessons from a real export

| Field | Actual original | Wrong guess |
|-------|-----------------|-------------|
| App bundle | whatever the app really uses (from export) | invented reverse-DNS |
| Crop | `image.crop` with explicit size/position | legacy `cropimage` (often Missing Action) |
| OCR input key | `WFImage` bound to ActionOutput | empty stack / wrong key |
| Speak key | `WFText` + attachments | only `WFSpeakTextText` |

## Sign (importable .shortcut for iPhone)

Agents often fail here. **Only** this form works on current macOS:

```bash
# RAW must be unsigned binary plist (bplist00), not AEA1
shortcuts sign -m anyone -i path/to/Name_raw.shortcut -o path/to/Name.shortcut
```

| Wrong | Result |
|-------|--------|
| `shortcuts sign --mode anyone --input … --output …` | format / open errors |
| Signing an already-AEA1 file | fail |
| Shipping only `*_raw.shortcut` to the user | **not importable as a finished product** |

Python:

```python
from signed_shortcut import sign_shortcut
sign_shortcut("dist/foo_raw.shortcut", "dist/foo.shortcut", mode="anyone")
```

**Definition of done for any improved build:** signed `Name.shortcut` exists, AEA-decrypts, and `open Name.shortcut` is offered for import. Raw alone is incomplete.

## CLI helpers

```bash
# Extract any signed export
python3 -c "
from signed_shortcut import load_workflow_plist, action_inventory
pl, m = load_workflow_plist('exported_shortcut.shortcut')
print(m); print(action_inventory(pl)[:5])
"

# Smoke
python3 scripts/smoke_test.py
```

## Related

- [RUNTIME_TRAPS.md](./RUNTIME_TRAPS.md)  
- [MAGIC_VARIABLES.md](./MAGIC_VARIABLES.md)  
- Module: `signed_shortcut.py`
