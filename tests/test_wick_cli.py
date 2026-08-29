#!/usr/bin/env python3
"""Tests for CLI edge cases in bin/wick."""
from __future__ import annotations

import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path


def _load_wick_module():
    wick_path = Path(__file__).resolve().parents[1] / "bin" / "wick"
    loader = SourceFileLoader("wick_cli", str(wick_path))
    spec = importlib.util.spec_from_loader("wick_cli", loader)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wick = _load_wick_module()


def test_lp_fetch_rejects_blank_url():
    result = wick.lp_fetch("   ")
    assert result["ok"] is False
    assert result["error"] == "no_url"
    assert result["product"] == "wick"


def test_lp_fetch_reports_missing_lightpanda(monkeypatch):
    monkeypatch.setattr(wick, "find_lightpanda", lambda: None)
    result = wick.lp_fetch("https://example.com/")
    assert result["ok"] is False
    assert result["error"] == "lightpanda_not_found"
    assert result["product"] == "wick"


def test_lp_fetch_rejects_javascript_url(monkeypatch):
    monkeypatch.setattr(wick, "find_lightpanda", lambda: Path("/usr/bin/true"))
    result = wick.lp_fetch("javascript:alert(1)")
    assert result["ok"] is False
    assert result["error"] == "dangerous_url"


def test_lp_fetch_rejects_private_url_when_blocked(monkeypatch):
    monkeypatch.setattr(wick, "find_lightpanda", lambda: Path("/usr/bin/true"))
    result = wick.lp_fetch("http://127.0.0.1:8080/")
    assert result["ok"] is False
    assert result["error"] in ("private_url", "dangerous_url")


def test_lp_fetch_honors_allow_hosts(monkeypatch):
    monkeypatch.setattr(wick, "find_lightpanda", lambda: Path("/usr/bin/true"))
    monkeypatch.setenv("WICK_ALLOW_HOSTS", "example.com")
    denied = wick.lp_fetch("https://evil.test/")
    assert denied["ok"] is False
    assert denied["error"] == "host_not_allowed"


TREE = "1 document 'Example Domain'\n2 [i] link 'More information'\n3 heading 'Example Domain'\n"


def test_gather_snap_micro_skips_markdown(monkeypatch):
    calls: list[str] = []

    def fake_fetch(url, dump="markdown", **_kw):
        calls.append(dump)
        return {
            "ok": True,
            "content": TREE,
            "ms": 12,
            "chars": len(TREE),
            "url": url,
            "http_ok": True,
            "http_status": 200,
        }

    monkeypatch.setattr(wick, "observe_fetch", fake_fetch)
    monkeypatch.setattr(wick, "wick_observe_cache", None)
    out = wick._gather_snap("https://example.com/", profile="micro")
    assert out["ok"] is True
    assert out.get("tree_only") is True
    assert calls == ["semantic_tree_text"]
    assert out.get("title") == "Example Domain"
    assert out.get("element_count", 0) >= 1
    assert out["timing"]["profile"] == "micro"
    assert out["timing"]["parallel"] is False


def test_gather_snap_default_fetches_tree_and_markdown(monkeypatch):
    calls: list[str] = []

    def fake_fetch(url, dump="markdown", **_kw):
        calls.append(dump)
        body = TREE if dump == "semantic_tree_text" else "# Example Domain\n\n[More information](https://example.com/info)"
        return {
            "ok": True,
            "content": body,
            "ms": 15,
            "chars": len(body),
            "url": url,
            "http_ok": True,
            "http_status": 200,
        }

    monkeypatch.setattr(wick, "observe_fetch", fake_fetch)
    monkeypatch.setattr(wick, "wick_observe_cache", None)
    out = wick._gather_snap("https://example.com/", profile="default")
    assert out["ok"] is True
    assert set(calls) == {"semantic_tree_text", "markdown"}
    assert out["timing"]["parallel"] is True
    assert out["link_count"] >= 1
    assert "More information" in (out.get("excerpt") or "")


def test_snap_many_payload_bounded(monkeypatch):
    monkeypatch.setattr(
        wick,
        "snap_payload",
        lambda u, **_kw: {"ok": True, "url": u, "title": "Example Domain"},
    )
    out = wick.snap_many_payload(
        ["https://example.com/", "https://example.com/about"],
        profile="micro",
        concurrency=2,
    )
    assert out["ok"] is True
    assert out["count"] == 2
    assert out["concurrency"] == 2
    assert out["mode"] == "agent_snap_many"


def test_shields_policy_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WICK_HOME", str(tmp_path))
    monkeypatch.delenv("WICK_POLICY", raising=False)
    monkeypatch.delenv("WICK_ALLOW_HOSTS", raising=False)
    monkeypatch.delenv("WICK_BLOCK_HOSTS", raising=False)
    monkeypatch.delenv("WICK_PROFILE", raising=False)
    dest = tmp_path / "policy.json"
    dest.write_text('{"block_hosts": ["evil.test"], "profile": "safe-act"}\n', encoding="utf-8")
    monkeypatch.setenv("WICK_POLICY", str(dest))
    ns = type("NS", (), {"update": False, "json_only": True, "policy": True, "policy_check": None, "policy_write": None})()
    rc = wick.cmd_shields(ns)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert "evil.test" in out["policy"]["block_hosts"]
    assert out["policy"]["profile"] == "safe-act"


def test_playbook_open_uses_observe_fetch(tmp_path, monkeypatch, capsys):
    calls: list[str] = []

    def fake_obs(url, dump="markdown", **_kw):
        calls.append(dump)
        return {
            "ok": True,
            "product": "wick",
            "engine": "chromium",
            "url": url,
            "content": "# Example Domain\n",
            "http_ok": True,
        }

    monkeypatch.setattr(wick, "observe_fetch", fake_obs)
    script = tmp_path / "play.json"
    script.write_text(
        '[{"action":"open","url":"https://example.com/","max":2000},'
        '{"action":"snap_note","note":"soft"}]',
        encoding="utf-8",
    )
    rc = wick.cmd_run(type("NS", (), {"script": str(script)})())
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["results"][0]["result"]["engine"] == "chromium"
    assert out["results"][1].get("soft") is True
    assert calls == ["markdown"]
