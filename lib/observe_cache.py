"""Short-TTL disk cache so snap → plan → ask does not triple-fetch one URL.

Agent loops often observe the same page three times in a few seconds.
Cache lives under WICK_HOME/observe-cache (0600 files). Disable with
WICK_OBSERVE_CACHE=0. Default TTL is 8 seconds.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


def _home() -> Path:
    raw = os.environ.get("WICK_HOME") or str(Path.home() / ".wick")
    return Path(raw).expanduser()


def enabled() -> bool:
    return os.environ.get("WICK_OBSERVE_CACHE", "1") != "0"


def ttl_seconds() -> int:
    try:
        return max(0, int(os.environ.get("WICK_OBSERVE_CACHE_TTL", "8")))
    except ValueError:
        return 8


def cache_dir() -> Path:
    d = _home() / "observe-cache"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
        os.chmod(_home(), 0o700)
    except OSError:
        pass
    return d


def cache_key(
    *,
    url: str,
    fast: bool,
    wait_ms: int,
    session: str,
    mode: str = "snap",
    profile: str = "",
) -> str:
    raw = f"{url.strip()}|{int(bool(fast))}|{int(wait_ms)}|{session}|{mode}|{profile}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def get(key: str) -> dict[str, Any] | None:
    if not enabled() or ttl_seconds() <= 0:
        return None
    p = cache_dir() / f"{key}.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    ts = float(data.get("ts") or 0)
    if time.time() - ts > ttl_seconds():
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return None
    out = dict(payload)
    out["_cache_hit"] = True
    return out


def put(key: str, payload: dict[str, Any]) -> None:
    if not enabled() or ttl_seconds() <= 0:
        return
    if not isinstance(payload, dict) or not payload.get("ok"):
        return
    stored = {k: v for k, v in payload.items() if k != "_cache_hit"}
    p = cache_dir() / f"{key}.json"
    tmp = p.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps({"ts": time.time(), "payload": stored}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.chmod(tmp, 0o600)
        tmp.replace(p)
        os.chmod(p, 0o600)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
