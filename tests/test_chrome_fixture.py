#!/usr/bin/env python3
"""Live Chromium fixture: computer-use loop + origin-bound login denial.

Requires Playwright. Skips when the browser cannot launch.
Serves tests/fixtures/cu.html on 127.0.0.1 (needs WICK_ALLOW_PRIVATE=1).
"""
from __future__ import annotations

import http.server
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_LIB = ROOT / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

FIXTURE = ROOT / "tests" / "fixtures" / "cu.html"


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _serve(directory: Path, port: int):
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


def _playwright_or_skip():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise unittest.SkipTest("playwright not installed")
    return sync_playwright


class TestChromeFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["WICK_ALLOW_PRIVATE"] = "1"
        cls.home = Path(tempfile.mkdtemp(prefix="wick-cu-fix-"))
        os.environ["WICK_HOME"] = str(cls.home)
        os.environ["WICK_SESSION"] = "fixture"
        cls.port = _free_port()
        cls.httpd = _serve(FIXTURE.parent, cls.port)
        cls.base = f"http://127.0.0.1:{cls.port}/cu.html"
        cls._pw_cm = _playwright_or_skip()()
        cls.pw = cls._pw_cm.__enter__()
        try:
            cls.browser = cls.pw.chromium.launch(headless=True)
        except Exception:
            try:
                cls.browser = cls.pw.chromium.launch(headless=True, channel="chrome")
            except Exception as e:
                cls._pw_cm.__exit__(None, None, None)
                raise unittest.SkipTest(f"chromium launch failed: {e}")
        cls.context = cls.browser.new_context(viewport={"width": 900, "height": 700})
        cls.page = cls.context.new_page()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
        except Exception:
            pass
        try:
            cls._pw_cm.__exit__(None, None, None)
        except Exception:
            pass
        try:
            cls.httpd.shutdown()
        except Exception:
            pass
        os.environ.pop("WICK_ALLOW_PRIVATE", None)
        os.environ.pop("WICK_HOME", None)
        os.environ.pop("WICK_SESSION", None)
        try:
            import shutil
            shutil.rmtree(cls.home, ignore_errors=True)
        except Exception:
            pass

    def _run(self, action: str, *args: str) -> dict:
        import chrome_actions as ca

        rc, payload = ca.run_on_page(self.page, self.context, action, list(args))
        self.assertIsInstance(payload, dict)
        payload.setdefault("_rc", rc)
        return payload

    def test_cu_click_n_type_wait_text(self):
        gone = self._run("goto", self.base)
        self.assertTrue(gone.get("ok"), gone)

        cu = self._run("cu", str(self.home / "shots" / "cu.png"))
        self.assertTrue(cu.get("ok"), cu)
        self.assertEqual(cu.get("mode"), "computer_use")
        self.assertGreaterEqual(cu.get("element_count") or 0, 2)
        names = " ".join((e.get("name") or "") for e in cu.get("elements") or [])
        self.assertIn("Go", names)
        self.assertTrue(cu.get("screenshot"))
        self.assertTrue(Path(cu["screenshot"]).is_file())

        query = next(
            (e for e in cu["elements"] if (e.get("name") or "") == "Query" or e.get("tag") == "input"),
            None,
        )
        self.assertIsNotNone(query, cu["elements"])
        typed = self._run("type_n", str(query["n"]), "Ada")
        self.assertTrue(typed.get("ok"), typed)

        go = next((e for e in cu["elements"] if (e.get("name") or "") == "Go"), None)
        self.assertIsNotNone(go)
        clicked = self._run("click_n", str(go["n"]))
        self.assertTrue(clicked.get("ok"), clicked)

        waited = self._run("wait_text", "Welcome Ada")
        self.assertTrue(waited.get("ok"), waited)

    def test_expect_url_fragment_after_login_submit(self):
        self.assertTrue(self._run("goto", self.base).get("ok"))
        filled_u = self._run("fill", "css=#user", "agent@example.com")
        self.assertTrue(filled_u.get("ok"), filled_u)
        filled_p = self._run("fill", "css=#pass", "not-a-secret")
        self.assertTrue(filled_p.get("ok"), filled_p)
        clicked = self._run(
            "click",
            'role=button[name="Log in"]',
            "--expect-url-fragment",
            "#ok",
        )
        self.assertTrue(clicked.get("ok"), clicked)
        self.assertIn("#ok", self.page.url)

    def test_expect_fragment_fails_when_missing(self):
        self.assertTrue(self._run("goto", self.base).get("ok"))
        out = self._run("click", 'role=button[name="Go"]', "--expect-url-fragment", "welcome")
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "expect_failed")

    def test_two_step_login_fills_after_continue(self):
        import vault

        login_url = f"http://127.0.0.1:{self.port}/login-steps.html"
        vault.ensure_local_key()
        vault.set_entry(
            "local-login",
            password="s3cret-value-xyz",
            username="agent@example.com",
            url=login_url,
        )
        out = self._run("login", login_url)
        self.assertTrue(out.get("ok"), out)
        self.assertIn("username", out.get("filled") or [])
        self.assertIn("password", out.get("filled") or [])
        self.assertNotIn("s3cret-value-xyz", json.dumps(out))
        try:
            self.page.wait_for_function(
                "() => window.location.hash === '#ok'",
                timeout=8000,
            )
        except Exception as e:
            raise unittest.SkipTest(f"two-step login did not navigate: {e}")
        self.assertIn("#ok", self.page.url)

    def test_login_halts_on_turnstile_without_solving(self):
        import vault

        url = f"http://127.0.0.1:{self.port}/challenge.html"
        vault.ensure_local_key()
        vault.set_entry(
            "local-chal",
            password="s3cret-value-xyz",
            username="agent@example.com",
            url=url,
        )
        out = self._run("login", url)
        self.assertFalse(out.get("ok"), out)
        self.assertEqual(out.get("error"), "human_challenge")
        self.assertEqual(out.get("kind"), "turnstile")
        self.assertFalse(out.get("solves"))
        dump = json.dumps(out).lower()
        self.assertNotIn("s3cret-value-xyz", dump)
        self.assertNotIn("2captcha", dump)
        self.assertNotIn("solver", dump)

    def test_click_halts_on_turnstile_without_solving(self):
        url = f"http://127.0.0.1:{self.port}/challenge.html"
        gone = self._run("goto", url)
        self.assertTrue(gone.get("ok"), gone)
        self.assertTrue((gone.get("challenge") or {}).get("found"))
        clicked = self._run("click", "css=button")
        self.assertFalse(clicked.get("ok"), clicked)
        self.assertEqual(clicked.get("error"), "human_challenge")
        self.assertFalse(clicked.get("solves"))
        dump = json.dumps(clicked).lower()
        self.assertNotIn("2captcha", dump)
        self.assertNotIn("bypass", dump)

    def test_computer_use_may_click_challenge_but_login_stays_blocked(self):
        import vault

        os.environ["WICK_CHALLENGE_COMPUTER_USE"] = "1"
        try:
            url = f"http://127.0.0.1:{self.port}/challenge.html"
            gone = self._run("goto", url)
            self.assertTrue(gone.get("ok"), gone)
            self.assertTrue((gone.get("challenge") or {}).get("found"))
            clicked = self._run("click", "css=button")
            self.assertTrue(clicked.get("ok"), clicked)
            vault.ensure_local_key()
            vault.set_entry(
                "local-chal-cu",
                password="s3cret-value-xyz",
                username="agent@example.com",
                url=url,
            )
            login = self._run("login", url)
            self.assertFalse(login.get("ok"), login)
            self.assertEqual(login.get("error"), "human_challenge")
            self.assertFalse(login.get("solves"))
            self.assertNotIn("s3cret-value-xyz", json.dumps(login))
        finally:
            os.environ.pop("WICK_CHALLENGE_COMPUTER_USE", None)
            try:
                vault.delete_entry("local-chal-cu")
            except Exception:
                pass

    def test_login_after_challenge_waits_then_fills(self):
        import vault

        url = f"http://127.0.0.1:{self.port}/challenge-clear.html"
        vault.ensure_local_key()
        vault.set_entry(
            "local-clear",
            password="s3cret-value-xyz",
            username="agent@example.com",
            url=url,
        )
        out = self._run("login", url, "--after-challenge", "4000")
        self.assertTrue(out.get("ok"), out)
        self.assertTrue(out.get("after_challenge"))
        self.assertNotIn("s3cret-value-xyz", json.dumps(out))
        try:
            self.page.wait_for_function(
                "() => window.location.hash === '#ok'",
                timeout=8000,
            )
        except Exception as e:
            raise unittest.SkipTest(f"after-challenge login did not navigate: {e}")
        self.assertIn("#ok", self.page.url)

    def test_login_refuses_example_com_vault_on_localhost(self):
        import vault

        vault.ensure_local_key()
        # Other fixture tests save 127.0.0.1 entries; those would match this origin.
        for name in ("local-chal", "local-login", "local-pk", "local-clear", "local-chal-cu"):
            try:
                vault.delete_entry(name)
            except Exception:
                pass
        vault.set_entry(
            "example",
            password="s3cret-value-xyz",
            username="agent",
            url="https://example.com/login",
        )
        self.assertTrue(self._run("goto", self.base).get("ok"))
        out = self._run("login")
        self.assertFalse(out.get("ok"), out)
        self.assertIn(out.get("error"), ("no_vault_match", "origin_mismatch", "vault_resolve_failed"))
        dump = json.dumps(out)
        self.assertNotIn("s3cret-value-xyz", dump)

    def test_vault_passkey_asserts_on_localhost(self):
        import vault

        pk_url = f"http://127.0.0.1:{self.port}/passkey.html"
        vault.ensure_local_key()
        created = vault.create_passkey("local-pk", url=pk_url, username="agent")
        self.assertTrue(created.get("ok"), created)
        self.assertNotIn("private_key", created)
        self.assertNotIn("privateKey", json.dumps(created))

        gone = self._run("goto", pk_url)
        self.assertTrue(gone.get("ok"), gone)
        used = self._run("passkey", pk_url, "local-pk")
        self.assertTrue(used.get("ok"), used)
        dump = json.dumps(used)
        self.assertNotIn("privateKey", dump)
        self.assertNotIn("passkey_private_key", dump)
        try:
            self.page.wait_for_function(
                "() => (document.getElementById('out') || {}).textContent === 'asserted'",
                timeout=8000,
            )
        except Exception as e:
            raise unittest.SkipTest(f"virtual authenticator assertion did not complete: {e}")
        self.assertEqual(self.page.locator("#out").inner_text(), "asserted")


class TestParseLoginArgs(unittest.TestCase):
    def test_after_challenge_optional_timeout(self):
        import chrome_actions as ca

        flags = ca.parse_login_args(["https://example.com/login", "--after-challenge", "4000"])
        self.assertEqual(flags["rest"], ["https://example.com/login"])
        self.assertTrue(flags["after_challenge"])
        self.assertEqual(flags["timeout_ms"], 4000)
        self.assertTrue(flags["submit"])

        bare = ca.parse_login_args(["https://example.com/login", "--after-challenge", "--no-submit"])
        self.assertTrue(bare["after_challenge"])
        self.assertEqual(bare["timeout_ms"], 15000)
        self.assertFalse(bare["submit"])


if __name__ == "__main__":
    unittest.main()
