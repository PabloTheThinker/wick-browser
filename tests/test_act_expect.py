#!/usr/bin/env python3
"""Post-action expect guards: --expect-url-fragment / --expect-element."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import act_expect  # noqa: E402


class TestSplitFlags(unittest.TestCase):
    def test_strips_expect_flags(self):
        clean, exp = act_expect.split_flags(
            [
                "css=button",
                "--expect-url-fragment",
                "welcome",
                "--expect-element",
                'role=heading[name="Hi"]',
            ]
        )
        self.assertEqual(clean, ["css=button"])
        self.assertEqual(exp["url_fragment"], "welcome")
        self.assertEqual(exp["element"], 'role=heading[name="Hi"]')

    def test_no_flags(self):
        clean, exp = act_expect.split_flags(["120", "340"])
        self.assertEqual(clean, ["120", "340"])
        self.assertIsNone(exp["url_fragment"])
        self.assertIsNone(exp["element"])


class FakePage:
    def __init__(self, url: str, visible: bool = True):
        self.url = url
        self._visible = visible

    def locator(self, _sel: str):
        return self

    def get_by_role(self, _role, name=None):  # noqa: ARG002
        return self

    def first(self):
        return self

    def count(self):
        return 1 if self._visible else 0

    def is_visible(self, timeout=2000):  # noqa: ARG002
        if not self._visible:
            raise RuntimeError("element is not visible")
        return True


class TestCheckExpect(unittest.TestCase):
    def test_url_fragment_ok(self):
        err = act_expect.check(FakePage("https://example.com/welcome"), {"url_fragment": "welcome"})
        self.assertIsNone(err)

    def test_url_fragment_miss(self):
        err = act_expect.check(FakePage("https://example.com/"), {"url_fragment": "welcome"})
        self.assertIsNotNone(err)
        self.assertEqual(err["error"], "expect_failed")
        self.assertEqual(err["expect"], "url_fragment")
        self.assertFalse(err["ok"])

    def test_element_miss(self):
        err = act_expect.check(
            FakePage("https://example.com/", visible=False),
            {"element": "css=#gone"},
        )
        self.assertIsNotNone(err)
        self.assertEqual(err["error"], "expect_failed")
        self.assertEqual(err["expect"], "element")


if __name__ == "__main__":
    unittest.main()
