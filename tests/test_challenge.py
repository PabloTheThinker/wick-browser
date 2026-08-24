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

_CU_ENV = (
    "WICK_CHALLENGE_COMPUTER_USE",
    "WICK_HEADED",
    "WICK_HEADLESS",
    "WICK_XVFB",
    "WAYLAND_DISPLAY",
    "XDG_SESSION_TYPE",
    "XDG_CURRENT_DESKTOP",
    "DESKTOP_SESSION",
)


class _CuEnv:
    """Isolate desktop/CU flags so CI DISPLAY=:1 does not look like a user seat."""

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in _CU_ENV}
        os.environ["WICK_CHALLENGE_COMPUTER_USE"] = "0"

    def tearDown(self):
        for k in _CU_ENV:
            os.environ.pop(k, None)
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v


class TestChallengeDetect(_CuEnv, unittest.TestCase):
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

    def test_geetest_friendly_waf_datadome_markers(self):
        self.assertEqual(challenge.detect(html='<div class="geetest_holder"></div>')["kind"], "geetest")
        self.assertEqual(
            challenge.detect(html='<div class="frc-captcha" data-sitekey="x"></div>')["kind"],
            "friendlycaptcha",
        )
        self.assertEqual(
            challenge.detect(html='<script src="https://token.awswaf.com/challenge.js">')["kind"],
            "aws_waf",
        )
        self.assertEqual(
            challenge.detect(html='<script src="https://geo.captcha-delivery.com/captcha">')["kind"],
            "datadome",
        )
        self.assertEqual(challenge.detect(html='<div id="px-captcha"></div>')["kind"], "perimeterx")

    def test_page_challenge_sees_late_loaded_iframe_url(self):
        class _Frame:
            url = "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/turnstile"

        class _Page:
            url = "https://example.com/login"
            frames = [_Frame()]

            def title(self):
                return "Sign in"

            def content(self):
                return "<form><input type=password></form>"

        hit = challenge.page_challenge(_Page())
        self.assertTrue(hit["found"])
        self.assertEqual(hit["kind"], "turnstile")

    def test_wait_cleared_polls_until_widget_gone(self):
        class _Page:
            url = "https://example.com/login"
            frames = []

            def __init__(self):
                self.n = 0

            def title(self):
                return "Sign in"

            def content(self):
                self.n += 1
                if self.n < 3:
                    return '<div class="cf-turnstile"></div>'
                return "<form><input type=password></form>"

        cleared = challenge.wait_cleared(_Page(), timeout_ms=1000, interval_ms=5)
        self.assertIsNone(cleared)

    def test_wait_cleared_times_out_if_still_present(self):
        class _Page:
            url = "https://example.com/login"
            frames = []

            def title(self):
                return "Sign in"

            def content(self):
                return '<div class="cf-turnstile"></div>'

        hit = challenge.wait_cleared(_Page(), timeout_ms=40, interval_ms=10)
        self.assertIsNotNone(hit)
        self.assertTrue(hit["found"])
        self.assertEqual(hit["kind"], "turnstile")

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


class TestChallengePolicy(_CuEnv, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="wick-chal-")
        os.environ["WICK_HOME"] = self._tmp.name
        os.environ.pop("WICK_POLICY", None)
        os.environ.pop("WICK_HALT_ON_CHALLENGE", None)

    def tearDown(self):
        os.environ.pop("WICK_HOME", None)
        os.environ.pop("WICK_POLICY", None)
        os.environ.pop("WICK_HALT_ON_CHALLENGE", None)
        self._tmp.cleanup()
        super().tearDown()

    def test_policy_can_force_halt(self):
        import json
        import policy

        path = Path(self._tmp.name) / "policy.json"
        path.write_text(json.dumps({"halt_on_challenge": False}), encoding="utf-8")
        os.environ["WICK_POLICY"] = str(path)
        self.assertFalse(challenge.halt_on_challenge())
        os.environ["WICK_HALT_ON_CHALLENGE"] = "1"
        self.assertTrue(challenge.halt_on_challenge())


