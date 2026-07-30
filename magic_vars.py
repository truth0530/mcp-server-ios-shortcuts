#!/usr/bin/env python3
"""
Magic-variable / action-output references for shortcut recipes.

Recipe authors can wire action outputs without relying only on the implicit
Shortcuts "magic variable" stack:

  {"$ref": {"action_index": 0}}
  {"$ref": "action:0"}
  {"$ref": "var:Clip"}
  {"$ref": "as:Greeting"}
  {"$ref": "input"}
  {"$var": "Clip"}
  {"$action": 0}
  {"$input": true}

  # string interpolation → WFTextTokenString
  "Hello ${action:0} / ${var:Name} / ${as:Greeting} / ${input}"

Deterministic UUIDs (uuid5) keep golden fixtures stable across runs.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Stable namespace for deterministic action UUIDs (do not change — breaks goldens).
UUID_NS = uuid.UUID("a6c3e9f0-7b2d-4e11-9c44-0f1a2b3c4d5e")

# Object-replacement char used by Shortcuts text tokens.
_OBJ_CHAR = "\ufffc"

_INTERP_RE = re.compile(
    r"\$\{("
    r"action:(?P<aidx>\d+)(?:\.(?P<aname>[^}]+))?"
    r"|var:(?P<vname>[^}]+)"
    r"|as:(?P<asname>[^}]+)"
    r"|input"
    r")\}"
)


def step_uuid(index: int) -> str:
    """Output UUID for recipe step *index* (last WF action of that step)."""
    return str(
        uuid.uuid5(UUID_NS, "ios-shortcuts-mcp/action/{0}".format(index))
    ).upper()


def part_uuid(index: int, part: int) -> str:
    """UUID for intermediate WF actions inside a multi-action step."""
    return str(
        uuid.uuid5(
            UUID_NS,
            "ios-shortcuts-mcp/action/{0}/part/{1}".format(index, part),
        )
    ).upper()


def variable_attachment(name: str) -> dict:
    return {
        "Value": {"VariableName": name, "Type": "Variable"},
        "WFSerializationType": "WFTextTokenAttachment",
    }


def action_output_attachment(
    output_uuid: str,
    output_name: Optional[str] = None,
) -> dict:
    value: Dict[str, Any] = {
        "OutputUUID": output_uuid,
        "Type": "ActionOutput",
    }
    if output_name:
        value["OutputName"] = output_name
    return {
        "Value": value,
        "WFSerializationType": "WFTextTokenAttachment",
    }


def input_attachment() -> dict:
    return {
        "Value": {"Type": "ExtensionInput"},
        "WFSerializationType": "WFTextTokenAttachment",
    }


def is_ref_like(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(
        k in value
        for k in ("$ref", "$var", "$action", "$input", "$as")
    )


def parse_ref(ref: Any) -> Dict[str, Any]:
    """
    Normalize a ref payload into:
      {kind: 'action'|'var'|'as'|'input', index?, name?, output_name?}
    """
    if ref is True or ref == "input":
        return {"kind": "input"}

    if isinstance(ref, int):
        return {"kind": "action", "index": int(ref)}

    if isinstance(ref, str):
        s = ref.strip()
        if s == "input":
            return {"kind": "input"}
        if s.startswith("action:"):
            rest = s[7:]
            if "." in rest:
                idx_s, oname = rest.split(".", 1)
                return {
                    "kind": "action",
                    "index": int(idx_s),
                    "output_name": oname or None,
                }
            return {"kind": "action", "index": int(rest)}
        if s.startswith("var:"):
            return {"kind": "var", "name": s[4:]}
        if s.startswith("as:"):
            return {"kind": "as", "name": s[3:]}
        # bare name → variable
        return {"kind": "var", "name": s}

    if isinstance(ref, dict):
        if ref.get("input") is True or ref.get("type") == "input":
            return {"kind": "input"}
        if "action_index" in ref or "index" in ref:
            idx = ref.get("action_index", ref.get("index"))
            return {
                "kind": "action",
                "index": int(idx),
                "output_name": ref.get("output_name") or ref.get("OutputName"),
            }
        if "variable" in ref or "var" in ref or "var_name" in ref:
            return {
                "kind": "var",
                "name": str(
                    ref.get("variable") or ref.get("var") or ref.get("var_name")
                ),
            }
        if "as" in ref or "alias" in ref:
            return {"kind": "as", "name": str(ref.get("as") or ref.get("alias"))}
        if "action" in ref and isinstance(ref["action"], int):
            return {
                "kind": "action",
                "index": int(ref["action"]),
                "output_name": ref.get("output_name"),
            }

    raise ValueError("Unrecognized magic ref: {0!r}".format(ref))


def ref_from_shorthand(obj: dict) -> Optional[Dict[str, Any]]:
    """If obj is a shorthand ref dict, return parse_ref result."""
    if "$ref" in obj:
        return parse_ref(obj["$ref"])
    if "$var" in obj:
        return parse_ref({"var": obj["$var"]})
    if "$as" in obj:
        return parse_ref({"as": obj["$as"]})
    if "$action" in obj:
        a = obj["$action"]
        if isinstance(a, int):
            return parse_ref(a)
        return parse_ref(a)
    if "$input" in obj:
        return parse_ref(True if obj["$input"] else "input")
    return None


class RecipeContext:
    """Compilation context for resolving refs at recipe step *current_index*."""

    def __init__(
        self,
        *,
        step_count: int,
        aliases: Dict[str, int],
        current_index: int,
    ) -> None:
        self.step_count = step_count
        self.aliases = dict(aliases)
        self.current_index = current_index
        self.step_uuids = {i: step_uuid(i) for i in range(step_count)}

    def resolve_parsed(self, parsed: Dict[str, Any]) -> dict:
        kind = parsed["kind"]
        if kind == "input":
            return input_attachment()
        if kind == "var":
            name = parsed.get("name") or ""
            if not name:
                raise ValueError("variable ref missing name")
            return variable_attachment(name)
        if kind == "as":
            name = parsed.get("name") or ""
            if name not in self.aliases:
                raise ValueError("unknown alias '{0}'".format(name))
            idx = self.aliases[name]
            if idx >= self.current_index:
                raise ValueError(
                    "alias '{0}' refers to step {1} which is not yet available "
                    "at step {2}".format(name, idx, self.current_index)
                )
            return action_output_attachment(
                self.step_uuids[idx],
                parsed.get("output_name"),
            )
        if kind == "action":
            idx = int(parsed["index"])
            if idx < 0 or idx >= self.step_count:
                raise ValueError(
                    "action_index {0} out of range 0..{1}".format(
                        idx, self.step_count - 1
                    )
                )
            if idx >= self.current_index:
                raise ValueError(
                    "forward/self action ref action:{0} not allowed at step {1}".format(
                        idx, self.current_index
                    )
                )
            return action_output_attachment(
                self.step_uuids[idx],
                parsed.get("output_name"),
            )
        raise ValueError("unknown ref kind {0}".format(kind))


def resolve_ref_object(obj: dict, ctx: RecipeContext) -> dict:
    parsed = ref_from_shorthand(obj)
    if parsed is None:
        raise ValueError("not a ref object: {0!r}".format(obj))
    return ctx.resolve_parsed(parsed)


def resolve_interpolated_string(text: str, ctx: RecipeContext) -> Any:
    """
    Convert strings with ${action:N} / ${var:X} / ${as:A} / ${input}
    into a WFTextTokenString, or return plain str when no tokens.
    """
    matches = list(_INTERP_RE.finditer(text))
    if not matches:
        return text

    out_chars: List[str] = []
    attachments: Dict[str, Any] = {}
    cursor = 0
    for m in matches:
        out_chars.append(text[cursor : m.start()])
        token_start = sum(len(c) for c in out_chars)
        out_chars.append(_OBJ_CHAR)
        # Build attachment value (inner Value dict, not full attachment wrapper)
        raw = m.group(1)
        if raw == "input":
            att = input_attachment()["Value"]
        elif m.group("aidx") is not None:
            parsed = {
                "kind": "action",
                "index": int(m.group("aidx")),
                "output_name": m.group("aname"),
            }
            att = ctx.resolve_parsed(parsed)["Value"]
        elif m.group("vname") is not None:
            att = variable_attachment(m.group("vname"))["Value"]
        elif m.group("asname") is not None:
            att = ctx.resolve_parsed(
                {"kind": "as", "name": m.group("asname")}
            )["Value"]
        else:
            raise ValueError("unhandled interpolation: {0}".format(m.group(0)))
        attachments["{{{0}, 1}}".format(token_start)] = att
        cursor = m.end()
    out_chars.append(text[cursor:])
    full = "".join(out_chars)
    return {
        "Value": {
            "string": full,
            "attachmentsByRange": attachments,
        },
        "WFSerializationType": "WFTextTokenString",
    }


def resolve_value(value: Any, ctx: RecipeContext) -> Any:
    """Deep-resolve refs and interpolations inside a params tree."""
    if is_ref_like(value):
        return resolve_ref_object(value, ctx)
    if isinstance(value, str) and "${" in value:
        return resolve_interpolated_string(value, ctx)
    if isinstance(value, dict):
        # Do not dive into already-resolved WF serializations
        if value.get("WFSerializationType") in {
            "WFTextTokenAttachment",
            "WFTextTokenString",
        }:
            return value
        return {k: resolve_value(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_value(v, ctx) for v in value]
    return value


def resolve_params(params: dict, ctx: RecipeContext) -> dict:
    if not isinstance(params, dict):
        return {}
    return {k: resolve_value(v, ctx) for k, v in params.items()}


def collect_aliases(actions_config: list) -> Tuple[Dict[str, int], List[str]]:
    aliases: Dict[str, int] = {}
    errors: List[str] = []
    for i, item in enumerate(actions_config or []):
        if not isinstance(item, dict):
            continue
        alias = item.get("as")
        if alias is None:
            continue
        name = str(alias).strip()
        if not name:
            errors.append("actions[{0}]: empty 'as' alias".format(i))
            continue
        if name in aliases:
            errors.append(
                "actions[{0}]: duplicate alias '{1}' (also at {2})".format(
                    i, name, aliases[name]
                )
            )
            continue
        aliases[name] = i
    return aliases, errors


def walk_ref_nodes(obj: Any, path: str = "") -> Iterable[Tuple[str, Any]]:
    """Yield (path, node) for every magic-ref node or interpolatable string."""
    if is_ref_like(obj):
        yield path or "$", obj
        return
    if isinstance(obj, str) and "${" in obj:
        yield path or "$", obj
        return
    if isinstance(obj, dict):
        if obj.get("WFSerializationType") in {
            "WFTextTokenAttachment",
            "WFTextTokenString",
        }:
            return
        for k, v in obj.items():
            p = "{0}.{1}".format(path, k) if path else k
            yield from walk_ref_nodes(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            p = "{0}[{1}]".format(path, i)
            yield from walk_ref_nodes(v, p)


def validate_magic_refs(
    actions_config: list,
    *,
    aliases: Optional[Dict[str, int]] = None,
) -> Tuple[List[str], List[str]]:
    """Return (errors, warnings) for magic refs across the whole recipe."""
    errors: List[str] = []
    warnings: List[str] = []
    if aliases is None:
        aliases, alias_errors = collect_aliases(actions_config)
        errors.extend(alias_errors)

    n = len(actions_config or [])
    for i, item in enumerate(actions_config or []):
        if not isinstance(item, dict):
            continue
        params = item.get("params") or item.get("arguments") or {}
        if not isinstance(params, dict):
            continue
        ctx = RecipeContext(step_count=n, aliases=aliases, current_index=i)
        for path, node in walk_ref_nodes(params):
            try:
                if isinstance(node, str):
                    # Validate each interpolation token by resolving
                    resolve_interpolated_string(node, ctx)
                else:
                    resolve_ref_object(node, ctx)
            except Exception as exc:
                errors.append(
                    "actions[{0}].params{1}: {2}".format(
                        i, ("." + path) if path != "$" else "", exc
                    )
                )
    return errors, warnings


def stamp_action_uuids(
    parts: List[dict],
    *,
    step_index: int,
) -> List[dict]:
    """Attach deterministic UUIDs; last part is the step's public output UUID."""
    if not parts:
        return parts
    out: List[dict] = []
    for j, part in enumerate(parts):
        cloned = {
            "WFWorkflowActionIdentifier": part["WFWorkflowActionIdentifier"],
            "WFWorkflowActionParameters": dict(
                part.get("WFWorkflowActionParameters") or {}
            ),
        }
        uid = (
            step_uuid(step_index)
            if j == len(parts) - 1
            else part_uuid(step_index, j)
        )
        cloned["WFWorkflowActionParameters"]["UUID"] = uid
        out.append(cloned)
    return out


