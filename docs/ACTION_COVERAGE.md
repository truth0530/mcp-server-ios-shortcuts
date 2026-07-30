# Apple action coverage (v2.5+)

## Goal

Cover **all Apple `is.workflow.actions.*` identifiers** available on a modern macOS install, not only a hand-picked dozen — **and** reduce Silent Corruption via auto-coercion, reverse decompilation, and platform preflight.

## Honest limits (read this)

1. **Identifier coverage ≠ executable parameter parity.**  
   Generic actions get auto-coerced wrappers (`WFTextTokenString`, `WFNumberSubstitutableState`). That fixes many empty-UI cases but is **not** a full reverse-engineered schema for every key.
2. **macOS harvest is one-eyed.** iOS-only and many App Intent domains need reverse-DNS / `app_intent` or iOS device harvest later.
3. **Smoke tests** now include decompile round-trip + optional `shortcuts run` when the library contains the probe shortcut. Pure “plist bytes exist” is no longer the only bar.
4. **Signed-only files** without `*_raw.shortcut` cannot be decompiled (Apple opaque package).

## Architecture

| Layer | What |
|-------|------|
| **Harvested catalog** | `data/apple_action_ids.txt` — 400+ identifiers |
| **Structured DB** | `data/apple_action_catalog.json` — platforms, serialization, short_names |
| **Auto short names** | collision-safe (`text_split`, disambiguated on clash) |
| **Curated aliases** | specialized param shaping (~100) |
| **Auto-coercion** | `wf_serialization.py` on generic path |
| **Decompiler** | `decompiler.py` / tool `decompile_shortcut` |
| **Learning loop** | `param_learning.py` → `data/learned_param_maps.json` (short→WF) |
| **App Intent** | `type: app_intent` + reverse-DNS identifiers |
| **Synthetic helpers** | `conditional_*` / `repeat_*` / `menu_*` |

## Learning loop (v2.6)

1. Compile seed recipes + templates + fixtures (known-good WF shapes)  
2. Optionally scan `dist/` and `IOS_SHORTCUTS_MCP_LEARN_ROOTS` for `*.shortcut` / `*_raw.shortcut`  
3. Aggregate per-identifier `key_freq`, `value_kinds`, `short_to_wf`  
4. Generic compiler remaps ergonomic keys before auto-coercion  

```bash
python3 scripts/learn_from_shortcuts.py
# or MCP: learn_from_corpus
```

Re-run after adding user-exported shortcuts to grow coverage beyond the seed set.

## How agents should call actions

### 1. Curated short name (best UX)

```json
{ "type": "speak_text", "params": { "text": "Hi", "wait": true } }
```

### 2. Auto short name from catalog

```json
{ "type": "text_split", "params": { "WFTextSeparator": "New Lines" } }
```

### 3. Full identifier (always works)

```json
{
  "type": "is.workflow.actions.downloadurl",
  "params": { "WFURL": "https://example.com", "WFHTTPMethod": "GET" }
}
```

### 4. Raw WF parameters escape hatch

```json
{
  "type": "is.workflow.actions.notification",
  "wf_params": {
    "WFNotificationActionTitle": "Hi",
    "WFNotificationActionBody": "Body"
  }
}
```

## Discovery tools

| Tool | Use |
|------|-----|
| `list_actions` | Browse catalog (`query`, `category`, `curated_only`, `limit`) |
| `lookup_action` | Resolve one short name / identifier + suggestions |
| `validate_recipe` | Reject unknown short names; accept full ids |

## Refreshing the harvest

On a Mac with Shortcuts installed:

```bash
python3 scripts/harvest_action_ids.py
python3 scripts/smoke_test.py
```

This re-scans dyld shared cache slices with `strings` and merges into `data/apple_action_ids.txt`.

## Honest limits

1. **Identifier coverage ≠ perfect parameter schemas.** Apple does not publish a stable public schema for every action. Curated types have rich params; generic types expect **Workflow parameter keys** (`WF…`) or `wf_params`.
2. **OS version drift.** Newer macOS/iOS may add identifiers; harvest again or pass the full id.
3. **Third-party app actions** (`com.something…`) can be passed as full identifiers when known; they are not fully harvested.
4. **Signing / runtime** still requires macOS `shortcuts` CLI for installable `.shortcut` files.

## Stats (check live)

```text
doctor → action_catalog.identifiers
list_actions → catalog.identifiers / curated_aliases
```
