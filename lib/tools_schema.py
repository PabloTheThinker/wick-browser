"""OpenAI-style function tool schemas for Wick agent commands."""
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

URL_PROP = {
    "type": "string",
    "description": (
        "Absolute URL to open. Omit, pass empty, or pass here to observe the current "
        "Chromium page after act — do not re-goto a page you are already on."
    ),
}

HERE_PROP = {
    "type": "boolean",
    "description": "Observe the current Chromium page (same as omitting url).",
    "default": False,
}

FAST_PROP = {
    "type": "boolean",
    "description": "Faster observe: domcontentloaded + ~1.2s wait. Skipped when the tab is reused.",
    "default": False,
}

FAIL_HTTP_PROP = {
    "type": "boolean",
    "description": "Treat non-2xx/3xx HTTP as failure (exit 2 on CLI).",
    "default": False,
}

PROFILE_PROP = {
    "type": "string",
    "enum": ["micro", "default", "full"],
    "description": "Observe budget: micro=tree only (~0.8s); default=fast excerpt; full=longer wait.",
}


def _fn(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


WICK_TOOLS: list[dict[str, Any]] = [
    _fn(
        "wick_skill",
        "Load Wick's compact agent skill: purpose, snap→plan→act loop, and hard rules. Call once at harness start.",
        {"type": "object", "properties": {}},
    ),
    _fn(
        "wick_snap",
        (
            "Primary observe: title, excerpt, links, interactive elements with role= hints. "
            "Omit url (or pass here) after act to reuse the current tab — do not re-goto. "
            "Use THIS snap's hints only. Prefer profile=micro for the cheapest first look."
        ),
        {
            "type": "object",
            "properties": {
                "url": URL_PROP,
                "here": HERE_PROP,
                "profile": PROFILE_PROP,
                "fast": FAST_PROP,
                "full": {
                    "type": "boolean",
                    "description": "Include full markdown body in response.",
                    "default": False,
                },
                "fail_http": FAIL_HTTP_PROP,
            },
        },
    ),
    _fn(
        "wick_observe",
        "Alias of wick_snap — compact observe snapshot for agents. Omit url to snap here.",
        {
            "type": "object",
            "properties": {
                "url": URL_PROP,
                "here": HERE_PROP,
                "profile": PROFILE_PROP,
                "fast": FAST_PROP,
                "full": {"type": "boolean", "default": False},
                "fail_http": FAIL_HTTP_PROP,
            },
        },
    ),
    _fn(
        "wick_plan",
        "Goal-agnostic next-step suggestions from a snap (open, click hints, screenshot, pdf, ask). Omit url after act.",
        {
            "type": "object",
            "properties": {
                "url": URL_PROP,
                "here": HERE_PROP,
                "profile": PROFILE_PROP,
                "fast": FAST_PROP,
                "fail_http": FAIL_HTTP_PROP,
            },
        },
    ),
    _fn(
        "wick_ask",
        "Snap + deterministic filter of links/elements/excerpt by query words (no LLM). Omit url after act.",
        {
            "type": "object",
            "properties": {
                "url": URL_PROP,
                "here": HERE_PROP,
                "q": {
                    "type": "string",
                    "description": "Search terms (case-insensitive substring match).",
                },
                "profile": PROFILE_PROP,
                "fast": FAST_PROP,
                "fail_http": FAIL_HTTP_PROP,
            },
            "required": ["q"],
        },
    ),
    _fn(
        "wick_snap_many",
        "Observe many URLs (serialized on standalone Chromium). Prefer profile=micro.",
        {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Absolute URLs to observe.",
                },
                "profile": {**PROFILE_PROP, "default": "micro"},
                "concurrency": {
                    "type": "integer",
                    "description": "Max parallel fetches (1–8). Chromium forces 1.",
                    "default": 4,
                },
            },
            "required": ["urls"],
        },
    ),
    _fn(
        "wick_open",
        "Full markdown read of a page (longer content than snap).",
        {
            "type": "object",
            "properties": {
                "url": URL_PROP,
                "fast": FAST_PROP,
                "max": {
                    "type": "integer",
                    "description": "Max markdown characters to return.",
                    "default": 8000,
                },
                "fail_http": FAIL_HTTP_PROP,
            },
            "required": ["url"],
        },
    ),
    _fn(
        "wick_elements",
        "Interactive element list from semantic tree (click targets). Prefer snap unless you only need hints.",
        {
            "type": "object",
            "properties": {
                "url": URL_PROP,
                "limit": {
                    "type": "integer",
                    "description": "Max elements to return.",
                    "default": 40,
                },
            },
            "required": ["url"],
        },
    ),
    _fn(
        "wick_act",
        (
            "Chromium interactive action. After a click that navigates: wait_url, then snap with no url. "
            "Search: fill the searchbox hint, then press Enter — do not click a generic Go. "
            "Computer-use (last resort): cu, then click_n / click_xy / type. "
            "Passwords: vault:// / pass:// / env:// refs; prefer action=login or passkey. Secrets never in JSON."
        ),
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "goto, cu, click, click_xy, click_n, type, type_n, key, press, fill, login, passkey, passkey_register, wait_url, scroll, pdf, …",
                },
                "rest": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Action arguments. Use THIS snap's elements[].hint. fill: [selector, text_or_secret_ref]. login: [url, optional --after-challenge MS, --no-submit]. Search: fill then press Enter.",
                    "default": [],
                },
                "after_challenge": {
                    "type": "integer",
                    "description": "With login: wait this many ms for a challenge widget to clear, then fill (does not solve).",
                },
                "no_submit": {
                    "type": "boolean",
                    "description": "With login: fill but do not click submit.",
                    "default": False,
                },
            },
            "required": ["action"],
        },
    ),
    _fn(
        "wick_session",
        "Cookie/session isolation: list, new (optional ephemeral+ttl), use, save/promote, drop, sweep, meta, path, export (redacted by default), import.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "new", "use", "save", "promote", "path", "meta", "drop", "sweep", "export", "import"],
                },
                "name": {
                    "type": "string",
                    "description": "Session name (default: default).",
                    "default": "default",
                },
                "ephemeral": {
                    "type": "boolean",
                    "description": "With new: delete on sweep/auto-drop unless promoted.",
                    "default": False,
                },
                "ttl": {
                    "type": "integer",
                    "description": "With new --ephemeral: lifetime in seconds.",
                },
                "owner": {
                    "type": "string",
                    "description": "Optional agent/owner tag.",
                },
                "reveal": {
                    "type": "boolean",
                    "description": "With export: include cookie values (full-act only).",
                    "default": False,
                },
                "file": {
                    "type": "string",
                    "description": "With import: path to a revealed session export.",
                },
            },
            "required": ["action"],
        },
    ),
    _fn(
        "wick_vault",
        "Password vault status/list/match/suggest (metadata only) plus the unlock/lock/grant broker. suggest/autofill returns origin-bound refs and login cmds — never secrets. Fill via wick_act login or fill with vault:// refs.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "status",
                        "backends",
                        "doctor",
                        "list",
                        "match",
                        "suggest",
                        "autofill",
                        "init",
                        "unlock",
                        "lock",
                        "grant",
                        "passkey-new",
                        "audit",
                        "backup",
                        "restore",
                        "harden",
                    ],
                    "description": "Metadata actions only; never request reveal. unlock/lock/grant/backup/restore/harden need WICK_PROFILE=full-act. audit is observe-safe (no secrets). backup/restore are file copies, not live sync. harden converts filekey→passphrase and deletes master.key.",
                },
                "name": {
                    "type": "string",
                    "description": "Entry name for passkey-new, or backup/restore path.",
                },
                "dest": {
                    "type": "string",
                    "description": "Destination path for backup (encrypted snapshot; passphrase from WICK_VAULT_BACKUP_PASSPHRASE).",
                },
                "src": {
                    "type": "string",
                    "description": "Source path for restore.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Audit tail length (default 50). Never includes secrets.",
                },
                "url": {
                    "type": "string",
                    "description": "URL for match (find entries by site), grant (origin to allow), or passkey-new.",
                },
                "ttl": {
                    "type": "integer",
                    "description": "Seconds for unlock (default 900) or grant (default 120).",
                },
            },
            "required": ["action"],
        },
    ),
    _fn(
        "wick_challenge",
        "Observe-only CAPTCHA/bot-wall detect. GET public HTML. Never logs in. Never solves.",
        {
            "type": "object",
            "properties": {
                "url": URL_PROP,
            },
            "required": ["url"],
        },
    ),
]


def tools_export(version: str) -> dict[str, Any]:
    purpose = wick_skill.PURPOSE if wick_skill is not None else "Wick is a standalone Chromium browser for agents."
    loop = list(wick_skill.LOOP) if wick_skill is not None else []
    rules = list(wick_skill.RULES) if wick_skill is not None else []
    return {
        "ok": True,
        "product": "wick",
        "version": version,
        "schema": "openai_tools_v1",
        "purpose": purpose,
        "loop": loop,
        "rules": rules,
        "tools": WICK_TOOLS,
        "hint": (
            "Call wick_skill once, then wick_snap (omit url after act). "
            "ChatGPT/Grok: load tools[] then wick rpc stdio. Claude/Hermes/Cursor: wick mcp."
        ),
    }
