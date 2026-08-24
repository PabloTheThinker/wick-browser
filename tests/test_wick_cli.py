#!/usr/bin/env python3
"""Tests for CLI edge cases in bin/wick."""
from __future__ import annotations

import importlib.util
import json
import sys
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


def test_lp_fetch_uses_chromium_when_engine_missing(monkeypatch):
    monkeypatch.delenv("WICK_ENGINE", raising=False)
    monkeypatch.setattr(wick, "find_lightpanda", lambda: None)

    def no_chrome(*_a, **_k):
        return {
            "ok": False,
            "product": "wick",
            "error": "observe_engine_missing",
            "hint": "wick install-engine or wick start --engine chromium",
        }

    monkeypatch.setattr(wick, "chrome_observe_fetch", no_chrome)
    result = wick.lp_fetch("https://example.com/")
    assert result["ok"] is False
    assert result["error"] == "observe_engine_missing"
    assert result["product"] == "wick"


def test_lp_fetch_rejects_javascript_url(monkeypatch):
    monkeypatch.setattr(wick, "find_lightpanda", lambda: Path("/usr/bin/true"))
    result = wick.lp_fetch("javascript:alert(1)")
    assert result["ok"] is False
    assert result["error"] == "dangerous_url"


def test_lp_fetch_rejects_private_url_when_blocked(monkeypatch):
    monkeypatch.setattr(wick, "find_lightpanda", lambda: Path("/usr/bin/true"))
    monkeypatch.delenv("WICK_ALLOW_PRIVATE", raising=False)
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

    monkeypatch.setenv("WICK_ENGINE", "lightpanda")
    monkeypatch.setattr(wick, "find_lightpanda", lambda: Path("/usr/bin/true"))
    monkeypatch.setattr(wick, "lp_fetch", fake_fetch)
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

    monkeypatch.setenv("WICK_ENGINE", "lightpanda")
    monkeypatch.setattr(wick, "find_lightpanda", lambda: Path("/usr/bin/true"))
    monkeypatch.setattr(wick, "lp_fetch", fake_fetch)
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
    monkeypatch.delenv("WICK_ENGINE", raising=False)
    out = wick.snap_many_payload(
        ["https://example.com/", "https://example.com/about"],
        profile="micro",
        concurrency=2,
    )
    assert out["ok"] is True
    assert out["count"] == 2
    assert out["concurrency"] == 1  # Chromium standalone serializes snap-many
    assert out["mode"] == "agent_snap_many"


def test_gather_snap_chromium_fallback_is_single_observe(monkeypatch):
    calls: list[str] = []

    def fake_observe(url, dump="markdown", max_chars=12000, wait_ms=2000):
        calls.append(dump)
        return {
            "ok": True,
            "url": url,
            "title": "Amazon.com : usb-c cable",
            "content": "# Amazon.com : usb-c cable\n\n[Anker USB C](https://www.amazon.com/dp/example)",
            "excerpt": "1-16 of over 70,000 results for usb-c cable Anker USB C to USB C Cable $9.99",
            "links": [
                {
                    "text": "Anker USB C to USB C Cable",
                    "href": "https://www.amazon.com/dp/example",
                }
            ],
            "elements": [
                {
                    "role": "searchbox",
                    "name": "Search Amazon",
                    "hint": 'role=textbox[name="Search Amazon"]',
                    "interactive": True,
                }
            ],
            "http_ok": True,
            "http_status": 200,
            "engine": "chromium",
            "ms": 20,
            "chars": 80,
        }

    monkeypatch.delenv("WICK_ENGINE", raising=False)
    monkeypatch.setattr(wick, "find_lightpanda", lambda: Path("/usr/bin/true"))
    monkeypatch.setattr(wick, "chrome_observe_fetch", fake_observe)
    monkeypatch.setattr(wick, "wick_observe_cache", None)
    out = wick._gather_snap("https://www.amazon.com/s?k=usb-c+cable")
    assert calls == ["markdown"]
    assert out["ok"] is True
    assert out["engine"] == "chromium"
    assert out.get("fallback") in (None, "")
    assert out["timing"]["parallel"] is False
    assert out["link_count"] >= 1
    assert "Anker" in (out.get("excerpt") or "")
    assert out["elements"][0]["hint"] == 'role=searchbox[name="Search Amazon"]'


