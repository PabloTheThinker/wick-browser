#!/usr/bin/env python3
"""Unit tests for lib/elements.py (semantic tree parsing + fuzzy ask helpers)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import elements  # noqa: E402


SAMPLE_TREE = """
1 document
  2 [i] link 'More information'
  3 heading 'Example Domain'
  4 [i] button 'Go'
  5 textbox 'Search'
  6 paragraph 'Learn more about domains'
""".strip()


class TestParseTree(unittest.TestCase):
    def test_parse_tree_text_roles_and_names(self):
        els = elements.parse_tree_text(SAMPLE_TREE)
        by_role = {e["role"]: e for e in els if e.get("name")}
        self.assertEqual(by_role["link"]["name"], "More information")
        self.assertTrue(by_role["link"]["interactive"])
        self.assertEqual(by_role["button"]["name"], "Go")
        self.assertEqual(by_role["textbox"]["name"], "Search")

    def test_hint_for_link(self):
        els = elements.parse_tree_text("12 [i] link 'More information'")
        self.assertEqual(els[0]["hint"], 'role=link[name="More information"]')

    def test_hint_for_searchbox_is_not_textbox(self):
        els = elements.parse_tree_text("15 [i] searchbox 'Search Amazon'")
        self.assertEqual(els[0]["role"], "searchbox")
        self.assertEqual(els[0]["hint"], 'role=searchbox[name="Search Amazon"]')

    def test_interactive_only_limits(self):
        all_e = elements.parse_tree_text(SAMPLE_TREE)
        hit = elements.interactive_only(all_e, limit=2)
        self.assertEqual(len(hit), 2)
        self.assertTrue(all(e["interactive"] for e in hit))


class TestFuzzyMatch(unittest.TestCase):
    def test_query_words_skips_short_tokens(self):
        self.assertEqual(elements.query_words("a x more info"), ["more", "info"])

    def test_fuzzy_score_substrings(self):
        words = elements.query_words("more information")
        self.assertEqual(elements.fuzzy_score("More information here", words), 2)

    def test_filter_links_by_text_and_href(self):
        links = [
            {"text": "More information", "href": "https://example.com/docs/domains"},
            {"text": "Home", "href": "https://example.com/"},
        ]
        hit = elements.filter_links(links, "docs domains")
        self.assertEqual(len(hit), 1)
        self.assertIn("docs", hit[0]["href"])

    def test_filter_elements_by_name(self):
        els = elements.parse_tree_text(SAMPLE_TREE)
        hit = elements.filter_elements(els, "search")
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["role"], "textbox")


class TestPlanSuggestions(unittest.TestCase):
    def test_plan_includes_open_and_click(self):
        els = elements.interactive_only(elements.parse_tree_text(SAMPLE_TREE))
        links = [{"text": "More information", "href": "https://example.com/docs/domains"}]
        plan = elements.plan_suggestions(
            url="https://example.com/",
            title="Example Domain",
            excerpt="Example Domain. This domain is for use in documentation.",
            links=links,
            elements=els,
            click_limit=2,
        )
        actions = {s["action"] for s in plan}
        self.assertIn("open", actions)
        self.assertIn("click", actions)
        self.assertIn("screenshot", actions)
        clicks = [s for s in plan if s["action"] == "click"]
        self.assertTrue(any("role=link" in (s.get("hint") or "") for s in clicks))

    def test_plan_suggests_fill_for_search_field(self):
        els = elements.parse_tree_text(
            "1 document\n  2 [i] searchbox 'Search Amazon'\n  3 [i] button 'Go'\n"
        )
        plan = elements.plan_suggestions(
            url="https://www.amazon.com/",
            title="Amazon.com",
            excerpt="Spend less. Smile more.",
            links=[],
            elements=els,
            click_limit=2,
        )
        fills = [s for s in plan if s["action"] == "fill"]
        self.assertEqual(len(fills), 1)
        self.assertIn("role=searchbox", fills[0]["cmd"])
        self.assertIn("press Enter", fills[0]["cmd"])

    def test_plan_suggests_login_when_password_form(self):
        tree = "1 document\n  2 textbox 'Email'\n  3 textbox 'Password'\n  4 [i] button 'Log in'\n"
        els = elements.parse_tree_text(tree)
        plan = elements.plan_suggestions(
            url="https://example.com/login",
            title="Sign in",
            excerpt="Sign in to your account",
            links=[],
            elements=els,
            click_limit=2,
        )
        actions = {s["action"] for s in plan}
        self.assertIn("login", actions)
        login = next(s for s in plan if s["action"] == "login")
        self.assertIn("wick act login", login["cmd"])
        self.assertIn("wick vault suggest", login.get("why", "") + login["cmd"])

    def test_plan_prefers_computer_use_when_challenge_present(self):
        os.environ["WICK_CHALLENGE_COMPUTER_USE"] = "1"
        try:
            tree = "1 document\n  2 textbox 'Email'\n  3 textbox 'Password'\n  4 [i] button 'Log in'\n"
            els = elements.parse_tree_text(tree)
            plan = elements.plan_suggestions(
                url="https://example.com/login",
                title="Sign in",
                excerpt='<div class="cf-turnstile"></div> Sign in',
                links=[],
                elements=els,
                click_limit=2,
            )
            actions = [s["action"] for s in plan]
            self.assertEqual(actions[0], "cu")
            self.assertNotIn("login", set(actions))
            why = (plan[0].get("why") or "").lower()
            self.assertTrue("computer-use" in why or "computer use" in why)
        finally:
            os.environ.pop("WICK_CHALLENGE_COMPUTER_USE", None)


class TestChromiumObserveShape(unittest.TestCase):
    def test_tree_from_elements_round_trips(self):
        tree = elements.tree_from_elements(
            "Example Domain",
            [{"role": "link", "name": "More information", "interactive": True}],
        )
        els = elements.parse_tree_text(tree)
        self.assertEqual(els[0]["role"], "document")
        link = next(e for e in els if e["role"] == "link")
        self.assertEqual(link["name"], "More information")
        self.assertEqual(link["hint"], 'role=link[name="More information"]')

    def test_markdown_from_observe_keeps_links(self):
        md = elements.markdown_from_observe(
            "Example Domain",
            "This domain is for use in documentation examples.",
            [{"text": "More information", "href": "https://www.iana.org/domains/example"}],
        )
        self.assertIn("# Example Domain", md)
        self.assertIn("[More information](https://www.iana.org/domains/example)", md)


if __name__ == "__main__":
    unittest.main()
