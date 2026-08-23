#!/usr/bin/env python3
"""Ephemeral session lifecycle: new, promote, drop, sweep."""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import shields  # noqa: E402


class TestEphemeralSession(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._td = tempfile.TemporaryDirectory()
        os.environ["WICK_HOME"] = self._td.name
        # reload paths on shields
        shields.HOME = Path(self._td.name)
        shields.SHIELDS = shields.HOME / "shields"
        shields.SESSIONS = shields.HOME / "sessions"

    def tearDown(self):
        self._td.cleanup()

    def test_new_ephemeral_writes_meta(self):
        out = shields.new_session("job1", ephemeral=True, ttl=60, owner="agent-a")
        self.assertTrue(out["ok"])
        self.assertTrue(out["ephemeral"])
        meta = shields.session_meta("job1")
        self.assertTrue(meta["ephemeral"])
        self.assertEqual(meta["owner"], "agent-a")
        self.assertEqual(meta["ttl"], 60)
        self.assertFalse(meta["promoted"])
        listed = {s["name"]: s for s in shields.list_sessions()}
        self.assertTrue(listed["job1"]["ephemeral"])

    def test_promote_clears_ephemeral(self):
        shields.new_session("job2", ephemeral=True, ttl=3600)
        load, jar = shields.session_cookie_paths("job2")
        jar.write_text("[]\n", encoding="utf-8")
        promo = shields.promote_session("job2")
        self.assertTrue(promo["ok"])
        meta = shields.session_meta("job2")
        self.assertTrue(meta["promoted"])
        self.assertFalse(meta["ephemeral"])
        self.assertTrue(load.is_file())

    def test_drop_removes_dir(self):
        shields.new_session("gone", ephemeral=True)
        self.assertTrue((shields.SESSIONS / "gone").is_dir())
        out = shields.drop_session("gone")
        self.assertTrue(out["ok"])
        self.assertFalse((shields.SESSIONS / "gone").exists())

    def test_sweep_drops_expired_unpromoted(self):
        shields.new_session("old", ephemeral=True, ttl=1)
        meta_path = shields.SESSIONS / "old" / "meta.json"
        raw = meta_path.read_text(encoding="utf-8")
        # backdate created
        import json

        data = json.loads(raw)
        data["created_ts"] = time.time() - 120
        meta_path.write_text(json.dumps(data), encoding="utf-8")
        shields.new_session("kept", ephemeral=True, ttl=3600)
        result = shields.sweep_sessions()
        self.assertTrue(result["ok"])
        names = [s["name"] for s in result["dropped"]]
        self.assertIn("old", names)
        self.assertFalse((shields.SESSIONS / "old").exists())
        self.assertTrue((shields.SESSIONS / "kept").exists())


if __name__ == "__main__":
    unittest.main()
