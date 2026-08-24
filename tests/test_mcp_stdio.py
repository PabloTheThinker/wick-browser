#!/usr/bin/env python3
"""MCP JSON-RPC stdio surface for Hermes / Claude / Cursor."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import mcp_stdio  # noqa: E402


def _handlers():
    return {
        "snap": lambda a: {"ok": True, "url": a.get("url"), "title": "Example", "profile": a.get("profile")},
        "plan": lambda a: {"ok": True, "suggestions": []},
        "version": lambda a: {"ok": True, "version": "0.9.0"},
    }


class TestMcpProtocol(unittest.TestCase):
    def test_initialize(self):
        resp = mcp_stdio.handle_rpc(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            handlers=_handlers(),
            version="0.9.0",
        )
        self.assertEqual(resp["jsonrpc"], "2.0")
        self.assertEqual(resp["id"], 1)
        self.assertIn("result", resp)
        self.assertEqual(resp["result"]["serverInfo"]["name"], "wick")
        self.assertIn("tools", resp["result"]["capabilities"])

    def test_initialized_notification_is_none(self):
        resp = mcp_stdio.handle_rpc(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            handlers=_handlers(),
            version="0.9.0",
        )
        self.assertIsNone(resp)

    def test_tools_list_short_names(self):
        resp = mcp_stdio.handle_rpc(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            handlers=_handlers(),
            version="0.9.0",
        )
        names = {t["name"] for t in resp["result"]["tools"]}
        for n in ("snap", "plan", "ask", "act", "session", "vault", "snap_many", "challenge", "skill", "read", "commands"):
            self.assertIn(n, names)
        snap = next(t for t in resp["result"]["tools"] if t["name"] == "snap")
        self.assertIn("url", snap["inputSchema"]["properties"])
        self.assertIn("profile", snap["inputSchema"]["properties"])
        self.assertNotIn("url", snap["inputSchema"].get("required") or [])

    def test_tools_call_snap(self):
        resp = mcp_stdio.handle_rpc(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "snap", "arguments": {"url": "https://example.com/", "profile": "micro"}},
            },
            handlers=_handlers(),
            version="0.9.0",
        )
        self.assertFalse(resp["result"].get("isError"))
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertEqual(payload["url"], "https://example.com/")
        self.assertEqual(payload["profile"], "micro")

    def test_tools_call_alias_wick_snap(self):
        resp = mcp_stdio.handle_rpc(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "wick_snap", "arguments": {"url": "https://example.com/"}},
            },
            handlers=_handlers(),
            version="0.9.0",
        )
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertTrue(payload["ok"])

    def test_ping(self):
        resp = mcp_stdio.handle_rpc(
            {"jsonrpc": "2.0", "id": 9, "method": "ping"},
            handlers=_handlers(),
            version="0.9.0",
        )
        self.assertEqual(resp["result"], {})


if __name__ == "__main__":
    unittest.main()
