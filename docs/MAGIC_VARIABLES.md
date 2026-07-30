# Magic variables & action chaining

v2.3+ lets recipes **wire prior step outputs** into later parameters without relying only on the implicit Shortcuts stack.

## Tag a step output

```json
{
  "type": "text",
  "params": { "text": "Agent" },
  "as": "Name"
}
```

The step’s **last** compiled Workflow action gets a deterministic UUID; that UUID is what later refs resolve to.

## Reference forms

| Form | Meaning |
|------|---------|
| `{"$ref": {"action_index": 0}}` | Output of recipe step 0 |
| `{"$ref": {"action_index": 0, "output_name": "Text"}}` | Same + optional OutputName |
| `{"$ref": "action:0"}` | Shorthand |
| `{"$ref": "as:Name"}` | Output of the step tagged `as: "Name"` |
| `{"$ref": "var:Clip"}` | Named Shortcuts variable |
| `{"$ref": "input"}` | Shortcut Input |
| `{"$var": "Clip"}` | Same as var ref |
| `{"$action": 0}` | Same as action:0 |
| `{"$input": true}` | Shortcut Input |

### String interpolation

Produces a `WFTextTokenString` with object-replacement tokens:

```json
{
  "type": "text",
  "params": {
    "text": "Hello ${as:Name} / ${action:0} / ${var:Clip} / ${input}"
  }
}
```

## Rules

1. **No forward refs** — `action_index` / `as` must refer to an **earlier** step.  
2. **Aliases unique** — duplicate `as` names fail validation.  
3. Prefer explicit `$ref` over “hope the magic variable stack is right”.  
4. UUIDs are **deterministic** (`uuid5`) so golden fixtures stay stable.

## Example (`magic_chain` template)

```json
[
  { "type": "text", "params": { "text": "Agent" }, "as": "Name" },
  {
    "type": "text",
    "params": { "text": "Hello ${as:Name} from Shortcuts MCP" },
    "as": "Greeting"
  },
  {
    "type": "show_notification",
    "params": {
      "title": { "$ref": "as:Name" },
      "body": { "$ref": "as:Greeting" }
    }
  },
  {
    "type": "speak_text",
    "params": { "text": { "$action": 1 }, "wait": true }
  }
]
```

## Golden fixtures

| Path | Role |
|------|------|
| `fixtures/recipes/*.json` | Input recipes |
| `fixtures/golden/*.json` | Normalized expected WF actions |
| `scripts/generate_fixtures.py` | Rebuild goldens |
| `scripts/check_fixtures.py` | CI / smoke compare |

```bash
python3 scripts/generate_fixtures.py
python3 scripts/check_fixtures.py
```

UUIDs in goldens are rewritten to `UUID#0`, `UUID#1`, … so compare is stable.
