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

from shortcut_builder import (  # noqa: E402
    build_shortcut_plist,
    get_template,
    list_supported_actions,
    list_templates,
    validate_actions,
)
import server as mcp_server  # noqa: E402


def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_catalog() -> None:
    actions = list_supported_actions()
    assert_true(len(actions) >= 40, f"expected rich action catalog, got {len(actions)}")
    templates = list_templates()
    assert_true(len(templates) >= 5, "expected several templates")
    tpl = get_template("hello_world")
    assert_true(len(tpl["actions"]) >= 1, "hello_world empty")


def test_validate_and_build() -> None:
    recipe = [
        {"type": "comment", "params": {"text": "smoke"}},
        {"type": "set_volume", "params": {"volume": 0.5}},
        {"type": "show_notification", "params": {"title": "Smoke", "body": "ok"}},
        {"type": "delay", "params": {"seconds": 0.1}},
    ]
    v = validate_actions(recipe)
    assert_true(v["ok"], f"validate failed: {v}")

    bad = validate_actions([{"type": "not_a_real_action_xyz", "params": {}}])
    assert_true(not bad["ok"], "expected unknown action to fail validation")

    with tempfile.TemporaryDirectory() as td:
        path = build_shortcut_plist(recipe, "SmokeTest", td, sign=True)
        assert_true(os.path.isfile(path), f"missing build output {path}")
        assert_true(os.path.getsize(path) > 50, "output too small")

        # inspect via tool handler
        result = mcp_server.handle_tool_call("inspect_shortcut", {"path": path})
        assert_true(not result.get("isError"), result)
        text = result["content"][0]["text"]
        payload = json.loads(text)
        assert_true(payload["size_bytes"] > 0, "inspect size")


def test_templates_build() -> None:
    with tempfile.TemporaryDirectory() as td:
        for name in ("hello_world", "volume_max_and_notify", "shell_echo"):
            tpl = get_template(name)
            path = build_shortcut_plist(tpl["actions"], f"T_{name}", td, sign=False)
            assert_true(path.endswith("_raw.shortcut"), path)
            assert_true(os.path.isfile(path), path)


def test_tool_list_and_doctor() -> None:
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
        assert_true(required in names, f"missing tool {required}")

    doc = mcp_server.handle_tool_call("doctor", {})
    assert_true(not doc.get("isError"), doc)
    payload = json.loads(doc["content"][0]["text"])
    assert_true(payload["version"] == mcp_server.SERVER_VERSION, payload)
    assert_true(payload["action_types"] >= 40, payload)


def test_examples_load() -> None:
    ex_dir = os.path.join(ROOT, "examples")
    for fn in os.listdir(ex_dir):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(ex_dir, fn), encoding="utf-8") as f:
            data = json.load(f)
        v = validate_actions(data["actions"])
        assert_true(v["ok"], f"{fn}: {v}")


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
    ]
    payload = "".join(json.dumps(r) + "\n" for r in reqs)
    try:
        out, err = proc.communicate(payload, timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError("server hung")

    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert_true(len(lines) >= 3, f"unexpected stdout: {out!r}\nstderr={err!r}")
    init = json.loads(lines[0])
    assert_true(init["result"]["serverInfo"]["name"] == "ios-shortcuts-mcp", init)
    tools = json.loads(lines[1])
    assert_true(len(tools["result"]["tools"]) >= 10, tools)
    tpls = json.loads(lines[2])
    body = tpls["result"]["content"][0]["text"]
    assert_true("hello_world" in body, body)


def main() -> int:
    tests = [
        test_catalog,
        test_validate_and_build,
        test_templates_build,
        test_tool_list_and_doctor,
        test_examples_load,
        test_ndjson_initialize,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"OK  {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    if failed:
        print(f"\n{failed}/{len(tests)} failed")
        return 1
    print(f"\nAll {len(tests)} smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
