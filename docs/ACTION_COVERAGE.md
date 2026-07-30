# Apple action coverage (v2.4+)

## Goal

Cover **all Apple `is.workflow.actions.*` identifiers** available on a modern macOS install, not only a hand-picked dozen.

## Architecture

| Layer | What |
|-------|------|
| **Harvested catalog** | `data/apple_action_ids.txt` — 400+ identifiers extracted from the system |
| **Auto short names** | `is.workflow.actions.text.split` → `text_split` |
| **Curated aliases** | Ergonomic names (`speak_text`, `open_app`) with specialized param shaping |
| **Generic compiler** | Any listed *or unlisted* `is.workflow.actions.*` builds with pass-through params |
| **Synthetic helpers** | `conditional_start` / `repeat_*` / `menu_*` (multi-part WF control flow) |

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
