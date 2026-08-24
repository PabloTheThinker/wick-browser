#!/usr/bin/env python3
"""Origin matching and URL guards — Chrome/Brave-style, no substring phishing."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import origins  # noqa: E402


class TestParseOrigin(unittest.TestCase):
    def test_https_origin(self):
        o = origins.parse_origin("https://Example.COM:443/login?x=1")
        self.assertIsNotNone(o)
        self.assertEqual(o["scheme"], "https")
        self.assertEqual(o["host"], "example.com")
        self.assertEqual(o["port"], 443)
        self.assertEqual(o["origin"], "https://example.com")

    def test_rejects_javascript(self):
        self.assertIsNone(origins.parse_origin("javascript:alert(1)"))
        self.assertTrue(origins.is_dangerous_url("javascript:alert(1)"))

    def test_rejects_data_and_file(self):
        self.assertTrue(origins.is_dangerous_url("data:text/html,hi"))
        self.assertTrue(origins.is_dangerous_url("file:///etc/passwd"))
        self.assertTrue(origins.is_dangerous_url("blob:https://example.com/x"))

    def test_https_first_bare_host(self):
        self.assertEqual(origins.normalize_agent_url("example.com/login"), "https://example.com/login")

    def test_private_hosts(self):
        self.assertTrue(origins.is_private_url("http://127.0.0.1/"))
        self.assertTrue(origins.is_private_url("http://localhost:8080/"))
        self.assertTrue(origins.is_private_url("http://192.168.1.4/"))
        self.assertTrue(origins.is_private_url("http://169.254.169.254/latest/meta-data"))
        self.assertFalse(origins.is_private_url("https://example.com/"))


class TestOriginCompat(unittest.TestCase):
    def test_exact_host_matches(self):
        ok, reason, score = origins.origins_compatible(
            "https://example.com/login",
            "https://example.com/account",
        )
        self.assertTrue(ok)
        self.assertGreaterEqual(score, 80)
        self.assertEqual(reason, "exact_host")

    def test_www_alias(self):
        ok, reason, _score = origins.origins_compatible(
            "https://www.example.com/",
            "https://example.com/login",
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "www_alias")

    def test_https_saved_never_fills_http(self):
        ok, reason, score = origins.origins_compatible(
            "https://example.com/login",
            "http://example.com/login",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "https_required")
        self.assertEqual(score, 0)

    def test_http_saved_can_upgrade_to_https(self):
        ok, reason, _score = origins.origins_compatible(
            "http://example.com/login",
            "https://example.com/login",
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "https_upgrade")

    def test_rejects_substring_phishing(self):
        ok, _reason, score = origins.origins_compatible(
            "https://example.com/login",
            "https://evil.example/phish?next=https://example.com/login",
        )
        self.assertFalse(ok)
        self.assertEqual(score, 0)

    def test_rejects_suffix_lookalike(self):
        ok, _reason, _score = origins.origins_compatible(
            "https://example.com/",
            "https://notexample.com/",
        )
        self.assertFalse(ok)
        ok2, _r, _s = origins.origins_compatible(
            "https://example.com/",
            "https://example.com.evil.test/",
        )
        self.assertFalse(ok2)

    def test_subdomain_requires_flag(self):
        ok, reason, _score = origins.origins_compatible(
            "https://example.com/",
            "https://app.example.com/login",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "host_mismatch")
        ok2, reason2, _s = origins.origins_compatible(
            "https://example.com/",
            "https://app.example.com/login",
            allow_subdomains=True,
        )
        self.assertTrue(ok2)
        self.assertEqual(reason2, "subdomain")

    def test_saved_subdomain_does_not_fill_parent(self):
        ok, _reason, _score = origins.origins_compatible(
            "https://app.example.com/",
            "https://example.com/",
            allow_subdomains=True,
        )
        self.assertFalse(ok)


class TestSameObserveTarget(unittest.TestCase):
    def test_same_path_ignores_live_tracking_query(self):
        self.assertTrue(
            origins.same_observe_target(
                "https://example.com/shop?ref=nav",
                "https://example.com/shop",
            )
        )

    def test_target_query_must_match(self):
        self.assertTrue(
            origins.same_observe_target(
                "https://example.com/s?k=usb&ref=1",
                "https://example.com/s?k=usb",
            )
        )
        self.assertFalse(
            origins.same_observe_target(
                "https://example.com/s?k=usb",
                "https://example.com/s?k=keyboard",
            )
        )

    def test_path_and_host_must_match(self):
        self.assertFalse(
            origins.same_observe_target(
                "https://example.com/a",
                "https://example.com/b",
            )
        )
        self.assertFalse(
            origins.same_observe_target(
                "https://example.com/",
                "https://evil.test/",
            )
        )

    def test_here_aliases(self):
        self.assertTrue(origins.is_here_url(""))
        self.assertTrue(origins.is_here_url("here"))
        self.assertTrue(origins.is_here_url("."))
        self.assertTrue(origins.is_here_url("--here"))
        self.assertFalse(origins.is_here_url("https://example.com/"))
        self.assertTrue(origins.same_observe_target("https://example.com/", "here"))


if __name__ == "__main__":
    unittest.main()
