#!/usr/bin/env python3
"""Capability profiles and outbound host allowlists."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import capability  # noqa: E402

_ENV = ("WICK_PROFILE", "WICK_ALLOW_HOSTS", "WICK_BLOCK_HOSTS", "WICK_POLICY", "WICK_HOME")


class EnvCase(unittest.TestCase):
    """Env-only expectations: no policy file, throwaway WICK_HOME."""

    def setUp(self):
        for k in _ENV:
            os.environ.pop(k, None)
        self._tmp = tempfile.TemporaryDirectory(prefix="wick-cap-")
        os.environ["WICK_HOME"] = self._tmp.name

    def tearDown(self):
        for k in _ENV:
            os.environ.pop(k, None)
        self._tmp.cleanup()


class TestProfiles(EnvCase):
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
        self.assertIsNone(capability.deny("challenge"))
        self.assertIsNone(capability.deny("vault", vault_action="suggest"))
        self.assertIsNone(capability.deny("vault", vault_action="audit"))
        self.assertIsNotNone(capability.deny("vault", vault_action="set"))
        self.assertIsNotNone(capability.deny("vault", vault_action="backup"))
        self.assertIsNotNone(capability.deny("vault", vault_action="restore"))
        self.assertIsNone(capability.deny("mcp"))
        self.assertIsNone(capability.deny("snap-many"))
        self.assertIsNone(capability.deny("snap_many"))
        self.assertIsNone(capability.deny("approve"))
        self.assertIsNone(capability.deny("skill"))
        self.assertIsNone(capability.deny("read"))
        self.assertIsNone(capability.deny("commands"))
        self.assertIsNone(capability.deny("call"))
        self.assertIsNone(capability.deny("help"))

    def test_safe_act_allows_click_blocks_fill(self):
        os.environ["WICK_PROFILE"] = "safe-act"
        self.assertIsNone(capability.deny("act", action="click"))
        self.assertIsNone(capability.deny("act", action="goto"))
        self.assertIsNotNone(capability.deny("act", action="fill"))
        self.assertIsNotNone(capability.deny("act", action="login"))
        self.assertIsNotNone(capability.deny("act", action="passkey"))
        self.assertIsNotNone(capability.deny("act", action="eval"))
        self.assertIsNotNone(capability.deny("get"))
        self.assertIsNone(capability.deny("approve"))

    def test_alias_observe(self):
        os.environ["WICK_PROFILE"] = "observe"
        self.assertEqual(capability.current_profile(), "observe-only")

    def test_session_export_reveal_needs_full_act(self):
        os.environ["WICK_PROFILE"] = "safe-act"
        self.assertIsNone(capability.deny("session", session_action="export"))
        self.assertIsNotNone(capability.deny("session", session_action="export-reveal"))
        self.assertIsNotNone(capability.deny("session", session_action="import"))
        os.environ["WICK_PROFILE"] = "full-act"
        self.assertIsNone(capability.deny("session", session_action="export-reveal"))
        self.assertIsNone(capability.deny("session", session_action="import"))
        os.environ["WICK_PROFILE"] = "observe-only"
        self.assertIsNone(capability.deny("session", session_action="export"))
        self.assertIsNotNone(capability.deny("session", session_action="new"))


class TestAllowHosts(EnvCase):
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

    def test_block_hosts_wins(self):
        os.environ["WICK_BLOCK_HOSTS"] = "evil.test,.ads.example.com"
        self.assertFalse(capability.host_allowed("https://evil.test/")[0])
        self.assertEqual(capability.host_allowed("https://evil.test/")[1], "blocked")
        self.assertFalse(capability.host_allowed("https://tracker.ads.example.com/")[0])
        self.assertTrue(capability.host_allowed("https://example.com/")[0])
        denied = capability.deny_host("https://evil.test/")
        self.assertIsNotNone(denied)
        self.assertIn("evil.test", denied["block_hosts"])

    def test_block_wins_over_allow(self):
        os.environ["WICK_ALLOW_HOSTS"] = "example.com"
        os.environ["WICK_BLOCK_HOSTS"] = "example.com"
        ok, reason = capability.host_allowed("https://example.com/")
        self.assertFalse(ok)
        self.assertEqual(reason, "blocked")


if __name__ == "__main__":
    unittest.main()
