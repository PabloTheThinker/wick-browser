"""Wick browsing history (agent-readable JSONL)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

HOME = Path(os.environ.get("WICK_HOME", Path.home() / ".wick"))
HIST = HOME / "history.jsonl"
MAX_LINES = 5000


def _path() -> Path:
    HOME.mkdir(parents=True, exist_ok=True)
    try:
        HOME.chmod(0o700)
    except OSError:
        pass
    return HIST


def record(event: dict) -> None:
    event = dict(event)
    event.setdefault("ts", time.time())
    event.setdefault("session", os.environ.get("WICK_SESSION", "default"))
    path = _path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    # trim if huge
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) > MAX_LINES:
            path.write_text("\n".join(lines[-MAX_LINES:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def read(limit: int = 50, session: str | None = None) -> list[dict]:
    path = _path()
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        if session and o.get("session") != session:
            continue
        rows.append(o)
    return rows[-limit:]


def clear(session: str | None = None) -> dict:
    path = _path()
    if not path.is_file():
        return {"ok": True, "cleared": 0}
    if not session:
        n = sum(1 for _ in path.open())
        path.unlink(missing_ok=True)
        return {"ok": True, "cleared": n}
    kept = []
    cleared = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("session") == session:
            cleared += 1
        else:
            kept.append(line)
    path.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
    return {"ok": True, "cleared": cleared, "session": session}
