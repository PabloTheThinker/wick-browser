#!/usr/bin/env python3
"""Headless agent search — parse SERP, unwrap DDG redirects, no pixels."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
_FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import search  # noqa: E402


def test_unwrap_ddg_uddg():
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F&amp;rut=abc"
    assert search.unwrap_result_url(href) == "https://example.com/"


def test_parse_ddg_html_fixture():
    html = (_FIX / "ddg-html.html").read_text(encoding="utf-8")
    rows = search.parse_serp_html(html)
    assert len(rows) == 2
    assert rows[0]["url"] == "https://example.com/"
    assert rows[0]["title"] == "Example Domain"
    assert "illustrative" in rows[0]["snippet"]
    assert rows[1]["url"] == "https://en.wikipedia.org/wiki/Example.com"
    assert all("javascript" not in r["url"] for r in rows)


def test_parse_ddg_lite_classes():
    html = """
    <a rel="nofollow" href="//duckduckgo.com/l/?uddg=http%3A%2F%2Fwww.example.com%2F" class='result-link'>Example Domain</a>
    <td class='result-snippet'>Example Domain is reserved.</td>
    """
    rows = search.parse_serp_html(html)
    assert rows[0]["url"] == "http://www.example.com/"
    assert rows[0]["title"] == "Example Domain"


def test_pack_search_is_headless_and_has_cmds():
    html = (_FIX / "ddg-html.html").read_text(encoding="utf-8")
    out = search.run_search("example domain", html=html, via="http", url="https://html.duckduckgo.com/html/?q=example+domain")
    assert out["ok"] is True
    assert out["mode"] == "agent_search"
    assert out["headless"] is True
    assert out["pixels"] is False
    assert out["count"] == 2
    assert out["results"][0]["cmd"].startswith("wick snap https://example.com/")
    assert out["suggestions"][0]["action"] == "snap"
    assert out["untrusted_content"] is True


def test_wiki_opensearch():
    payload = [
        "example",
        ["Example.com"],
        ["Reserved domain"],
        ["https://en.wikipedia.org/wiki/Example.com"],
    ]
    out = search.run_search("example", engine="wiki", wiki_json=payload)
    assert out["ok"] is True
    assert out["engine"] == "wiki"
    assert out["results"][0]["url"] == "https://en.wikipedia.org/wiki/Example.com"


def test_missing_query():
    out = search.run_search("   ")
    assert out["ok"] is False
    assert out["error"] == "missing_query"


def test_search_url_engines():
    assert "html.duckduckgo.com" in search.search_url("example domain")
    assert "lite.duckduckgo.com" in search.search_url("x", "ddg_lite")
    assert "wikipedia.org" in search.search_url("x", "wiki")


def test_challenge_marker():
    assert search.looks_like_challenge("... anomaly.js challenge ...")
    assert not search.looks_like_challenge("<a class='result__a' href='https://example.com/'>ok</a>")


def test_search_payload_uses_parser(monkeypatch):
    from importlib.machinery import SourceFileLoader
    import importlib.util

    wick_path = Path(__file__).resolve().parents[1] / "bin" / "wick"
    loader = SourceFileLoader("wick_cli_search", str(wick_path))
    spec = importlib.util.spec_from_loader("wick_cli_search", loader)
    assert spec is not None and spec.loader is not None
    wick = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wick)

    html = (_FIX / "ddg-html.html").read_text(encoding="utf-8")
    original = wick.wick_search.run_search

    def fake_run(q, **kw):
        return original(q, html=html, via="http", engine=kw.get("engine"), limit=kw.get("limit") or 8)

    monkeypatch.setattr(wick.wick_search, "run_search", fake_run)
    out = wick.search_payload("example domain")
    assert out["ok"] is True
    assert out["count"] >= 1
    assert out["pixels"] is False


def test_wiki_json_roundtrip_in_pack():
    raw = json.dumps(["q", ["T"], ["S"], ["https://en.wikipedia.org/wiki/T"]])
    # simulate light_fetch body
    out = search.parse_wiki_opensearch(json.loads(raw))
    assert out[0]["title"] == "T"
