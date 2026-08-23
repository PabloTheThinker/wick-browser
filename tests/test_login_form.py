#!/usr/bin/env python3
"""Login form detection from semantic-tree elements (agent autofill targeting)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import elements  # noqa: E402
import login_form  # noqa: E402

LOGIN_TREE = """
1 document
  2 heading 'Sign in'
  3 textbox 'Email'
  4 textbox 'Password'
  5 [i] button 'Log in'
  6 [i] link 'Forgot password'
""".strip()

SEARCH_TREE = """
1 document
  2 textbox 'Search'
  3 [i] button 'Go'
""".strip()


class TestDetectLogin(unittest.TestCase):
    def test_detects_email_password_submit(self):
        els = elements.parse_tree_text(LOGIN_TREE)
        form = login_form.detect_login_fields(els)
        self.assertTrue(form["is_login"])
        self.assertEqual(form["username"]["name"], "Email")
        self.assertEqual(form["password"]["name"], "Password")
        self.assertEqual(form["submit"]["name"], "Log in")
        self.assertIn("role=textbox", form["username"]["hint"] or "")

    def test_search_is_not_login(self):
        els = elements.parse_tree_text(SEARCH_TREE)
        form = login_form.detect_login_fields(els)
        self.assertFalse(form["is_login"])
        self.assertIsNone(form["password"])


if __name__ == "__main__":
    unittest.main()
