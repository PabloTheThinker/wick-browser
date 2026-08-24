"""Observe budget profiles so agent loops stay token-cheap and fast.

micro   — tree + elements only (no markdown fetch). Hermes/Claude first look.
default — fast wait + short excerpt (same as --fast).
full    — longer wait + larger excerpt (human-length read).

WICK_SNAP_PROFILE overrides the default when --profile is omitted.
"""
from __future__ import annotations

import os
from typing import Any

PROFILES: dict[str, dict[str, Any]] = {
    "micro": {
        "fast": True,
        "skip_markdown": True,
        "wait_ms": 800,
        "max_chars": 0,
        "excerpt": 240,
        "elements": 20,
        "link_limit": 8,
        "tree_max": 20000,
    },
    "default": {
        "fast": True,
        "skip_markdown": False,
        "wait_ms": 1200,
        "max_chars": 4000,
        "excerpt": 400,
        "elements": 30,
        "link_limit": 15,
        "tree_max": 40000,
    },
    "full": {
        "fast": False,
        "skip_markdown": False,
        "wait_ms": 2000,
        "max_chars": 12000,
        "excerpt": 800,
        "elements": 40,
        "link_limit": 25,
        "tree_max": 60000,
    },
}

_ALIASES = {
    "fast": "default",
    "tiny": "micro",
    "brief": "micro",
    "long": "full",
    "observe": "default",
}


def resolve(name: str | None = None) -> str:
    raw = (name if name is not None else os.environ.get("WICK_SNAP_PROFILE") or "default")
    raw = str(raw).strip().lower() or "default"
    raw = _ALIASES.get(raw, raw)
    return raw if raw in PROFILES else "default"


def apply(name: str | None = None) -> dict[str, Any]:
    return dict(PROFILES[resolve(name)])
