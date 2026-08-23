"""Wick Shields — Brave-inspired network privacy for agent browsing.

Honest scope:
  - We block trackers/ads at the *request* layer (EasyList/EasyPrivacy + Wick URL patterns).
  - We block private-network SSRF by default.
  - We isolate sessions (cookie jars) so agent runs don't cross-contaminate.
  - We do NOT claim Brave-grade canvas/WebGL farbling inside Lightpanda (engine limitation).
  - Chromium shot path gets automation-hardening flags; still not a full anti-detect browser.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

HOME = Path(os.environ.get("WICK_HOME", Path.home() / ".wick"))
SHIELDS = HOME / "shields"
SESSIONS = HOME / "sessions"


def ensure_shield_dirs() -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    try:
        HOME.chmod(0o700)
    except OSError:
        pass
    SHIELDS.mkdir(parents=True, exist_ok=True)
    SESSIONS.mkdir(parents=True, exist_ok=True)


def list_files() -> dict:
    ensure_shield_dirs()
    files = {}
    for name in ("easylist.txt", "easyprivacy.txt", "fanboy-social.txt", "wick-block-urls.txt"):
        p = SHIELDS / name
        files[name] = {
            "path": str(p),
            "exists": p.is_file(),
            "bytes": p.stat().st_size if p.is_file() else 0,
        }
    return files


def block_url_patterns() -> list[str]:
    p = SHIELDS / "wick-block-urls.txt"
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def adblock_lists(enabled: bool = True) -> list[Path]:
    if not enabled:
        return []
    ensure_shield_dirs()
    paths = []
    for name in ("easylist.txt", "easyprivacy.txt", "fanboy-social.txt"):
        p = SHIELDS / name
        if p.is_file() and p.stat().st_size > 1000:
            paths.append(p)
    return paths


def session_name_safe(name: str = "default") -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (name or ""))[:64] or "default"


def session_dir(name: str = "default") -> Path:
    ensure_shield_dirs()
    d = SESSIONS / session_name_safe(name)
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_meta_path(name: str = "default") -> Path:
    return session_dir(name) / "meta.json"


def session_meta(name: str = "default") -> dict[str, Any]:
    p = session_meta_path(name)
    if not p.is_file():
        return {
            "name": session_name_safe(name),
            "ephemeral": False,
            "promoted": False,
            "ttl": None,
            "owner": None,
            "created": None,
            "created_ts": None,
        }
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("name", session_name_safe(name))
    return data


def write_session_meta(name: str, meta: dict[str, Any]) -> dict[str, Any]:
    p = session_meta_path(name)
    payload = dict(meta)
    payload["name"] = session_name_safe(name)
    payload["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return payload


def new_session(
    name: str,
    *,
    ephemeral: bool = False,
    ttl: int | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    """Create an isolated session dir. Ephemeral sessions are swept unless promoted."""
    safe = session_name_safe(name)
    d = session_dir(safe)
    now = time.time()
    meta = {
        "name": safe,
        "ephemeral": bool(ephemeral),
        "promoted": False,
        "ttl": int(ttl) if ttl else None,
        "owner": (owner or "").strip() or None,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "created_ts": now,
        "path": str(d),
    }
    write_session_meta(safe, meta)
    return {"ok": True, **meta}


def promote_session(name: str) -> dict[str, Any]:
    """Keep cookies (jar → load) and mark the session persistent."""
    saved = promote_jar_to_load(name)
    meta = session_meta(name)
    meta["ephemeral"] = False
    meta["promoted"] = True
    meta["promoted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_session_meta(name, meta)
    out = {"ok": True, "session": session_name_safe(name), "promoted": True, "ephemeral": False}
    if saved.get("ok"):
        out["load"] = saved.get("load")
        out["bytes"] = saved.get("bytes")
    else:
        out["save"] = saved
    return out


def drop_session(name: str, *, force_default: bool = False) -> dict[str, Any]:
    """Delete a session directory (cookies + chrome profile)."""
    safe = session_name_safe(name)
    if safe == "default" and not force_default:
        return {
            "ok": False,
            "error": "refuse_drop_default",
            "hint": "Pass force=true / --force to delete the default session.",
        }
    d = SESSIONS / safe
    if not d.is_dir():
        return {"ok": False, "error": "not_found", "session": safe}
    shutil.rmtree(d, ignore_errors=True)
    return {"ok": True, "dropped": safe}


def session_expired(meta: dict[str, Any], *, now: float | None = None) -> bool:
    if not meta.get("ephemeral") or meta.get("promoted"):
        return False
    ttl = meta.get("ttl")
    if not ttl:
        return False
    created = meta.get("created_ts")
    if created is None:
        return False
    return (now if now is not None else time.time()) - float(created) >= float(ttl)


def sweep_sessions(*, now: float | None = None) -> dict[str, Any]:
    """Drop expired ephemeral sessions that were never promoted."""
    ensure_shield_dirs()
    dropped = []
    kept = []
    for d in sorted(SESSIONS.iterdir() if SESSIONS.exists() else []):
        if not d.is_dir():
            continue
        meta = session_meta(d.name)
        if session_expired(meta, now=now):
            drop_session(d.name, force_default=True)
            dropped.append({"name": d.name, "reason": "ttl"})
        else:
            kept.append(d.name)
    return {"ok": True, "dropped": dropped, "kept": kept, "count_dropped": len(dropped)}


def session_cookie_paths(name: str = "default") -> tuple[Path, Path]:
    d = session_dir(name)
    return d / "load.json", d / "jar.json"


def append_lp_shield_args(
    cmd: list[str],
    *,
    shields: bool = True,
    session: str = "default",
    block_private: bool = True,
    extra_block_urls: list[str] | None = None,
) -> list[str]:
    """Mutate/return lightpanda argv with Shields + session cookies."""
    ensure_shield_dirs()
    if block_private:
        if "--block-private-networks" not in cmd:
            cmd.append("--block-private-networks")

    if shields:
        for p in adblock_lists(True):
            cmd.extend(["--adblock-lists", str(p)])
        for pat in block_url_patterns():
            cmd.extend(["--block-urls", pat])
        if extra_block_urls:
            for pat in extra_block_urls:
                cmd.extend(["--block-urls", pat])

    load, jar = session_cookie_paths(session)
    # Always write jar for session continuity
    cmd.extend(["--cookie-jar", str(jar)])
    if load.is_file() and load.stat().st_size > 2:
        cmd.extend(["--cookie", str(load)])
    # After runs, agents can promote jar → load via `wick session save`
    return cmd


def promote_jar_to_load(session: str = "default") -> dict:
    load, jar = session_cookie_paths(session)
    if not jar.is_file():
        return {"ok": False, "error": "no_jar", "session": session}
    load.write_bytes(jar.read_bytes())
    return {"ok": True, "session": session, "load": str(load), "bytes": load.stat().st_size}


def list_sessions() -> list[dict]:
    ensure_shield_dirs()
    out = []
    for d in sorted(SESSIONS.iterdir() if SESSIONS.exists() else []):
        if not d.is_dir():
            continue
        jar = d / "jar.json"
        load = d / "load.json"
        meta = session_meta(d.name)
        out.append({
            "name": d.name,
            "path": str(d),
            "jar_bytes": jar.stat().st_size if jar.is_file() else 0,
            "load_bytes": load.stat().st_size if load.is_file() else 0,
            "ephemeral": bool(meta.get("ephemeral")),
            "promoted": bool(meta.get("promoted")),
            "owner": meta.get("owner"),
            "ttl": meta.get("ttl"),
            "created": meta.get("created"),
            "expired": session_expired(meta),
        })
    return out


# Chromium launch args: reduce automation tells (not full stealth)
CHROME_HARDENING_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-default-browser-check",
    "--no-first-run",
    "--disable-background-networking",
    "--disable-client-side-phishing-detection",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-domain-reliability",
    "--disable-hang-monitor",
    "--disable-ipc-flooding-protection",
    "--disable-popup-blocking",
    "--disable-prompt-on-repost",
    "--disable-sync",
    "--metrics-recording-only",
    "--password-store=basic",
    "--use-mock-keychain",
    # privacy-ish
    "--disable-breakpad",
    "--no-pings",
]


PRIVACY_HEADERS = [
    "DNT: 1",
    "Sec-GPC: 1",
    "Upgrade-Insecure-Requests: 1",
    "Referrer-Policy: strict-origin-when-cross-origin",
]


def append_privacy_headers(cmd: list[str]) -> list[str]:
    """Brave-like preference signals (best-effort; not fingerprint farbling)."""
    for h in PRIVACY_HEADERS:
        cmd.extend(["--http-header", h])
    return cmd


def session_chrome_profile(name: str = "default") -> Path:
    """Isolated Chromium user-data-dir per session (Browser-Use-like persistence)."""
    d = session_dir(name) / "chrome-profile"
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_downloads(name: str = "default") -> Path:
    d = session_dir(name) / "downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_proxy() -> str | None:
    """Proxy URL for Lightpanda --http-proxy. Never log credentials."""
    for key in ("WICK_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        v = os.environ.get(key, "").strip()
        if v:
            return v
    return None


def append_proxy(cmd: list[str]) -> list[str]:
    proxy = resolve_proxy()
    if proxy:
        cmd.extend(["--http-proxy", proxy])
    return cmd
