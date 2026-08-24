#!/usr/bin/env python3
"""Observe-only challenge probe. Never logs in. Never solves."""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import challenge  # noqa: E402

_FIXTURE = Path(__file__).resolve().parent / "fixtures"
_CU_ENV = (
    "WICK_CHALLENGE_COMPUTER_USE",
    "WICK_HEADED",
    "WICK_HEADLESS",
    "WICK_ALLOW_PRIVATE",
    "WAYLAND_DISPLAY",
    "XDG_SESSION_TYPE",
    "XDG_CURRENT_DESKTOP",
)


class TestChallengeProbe(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in _CU_ENV}
        os.environ["WICK_CHALLENGE_COMPUTER_USE"] = "0"

    def tearDown(self):
        for k in _CU_ENV:
            os.environ.pop(k, None)
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def test_probe_html_reports_kind_and_never_solves(self):
        html = (_FIXTURE / "live-github-login.excerpt.html").read_text(encoding="utf-8")
        out = challenge.probe("https://github.com/login", html=html, title="Sign in to GitHub")
        self.assertTrue(out["ok"])
        self.assertTrue(out["found"])
        self.assertEqual(out["kind"], "turnstile")
        self.assertFalse(out["solves"])
        self.assertFalse(out["login"])
        self.assertEqual(out["mode"], "observe")
        blob = json.dumps(out).lower()
        for banned in ("2captcha", "anticaptcha", "solver", "bypass"):
            self.assertNotIn(banned, blob)

    def test_probe_google_recaptcha_excerpt(self):
        html = (_FIXTURE / "live-google-login.excerpt.html").read_text(encoding="utf-8")
        out = challenge.probe("https://accounts.google.com/", html=html, title="Sign in")
        self.assertTrue(out["ok"])
        self.assertTrue(out["found"])
        self.assertEqual(out["kind"], "recaptcha")
        self.assertFalse(out["solves"])

    def test_probe_bank_style_geetest_excerpt(self):
        html = (_FIXTURE / "live-bank-geetest.excerpt.html").read_text(encoding="utf-8")
        out = challenge.probe("https://example-bank.test/login", html=html, title="Secure sign in")
        self.assertTrue(out["ok"])
        self.assertEqual(out["kind"], "geetest")
        self.assertFalse(out["login"])

    def test_probe_refuses_private_url(self):
        out = challenge.probe("http://127.0.0.1/login")
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "private_url")
        self.assertFalse(out.get("login"))

    def test_live_public_login_pages_are_observe_only(self):
        """Optional: GET public HTML only. Skip when the network is blocked."""
        url = "https://github.com/login"
        out = challenge.probe(url)
        if not out.get("ok"):
            raise unittest.SkipTest(out.get("error") or "live fetch unavailable")
        self.assertFalse(out["solves"])
        self.assertFalse(out["login"])
        self.assertEqual(out["mode"], "observe")
        self.assertNotIn("2captcha", json.dumps(out).lower())


if __name__ == "__main__":
    unittest.main()