class TestComputerUseOnChallenge(_CuEnv, unittest.TestCase):
    """Desktop / Hermes / Grokbot may click a challenge; vault secrets may not."""

    def _hit(self):
        return challenge.detect(html='<div class="cf-turnstile" data-sitekey="x"></div>')

    def test_headless_cloud_disallows_computer_use(self):
        self.assertFalse(challenge.computer_use_allowed())
        hit = self._hit()
        self.assertFalse(hit["computer_use"])
        self.assertIsNotNone(challenge.deny_if_halted(hit, action="click"))
        self.assertIsNotNone(challenge.deny_if_halted(hit, action="login"))

    def test_explicit_flag_allows_click_not_login(self):
        os.environ["WICK_CHALLENGE_COMPUTER_USE"] = "1"
        self.assertTrue(challenge.computer_use_allowed())
        hit = self._hit()
        self.assertTrue(hit["computer_use"])
        self.assertTrue(hit["halt"])
        self.assertIsNone(challenge.deny_if_halted(hit, action="click"))
        self.assertIsNone(challenge.deny_if_halted(hit, action="click_xy"))
        self.assertIsNone(challenge.deny_if_halted(hit, action="type"))
        self.assertIsNone(challenge.deny_if_halted(hit, action="key"))
        self.assertIsNone(challenge.deny_if_halted(hit, action="drag"))
        blocked = challenge.deny_if_halted(hit, action="login")
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked["error"], "human_challenge")
        self.assertFalse(blocked["solves"])
        self.assertIsNotNone(challenge.deny_if_halted(hit, action="passkey"))
        self.assertIsNotNone(challenge.deny_if_halted(hit, action="fill", secret=True))
        self.assertIsNone(challenge.deny_if_halted(hit, action="fill", secret=False))

    def test_headed_desktop_session_allows_computer_use(self):
        os.environ.pop("WICK_CHALLENGE_COMPUTER_USE", None)
        os.environ["WICK_HEADLESS"] = "0"
        self.assertTrue(challenge.desktop_session())
        self.assertTrue(challenge.computer_use_allowed())

    def test_xdg_user_seat_allows_computer_use(self):
        os.environ.pop("WICK_CHALLENGE_COMPUTER_USE", None)
        os.environ["XDG_SESSION_TYPE"] = "wayland"
        os.environ["XDG_CURRENT_DESKTOP"] = "GNOME"
        self.assertTrue(challenge.desktop_session())
        self.assertTrue(challenge.computer_use_allowed())

    def test_display_alone_is_not_a_user_desktop(self):
        os.environ.pop("WICK_CHALLENGE_COMPUTER_USE", None)
        os.environ["DISPLAY"] = ":1"
        self.assertFalse(challenge.desktop_session())
        self.assertFalse(challenge.computer_use_allowed())

    def test_cu_hint_has_no_solver_and_names_computer_use(self):
        os.environ["WICK_CHALLENGE_COMPUTER_USE"] = "1"
        hit = self._hit()
        hint = (hit.get("hint") or "").lower()
        self.assertIn("computer-use", hint.replace(" ", "-") if "computer use" not in hint else hint)
        self.assertIn("cu", hint)
        blob = json_blob(hit).lower()
        for banned in ("2captcha", "anticaptcha", "solver", "bypass", "auto-submit"):
            self.assertNotIn(banned, blob)

    def test_policy_can_enable_computer_use(self):
        import json
        import policy

        tmp = tempfile.TemporaryDirectory(prefix="wick-cu-pol-")
        try:
            os.environ["WICK_HOME"] = tmp.name
            path = Path(tmp.name) / "policy.json"
            path.write_text(json.dumps({"challenge_computer_use": True}), encoding="utf-8")
            os.environ["WICK_POLICY"] = str(path)
            os.environ.pop("WICK_CHALLENGE_COMPUTER_USE", None)
            self.assertTrue(policy.effective()["challenge_computer_use"])
            self.assertTrue(challenge.computer_use_allowed())
        finally:
            os.environ.pop("WICK_POLICY", None)
            os.environ.pop("WICK_HOME", None)
            tmp.cleanup()


def json_blob(obj) -> str:
    import json

    return json.dumps(obj)


if __name__ == "__main__":
    unittest.main()
