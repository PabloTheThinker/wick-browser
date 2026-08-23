#!/usr/bin/env python3
"""Harness approval gate for credential actions."""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import approval  # noqa: E402


class TestApproval(unittest.TestCase):
    def setUp(self):
        for k in ("WICK_REQUIRE_APPROVAL", "WICK_APPROVE", "WICK_APPROVE_ONCE", "WICK_HOME"):
            os.environ.pop(k, None)

    def tearDown(self):
        for k in ("WICK_REQUIRE_APPROVAL", "WICK_APPROVE", "WICK_APPROVE_ONCE", "WICK_HOME"):
            os.environ.pop(k, None)

    def test_off_by_default(self):
        self.assertIsNone(approval.check("login"))
        self.assertIsNone(approval.check("passkey"))

    def test_require_blocks_until_approved(self):
        os.environ["WICK_REQUIRE_APPROVAL"] = "1"
        denied = approval.check("login")
        self.assertIsNotNone(denied)
        self.assertEqual(denied["error"], "approval_required")
        self.assertEqual(denied["action"], "login")
        self.assertIsNone(approval.check("goto"))

        os.environ["WICK_APPROVE"] = "login"
        self.assertIsNone(approval.check("login"))
        still = approval.check("passkey")
        self.assertIsNotNone(still)

    def test_file_token_ttl_and_once(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            os.environ["WICK_HOME"] = td
            os.environ["WICK_REQUIRE_APPROVAL"] = "login,passkey"
            issued = approval.issue(["login"], ttl=60)
            self.assertTrue(issued["ok"])
            self.assertIsNone(approval.check("login"))
            os.environ["WICK_APPROVE_ONCE"] = "1"
            self.assertIsNone(approval.check("login"))
            denied = approval.check("login")
            self.assertIsNotNone(denied)

    def test_expired_file_does_not_approve(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            os.environ["WICK_HOME"] = td
            os.environ["WICK_REQUIRE_APPROVAL"] = "login"
            approval.issue(["login"], ttl=1)
            time.sleep(1.1)
            denied = approval.check("login")
            self.assertIsNotNone(denied)


if __name__ == "__main__":
    unittest.main()