# ---------------------------------------------------------------------------
# Golden fixture normalization
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b"
)


def normalize_for_golden(obj: Any, uuid_table: Optional[Dict[str, str]] = None) -> Any:
    """
    Replace concrete UUIDs with stable placeholders UUID#0, UUID#1, …
    so fixtures compare cleanly even if generation order differs slightly.
    """
    if uuid_table is None:
        uuid_table = {}

    def map_uuid(u: str) -> str:
        key = u.upper()
        if key not in uuid_table:
            uuid_table[key] = "UUID#{0}".format(len(uuid_table))
        return uuid_table[key]

    if isinstance(obj, dict):
        return {
            k: normalize_for_golden(v, uuid_table)
            for k, v in sorted(obj.items(), key=lambda kv: kv[0])
        }
    if isinstance(obj, list):
        return [normalize_for_golden(v, uuid_table) for v in obj]
    if isinstance(obj, str):
        def repl(m: re.Match) -> str:
            return map_uuid(m.group(0))

        return _UUID_RE.sub(repl, obj)
    return obj


def workflow_actions_golden(wf_actions: List[dict]) -> List[dict]:
    """Normalize a list of WF actions for fixture storage/compare."""
    slim = []
    for a in wf_actions:
        slim.append(
            {
                "identifier": a.get("WFWorkflowActionIdentifier"),
                "params": a.get("WFWorkflowActionParameters") or {},
            }
        )
    return normalize_for_golden(slim)  # type: ignore[return-value]


def explain_magic_syntax() -> Dict[str, Any]:
    """Agent-facing documentation blob."""
    return {
        "summary": (
            "Reference prior action outputs, named variables, aliases, or "
            "shortcut input via $ref / $var / $action / $input or ${…} interpolation."
        ),
        "forms": [
            {"$ref": {"action_index": 0}},
            {"$ref": {"action_index": 0, "output_name": "Text"}},
            {"$ref": "action:0"},
            {"$ref": "var:Clip"},
            {"$ref": "as:Greeting"},
            {"$ref": "input"},
            {"$var": "Clip"},
            {"$action": 0},
            {"$input": True},
            "Hello ${action:0} ${var:Name} ${as:Greeting} ${input}",
        ],
        "alias": {
            "description": "Tag a step with top-level 'as' to name its output",
            "example": {
                "type": "text",
                "params": {"text": "hi"},
                "as": "Greeting",
            },
        },
        "rules": [
            "action/as refs must point to earlier steps only (no forward refs)",
            "each step gets a deterministic UUID; last sub-action is the step output",
            "prefer $ref over relying on implicit magic-variable stack alone",
        ],
    }
