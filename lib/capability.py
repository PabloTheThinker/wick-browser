"""Capability profiles and outbound host allowlists for agent harnesses.

Profiles (WICK_PROFILE):
  observe-only  — read the web; no clicks, fills, downloads, or secret writes
  safe-act      — observe + navigate/click/scroll; no credentials, eval, or files
  full-act      — default; full act + vault write/resolve

Host allowlist (WICK_ALLOW_HOSTS): comma-separated hosts. A leading '.'
means suffix match ('.example.com' allows app.example.com, not evilexample.com).
Empty / unset = unrestricted (unless blocked).

Host denylist (WICK_BLOCK_HOSTS): same syntax. Deny wins over the allowlist.

A policy file (WICK_POLICY or $WICK_HOME/policy.json) can supply the same
three knobs; see lib/policy.py for the merge rules. Env wins for the profile
and the allowlist; block lists are unioned so deny always wins.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def _sibling_module(name: str) -> Any:
    """Import a lib/ sibling whether or not lib/ is on sys.path."""
    try:
        return __import__(name)
    except Exception:
        pass
    try:
        import importlib.util
        from importlib.machinery import SourceFileLoader

        path = Path(__file__).resolve().parent / f"{name}.py"
        if not path.is_file():
            return None
        loader = SourceFileLoader(name, str(path))
        spec = importlib.util.spec_from_loader(name, loader)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


wick_policy = _sibling_module("policy")

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
        "challenge",
        "snap",
        "observe",
        "elements",
        "plan",
        "ask",
        "tools",
        "rpc",
        "mcp",
        "snap-many",
        "snap_many",
        "approve",
        "history",
        "shields",
        "xexam",
        "prune",
        "install-engine",
        "skill",
        "read",
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
    {
        "status",
        "backends",
        "doctor",
        "list",
        "match",
        "suggest",
        "autofill",
        "init",
        "audit",
    }
)
_SAFE_SESSION = frozenset(
    {"list", "new", "use", "save", "path", "drop", "sweep", "meta", "promote", "export"}
)


def _policy() -> dict[str, Any]:
    if wick_policy is None:
        return {}
    try:
        return wick_policy.effective() or {}
    except Exception:
        return {}


def current_profile() -> str:
    raw = (_policy().get("profile") or os.environ.get("WICK_PROFILE") or "full-act")
    raw = str(raw).strip().lower()
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
        if sa in {"export-reveal", "import"} and level < 2:
            return _deny(
                "session",
                action=sa,
                detail="revealed cookie export/import requires full-act",
            )
        if level <= 0 and sa not in {"list", "path", "use", "meta", "export"}:
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


def _parse_host_list(env_name: str) -> list[str]:
    raw = (os.environ.get(env_name) or "").strip()
    if not raw:
        return []
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def parse_allow_hosts() -> list[str]:
    pol = _policy()
    if "allow_hosts" in pol:
        return list(pol["allow_hosts"])
    return _parse_host_list("WICK_ALLOW_HOSTS")


def parse_block_hosts() -> list[str]:
    pol = _policy()
    if "block_hosts" in pol:
        return list(pol["block_hosts"])
    return _parse_host_list("WICK_BLOCK_HOSTS")


def _url_host(url: str | None) -> tuple[str, str]:
    """Return (host, reason_if_empty). host is '' when unusable."""
    s = (url or "").strip()
    if not s:
        return "", "empty_url"
    if "://" not in s:
        s = "https://" + s.lstrip("/")
    host = (urlsplit(s).hostname or "").lower().rstrip(".")
    if not host:
        return "", "empty_host"
    return host, ""


def _host_matches(host: str, pat: str) -> bool:
    p = (pat or "").lstrip("*").lower()
    if not host or not p:
        return False
    if p.startswith("."):
        base = p[1:]
        return host == base or host.endswith("." + base)
    return host == p or host.endswith("." + p)


def host_allowed(url: str | None) -> tuple[bool, str]:
    """Block list wins. Then, if WICK_ALLOW_HOSTS is set, hostname must match."""
    host, empty_reason = _url_host(url)
    for pat in parse_block_hosts():
        if host and _host_matches(host, pat):
            return False, "blocked"
    allow = parse_allow_hosts()
    if not allow:
        return True, "unrestricted"
    if empty_reason:
        return False, empty_reason
    for pat in allow:
        if _host_matches(host, pat):
            return True, "suffix" if pat.lstrip("*").startswith(".") else "exact"
    return False, "host_not_allowed"


def deny_host(url: str | None) -> dict[str, Any] | None:
    ok, reason = host_allowed(url)
    if ok:
        return None
    pol = _policy()
    err = {
        "ok": False,
        "product": "wick",
        "error": "host_not_allowed",
        "url": (url or "")[:160],
        "reason": reason,
        "allow_hosts": parse_allow_hosts(),
        "block_hosts": parse_block_hosts(),
        "hint": "WICK_BLOCK_HOSTS wins; add the host to WICK_ALLOW_HOSTS or unset the allowlist.",
    }
    if pol.get("source") not in (None, "none"):
        err["policy"] = pol.get("path")
    return err
