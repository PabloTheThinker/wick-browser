#!/usr/bin/env python3
"""Privacy leak guards and fingerprint *reporting* — not stealth farbling."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import privacy  # noqa: E402


class TestPrivacyGuards(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("WICK_WEBRTC_IP_GUARD", None)
        os.environ.pop("WICK_REDUCE_CLIENT_HINTS", None)

    def test_webrtc_args_block_lan_ice(self):
        args = privacy.webrtc_args()
        joined = " ".join(args)
        self.assertIn("disable_non_proxied_udp", joined)
        self.assertFalse(privacy.status()["fingerprint_farbling"])
        self.assertTrue(privacy.status()["webrtc_ip_guard"])

    def test_webrtc_guard_can_be_disabled(self):
        os.environ["WICK_WEBRTC_IP_GUARD"] = "0"
        self.assertEqual(privacy.webrtc_args(), [])
        self.assertFalse(privacy.status()["webrtc_ip_guard"])

    def test_client_hint_reduction_is_privacy_not_spoof(self):
        args = privacy.chrome_privacy_args()
        joined = " ".join(args)
        self.assertIn("UserAgentClientHint", joined)
        # We reduce entropy; we do not spoof another browser's UA.
        self.assertNotIn("--user-agent=", joined)

    def test_fingerprint_probes_reported(self):
        probes = privacy.fingerprint_probes(
            url="https://example.com/",
            excerpt="loading FingerprintJS",
            links=[{"href": "https://api.fpjs.io/v3", "text": "fp"}],
            elements=[],
        )
        kinds = {p["kind"] for p in probes}
        self.assertIn("fingerprintjs", kinds)
        self.assertTrue(all("farble" not in p.get("kind", "") for p in probes))

    def test_clean_page_has_no_probes(self):
        probes = privacy.fingerprint_probes(
            url="https://example.com/login",
            excerpt="Sign in to your account",
            links=[{"href": "https://example.com/about", "text": "About"}],
            elements=[],
        )
        self.assertEqual(probes, [])

    def test_honest_status_never_claims_farbling(self):
        st = privacy.status()
        self.assertFalse(st["fingerprint_farbling"])
        self.assertFalse(st["stealth"])
        self.assertIn("not claimed", st["not_claimed"].lower())


if __name__ == "__main__":
    unittest.main()
