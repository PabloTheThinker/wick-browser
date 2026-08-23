"""Harness approval gate for credential / destructive Chromium actions.

Off by default. When WICK_REQUIRE_APPROVAL is set, login/fill/passkey/eval
need an explicit approve from outside the model (env or a short-TTL file).

A page cannot mint this token. The agent should not set WICK_APPROVE itself.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

SENSITIVE = frozenset(
    {"login", "fill", "passkey", "passkey_register", "eval", "download"}
)
DEFAULT_TTL = 300


def _home() -> Path:
    raw = os.environ.get("WICK_HOME") or str(Path.home() / ".wick")
    return Path(raw).expanduser()


def token_path() -> Path:
    d = _home() / "approve"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
        os.chmod(_home(), 0o700)
    except OSError:
        pass
    return d / "once.json"


def required_actions() -> set[str]:
    raw = (os.environ.get("WICK_REQUIRE_APPROVAL") or "").strip().lower()
    if not raw or raw in ("0", "false", "off", "no"):
        return set()
    if raw in ("1", "true", "on", "yes", "*"):
        return set(SENSITIVE)
    return {p.strip() for p in raw.split(",") if p.strip() and p.strip() in SENSITIVE | {"*"}}


def _file_actions() -> tuple[set[str], dict[str, Any] | None]:
    p = token_path()
    if not p.is_file():
        return set(), None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(), None
    if not isinstance(obj, dict):
        return set(), None
    if int(obj.get("exp") or 0) <= int(time.time()):
        try:
            p.unlink()
        except OSError:
            pass
        return set(), None
    acts = {str(a).strip().lower() for a in (obj.get("actions") or []) if str(a).strip()}
    return acts, obj


def approved_actions() -> set[str]:
    acts: set[str] = set()
    env = (os.environ.get("WICK_APPROVE") or "").strip().lower()
    if env in ("*", "1", "all", "true"):
        acts |= required_actions() or set(SENSITIVE)
        acts.add("*")
    elif env:
        acts |= {p.strip() for p in env.split(",") if p.strip()}
    file_acts, _obj = _file_actions()
    acts |= file_acts
    return acts


def check(action: str) -> dict[str, Any] | None:
    """Return an error object if this action needs approval and does not have it."""
    a = (action or "").strip().lower()
    need = required_actions()
    if not need:
        return None
    if a not in need and "*" not in need:
        return None
    have = approved_actions()
    if a in have or "*" in have:
        if os.environ.get("WICK_APPROVE_ONCE") == "1":
            consume()
        return None
    return {
        "ok": False,
        "product": "wick",
        "error": "approval_required",
        "action": a,
        "required": sorted(need),
        "hint": "A human or outer harness must run: wick approve "
        + a
        + "   or set WICK_APPROVE="
        + a,
    }


def consume() -> None:
    try:
        token_path().unlink()
    except OSError:
        pass


def issue(actions: list[str] | str, ttl: int | None = None) -> dict[str, Any]:
    """Write a 0600 one-shot approval file. Never logs secrets."""
    if isinstance(actions, str):
        raw = [p.strip().lower() for p in actions.split(",") if p.strip()]
    else:
        raw = [str(a).strip().lower() for a in actions if str(a).strip()]
    acts = [a for a in raw if a in SENSITIVE or a == "*"]
    if not acts:
        return {"ok": False, "error": "no_actions", "hint": "wick approve login"}
    try:
        seconds = int(ttl if ttl is not None else DEFAULT_TTL)
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad_ttl"}
    if seconds <= 0:
        return {"ok": False, "error": "bad_ttl"}
    seconds = min(86400, seconds)
    exp = int(time.time()) + seconds
    payload = {
        "actions": acts,
        "exp": exp,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    p = token_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(p)
    os.chmod(p, 0o600)
    return {
        "ok": True,
        "approved": acts,
        "ttl": seconds,
        "exp": exp,
        "path": str(p),
        "note": "Token is local 0600. The model should not mint this for itself.",
    }
