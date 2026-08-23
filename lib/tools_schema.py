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
        "Compact page snapshot: title, excerpt, links, interactive elements (primary observe).",
        {
            "type": "object",
            "properties": {
                "url": URL_PROP,
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
                "fast": FAST_PROP,
                "fail_http": FAIL_HTTP_PROP,
            },
            "required": ["url", "q"],
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
        "Chromium interactive action. For passwords pass secret refs (vault://…, pass://…, env://…). Prefer action=login for origin-bound autofill like a human password manager.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action name: goto, click, fill, login, wait_url, scroll, pdf, …",
                },
                "rest": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Action arguments. For fill: [selector, text_or_secret_ref].",
                    "default": [],
                },
            },
            "required": ["action"],
        },
    ),
    _fn(
        "wick_session",
        "Cookie/session isolation: list, new, use, save, path.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "new", "use", "save", "path"],
                },
                "name": {
                    "type": "string",
                    "description": "Session name (default: default).",
                    "default": "default",
                },
            },
            "required": ["action"],
        },
    ),
    _fn(
        "wick_vault",
        "Password vault status/list/match/suggest (metadata only). suggest/autofill returns origin-bound refs and login cmds — never secrets. Fill via wick_act login or fill with vault:// refs.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "backends", "doctor", "list", "match", "suggest", "autofill", "init"],
                    "description": "Metadata actions only. Never request reveal. Use suggest then wick_act login.",
                },
                "url": {
                    "type": "string",
                    "description": "URL for match (find entries by site).",
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
        "hint": "Load tools[] into agent harness; call via wick rpc stdio or CLI.",
    }
