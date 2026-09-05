#!/usr/bin/env python3
"""Unit tests for Chromium observe (no browser required)."""
from __future__ import annotations

import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path
_LIB = Path(__file__).resolve().parents[1] / "lib"
_WICK = Path(__file__).resolve().parents[1] / "bin" / "wick"


def _load(name: str, path: Path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


chrome_observe = _load("chrome_observe", _LIB / "chrome_observe.py")
elements = _load("elements", _LIB / "elements.py")
wick = _load("wick_cli", _WICK)

A11Y = {
    "role": "WebArea",
    "name": "Example Domain",
    "children": [
        {"role": "heading", "name": "Example Domain"},
        {"role": "link", "name": "More information"},
        {"role": "button", "name": "Go"},
    ],
}


def test_flatten_a11y_is_parseable_by_elements():
    tree = chrome_observe.flatten_a11y(A11Y)
    els = elements.parse_tree_text(tree)
    by_role = {e["role"]: e for e in els if e.get("name")}
    assert by_role["document"]["name"] == "Example Domain"
    assert by_role["link"]["name"] == "More information"
    assert by_role["link"]["interactive"] is True
    assert by_role["link"]["hint"] == 'role=link[name="More information"]'
    assert by_role["button"]["hint"] == 'role=button[name="Go"]'


def test_tree_from_elements_maps_anchor_tag():
    tree = chrome_observe.tree_from_elements(
        [{"role": "a", "name": "More information", "tag": "a"}],
        title="Example Domain",
    )
    els = elements.interactive_only(elements.parse_tree_text(tree))
    assert els[0]["role"] == "link"
    assert els[0]["hint"] == 'role=link[name="More information"]'


def test_merge_tree_adds_missing_interactive():
    thin = "1 document 'Example Domain'\n2 heading 'Example Domain'"
    merged = chrome_observe.merge_tree(
        thin,
        [{"role": "link", "name": "More information", "tag": "a"}],
        "Example Domain",
    )
    assert "link 'More information'" in merged
    assert merged.count("document") == 1


def test_build_markdown_has_heading_and_links():
    md = chrome_observe.build_markdown(
        "Example Domain",
        "This domain is for use in documentation examples.",
        [{"text": "More information", "href": "https://example.com/info"}],
    )
    assert md.startswith("# Example Domain")
    assert "[More information](https://example.com/info)" in md
    links = wick.extract_md_links(md)
    assert links[0]["href"] == "https://example.com/info"


def test_pack_observe_markdown_and_tree():
    packed = chrome_observe.pack_observe(
        url="https://example.com/",
        dump="markdown",
        title="Example Domain",
        text="Hello",
        html="<html></html>",
        links=[{"text": "More", "href": "https://example.com/x"}],
        tree_text="1 document 'Example Domain'",
        http_status=200,
        max_chars=4000,
        ms=12,
        wait_until="load",
        wait_ms=800,
    )
    assert packed["ok"] is True
    assert packed["engine"] == "chromium"
    assert packed["http_ok"] is True
    assert "# Example Domain" in packed["content"]

    tree = chrome_observe.pack_observe(
        url="https://example.com/",
        dump="semantic_tree_text",
        title="Example Domain",
        text="Hello",
        html="",
        links=[],
        tree_text="1 document 'Example Domain'\n2 [i] link 'More information'",
        http_status=200,
        max_chars=4000,
        ms=8,
        wait_until="domcontentloaded",
        wait_ms=800,
    )
    assert "link 'More information'" in tree["content"]


class _FakeA11y:
    def snapshot(self):
        return A11Y


class _FakeResp:
    status = 200


class _FakePage:
    url = "https://example.com/"
    accessibility = _FakeA11y()

    def goto(self, url, wait_until="load", timeout=60000):
        self.url = url
        return _FakeResp()

    def wait_for_timeout(self, _ms):
        return None

    def title(self):
        return "Example Domain"

    def inner_text(self, _sel):
        return "This domain is for use in illustrative examples."

    def content(self):
        return "<html><body>Example</body></html>"

    def evaluate(self, script):
        if "querySelectorAll('a[href]')" in script or "a[href]" in script:
            return [{"text": "More information", "href": "https://example.com/info"}]
        return [{"role": "link", "name": "More information", "tag": "a"}]


def test_collect_from_page_markdown():
    out = chrome_observe.collect_from_page(
        _FakePage(),
        "https://example.com/",
        dump="markdown",
        max_chars=4000,
        wait_until="domcontentloaded",
        wait_ms=0,
    )
    assert out["ok"] is True
    assert out["http_status"] == 200
    assert out["title"] == "Example Domain"
    assert "More information" in out["content"]


def test_observe_fetch_uses_chromium(monkeypatch):
    def fake_chrome(url, dump="markdown", **_kw):
        return {
            "ok": True,
            "product": "wick",
            "engine": "chromium",
            "url": url,
            "dump": dump,
            "content": "# Example Domain\n",
            "http_ok": True,
            "http_status": 200,
        }

    monkeypatch.setattr(wick, "chrome_fetch", fake_chrome)
    monkeypatch.setattr(wick, "find_playwright_python", lambda: Path("/tmp/fake-python"))
    monkeypatch.delenv("WICK_OBSERVE", raising=False)
    out = wick.observe_fetch("https://example.com/", dump="markdown")
    assert out["ok"] is True
    assert out["engine"] == "chromium"


def test_observe_fetch_rejects_blank_url():
    out = wick.observe_fetch("   ")
    assert out["ok"] is False
    assert out["error"] == "no_url"


def test_gather_snap_uses_observe_fetch(monkeypatch):
    calls: list[str] = []

    def fake_obs(url, dump="markdown", **_kw):
        calls.append(dump)
        if dump == "semantic_tree_text":
            body = "1 document 'Example Domain'\n2 [i] link 'More information'"
        else:
            body = "# Example Domain\n\n[More information](https://example.com/info)"
        return {
            "ok": True,
            "content": body,
            "ms": 10,
            "chars": len(body),
            "url": url,
            "http_ok": True,
            "http_status": 200,
            "engine": "chromium",
        }

    monkeypatch.setattr(wick, "observe_fetch", fake_obs)
    monkeypatch.setattr(wick, "wick_observe_cache", None)
    out = wick._gather_snap("https://example.com/", profile="default")
    assert out["ok"] is True
    assert set(calls) == {"semantic_tree_text", "markdown"}
    assert out["element_count"] >= 1
    assert out["link_count"] >= 1


def test_collect_from_page_refuses_private_landing(monkeypatch):
    class _PrivatePage(_FakePage):
        url = "http://127.0.0.1/admin"

        def goto(self, url, wait_until="load", timeout=60000):
            self.url = "http://127.0.0.1/admin"
            return _FakeResp()

    monkeypatch.delenv("WICK_ALLOW_PRIVATE", raising=False)
    out = chrome_observe.collect_from_page(
        _PrivatePage(),
        "https://example.com/",
        dump="markdown",
        max_chars=400,
        wait_until="domcontentloaded",
        wait_ms=0,
    )
    assert out["ok"] is False
    assert out["error"] == "private_url"
    assert out.get("landed") is True
    assert "content" not in out


def test_chrome_fetch_reports_missing_playwright(monkeypatch):
    monkeypatch.setattr(wick, "find_playwright_python", lambda: None)
    result = wick.chrome_fetch("https://example.com/")
    assert result["ok"] is False
    assert result["error"] == "engine_unavailable"
