#!/usr/bin/env python3
"""CLI catalog — agents run the same Wick surface from the shell."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WICK = ROOT / "bin" / "wick"
_LIB = ROOT / "lib"


def _load_lib(name: str):
    path = _LIB / f"{name}.py"
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cli_catalog = _load_lib("cli_catalog")
tools_schema = _load_lib("tools_schema")
capability = _load_lib("capability")


def _wick(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WICK), *args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )


def test_argv_from_call_matches_cli():
    assert cli_catalog.argv_from_call("snap", {"url": "https://example.com/", "fast": True}) == [
        "wick",
        "snap",
        "https://example.com/",
        "--fast",
    ]
    assert cli_catalog.argv_from_call("wick_read", {"here": True, "q": "rfc 2606"}) == [
        "wick",
        "read",
        "--here",
        "--q",
        "rfc 2606",
    ]
    assert cli_catalog.argv_from_call(
        "act",
        {"action": "click", "rest": ['role=link[name="More information"]']},
    ) == ["wick", "act", "click", 'role=link[name="More information"]']
    assert cli_catalog.argv_from_call("vault", {"action": "suggest", "url": "https://example.com/"}) == [
        "wick",
        "vault",
        "suggest",
        "--url",
        "https://example.com/",
    ]
    assert cli_catalog.argv_from_call("snap_many", {"urls": ["https://example.com/", "https://example.org/"]}) == [
        "wick",
        "snap-many",
        "https://example.com/",
        "https://example.org/",
    ]


def test_commands_export_covers_tools():
    out = cli_catalog.commands_export("0.9.0")
    assert out["ok"] is True
    assert out["mode"] == "agent_cli"
    assert out["schema"] == "wick_cli_v1"
    assert "cli" in (out.get("hint") or "").lower() or "shell" in (out.get("hint") or "").lower()
    names = {c["name"] for c in out["commands"]}
    for expected in (
        "skill",
        "commands",
        "call",
        "snap",
        "read",
        "plan",
        "ask",
        "act",
        "session",
        "vault",
        "challenge",
        "snap-many",
    ):
        assert expected in names, expected
    tools = {t["function"]["name"] for t in tools_schema.WICK_TOOLS}
    cli_by_tool = {c.get("tool") for c in out["commands"] if c.get("tool")}
    missing = tools - cli_by_tool
    assert not missing, missing
    snap = next(c for c in out["commands"] if c["name"] == "snap")
    assert snap["cli"].startswith("wick snap")
    assert snap["example"][0] == "wick"


def test_tools_export_includes_cli_map():
    out = tools_schema.tools_export("0.9.0")
    cli = out.get("cli") or {}
    assert cli.get("wick_snap", "").startswith("wick snap")
    assert cli.get("wick_act", "").startswith("wick act")
    hint = (out.get("hint") or "").lower()
    assert "wick commands" in hint or "cli" in hint


def test_observe_only_allows_commands_and_call():
    import os

    os.environ["WICK_PROFILE"] = "observe-only"
    try:
        assert capability.deny("commands") is None
        assert capability.deny("call") is None
        assert capability.deny("help") is None
    finally:
        os.environ.pop("WICK_PROFILE", None)


def test_wick_no_args_prints_catalog():
    proc = _wick()
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["ok"] is True
    assert out["mode"] == "agent_cli"
    assert out["commands"]


def test_wick_commands_cli():
    proc = _wick("commands")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["schema"] == "wick_cli_v1"
    assert any(c["name"] == "call" for c in out["commands"])


def test_wick_unknown_cmd_is_json_soft():
    proc = _wick("definitely-not-a-command")
    assert proc.returncode != 0
    out = json.loads(proc.stdout)
    assert out["ok"] is False
    assert out.get("soft") is True
    assert "commands" in json.dumps(out).lower()


def test_wick_call_version_and_unknown():
    proc = _wick("call", "version")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["ok"] is True
    assert out.get("version") or out.get("product") == "wick"

    snap = _wick("call", "skill", "{}")
    assert snap.returncode == 0, snap.stderr
    skill = json.loads(snap.stdout)
    assert skill["mode"] == "agent_skill"

    bad = _wick("call", "nope")
    assert bad.returncode != 0
    err = json.loads(bad.stdout)
    assert err["ok"] is False
    assert err.get("soft") is True
    assert err.get("error") == "unknown_cmd"
