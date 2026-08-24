"""JSON-lines stdio RPC for Wick agent harness integration."""
from __future__ import annotations

import json
import sys
from typing import Any, Callable

Handler = Callable[[dict[str, Any]], dict[str, Any]]


def parse_line(line: str) -> dict[str, Any] | None:
    line = (line or "").strip()
    if not line:
        return None
    try:
        req = json.loads(line)
    except json.JSONDecodeError as e:
        return {"id": None, "ok": False, "error": "bad_json", "detail": str(e)[:160]}
    if not isinstance(req, dict):
        return {"id": None, "ok": False, "error": "request_must_be_object"}
    return req


def handle_request(req: dict[str, Any], handlers: dict[str, Handler]) -> dict[str, Any]:
    req_id = req.get("id")
    cmd = req.get("cmd")
    args = req.get("args")
    if not cmd or not isinstance(cmd, str):
        return {
            "id": req_id,
            "ok": False,
            "soft": True,
            "error": "missing_cmd",
            "hint": 'Each line: {"id":1,"cmd":"snap","args":{"url":"https://example.com/"}}',
        }
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return {"id": req_id, "ok": False, "error": "args_must_be_object"}

    handler = handlers.get(cmd)
    if handler is None:
        return {
            "id": req_id,
            "ok": False,
            "soft": True,
            "error": "unknown_cmd",
            "cmd": cmd,
            "hint": "Known: skill, commands, snap, read, observe, plan, ask, open, elements, act, session, vault, challenge, tools, version, status",
        }

    try:
        result = handler(args)
        if not isinstance(result, dict):
            result = {"ok": True, "result": result}
        if "ok" not in result:
            result["ok"] = True
        result["id"] = req_id
        return result
    except Exception as e:
        return {
            "id": req_id,
            "ok": False,
            "error": "handler_failed",
            "detail": str(e)[:200],
        }


def run_stdio_loop(handlers: dict[str, Handler]) -> int:
    """Read JSON lines from stdin; write one JSON object per line to stdout."""
    for raw in sys.stdin:
        req = parse_line(raw)
        if req is None:
            continue
        if req.get("error") == "bad_json" and "cmd" not in req:
            print(json.dumps(req, ensure_ascii=False), flush=True)
            continue
        resp = handle_request(req, handlers)
        print(json.dumps(resp, ensure_ascii=False), flush=True)
    return 0
