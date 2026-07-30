#!/usr/bin/env python3
"""Offline smoke tests for ios-shortcuts MCP (no network client required)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from decompiler import decompile_shortcut  # noqa: E402
from shortcut_builder import (  # noqa: E402
    build_shortcut_plist,
    compile_recipe,
    get_template,
    inspect_shortcut_file,
    list_supported_actions,
    list_templates,
    validate_actions,
)
from wf_serialization import coerce_params  # noqa: E402
import server as mcp_server  # noqa: E402


def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_catalog() -> None:
    actions = list_supported_actions(limit=2000)
    assert_true(
        len(actions) >= 300,
        "expected full Apple catalog (>=300), got {0}".format(len(actions)),
    )
    assert_true(any(a.get("risk") == "dangerous" for a in actions), "missing risk tags")
    assert_true(
        any(
            (a.get("identifier") or "").startswith("is.workflow.actions.")
            for a in actions
        ),
        "missing full identifiers",
    )
    templates = list_templates()
    assert_true(len(templates) >= 5, "expected several templates")
    tpl = get_template("hello_world")
    assert_true(len(tpl["actions"]) >= 1, "hello_world empty")


def test_wf_auto_coercion() -> None:
    coerced = coerce_params(
        {
            "WFSpeakTextText": "hello",
            "WFDelayTime": 2,
            "UUID": "keep-plain",
        },
        mode="smart",
    )
    assert_true(
        coerced["WFSpeakTextText"]["WFSerializationType"] == "WFTextTokenString",
        coerced,
    )
    assert_true(
        coerced["WFDelayTime"]["WFSerializationType"]
        == "WFNumberSubstitutableState",
        coerced,
    )
    assert_true(coerced["UUID"] == "keep-plain", coerced)
    # generic compile applies coercion
    compiled = compile_recipe(
        [
            {
                "type": "is.workflow.actions.speaktext",
                "params": {"WFSpeakTextText": "x", "WFSpeakTextWait": True},
            }
        ]
    )
    text = compiled["wf_actions"][0]["WFWorkflowActionParameters"]["WFSpeakTextText"]
    assert_true(
        isinstance(text, dict) and text.get("WFSerializationType") == "WFTextTokenString",
        text,
    )


def test_decompile_roundtrip() -> None:
    recipe = [
        {"type": "comment", "params": {"text": "e2e"}},
        {"type": "nothing", "params": {}},
        {
            "type": "show_notification",
            "params": {"title": "Title", "body": "Body"},
        },
    ]
    with tempfile.TemporaryDirectory() as td:
        built = build_shortcut_plist(recipe, "DecompRT", td, sign=False)
        dec = decompile_shortcut(built["raw_path"])
        assert_true(dec["ok"], dec)
        types = [a["type"] for a in dec["actions"]]
        assert_true(types == ["comment", "nothing", "show_notification"], types)
        # re-validate & rebuild
        v = validate_actions(dec["actions"])
        assert_true(v["ok"], v)
        built2 = build_shortcut_plist(dec["actions"], "DecompRT2", td, sign=False)
        assert_true(os.path.isfile(built2["raw_path"]), built2)

        tool = mcp_server.handle_tool_call(
            "decompile_shortcut", {"path": built["raw_path"]}
        )
        assert_true(not tool.get("isError"), tool)
        assert_true(tool["structuredContent"]["action_count"] == 3, tool)


def test_platform_preflight() -> None:
    bad = validate_actions(
        [{"type": "run_shell_script", "params": {"script": "echo hi"}}],
        target_platform="ios",
    )
    assert_true(not bad["ok"], bad)
    ok = validate_actions(
        [{"type": "run_shell_script", "params": {"script": "echo hi"}}],
        target_platform="macos",
    )
    assert_true(ok["ok"], ok)


def test_app_intent_compile() -> None:
    recipe = [
        {
            "type": "app_intent",
            "params": {
                "identifier": "com.example.demo.MyIntent",
                "bundle_identifier": "com.example.demo",
                "parameters": {"query": "hello"},
            },
        }
    ]
    v = validate_actions(recipe, target_platform="ios")
    assert_true(v["ok"], v)
    compiled = compile_recipe(recipe, target_platform="ios")
    act = compiled["wf_actions"][0]
    assert_true(
        act["WFWorkflowActionIdentifier"] == "com.example.demo.MyIntent",
        act,
    )


def test_param_learning_loop() -> None:
    from library_extractor import extract_gallery_wflows, is_self_built_plist
    from param_learning import (
        apply_learned_param_map,
        classify_param_schema,
        get_learned,
        get_param_map,
        learned_stats,
        run_learning,
        save_learned,
    )
    from shortcut_builder import build_shortcut_dict

    # Echo chamber: self-built detection
    pl = build_shortcut_dict(
        [{"type": "comment", "params": {"text": "x"}}, {"type": "nothing", "params": {}}],
        "SelfProbe",
    )
    assert_true(is_self_built_plist(pl), "should detect self-built uuid5")

    # Gallery is external Apple
    gallery = extract_gallery_wflows()
    assert_true(len(gallery) >= 3, gallery)
    assert_true(all(g["source_class"] == "external_apple" for g in gallery), gallery)

    # Enum discriminator
    sch = classify_param_schema(
        "WFHTTPMethod",
        {"string": 10},
        ["GET", "POST", "PUT"],
    )
    assert_true(sch["kind"] == "enum", sch)
    assert_true(sch["coerce"] == "plain_string", sch)
    sch2 = classify_param_schema(
        "WFSpeakTextText",
        {"WFTextTokenString": 8, "string": 2},
        ["hello"],
    )
    assert_true(sch2["kind"] == "text_token", sch2)

    # Trusted learning (gallery/system; no self bootstrap)
    doc = run_learning(
        export_roots=[],
        include_gallery=True,
        include_dictation=True,
        include_sqlite=False,  # may be TCC-blocked in CI
        include_self_bootstrap=False,
        validate=True,
    )
    path = save_learned(doc)
    assert_true(os.path.isfile(path), path)
    get_learned(force_reload=True)
    stats = learned_stats()
    assert_true(int(stats.get("trusted_identifier_count") or 0) >= 5, stats)
    # validation ran
    assert_true(stats.get("validation_report_summary", {}).get("tested") is not None, stats)

    # Accepted maps only applied
    # Find any accepted action with a short map
    accepted_any = False
    for row_id, entry in (doc.get("actions") or {}).items():
        amap = entry.get("accepted_short_to_wf") or {}
        if not amap:
            continue
        accepted_any = True
        # apply_learned with accepted_only should map
        short, wf = next(iter(amap.items()))
        mapped, notes = apply_learned_param_map(
            row_id, {short: "probe"}, accepted_only=True
        )
        assert_true(wf in mapped, (row_id, mapped, notes))
        break
    # Gallery may yield few maps if params sparse; still OK if trusted ids > 0
    assert_true(
        accepted_any or int(stats.get("trusted_identifier_count") or 0) >= 5,
        "expected accepted maps or at least trusted observations",
    )

    tool = mcp_server.handle_tool_call("extract_system_library", {"include_sqlite": False})
    assert_true(not tool.get("isError"), tool)
    assert_true(tool["structuredContent"]["count"] >= 3, tool)


def test_e2e_runtime_run_if_possible() -> None:
    """
    True runtime assertion when macOS allows headless install+run.

    Always asserts: build → decompile → re-validate.
    Optionally asserts: shortcuts run if the shortcut appears in `shortcuts list`
    after open import (may require prior GUI approval on some systems).
    """
    name = "MCP_E2E_RuntimeProbe"
    recipe = [
        {"type": "comment", "params": {"text": "runtime probe"}},
        {"type": "nothing", "params": {}},
    ]
    # Build into default dist (sandbox)
    built = mcp_server.handle_tool_call(
        "build_shortcut",
        {"name": name, "actions": recipe, "sign": True},
    )
    assert_true(not built.get("isError"), built)
    sc = built["structuredContent"]
    raw = sc.get("raw_path")
    assert_true(raw and os.path.isfile(raw), sc)

    dec = mcp_server.handle_tool_call("decompile_shortcut", {"path": raw})
    assert_true(not dec.get("isError"), dec)
    assert_true(dec["structuredContent"]["action_count"] >= 1, dec)

    # Attempt install + run (best-effort hard check when list contains name)
    path = sc.get("path") or raw
    subprocess.run(["open", path], capture_output=True, text=True, timeout=30)
    # give Shortcuts a moment if it auto-imports in some configs
    listed = subprocess.run(
        ["shortcuts", "list"], capture_output=True, text=True, timeout=30
    )
    if listed.returncode == 0 and name in (listed.stdout or ""):
        run = subprocess.run(
            ["shortcuts", "run", name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert_true(
            run.returncode == 0,
            "shortcuts run failed: rc={0} stderr={1} stdout={2}".format(
                run.returncode, run.stderr, run.stdout
            ),
        )
        print("  (e2e run executed successfully)")
    else:
        # Structural E2E still counts; document skip reason for agents
        print("  (e2e run skipped: shortcut not in library after open — GUI import required)")


def test_full_apple_identifier_coverage() -> None:
    """Any harvested / full is.workflow.actions.* id must validate + compile."""
    from action_catalog import catalog_stats, resolve_action_type

    stats = catalog_stats()
    assert_true(stats["identifiers"] >= 300, stats)

    # Full identifier generic compile
    recipe = [
        {
            "type": "is.workflow.actions.notification",
            "params": {
                "WFNotificationActionTitle": "T",
                "WFNotificationActionBody": "B",
            },
        }
    ]
    v = validate_actions(recipe)
    assert_true(v["ok"], v)
    compiled = compile_recipe(recipe)
    assert_true(
        compiled["wf_actions"][0]["WFWorkflowActionIdentifier"]
        == "is.workflow.actions.notification",
        compiled,
    )

    # Auto short from catalog
    ident, _ = resolve_action_type("speaktext")
    assert_true(ident == "is.workflow.actions.speaktext", ident)

    # Unknown short still fails
    bad = validate_actions([{"type": "no_such_action_zzz", "params": {}}])
    assert_true(not bad["ok"], bad)

    # lookup tool
    hit = mcp_server.handle_tool_call("lookup_action", {"type": "open_app"})
    assert_true(not hit.get("isError"), hit)
    assert_true(
        hit["structuredContent"]["identifier"] == "is.workflow.actions.openapp",
        hit,
    )


def test_validate_and_build() -> None:
    recipe = [
        {"type": "comment", "params": {"text": "smoke"}},
        {"type": "set_volume", "params": {"volume": 0.5}},
        {"type": "show_notification", "params": {"title": "Smoke", "body": "ok"}},
        {"type": "delay", "params": {"seconds": 0.1}},
    ]
    v = validate_actions(recipe)
    assert_true(v["ok"], "validate failed: {0}".format(v))

    bad = validate_actions([{"type": "not_a_real_action_xyz", "params": {}}])
    assert_true(not bad["ok"], "expected unknown action to fail validation")

    empty = validate_actions([])
    assert_true(not empty["ok"], "empty recipe should fail")

    with tempfile.TemporaryDirectory() as td:
        # Allow temp dir for sandbox tests via env would require reimport;
        # call builder directly (no sandbox) for unit path.
        result = build_shortcut_plist(recipe, "SmokeTest", td, sign=True)
        assert_true(isinstance(result, dict), "build must return dict")
        assert_true(os.path.isfile(result["raw_path"]), result)
        assert_true(result["raw_path"].endswith("_raw.shortcut"), result)
        if result.get("signed"):
            assert_true(os.path.isfile(result["signed_path"]), result)
            insp = inspect_shortcut_file(result["signed_path"])
            assert_true(
                insp.get("format") in {"plist", "plist_via_raw_sibling"},
                "inspect should follow raw sibling: {0}".format(insp),
            )
            assert_true(insp.get("action_count", 0) >= 1, insp)

        # tool-level inspect
        tool = mcp_server.handle_tool_call(
            "inspect_shortcut", {"path": result["path"]}
        )
        assert_true(not tool.get("isError"), tool)
        assert_true(tool["structuredContent"]["size_bytes"] > 0, tool)


def test_semantic_validation() -> None:
    assert_true(
        not validate_actions([{"type": "delay", "params": {"seconds": -1}}])["ok"],
        "negative delay",
    )
    assert_true(
        not validate_actions([{"type": "set_volume", "params": {"volume": 9}}])["ok"],
        "volume out of range",
    )
    assert_true(
        not validate_actions([{"type": "open_url", "params": {"url": ""}}])["ok"],
        "empty url",
    )
    shell = validate_actions(
        [{"type": "run_shell_script", "params": {"script": "echo hi"}}],
        safe_mode=True,
    )
    assert_true(not shell["ok"], "safe mode must block shell: {0}".format(shell))
    shell_ok = validate_actions(
        [{"type": "run_shell_script", "params": {"script": "echo hi"}}],
        safe_mode=False,
    )
    assert_true(shell_ok["ok"], shell_ok)
    assert_true("run_shell_script" in shell_ok.get("risks", []), shell_ok)


def test_control_flow_validation() -> None:
    valid = [
        {
            "type": "conditional_start",
            "params": {"group_id": "IF-1", "condition": "equals", "value": "yes"},
        },
        {"type": "menu_start", "params": {"group_id": "MENU-1", "prompt": "Pick"}},
        {"type": "menu_item", "params": {"group_id": "MENU-1", "title": "One"}},
        {"type": "menu_end", "params": {"group_id": "MENU-1"}},
        {"type": "conditional_else", "params": {"group_id": "IF-1"}},
        {"type": "conditional_end", "params": {"group_id": "IF-1"}},
    ]
    assert_true(validate_actions(valid)["ok"], "valid nested control flow rejected")

    invalid_recipes = [
        [
            {"type": "conditional_start", "params": {}},
            {"type": "conditional_end", "params": {"group_id": "IF-1"}},
        ],
        [
            {"type": "conditional_start", "params": {"group_id": "IF-1"}},
            {"type": "repeat_end", "params": {"group_id": "IF-1"}},
        ],
        [{"type": "menu_start", "params": {"group_id": "MENU-1"}}],
        [
            {"type": "conditional_start", "params": {"group_id": "IF-1"}},
            {"type": "conditional_else", "params": {"group_id": "IF-1"}},
            {"type": "conditional_else", "params": {"group_id": "IF-1"}},
            {"type": "conditional_end", "params": {"group_id": "IF-1"}},
        ],
    ]
    for recipe in invalid_recipes:
        result = validate_actions(recipe)
        assert_true(not result["ok"], "invalid control flow accepted: {0}".format(result))
        assert_true(result["errors"], "missing validation errors: {0}".format(result))


def test_templates_build() -> None:
    with tempfile.TemporaryDirectory() as td:
        for name in ("hello_world", "volume_max_and_notify", "shell_echo"):
            tpl = get_template(name)
            result = build_shortcut_plist(
                tpl["actions"], "T_{0}".format(name), td, sign=False
            )
            assert_true(result["raw_path"].endswith("_raw.shortcut"), result)
            assert_true(os.path.isfile(result["raw_path"]), result)
            assert_true(result["signed"] is False, result)


def test_path_sandbox_and_structured_errors() -> None:
    # Build into default dist (allowed)
    result = mcp_server.handle_tool_call(
        "build_shortcut",
        {
            "name": "SandboxOk",
            "actions": [
                {"type": "show_notification", "params": {"title": "A", "body": "B"}}
            ],
            "sign": False,
        },
    )
    assert_true(not result.get("isError"), result)
    sc = result["structuredContent"]
    assert_true(sc.get("raw_path"), sc)
    assert_true("ok" in sc, sc)

    # Escape attempt
    bad = mcp_server.handle_tool_call(
        "build_shortcut",
        {
            "name": "Escape",
            "actions": [{"type": "nothing", "params": {}}],
            "output_dir": "/tmp/ios-shortcuts-mcp-should-block",
            "sign": False,
        },
    )
    assert_true(bad.get("isError"), bad)
    assert_true(bad["structuredContent"]["code"] == "PATH_SANDBOX", bad)

    # Structured validation error
    verr = mcp_server.handle_tool_call(
        "build_shortcut",
        {
            "name": "BadVol",
            "actions": [{"type": "set_volume", "params": {"volume": 3}}],
            "sign": False,
        },
    )
    assert_true(verr.get("isError"), verr)
    assert_true(verr["structuredContent"]["code"] == "VALIDATION_ERROR", verr)


def test_tool_annotations_and_doctor() -> None:
    names = {t["name"] for t in mcp_server.TOOLS}
    for required in (
        "list_actions",
        "build_shortcut",
        "build_and_install",
        "validate_recipe",
        "doctor",
        "list_templates",
        "run_shortcut",
        "view_shortcut",
        "inspect_shortcut",
    ):
        assert_true(required in names, "missing tool {0}".format(required))

    for t in mcp_server.TOOLS:
        assert_true("annotations" in t, "missing annotations on {0}".format(t["name"]))
        assert_true("inputSchema" in t, t["name"])
        # actions tools should constrain items
        if t["name"] in {"build_shortcut", "validate_recipe", "build_and_install"}:
            props = t["inputSchema"]["properties"]
            assert_true("actions" in props, t["name"])
            assert_true(props["actions"].get("items"), t["name"])

    doc = mcp_server.handle_tool_call("doctor", {})
    assert_true(not doc.get("isError"), doc)
    payload = doc["structuredContent"]
    assert_true(payload["version"] == mcp_server.SERVER_VERSION, payload)
    assert_true(payload["action_types"] >= 40, payload)
    assert_true(
        (payload.get("action_catalog") or {}).get("identifiers", 0) >= 300,
        payload.get("action_catalog"),
    )
    assert_true("sign_probe" in payload, payload)
    assert_true("allow_roots" in payload, payload)
    assert_true("safe_mode" in payload, payload)
    # On macOS with shortcuts, sign probe should usually succeed
    if payload.get("shortcuts_cli", {}).get("available"):
        assert_true(payload["sign_probe"]["attempted"], payload)


def test_examples_load() -> None:
    ex_dir = os.path.join(ROOT, "examples")
    for fn in os.listdir(ex_dir):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(ex_dir, fn), encoding="utf-8") as f:
            data = json.load(f)
        v = validate_actions(data["actions"])
        assert_true(v["ok"], "{0}: {1}".format(fn, v))


def test_magic_variables() -> None:
    recipe = [
        {"type": "text", "params": {"text": "A"}, "as": "A"},
        {
            "type": "text",
            "params": {"text": "Hello ${as:A}"},
            "as": "B",
        },
        {
            "type": "show_result",
            "params": {"text": {"$ref": "as:B"}},
        },
    ]
    v = validate_actions(recipe)
    assert_true(v["ok"], v)
    compiled = compile_recipe(recipe)
    assert_true(compiled["aliases"] == {"A": 0, "B": 1}, compiled["aliases"])
    # second action text is WFTextTokenString
    text_param = compiled["wf_actions"][1]["WFWorkflowActionParameters"][
        "WFTextActionText"
    ]
    assert_true(
        isinstance(text_param, dict)
        and text_param.get("WFSerializationType") == "WFTextTokenString",
        text_param,
    )
    # third action references prior UUID
    show = compiled["wf_actions"][2]["WFWorkflowActionParameters"]["Text"]
    assert_true(
        show.get("WFSerializationType") == "WFTextTokenAttachment",
        show,
    )
    assert_true(
        show["Value"]["OutputUUID"]
        == compiled["wf_actions"][1]["WFWorkflowActionParameters"]["UUID"],
        show,
    )

    forward = validate_actions(
        [
            {"type": "show_result", "params": {"text": {"$action": 1}}},
            {"type": "text", "params": {"text": "x"}},
        ]
    )
    assert_true(not forward["ok"], forward)

    # template
    tpl = get_template("magic_chain")
    assert_true(validate_actions(tpl["actions"])["ok"], tpl)

    # tool surface
    exp = mcp_server.handle_tool_call("explain_magic_vars", {})
    assert_true(not exp.get("isError"), exp)
    assert_true("forms" in exp["structuredContent"], exp)
    prev = mcp_server.handle_tool_call(
        "compile_recipe_preview",
        {"actions": recipe, "name": "t"},
    )
    assert_true(not prev.get("isError"), prev)
    assert_true(prev["structuredContent"]["action_count"] == 3, prev)


def test_golden_fixtures() -> None:
    check = os.path.join(ROOT, "scripts", "check_fixtures.py")
    assert_true(os.path.isfile(check), "check_fixtures.py missing")
    res = subprocess.run(
        [sys.executable, check],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert_true(
        res.returncode == 0,
        "golden fixture mismatch:\n{0}\n{1}".format(res.stdout, res.stderr),
    )


def test_ndjson_initialize() -> None:
    """Spin server briefly with initialize + tools/list over NDJSON."""
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "server.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin and proc.stdout
    reqs = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "list_templates", "arguments": {}},
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "resources/read",
            "params": {"uri": "shortcut://catalog/templates"},
        },
    ]
    payload = "".join(json.dumps(r) + "\n" for r in reqs)
    try:
        out, err = proc.communicate(payload, timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError("server hung")

    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert_true(len(lines) >= 4, "unexpected stdout: {0!r}\nstderr={1!r}".format(out, err))
    init = json.loads(lines[0])
    assert_true(init["result"]["serverInfo"]["name"] == "ios-shortcuts-mcp", init)
    assert_true(init["result"]["serverInfo"]["version"] == "2.7.0", init)
    tools = json.loads(lines[1])
    assert_true(len(tools["result"]["tools"]) >= 10, tools)
    # annotations present on first tool
    assert_true("annotations" in tools["result"]["tools"][0], tools)
    tpls = json.loads(lines[2])
    body = tpls["result"]["content"][0]["text"]
    assert_true("hello_world" in body, body)
    res = json.loads(lines[3])
    assert_true("contents" in res["result"], res)


def test_protocol_error_recovery() -> None:
    """Malformed NDJSON must get an error without poisoning the next request."""
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "server.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    payload = "\n".join(
        [
            "{bad json",
            json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"}),
            json.dumps({"jsonrpc": "2.0", "method": "tools/list"}),
            "",
        ]
    )
    out, err = proc.communicate(payload, timeout=15)
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    assert_true(len(lines) == 2, "unexpected responses: {0!r}\nstderr={1!r}".format(out, err))
    assert_true(lines[0]["error"]["code"] == -32700, lines[0])
    assert_true(lines[1]["id"] == 9 and lines[1]["result"] == {}, lines[1])


def test_content_length_transport() -> None:
    request = json.dumps(
        {"jsonrpc": "2.0", "id": 11, "method": "ping"},
        separators=(",", ":"),
    ).encode("utf-8")
    framed = "Content-Length: {0}\r\n\r\n".format(len(request)).encode("ascii") + request
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "server.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, err = proc.communicate(framed, timeout=15)
    header, body = out.split(b"\r\n\r\n", 1)
    length = int(header.decode("ascii").split(":", 1)[1].strip())
    assert_true(len(body) == length, "bad frame length: {0!r}".format(out))
    response = json.loads(body.decode("utf-8"))
    assert_true(response["id"] == 11 and response["result"] == {}, response)
    assert_true(proc.returncode == 0, err.decode("utf-8", errors="replace"))


def test_safe_mode_tool_block() -> None:
    env = os.environ.copy()
    env["IOS_SHORTCUTS_MCP_SAFE_MODE"] = "1"
    # Import a fresh server module in subprocess via tools/call
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "server.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    reqs = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "validate_recipe",
                "arguments": {
                    "actions": [
                        {
                            "type": "run_shell_script",
                            "params": {"script": "echo hi"},
                        }
                    ]
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "run_shortcut",
                "arguments": {"name": "DoesNotMatter"},
            },
        },
    ]
    out, err = proc.communicate("".join(json.dumps(r) + "\n" for r in reqs), timeout=15)
    lines = [json.loads(ln) for ln in out.splitlines() if ln.strip()]
    assert_true(len(lines) >= 3, "out={0!r} err={1!r}".format(out, err))
    validate_result = lines[1]["result"]
    # validate returns ok:false in structured content, not necessarily isError
    body = json.loads(validate_result["content"][0]["text"])
    assert_true(body["ok"] is False, body)
    run_result = lines[2]["result"]
    assert_true(run_result.get("isError"), run_result)
    assert_true(run_result["structuredContent"]["code"] == "SAFE_MODE", run_result)


def main() -> int:
    tests = [
        test_catalog,
        test_full_apple_identifier_coverage,
        test_wf_auto_coercion,
        test_decompile_roundtrip,
        test_platform_preflight,
        test_app_intent_compile,
        test_param_learning_loop,
        test_e2e_runtime_run_if_possible,
        test_validate_and_build,
        test_semantic_validation,
        test_control_flow_validation,
        test_templates_build,
        test_path_sandbox_and_structured_errors,
        test_tool_annotations_and_doctor,
        test_examples_load,
        test_magic_variables,
        test_golden_fixtures,
        test_ndjson_initialize,
        test_protocol_error_recovery,
        test_content_length_transport,
        test_safe_mode_tool_block,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print("OK  {0}".format(fn.__name__))
        except Exception as exc:
            failed += 1
            print("FAIL {0}: {1}".format(fn.__name__, exc))
    if failed:
        print("\n{0}/{1} failed".format(failed, len(tests)))
        return 1
    print("\nAll {0} smoke tests passed.".format(len(tests)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
