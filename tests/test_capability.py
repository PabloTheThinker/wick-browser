#!/usr/bin/env python3
"""Capability profiles and outbound host allowlists."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import capability  # noqa: E402


class TestProfiles(unittest.TestCase):
    def setUp(self):
        os.environ.pop("WICK_PROFILE", None)
        os.environ.pop("WICK_ALLOW_HOSTS", None)

    def tearDown(self):
        os.environ.pop("WICK_PROFILE", None)
        os.environ.pop("WICK_ALLOW_HOSTS", None)

    def test_default_is_full(self):
        self.assertEqual(capability.current_profile(), "full-act")
        self.assertIsNone(capability.deny("act", action="login"))
        self.assertIsNone(capability.deny("vault", vault_action="resolve"))

    def test_observe_only_blocks_act_and_login(self):
        os.environ["WICK_PROFILE"] = "observe-only"
        snap = capability.deny("snap")
        self.assertIsNone(snap)
        blocked = capability.deny("act", action="click")
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked["error"], "capability_denied")
        self.assertEqual(blocked["profile"], "observe-only")
        self.assertIsNotNone(capability.deny("act", action="login"))
        self.assertIsNone(capability.deny("vault", vault_action="suggest"))
        self.assertIsNotNone(capability.deny("vault", vault_action="set"))
        self.assertIsNone(capability.deny("mcp"))
        self.assertIsNone(capability.deny("snap-many"))
        self.assertIsNone(capability.deny("snap_many"))

    def test_safe_act_allows_click_blocks_fill(self):
        os.environ["WICK_PROFILE"] = "safe-act"
        self.assertIsNone(capability.deny("act", action="click"))
        self.assertIsNone(capability.deny("act", action="goto"))
        self.assertIsNotNone(capability.deny("act", action="fill"))
        self.assertIsNotNone(capability.deny("act", action="login"))
        self.assertIsNotNone(capability.deny("act", action="eval"))
        self.assertIsNotNone(capability.deny("get"))

    def test_alias_observe(self):
        os.environ["WICK_PROFILE"] = "observe"
        self.assertEqual(capability.current_profile(), "observe-only")


class TestAllowHosts(unittest.TestCase):
    def setUp(self):
        os.environ.pop("WICK_ALLOW_HOSTS", None)

    def tearDown(self):
        os.environ.pop("WICK_ALLOW_HOSTS", None)

    def test_unrestricted_by_default(self):
        ok, reason = capability.host_allowed("https://evil.test/")
        self.assertTrue(ok)
        self.assertEqual(reason, "unrestricted")

    def test_allowlist_exact_and_suffix(self):
        os.environ["WICK_ALLOW_HOSTS"] = "example.com,.github.com"
        self.assertTrue(capability.host_allowed("https://example.com/login")[0])
        self.assertTrue(capability.host_allowed("https://docs.github.com/")[0])
        self.assertFalse(capability.host_allowed("https://evil.test/")[0])
        self.assertFalse(capability.host_allowed("https://notexample.com/")[0])


if __name__ == "__main__":
    unittest.main()
