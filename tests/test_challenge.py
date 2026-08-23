#!/usr/bin/env python3
"""Human-challenge detection: halt, never solve."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import challenge  # noqa: E402


class TestChallengeDetect(unittest.TestCase):
    def test_turnstile_in_html(self):
        hit = challenge.detect(
            url="https://example.com/login",
            title="Sign in",
            html='<div class="cf-turnstile" data-sitekey="x"></div>',
        )
        self.assertTrue(hit["found"])
        self.assertEqual(hit["kind"], "turnstile")
        self.assertTrue(hit["halt"])
        blob = json_blob(hit).lower()
        for banned in ("2captcha", "anticaptcha", "solver", "bypass", "auto-submit"):
            self.assertNotIn(banned, blob)

    def test_recaptcha_iframe(self):
        hit = challenge.detect(html='<iframe src="https://www.google.com/recaptcha/api2/anchor">')
        self.assertTrue(hit["found"])
        self.assertEqual(hit["kind"], "recaptcha")

    def test_hcaptcha_host(self):
        hit = challenge.detect(url="https://example.com/", html="https://hcaptcha.com/1/api.js")
        self.assertTrue(hit["found"])
        self.assertEqual(hit["kind"], "hcaptcha")

    def test_cloudflare_just_a_moment(self):
        hit = challenge.detect(title="Just a moment...", url="https://example.com/cdn-cgi/challenge")
        self.assertTrue(hit["found"])
        self.assertEqual(hit["kind"], "cloudflare")

    def test_docs_mentioning_captcha_is_not_a_challenge(self):
        hit = challenge.detect(
            url="https://example.com/security",
            title="Security and privacy",
            excerpt="We never solve CAPTCHAs on your behalf. Agents halt instead.",
            html="<p>This policy page mentions captcha only as documentation.</p>",
        )
        self.assertFalse(hit["found"])
        self.assertIsNone(hit["kind"])
        self.assertFalse(hit["halt"])

    def test_captcha_widget_attribute_counts(self):
        hit = challenge.detect(
            url="https://example.com/login",
            title="Sign in",
            html='<input name="captcha" type="text">',
        )
        self.assertTrue(hit["found"])
        self.assertEqual(hit["kind"], "captcha")

    def test_clean_login_is_not_a_challenge(self):
        hit = challenge.detect(
            url="https://example.com/login",
            title="Sign in",
            html="<form><input type=password><button>Log in</button></form>",
        )
        self.assertFalse(hit["found"])
        self.assertIsNone(hit["kind"])

    def test_never_returns_solver_hints(self):
        hit = challenge.detect(html='<div class="g-recaptcha"></div>')
        blob = json_blob(hit)
        for banned in ("2captcha", "anticaptcha", "solver", "bypass", "auto-submit"):
            self.assertNotIn(banned, blob.lower())
        self.assertIn("human", (hit.get("hint") or "").lower())

    def test_halt_env_can_be_disabled(self):
        self.assertTrue(challenge.halt_on_challenge())
        os.environ["WICK_HALT_ON_CHALLENGE"] = "0"
        try:
            self.assertFalse(challenge.halt_on_challenge())
            hit = challenge.detect(html='<div class="cf-turnstile"></div>')
            self.assertTrue(hit["found"])
            self.assertFalse(hit["halt"])
        finally:
            os.environ.pop("WICK_HALT_ON_CHALLENGE", None)


class TestChallengePolicy(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="wick-chal-")
        os.environ["WICK_HOME"] = self._tmp.name
        os.environ.pop("WICK_POLICY", None)
        os.environ.pop("WICK_HALT_ON_CHALLENGE", None)

    def tearDown(self):
        os.environ.pop("WICK_HOME", None)
        os.environ.pop("WICK_POLICY", None)
        os.environ.pop("WICK_HALT_ON_CHALLENGE", None)
        self._tmp.cleanup()

    def test_policy_can_force_halt(self):
        import json
        import policy

        path = Path(self._tmp.name) / "policy.json"
        path.write_text(json.dumps({"halt_on_challenge": False}), encoding="utf-8")
        os.environ["WICK_POLICY"] = str(path)
        self.assertFalse(challenge.halt_on_challenge())
        os.environ["WICK_HALT_ON_CHALLENGE"] = "1"
        self.assertTrue(challenge.halt_on_challenge())


def json_blob(obj) -> str:
    import json

    return json.dumps(obj)


if __name__ == "__main__":
    unittest.main()