def test_chrome_observe_fetch_here_without_chrome(monkeypatch):
    monkeypatch.setattr(wick, "chrome_up", lambda: False)
    out = wick.chrome_observe_fetch("here")
    assert out["ok"] is False
    assert out["error"] == "no_current_page"
    blank = wick.chrome_observe_fetch("")
    assert blank["error"] == "no_current_page"


def test_gather_snap_here_skips_cache_and_passes_reused(monkeypatch):
    seen: list[str] = []

    def fake_observe(url, dump="markdown", max_chars=12000, wait_ms=2000):
        seen.append(url)
        return {
            "ok": True,
            "url": "https://example.com/",
            "title": "Example Domain",
            "content": "# Example Domain\n\nHello",
            "excerpt": "Hello",
            "links": [],
            "elements": [],
            "http_ok": True,
            "http_status": 200,
            "engine": "chromium",
            "ms": 8,
            "chars": 20,
            "reused": True,
        }

    monkeypatch.delenv("WICK_ENGINE", raising=False)
    monkeypatch.setattr(wick, "chrome_observe_fetch", fake_observe)
    monkeypatch.setattr(wick, "wick_observe_cache", None)
    out = wick._gather_snap("here", profile="default")
    assert seen == ["here"]
    assert out["ok"] is True
    assert out["reused"] is True
    assert out["url"] == "https://example.com/"
    payload = wick.snap_payload("here")
    assert payload["ok"] is True
    assert payload.get("reused") is True
    assert "here" in (payload.get("hint") or "").lower() or "current" in (payload.get("hint") or "").lower()


def test_rpc_snap_accepts_omitted_url(monkeypatch):
    monkeypatch.setattr(
        wick,
        "snap_payload",
        lambda url, **_kw: {"ok": True, "url": url or "https://example.com/", "reused": True},
    )
    handlers = wick._rpc_handlers()
    out = handlers["snap"]({})
    assert out["ok"] is True
    skill = handlers["skill"]({})
    assert skill["mode"] == "agent_skill"


def test_chrome_launch_mode_default_is_headless(monkeypatch):
    monkeypatch.delenv("WICK_HEADED", raising=False)
    monkeypatch.delenv("WICK_HEADLESS", raising=False)
    assert wick.chrome_launch_mode() == ("1", "0")
    assert wick.chrome_launch_mode(headed=False, xvfb=False) == ("1", "0")


def test_chrome_launch_mode_xvfb_wins_over_headed(monkeypatch):
    monkeypatch.setenv("WICK_HEADED", "1")
    monkeypatch.setenv("WICK_HEADLESS", "0")
    assert wick.chrome_launch_mode(xvfb=True, headed=True) == ("0", "1")


def test_chrome_launch_mode_headed_env_uses_current_display(monkeypatch):
    monkeypatch.setenv("WICK_HEADED", "1")
    monkeypatch.delenv("WICK_HEADLESS", raising=False)
    monkeypatch.setenv("DISPLAY", ":1")
    assert wick.chrome_launch_mode() == ("0", "0")


def test_chrome_launch_mode_headless_off_is_headed(monkeypatch):
    monkeypatch.delenv("WICK_HEADED", raising=False)
    monkeypatch.setenv("WICK_HEADLESS", "0")
    assert wick.chrome_launch_mode() == ("0", "0")


def test_chrome_launch_mode_headed_flag(monkeypatch):
    monkeypatch.delenv("WICK_HEADED", raising=False)
    monkeypatch.delenv("WICK_HEADLESS", raising=False)
    assert wick.chrome_launch_mode(headed=True) == ("0", "0")


