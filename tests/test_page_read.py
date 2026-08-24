#!/usr/bin/env python3
"""Structured page read — excerpt, headings, kind, agent read payload."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import page_read  # noqa: E402


def _load_wick():
    path = Path(__file__).resolve().parents[1] / "bin" / "wick"
    loader = SourceFileLoader("wick_cli_page_read", str(path))
    spec = importlib.util.spec_from_loader("wick_cli_page_read", loader)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ARTICLE = {
    "title": "Example Domains — IANA notes",
    "text": (
        "Home Cart Accept all cookies Guides News Example Domains Why these names exist "
        "As described in RFC 2606 and RFC 6761, a number of domains such as example.com "
        "are maintained for documentation purposes."
    ),
    "excerpt": "Home Cart Accept all cookies Guides News Example Domains",
    "headings": [
        {"level": 1, "text": "Example Domains"},
        {"level": 2, "text": "Why these names exist"},
        {"level": 2, "text": "How agents should read them"},
    ],
    "paragraphs": [
        "As described in RFC 2606 and RFC 6761, a number of domains such as example.com and example.org are maintained for documentation purposes.",
        "A structured read should keep this paragraph and the headings above. Cookie banners, cart links, and site chrome must not replace the article body.",
    ],
    "links": [
        {"text": "Home", "href": "https://example.com/"},
        {"text": "Cart", "href": "https://example.com/cart"},
        {"text": "Guides", "href": "https://example.com/guides"},
        {"text": "Privacy", "href": "https://example.com/privacy"},
    ],
    "elements": [
        {"role": "link", "name": "Home"},
        {"role": "button", "name": "Accept all cookies"},
        {"role": "link", "name": "Guides"},
    ],
}

SEARCH = {
    "title": "Shop : usb-c cable",
    "text": "1-16 of over 70,000 results for usb-c cable Anker USB C $9.99",
    "headings": [{"level": 1, "text": '1-16 of over 70,000 results for "usb-c cable"'}],
    "paragraphs": [],
    "links": [
        {"text": "Anker USB C to USB C Cable", "href": "https://www.amazon.com/dp/anker"},
        {"text": "LISEN USB C Cable", "href": "https://www.amazon.com/dp/lisen"},
        {"text": "Cart", "href": "https://www.amazon.com/cart"},
    ],
    "elements": [
        {"role": "searchbox", "name": "Search Amazon"},
        {"role": "button", "name": "Go"},
        {"role": "link", "name": "Anker USB C to USB C Cable"},
    ],
}

LOGIN = {
    "title": "Sign in",
    "text": "Sign in to your account",
    "headings": [{"level": 1, "text": "Sign in"}],
    "paragraphs": ["Sign in to your account to continue."],
    "links": [],
    "elements": [
        {"role": "textbox", "name": "Email"},
        {"role": "textbox", "name": "Password"},
        {"role": "button", "name": "Log in"},
    ],
}


class TestShapeObserve(unittest.TestCase):
    def test_article_kind_and_excerpt_skips_chrome(self):
        out = page_read.shape_observe(ARTICLE, excerpt_len=280)
        self.assertEqual(out["kind"], "article")
        self.assertIn("RFC 2606", out["excerpt"])
        self.assertNotIn("Accept all cookies", out["excerpt"])
        self.assertNotIn("Cart", out["excerpt"])
        texts = [h["text"] for h in out["headings"]]
        self.assertIn("Example Domains", texts)
        self.assertGreaterEqual(len(out["paragraphs"]), 1)

    def test_search_kind(self):
        out = page_read.shape_observe(SEARCH)
        self.assertEqual(out["kind"], "search")

    def test_login_kind(self):
        out = page_read.shape_observe(LOGIN)
        self.assertEqual(out["kind"], "login")

    def test_headings_from_markdown_when_missing(self):
        out = page_read.shape_observe(
            {
                "title": "Notes",
                "markdown": "# Example Domains\n\n## Why these names exist\n\nBody text here.",
                "text": "Example Domains Why these names exist Body text here.",
                "elements": [],
                "links": [],
            }
        )
        texts = [h["text"] for h in out["headings"]]
        self.assertIn("Example Domains", texts)
        self.assertIn("Why these names exist", texts)

    def test_read_payload_is_structured(self):
        snap = {"ok": True, "url": "https://example.com/", **ARTICLE}
        out = page_read.read_payload(snap)
        self.assertTrue(out["ok"])
        self.assertEqual(out["mode"], "agent_read")
        self.assertEqual(out["kind"], "article")
        self.assertIn("RFC 2606", out["excerpt"])
        self.assertTrue(out["headings"])
        self.assertTrue(out["paragraphs"])
        self.assertIn("untrusted", (out.get("hint") or "").lower())

    def test_filter_headings_for_ask(self):
        hit = page_read.filter_headings(ARTICLE["headings"], "agents read")
        self.assertEqual(len(hit), 1)
        self.assertIn("agents", hit[0]["text"].lower())

    def test_filter_paragraphs_for_ask(self):
        hit = page_read.filter_paragraphs(ARTICLE["paragraphs"], "RFC 2606")
        self.assertEqual(len(hit), 1)
        self.assertIn("RFC 2606", hit[0])

    def test_read_payload_query_keeps_matching_body(self):
        snap = {"ok": True, "url": "https://example.com/", **ARTICLE}
        out = page_read.read_payload(snap, query="RFC 2606")
        self.assertTrue(out["focused"])
        self.assertEqual(out["query"], "RFC 2606")
        self.assertIn("RFC 2606", out["excerpt"])
        self.assertTrue(out["paragraphs"])
        self.assertTrue(all("rfc" in p.lower() for p in out["paragraphs"]))
        self.assertFalse(any("cookie banners" in p.lower() for p in out["paragraphs"]))

    def test_read_payload_section_keeps_one_heading(self):
        snap = {"ok": True, "url": "https://example.com/", **ARTICLE}
        out = page_read.read_payload(snap, section="How agents should read")
        self.assertTrue(out["focused"])
        self.assertEqual(out["section"], "How agents should read")
        texts = [h["text"] for h in out["headings"]]
        self.assertTrue(any("agents" in t.lower() for t in texts))
        self.assertFalse(any("RFC 2606" in p for p in out["paragraphs"]))
        self.assertTrue(any("structured read" in p.lower() for p in out["paragraphs"]))
        heads = [s["heading"] for s in out.get("sections") or []]
        self.assertTrue(any("agents" in h.lower() for h in heads))
        self.assertFalse(any("why these names" in h.lower() for h in heads))

    def test_sections_from_markdown_when_missing(self):
        out = page_read.shape_observe(
            {
                "title": "Notes",
                "markdown": (
                    "# Example Domains\n\n"
                    "Intro line that is long enough to count as a real paragraph for sectioning.\n\n"
                    "## Why these names exist\n\n"
                    "As described in RFC 2606 and RFC 6761, a number of domains such as example.com "
                    "are maintained for documentation purposes.\n\n"
                    "## How agents should read them\n\n"
                    "A structured read should keep this paragraph and the headings above without chrome."
                ),
                "text": "Example Domains Why these names exist Body",
                "elements": [],
                "links": [],
            }
        )
        heads = [s["heading"] for s in out["sections"]]
        self.assertIn("Why these names exist", heads)
        why = next(s for s in out["sections"] if s["heading"] == "Why these names exist")
        self.assertTrue(any("RFC 2606" in p for p in why["paragraphs"]))


class TestPlanSuggestsRead(unittest.TestCase):
    def test_article_plan_leads_with_read(self):
        import elements

        plan = elements.plan_suggestions(
            url="https://example.com/docs",
            title="Example Domains",
            excerpt="As described in RFC 2606.",
            links=[{"text": "Docs", "href": "https://example.com/docs"}],
            elements=[{"role": "link", "name": "Docs", "hint": 'role=link[name="Docs"]'}],
            kind="article",
            headings=ARTICLE["headings"],
        )
        actions = [s["action"] for s in plan]
        self.assertIn("read", actions)
        self.assertLess(actions.index("read"), actions.index("open"))
        self.assertIn("wick read", next(s["cmd"] for s in plan if s["action"] == "read"))
        self.assertTrue(any("--section" in (s.get("cmd") or "") for s in plan))


class TestWickReadCli(unittest.TestCase):
    def test_rpc_read_and_snap_kind(self):
        wick = _load_wick()

        def fake_gather(url, **_kw):
            return {
                "ok": True,
                "url": url or "https://example.com/",
                "title": ARTICLE["title"],
                "excerpt": ARTICLE["excerpt"],
                "text": ARTICLE["text"],
                "headings": ARTICLE["headings"],
                "paragraphs": ARTICLE["paragraphs"],
                "links": ARTICLE["links"],
                "links_all": ARTICLE["links"],
                "elements": ARTICLE["elements"],
                "http_ok": True,
            }

        wick._gather_snap = fake_gather  # type: ignore[method-assign]
        handlers = wick._rpc_handlers()
        read = handlers["read"]({})
        self.assertEqual(read["mode"], "agent_read")
        self.assertEqual(read["kind"], "article")
        self.assertIn("RFC 2606", read["excerpt"])
        snap = wick.snap_payload("https://example.com/")
        self.assertEqual(snap.get("kind"), "article")
        self.assertTrue(snap.get("headings"))
        focused = handlers["read"]({"q": "RFC 2606"})
        self.assertTrue(focused.get("focused"))
        self.assertTrue(all("rfc" in p.lower() for p in focused.get("paragraphs") or []))

    def test_ask_rpc_includes_matching_paragraphs(self):
        wick = _load_wick()

        def fake_gather(url, **_kw):
            return {
                "ok": True,
                "url": url or "https://example.com/",
                "title": ARTICLE["title"],
                "excerpt": ARTICLE["excerpt"],
                "text": ARTICLE["text"],
                "headings": ARTICLE["headings"],
                "paragraphs": ARTICLE["paragraphs"],
                "links": ARTICLE["links"],
                "links_all": ARTICLE["links"],
                "elements": ARTICLE["elements"],
                "http_ok": True,
            }

        wick._gather_snap = fake_gather  # type: ignore[method-assign]
        ask = wick._rpc_handlers()["ask"]({"q": "RFC 2606"})
        paras = ask.get("paragraphs") or []
        self.assertTrue(any("RFC 2606" in p for p in paras), ask)
        self.assertFalse(any("cookie" in p.lower() for p in paras))

    def test_cmd_read_cli_does_not_crash_history(self):
        wick = _load_wick()

        def fake_gather(url, **_kw):
            return {"ok": True, "url": url or "https://example.com/", **ARTICLE, "http_ok": True}

        wick._gather_snap = fake_gather  # type: ignore[method-assign]
        ns = type("NS", (), {"url": "", "here": False, "fail_http": False})()
        rc = wick.cmd_read(ns)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
