#!/usr/bin/env python3
"""Computer-use helpers: coordinates, labeled targets, action error classes."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import computer_use  # noqa: E402
import capability  # noqa: E402
import elements  # noqa: E402


class TestXY(unittest.TestCase):
    def test_looks_like_xy(self):
        self.assertTrue(computer_use.looks_like_xy(["120", "340"]))
        self.assertTrue(computer_use.looks_like_xy(["12.5", "9"]))
        self.assertFalse(computer_use.looks_like_xy(["css=button"]))
        self.assertFalse(computer_use.looks_like_xy(["120"]))

    def test_parse_xy(self):
        self.assertEqual(computer_use.parse_xy(["120", "340"]), (120.0, 340.0))


class TestParseN(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(computer_use.parse_n(["3"]), 3)
        self.assertEqual(computer_use.parse_n(["n=3"]), 3)
        self.assertEqual(computer_use.parse_n(["#3"]), 3)
        self.assertIsNone(computer_use.parse_n(["css=button"]))
        self.assertIsNone(computer_use.parse_n(["0"]))
        self.assertTrue(computer_use.looks_like_n(["n=2"]))


class TestClassifyError(unittest.TestCase):
    def test_timeout(self):
        self.assertEqual(computer_use.classify_action_error("Timeout 15000ms exceeded"), "timeout")

    def test_not_found(self):
        self.assertEqual(
            computer_use.classify_action_error("Locator.click: Error: No element found"),
            "not_found",
        )

    def test_not_interactable(self):
        self.assertEqual(
            computer_use.classify_action_error("element is not visible / not enabled"),
            "not_interactable",
        )

    def test_navigation(self):
        self.assertEqual(
            computer_use.classify_action_error("net::ERR_BLOCKED_BY_CLIENT during navigation"),
            "navigation_blocked",
        )

    def test_fail_payload(self):
        out = computer_use.fail_payload("click", "Timeout 15000ms exceeded", url="https://example.com/")
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "timeout")
        self.assertTrue(out["retryable"])
        self.assertEqual(out["url"], "https://example.com/")


class TestNumberTargets(unittest.TestCase):
    def test_adds_n_and_xy_hint(self):
        els = [{"role": "button", "name": "Go", "cx": 40, "cy": 80, "x": 10, "y": 60, "w": 60, "h": 40}]
        out = computer_use.number_targets(els)
        self.assertEqual(out[0]["n"], 1)
        self.assertEqual(out[0]["hint"], "xy=40,80")
        self.assertEqual(out[0]["click"], "wick act click_xy 40 80")


class TestCuPayload(unittest.TestCase):
    def test_payload_shape(self):
        raw = {
            "vw": 1440,
            "vh": 900,
            "elements": [{"role": "link", "name": "More", "cx": 10, "cy": 20, "x": 0, "y": 0, "w": 20, "h": 40}],
        }
        out = computer_use.build_cu_payload(
            url="https://example.com/",
            title="Example",
            screenshot="/tmp/cu.png",
            raw=raw,
            annotated="/tmp/cu-boxes.png",
        )
        self.assertEqual(out["mode"], "computer_use")
        self.assertEqual(out["element_count"], 1)
        self.assertEqual(out["elements"][0]["n"], 1)
        self.assertEqual(out["annotated"], "/tmp/cu-boxes.png")
        self.assertTrue(out["untrusted_content"])
        self.assertIn("click_xy", out["hint"])


class TestLastState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wick-cu-")
        os.environ["WICK_HOME"] = self.tmp
        os.environ["WICK_SESSION"] = "cutest"

    def tearDown(self):
        os.environ.pop("WICK_HOME", None)
        os.environ.pop("WICK_SESSION", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roundtrip_and_resolve_n(self):
        payload = {
            "url": "https://example.com/",
            "title": "Example",
            "elements": [{"n": 1, "cx": 10, "cy": 20, "name": "More"}],
            "viewport": {"w": 800, "h": 600},
        }
        path = computer_use.save_last_state(payload)
        self.assertTrue(path.is_file())
        loaded = computer_use.load_last_state()
        self.assertEqual(loaded["url"], "https://example.com/")
        hit = computer_use.resolve_n(1, loaded)
        self.assertEqual(hit["cx"], 10)
        self.assertIsNone(computer_use.resolve_n(9, loaded))


class TestNormalizeKey(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(computer_use.normalize_key("enter"), "Enter")
        self.assertEqual(computer_use.normalize_key("esc"), "Escape")
        self.assertEqual(computer_use.normalize_key("Control+A"), "Control+A")


class TestSafeActIncludesCu(unittest.TestCase):
    def test_safe_act_allows_click_xy_and_cu(self):
        os.environ["WICK_PROFILE"] = "safe-act"
        try:
            self.assertIsNone(capability.deny("act", action="click_xy"))
            self.assertIsNone(capability.deny("act", action="click_n"))
            self.assertIsNone(capability.deny("act", action="cu"))
            self.assertIsNone(capability.deny("act", action="type"))
            self.assertIsNone(capability.deny("act", action="key"))
            self.assertIsNotNone(capability.deny("act", action="fill"))
        finally:
            os.environ.pop("WICK_PROFILE", None)


class TestPlanSuggestsCu(unittest.TestCase):
    def test_plan_includes_cu(self):
        plan = elements.plan_suggestions(
            url="https://example.com/",
            title="Example Domain",
            excerpt="Example Domain.",
            links=[],
            elements=[{"id": 1, "role": "link", "name": "More", "hint": 'role=link[name="More"]'}],
            click_limit=1,
        )
        actions = {s["action"] for s in plan}
        self.assertIn("cu", actions)
        cu = next(s for s in plan if s["action"] == "cu")
        self.assertIn("wick act cu", cu["cmd"])


if __name__ == "__main__":
    unittest.main()
