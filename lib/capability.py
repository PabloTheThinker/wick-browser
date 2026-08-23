"""Capability profiles and outbound host allowlists for agent harnesses.

Profiles (WICK_PROFILE):
  observe-only  — read the web; no clicks, fills, downloads, or secret writes
  safe-act      — observe + navigate/click/scroll; no credentials, eval, or files
  full-act      — default; full act + vault write/resolve

Host allowlist (WICK_ALLOW_HOSTS): comma-separated hosts. A leading '.'
means suffix match ('.example.com' allows app.example.com, not evilexample.com).
Empty / unset = unrestricted.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

PROFILES = ("observe-only", "safe-act", "full-act")
ALIASES = {
    "observe": "observe-only",
    "observe_only": "observe-only",
    "safe": "safe-act",
    "safe_act": "safe-act",
    "observe+safe-act": "safe-act",
    "full": "full-act",
    "full_act": "full-act",
}

# Minimum profile level required (0=observe, 1=safe, 2=full)
_LEVEL = {"observe-only": 0, "safe-act": 1, "full-act": 2}

_OBSERVE_CMDS = frozenset(
    {
        "version",
        "doctor",
        "ensure",
        "start",
        "stop",
        "status",
        "fetch",
        "open",
        "links",
        "tree",
        "batch",
        "metrics",
        "probe",
        "snap",
        "observe",
        "elements",
        "plan",
        "ask",
        "tools",
        "rpc",
        "history",
        "shields",
        "xexam",
        "prune",
        "install-engine",
    }
)
_SAFE_CMDS = _OBSERVE_CMDS | frozenset(
    {
        "goto",
        "shot",
        "text",
        "pdf",
        "tabs",
        "session",
        "run",
        "shields-bench",
    }
)
_SAFE_ACTS = frozenset(
    {
        "goto",
        "click",
        "hover",
        "scroll",
        "wait",
        "wait_url",
        "content",
        "title",
        "back",
        "forward",
        "reload",
        "tab_new",
        "tab_list",
        "tab_switch",
        "tab_close",
        "screenshot",
        "pdf",
        "press",
        "click_xy",
        "click_n",
        "dblclick",
        "doubleclick",
        "rightclick",
        "contextclick",
        "move",
        "drag",
        "type",
        "type_n",
        "key",
        "scroll_xy",
        "wait_text",
        "wait_visible",
        "cu",
        "a11y",
        "dialog",
        "computer",
    }
)
_OBSERVE_VAULT = frozenset(
    {"status", "backends", "doctor", "list", "match", "suggest", "autofill", "init"}
)
_SAFE_SESSION = frozenset(
    {"list", "new", "use", "save", "path", "drop", "sweep", "meta", "promote"}
)


def current_profile() -> str:
    raw = (os.environ.get("WICK_PROFILE") or "full-act").strip().lower()
    if raw in ALIASES:
        return ALIASES[raw]
    if raw in PROFILES:
        return raw
    return "full-act"


def profile_level(name: str | None = None) -> int:
    return _LEVEL.get(name or current_profile(), 2)


def _deny(cmd: str, *, action: str | None = None, detail: str = "") -> dict[str, Any]:
    prof = current_profile()
    return {
        "ok": False,
        "product": "wick",
        "error": "capability_denied",
        "profile": prof,
        "cmd": cmd,
        "action": action,
        "detail": detail or f"profile {prof} cannot run {cmd}" + (f" {action}" if action else ""),
        "hint": "Set WICK_PROFILE=full-act (or safe-act) to allow this command.",
    }


def deny(
    cmd: str,
    *,
    action: str | None = None,
    vault_action: str | None = None,
    session_action: str | None = None,
) -> dict[str, Any] | None:
    """Return an error object if the current profile forbids this command."""
    prof = current_profile()
    level = profile_level(prof)
    c = (cmd or "").strip().lower()
    act = (action or "").strip().lower()

    if c == "act":
        if level <= 0:
            return _deny(c, action=act or "act", detail="observe-only cannot drive Chromium")
        if level == 1 and act and act not in _SAFE_ACTS:
            return _deny(c, action=act, detail="safe-act forbids credential/eval/download actions")
        return None

    if c == "vault":
        va = (vault_action or "status").strip().lower()
        if va in _OBSERVE_VAULT:
            return None
        if level < 2:
            return _deny("vault", action=va, detail="vault write/resolve requires full-act")
        return None

    if c == "session":
        sa = (session_action or "list").strip().lower()
        if level <= 0 and sa not in {"list", "path", "use", "meta"}:
            return _deny("session", action=sa, detail="observe-only can inspect sessions only")
        if sa in _SAFE_SESSION or level >= 2:
            return None
        return _deny("session", action=sa)

    if c in ("get", "eval", "download"):
        if level < 2:
            return _deny(c, detail="downloads/eval require full-act")
        return None

    if level >= 2:
        return None
    if level >= 1 and c in _SAFE_CMDS:
        return None
    if c in _OBSERVE_CMDS:
        return None
    return _deny(c)


def parse_allow_hosts() -> list[str]:
    raw = (os.environ.get("WICK_ALLOW_HOSTS") or "").strip()
    if not raw:
        return []
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def host_allowed(url: str | None) -> tuple[bool, str]:
    allow = parse_allow_hosts()
    if not allow:
        return True, "unrestricted"
    s = (url or "").strip()
    if not s:
        return False, "empty_url"
    if "://" not in s:
        s = "https://" + s.lstrip("/")
    host = (urlsplit(s).hostname or "").lower().rstrip(".")
    if not host:
        return False, "empty_host"
    for pat in allow:
        p = pat.lstrip("*").lower()
        if p.startswith("."):
            base = p[1:]
            if host == base or host.endswith("." + base):
                return True, "suffix"
        elif host == p:
            return True, "exact"
    return False, "host_not_allowed"


def deny_host(url: str | None) -> dict[str, Any] | None:
    ok, reason = host_allowed(url)
    if ok:
        return None
    return {
        "ok": False,
        "product": "wick",
        "error": "host_not_allowed",
        "url": (url or "")[:160],
        "reason": reason,
        "allow_hosts": parse_allow_hosts(),
        "hint": "Add the host to WICK_ALLOW_HOSTS or unset the allowlist.",
    }
