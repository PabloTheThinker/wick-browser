#!/usr/bin/env python3
"""Agent skill contract: purpose, loop, and harness export."""
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


agent_skill = _load_lib("agent_skill")
tools_schema = _load_lib("tools_schema")
mcp_stdio = _load_lib("mcp_stdio")


def test_skill_payload_shape():
    out = agent_skill.skill_payload("0.9.0")
    assert out["ok"] is True
    assert out["product"] == "wick"
    assert out["mode"] == "agent_skill"
    assert "standalone" in out["purpose"].lower()
    assert "chromium" in out["purpose"].lower()
    assert isinstance(out["loop"], list) and len(out["loop"]) >= 3
    assert any("snap" in step.lower() for step in out["loop"])
    assert any("read" in step.lower() for step in out["loop"])
    assert any("here" in step.lower() or "omit" in step.lower() for step in out["loop"])
    rules = " ".join(out["rules"]).lower()
    assert "untrusted" in rules
    assert "secret" in rules
    assert "searchbox" in rules or "press enter" in rules
    assert "cu" in rules
    dump = json.dumps(out).lower()
    assert "2captcha" not in dump
    assert "solver" not in dump
    assert "password" not in dump or "never" in dump


def test_tools_export_includes_skill_and_optional_url():
    out = tools_schema.tools_export("0.9.0")
    assert out["purpose"]
    assert out["loop"]
    names = {t["function"]["name"] for t in out["tools"]}
    assert "wick_skill" in names
    snap = next(t for t in out["tools"] if t["function"]["name"] == "wick_snap")
    required = snap["function"]["parameters"].get("required") or []
    assert "url" not in required
    desc = snap["function"]["description"].lower()
    assert "here" in desc or "omit" in desc or "current" in desc


def test_mcp_lists_skill_and_optional_snap_url():
    names = {t["name"] for t in mcp_stdio.mcp_tools()}
    assert "skill" in names
    snap = next(t for t in mcp_stdio.mcp_tools() if t["name"] == "snap")
    required = snap["inputSchema"].get("required") or []
    assert "url" not in required
    resp = mcp_stdio.handle_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        handlers={"skill": lambda _a: agent_skill.skill_payload("0.9.0")},
        version="0.9.0",
    )
    instructions = resp["result"]["instructions"].lower()
    assert "snap" in instructions
    assert "untrusted" in instructions


def test_wick_skill_cli():
    proc = subprocess.run(
        [sys.executable, str(WICK), "skill"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["ok"] is True
    assert out["mode"] == "agent_skill"
    assert out["loop"]
