#!/usr/bin/env python3
"""Short-TTL observe cache for snap → plan → ask loops."""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import observe_cache  # noqa: E402


class TestObserveCache(unittest.TestCase):
    def test_roundtrip_and_ttl(self):
        home = Path(self.id().replace(".", "_"))
        # use tmp via env
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            os.environ["WICK_HOME"] = td
            os.environ["WICK_OBSERVE_CACHE"] = "1"
            os.environ["WICK_OBSERVE_CACHE_TTL"] = "1"
            key = observe_cache.cache_key(
                url="https://example.com/",
                fast=True,
                wait_ms=1200,
                session="default",
                mode="snap",
            )
            observe_cache.put(key, {"ok": True, "url": "https://example.com/", "excerpt": "hi"})
            hit = observe_cache.get(key)
            self.assertIsNotNone(hit)
            self.assertEqual(hit["excerpt"], "hi")
            self.assertTrue(hit.get("_cache_hit"))
            time.sleep(1.1)
            miss = observe_cache.get(key)
            self.assertIsNone(miss)

    def test_disabled(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            os.environ["WICK_HOME"] = td
            os.environ["WICK_OBSERVE_CACHE"] = "0"
            key = observe_cache.cache_key(
                url="https://example.com/",
                fast=False,
                wait_ms=2000,
                session="default",
                mode="snap",
            )
            observe_cache.put(key, {"ok": True})
            self.assertIsNone(observe_cache.get(key))


if __name__ == "__main__":
    unittest.main()
