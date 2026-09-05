#!/usr/bin/env python3
"""Static HTTP observe — search follow-up without Chromium."""
from __future__ import annotations

import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import http_observe  # noqa: E402


EXAMPLE_HTML = """<!DOCTYPE html>
<html><head><title>Example Domain</title></head>
<body>
<h1>Example Domain</h1>
<p>This domain is for use in illustrative examples in documents.</p>
<p><a href="https://iana.org/domains/example">Learn more</a></p>
<p><a href="javascript:alert(1)">Ignore</a></p>
<button>Accept</button>
<input type="search" name="q" placeholder="Search the site">
</body></html>
"""


def test_parse_title_links_and_drop_js():
    title = http_observe.parse_title(EXAMPLE_HTML)
    links = http_observe.parse_links(EXAMPLE_HTML, "https://example.com/")
    assert title == "Example Domain"
    assert any(l["href"].startswith("https://iana.org/") for l in links)
    assert all("javascript" not in l["href"] for l in links)


def test_observe_html_tree_and_markdown():
    md = http_observe.observe_html(EXAMPLE_HTML, url="https://example.com/", dump="markdown")
    assert md["ok"] is True
    assert md["engine"] == "http"
    assert md["headless"] is True
    assert md["pixels"] is False
    assert md["js"] is False
    assert md["title"] == "Example Domain"
    assert "Learn more" in md["content"]

    tree = http_observe.observe_html(
        EXAMPLE_HTML, url="https://example.com/", dump="semantic_tree_text"
    )
    assert "link 'Learn more'" in tree["content"]
    assert "button 'Accept'" in tree["content"]
    assert "searchbox 'Search the site'" in tree["content"]


def test_http_fetch_uses_light_fetch(monkeypatch):
    def fake_light(url, **_kw):
        return {
            "ok": True,
            "url": url,
            "http_status": 200,
            "html": EXAMPLE_HTML,
            "ms": 3,
        }

    monkeypatch.setattr(http_observe.wick_search, "light_fetch", fake_light)
    out = http_observe.http_fetch("https://example.com/", dump="markdown")
    assert out["ok"] is True
    assert out["engine"] == "http"
    assert out["title"] == "Example Domain"


def test_observe_fetch_http_fallback(monkeypatch):
    from importlib.machinery import SourceFileLoader
    import importlib.util

    wick_path = Path(__file__).resolve().parents[1] / "bin" / "wick"
    loader = SourceFileLoader("wick_cli_http_obs", str(wick_path))
    spec = importlib.util.spec_from_loader("wick_cli_http_obs", loader)
    assert spec is not None and spec.loader is not None
    wick = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wick)

    monkeypatch.setattr(wick, "find_playwright_python", lambda: None)
    monkeypatch.setenv("WICK_OBSERVE", "http")

    def fake_http(url, dump="markdown", max_chars=12000):
        return {
            "ok": True,
            "engine": "http",
            "url": url,
            "dump": dump,
            "content": "# Example Domain\n",
            "title": "Example Domain",
            "http_ok": True,
            "http_status": 200,
        }

    monkeypatch.setattr(wick.wick_http_observe, "http_fetch", fake_http)
    out = wick.observe_fetch("https://example.com/", dump="markdown")
    assert out["ok"] is True
    assert out["engine"] == "http"
