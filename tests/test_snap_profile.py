#!/usr/bin/env python3
"""Observe budget profiles: micro / default / full."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import snap_profile  # noqa: E402


class TestProfiles(unittest.TestCase):
    def test_micro_skips_markdown_and_is_fast(self):
        p = snap_profile.apply("micro")
        self.assertTrue(p["fast"])
        self.assertTrue(p["skip_markdown"])
        self.assertLessEqual(p["wait_ms"], 900)
        self.assertLessEqual(p["elements"], 20)
        self.assertLessEqual(p["excerpt"], 280)

    def test_default_is_fast_but_keeps_excerpt(self):
        p = snap_profile.apply("default")
        self.assertTrue(p["fast"])
        self.assertFalse(p["skip_markdown"])
        self.assertEqual(p["wait_ms"], 1200)

    def test_full_waits_longer(self):
        p = snap_profile.apply("full")
        self.assertFalse(p["fast"])
        self.assertGreaterEqual(p["wait_ms"], 2000)
        self.assertFalse(p["skip_markdown"])

    def test_alias_fast_and_env_default(self):
        import os

        self.assertEqual(snap_profile.resolve("fast"), "default")
        self.assertEqual(snap_profile.resolve("tiny"), "micro")
        self.assertEqual(snap_profile.resolve(None), "default")
        os.environ["WICK_SNAP_PROFILE"] = "micro"
        try:
            self.assertEqual(snap_profile.resolve(None), "micro")
        finally:
            os.environ.pop("WICK_SNAP_PROFILE", None)

    def test_unknown_falls_back(self):
        self.assertEqual(snap_profile.resolve("nope"), "default")


if __name__ == "__main__":
    unittest.main()