def test_lp_fetch_uses_chromium_even_if_lightpanda_binary_exists(monkeypatch):
    monkeypatch.delenv("WICK_ENGINE", raising=False)
    monkeypatch.setattr(wick, "find_lightpanda", lambda: Path("/usr/bin/true"))

    def fake_observe(url, dump="markdown", max_chars=12000, wait_ms=2000):
        return {
            "ok": True,
            "url": url,
            "title": "Example Domain",
            "content": "# Example Domain\n\n[More information](https://example.com/info)",
            "http_ok": True,
            "http_status": 200,
            "engine": "chromium",
            "ms": 12,
            "chars": 40,
        }

    monkeypatch.setattr(wick, "chrome_observe_fetch", fake_observe)
    out = wick.lp_fetch("https://example.com/", dump="markdown")
    assert out["ok"] is True
    assert out["engine"] == "chromium"
    assert "fallback" not in out or not out.get("fallback")
    assert "Example Domain" in (out.get("content") or "")


def test_resolve_engine_is_chromium_by_default(monkeypatch):
    monkeypatch.delenv("WICK_ENGINE", raising=False)
    monkeypatch.setattr(wick, "find_lightpanda", lambda: Path("/usr/bin/true"))
    assert wick.resolve_engine(None) == "chromium"
    assert wick.resolve_engine("auto") == "chromium"
    assert wick.observe_uses_lightpanda() is False
    monkeypatch.setenv("WICK_ENGINE", "lightpanda")
    assert wick.observe_uses_lightpanda() is True


def test_rpc_challenge_handler(monkeypatch):
    handlers = wick._rpc_handlers()
    assert "challenge" in handlers

    def fake_probe(url):
        return {
            "ok": True,
            "product": "wick",
            "mode": "observe",
            "login": False,
            "solves": False,
            "url": url,
            "found": False,
        }

    monkeypatch.setattr(wick.wick_challenge, "probe", fake_probe)
    out = handlers["challenge"]({"url": "https://example.com/"})
    assert out.get("login") is False
    assert out.get("solves") is False
    assert out.get("mode") == "observe"


def test_act_login_cli_forwards_after_challenge(monkeypatch):
    seen: dict = {}

    def fake_call(cmd, **_kw):
        seen["cmd"] = cmd
        return 0

    monkeypatch.setattr(wick, "chrome_up", lambda: True)
    monkeypatch.setattr(wick.subprocess, "call", fake_call)
    ns = type(
        "NS",
        (),
        {
            "action": "login",
            "rest": ["http://127.0.0.1:8765/challenge-clear.html"],
            "after_challenge": 4000,
            "no_submit": False,
            "expect_url_fragment": None,
            "expect_element": None,
        },
    )()
    assert wick.cmd_act(ns) == 0
    assert seen["cmd"][-4:] == [
        "login",
        "http://127.0.0.1:8765/challenge-clear.html",
        "--after-challenge",
        "4000",
    ]


def test_act_parser_accepts_after_challenge_and_no_submit(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "wick",
            "act",
            "login",
            "http://127.0.0.1/x",
            "--after-challenge",
            "5000",
            "--no-submit",
        ],
    )
    captured = {}

    def fake_act(args):
        captured["after"] = args.after_challenge
        captured["no_submit"] = args.no_submit
        captured["rest"] = args.rest
        return 0

    monkeypatch.setattr(wick, "cmd_act", fake_act)
    assert wick.main() == 0
    assert captured["after"] == 5000
    assert captured["no_submit"] is True
    assert captured["rest"] == ["http://127.0.0.1/x"]


def test_chrome_launch_mode_display_alone_stays_headless(monkeypatch):
    monkeypatch.delenv("WICK_HEADED", raising=False)
    monkeypatch.delenv("WICK_HEADLESS", raising=False)
    monkeypatch.setenv("DISPLAY", ":1")
    assert wick.chrome_launch_mode() == ("1", "0")


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
