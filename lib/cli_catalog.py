"""CLI catalog so shell-only agents can run the full Wick surface.

MCP and RPC are optional sockets. The command line is the product:
every tool/RPC action has a `wick …` invocation that prints one JSON object.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

try:
    import agent_skill as wick_skill
except Exception:
    wick_skill = None  # type: ignore

_BOOL_FLAGS = {
    "fast": "--fast",
    "here": "--here",
    "full": "--full",
    "fail_http": "--fail-http",
    "no_submit": "--no-submit",
    "no_strip": "--no-strip",
    "ephemeral": "--ephemeral",
    "reveal": "--reveal",
    "force": "--force",
}

_OPT_FLAGS = {
    "profile": "--profile",
    "q": "--q",
    "section": "--section",
    "ttl": "--ttl",
    "owner": "--owner",
    "limit": "--limit",
    "dest": "--dest",
    "src": "--src",
    "file": "--file",
    "concurrency": "--concurrency",
    "max": "--max",
}

# url is positional on observe commands, --url on vault/session/pdf.
_POSITIONAL_URL = frozenset(
    {"snap", "observe", "read", "plan", "ask", "open", "elements", "challenge"}
)

_SAMPLES: dict[str, dict[str, Any]] = {
    "skill": {},
    "commands": {},
    "help": {},
    "call": {},
    "snap": {"url": "https://example.com/", "fast": True},
    "observe": {"url": "https://example.com/", "fast": True},
    "read": {"q": "rfc 2606"},
    "plan": {"url": "https://example.com/", "fast": True},
    "ask": {"url": "https://example.com/", "q": "more information"},
    "open": {"url": "https://example.com/", "fast": True},
    "elements": {"url": "https://example.com/"},
    "act": {"action": "click", "rest": ['role=link[name="More information"]']},
    "session": {"action": "list"},
    "vault": {"action": "suggest", "url": "https://example.com/"},
    "challenge": {"url": "https://example.com/"},
    "snap-many": {"urls": ["https://example.com/", "https://example.org/"]},
    "snap_many": {"urls": ["https://example.com/", "https://example.org/"]},
}

# Agent-facing commands (same coverage as wick tools / RPC). Not every human flag.
_CATALOG: list[dict[str, str]] = [
    {"name": "skill", "cli": "wick skill", "tool": "wick_skill", "rpc": "skill", "when": "once at session start"},
    {"name": "commands", "cli": "wick commands", "rpc": "commands", "when": "full CLI catalog + example argv"},
    {"name": "call", "cli": "wick call CMD '{json}'", "when": "same JSON args as RPC/tools, via the CLI"},
    {"name": "help", "cli": "wick help", "rpc": "commands", "when": "alias of wick commands"},
    {"name": "snap", "cli": "wick snap [URL] --fast", "tool": "wick_snap", "rpc": "snap", "when": "first look; omit URL after act"},
    {"name": "observe", "cli": "wick observe [URL] --fast", "tool": "wick_observe", "rpc": "observe", "when": "alias of snap"},
    {"name": "read", "cli": "wick read [URL] [--q terms] [--section Heading]", "tool": "wick_read", "rpc": "read", "when": "structured body; prefer over open"},
    {"name": "plan", "cli": "wick plan [URL] --fast", "tool": "wick_plan", "rpc": "plan", "when": "goal-agnostic next cmds"},
    {"name": "ask", "cli": "wick ask [URL] --q terms", "tool": "wick_ask", "rpc": "ask", "when": "filter links/headings/paragraphs"},
    {"name": "open", "cli": "wick open URL --fast", "tool": "wick_open", "rpc": "open", "when": "full markdown dump"},
    {"name": "elements", "cli": "wick elements URL", "tool": "wick_elements", "rpc": "elements", "when": "click targets only"},
    {"name": "act", "cli": "wick act ACTION [args…]", "tool": "wick_act", "rpc": "act", "when": "click/fill/login/cu using THIS snap's hints"},
    {"name": "session", "cli": "wick session ACTION [name]", "tool": "wick_session", "rpc": "session", "when": "cookie isolation"},
    {"name": "vault", "cli": "wick vault ACTION [--url URL]", "tool": "wick_vault", "rpc": "vault", "when": "suggest/list/match — never secrets"},
    {"name": "challenge", "cli": "wick challenge URL", "tool": "wick_challenge", "rpc": "challenge", "when": "observe-only detect; never solve"},
    {"name": "snap-many", "cli": "wick snap-many URL URL…", "tool": "wick_snap_many", "rpc": "snap_many", "when": "several pages, serialized Chromium"},
]


def normalize_cmd(name: str | None) -> str:
    raw = (name or "").strip()
    if raw.startswith("wick_"):
        raw = raw[5:]
    return raw.replace("-", "_")


def argv_from_call(cmd: str, args: dict[str, Any] | None = None) -> list[str]:
    """Build `wick …` argv from an RPC / OpenAI-tool args object."""
    payload = dict(args or {})
    key = normalize_cmd(cmd)
    if key in {"snap_many"}:
        out = ["wick", "snap-many"]
        out.extend(str(u) for u in (payload.get("urls") or []) if str(u).strip())
        _append_flags(out, payload, skip={"urls"})
        return out
    if key == "act":
        action = str(payload.get("action") or "").strip()
        out = ["wick", "act"]
        if action:
            out.append(action)
        out.extend(str(x) for x in (payload.get("rest") or []))
        ac = payload.get("after_challenge")
        if ac not in (None, False):
            out.append("--after-challenge")
            if isinstance(ac, (int, float)) and not isinstance(ac, bool):
                out.append(str(int(ac)))
        if payload.get("no_submit"):
            out.append("--no-submit")
        if payload.get("expect_url_fragment"):
            out.extend(["--expect-url-fragment", str(payload["expect_url_fragment"])])
        if payload.get("expect_element"):
            out.extend(["--expect-element", str(payload["expect_element"])])
        return out
    if key == "vault":
        out = ["wick", "vault", str(payload.get("action") or "status")]
        if payload.get("name"):
            out.append(str(payload["name"]))
        if payload.get("url"):
            out.extend(["--url", str(payload["url"])])
        _append_flags(out, payload, skip={"action", "name", "url"})
        return out
    if key == "session":
        out = ["wick", "session", str(payload.get("action") or "list")]
        if payload.get("name"):
            out.append(str(payload["name"]))
        _append_flags(out, payload, skip={"action", "name"})
        return out
    if key == "call":
        target = str(payload.get("cmd") or payload.get("name") or "snap")
        body = payload.get("args")
        out = ["wick", "call", target]
        if isinstance(body, dict) and body:
            import json

            out.append(json.dumps(body, ensure_ascii=False))
        return out
    cli_name = "snap-many" if key == "snap_many" else key.replace("_", "-")
    if key in {"skill", "commands", "help", "tools", "version", "status"}:
        return ["wick", cli_name]
    out = ["wick", cli_name]
    if key in _POSITIONAL_URL:
        if payload.get("here"):
            out.append("--here")
        elif payload.get("url"):
            out.append(str(payload["url"]))
        _append_flags(out, payload, skip={"url", "here"})
        return out
    if payload.get("url"):
        out.append(str(payload["url"]))
    _append_flags(out, payload, skip={"url"})
    return out


def _append_flags(out: list[str], payload: dict[str, Any], *, skip: set[str]) -> None:
    for key, flag in _BOOL_FLAGS.items():
        if key in skip:
            continue
        if payload.get(key):
            out.append(flag)
    for key, flag in _OPT_FLAGS.items():
        if key in skip:
            continue
        val = payload.get(key)
        if val is None or val is False:
            continue
        if isinstance(val, bool):
            continue
        out.extend([flag, str(val)])


def cli_map() -> dict[str, str]:
    return {c["tool"]: c["cli"] for c in _CATALOG if c.get("tool")}


def commands_export(version: str) -> dict[str, Any]:
    purpose = (
        wick_skill.PURPOSE
        if wick_skill is not None
        else "Wick is a standalone Chromium browser for agents."
    )
    loop = list(wick_skill.LOOP) if wick_skill is not None else []
    rules = list(wick_skill.RULES) if wick_skill is not None else []
    commands: list[dict[str, Any]] = []
    for row in _CATALOG:
        item = dict(row)
        sample = _SAMPLES.get(row["name"]) or _SAMPLES.get(normalize_cmd(row["name"])) or {}
        if row["name"] not in {"call", "help"}:
            item["example"] = argv_from_call(row["name"], sample)
        elif row["name"] == "call":
            item["example"] = [
                "wick",
                "call",
                "snap",
                '{"url":"https://example.com/","fast":true}',
            ]
        else:
            item["example"] = ["wick", "help"]
        commands.append(item)
    return {
        "ok": True,
        "product": "wick",
        "version": version,
        "mode": "agent_cli",
        "schema": "wick_cli_v1",
        "purpose": purpose,
        "loop": loop,
        "rules": rules,
        "surface": "cli",
        "hint": (
            "You have a shell. Run commands[].cli — every command prints one JSON object. "
            "wick call CMD '{json}' uses the same args as RPC/tools. "
            "Do not start wick mcp or wick rpc unless your harness requires a socket."
        ),
        "call": "wick call snap '{\"url\":\"https://example.com/\",\"fast\":true}'",
        "commands": commands,
        "cli": cli_map(),
    }
