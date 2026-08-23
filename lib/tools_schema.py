"""OpenAI-style function tool schemas for Wick agent commands."""
from __future__ import annotations

from typing import Any

URL_PROP = {
    "type": "string",
    "description": "Absolute URL to observe or act on (e.g. https://example.com/).",
}

FAST_PROP = {
    "type": "boolean",
    "description": "Faster observe: domcontentloaded + ~1.2s wait.",
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
        "wick_snap",
        "Compact page snapshot: title, excerpt, links, interactive elements (primary observe). Use profile=micro for the cheapest first look (Hermes/Claude).",
        {
            "type": "object",
            "properties": {
                "url": URL_PROP,
                "profile": PROFILE_PROP,
                "fast": FAST_PROP,
                "full": {
                    "type": "boolean",
                    "description": "Include full markdown body in response.",
                    "default": False,
                },
                "fail_http": FAIL_HTTP_PROP,
            },
            "required": ["url"],
        },
    ),
    _fn(
        "wick_observe",
        "Alias of wick_snap — compact observe snapshot for agents.",
        {
            "type": "object",
            "properties": {
                "url": URL_PROP,
                "profile": PROFILE_PROP,
                "fast": FAST_PROP,
                "full": {"type": "boolean", "default": False},
                "fail_http": FAIL_HTTP_PROP,
            },
            "required": ["url"],
        },
    ),
    _fn(
        "wick_plan",
        "Goal-agnostic next-step suggestions from a snap (open, click hints, screenshot, pdf, ask).",
        {
            "type": "object",
            "properties": {
                "url": URL_PROP,
                "profile": PROFILE_PROP,
                "fast": FAST_PROP,
                "fail_http": FAIL_HTTP_PROP,
            },
            "required": ["url"],
        },
    ),
    _fn(
        "wick_ask",
        "Snap + deterministic filter of links/elements/excerpt by query words (no LLM).",
        {
            "type": "object",
            "properties": {
                "url": URL_PROP,
                "q": {
                    "type": "string",
                    "description": "Search terms (case-insensitive substring match).",
                },
                "profile": PROFILE_PROP,
                "fast": FAST_PROP,
                "fail_http": FAIL_HTTP_PROP,
            },
            "required": ["url", "q"],
        },
    ),
    _fn(
        "wick_snap_many",
        "Parallel observe of many URLs (bounded concurrency). Prefer profile=micro.",
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
                    "description": "Max parallel fetches (1–8).",
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
        "Interactive element list from semantic tree (click targets).",
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
        "Chromium interactive action. Computer-use: cu (screenshot + numbered boxes), click_xy / click_n, type / type_n, key. For passwords pass secret refs (vault://…, pass://…, env://…). Prefer action=login or action=passkey (vault-backed WebAuthn via Chromium virtual authenticator — not Touch ID).",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "goto, cu, click, click_xy, click_n, type, type_n, key, fill, login, passkey, passkey_register, wait_url, scroll, pdf, …",
                },
                "rest": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Action arguments. cu: [optional screenshot path]. click_xy: [x, y]. click_n: [n]. type: [text]. fill: [selector, text_or_secret_ref]. Optional --expect-url-fragment FRAG and --expect-element SEL.",
                    "default": [],
                },
            },
            "required": ["action"],
        },
    ),
    _fn(
        "wick_session",
        "Cookie/session isolation: list, new (optional ephemeral+ttl), use, save/promote, drop, sweep, meta, path.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "new", "use", "save", "promote", "path", "meta", "drop", "sweep"],
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
                    ],
                    "description": "Metadata actions only; never request reveal. unlock/lock/grant need WICK_PROFILE=full-act. passkey-new stores an origin-bound WebAuthn credential (no key in JSON).",
                },
                "name": {
                    "type": "string",
                    "description": "Entry name for passkey-new.",
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
]


def tools_export(version: str) -> dict[str, Any]:
    return {
        "ok": True,
        "product": "wick",
        "version": version,
        "schema": "openai_tools_v1",
        "tools": WICK_TOOLS,
        "hint": "ChatGPT/Grok: load tools[] then call wick rpc stdio. Claude/Hermes/Cursor: wick mcp (JSON-RPC 2.0).",
    }
