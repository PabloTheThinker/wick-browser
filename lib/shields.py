"""Wick Shields — Brave-inspired network privacy for agent browsing.

Honest scope:
  - EasyList/EasyPrivacy/Fanboy files can be downloaded via `wick shields --update`.
    Chromium does not apply those lists as request filters.
  - We block private-network SSRF by default.
  - We isolate sessions (cookie jars + Chromium profiles) so agent runs don't cross-contaminate.
  - Privacy headers (DNT / Sec-GPC) are set on the Chromium path when enabled.
  - We do NOT claim Brave-grade canvas/WebGL farbling (Chromium limitation).
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
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
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


_COOKIE_META_KEYS = (
    "name",
    "domain",
    "path",
    "secure",
    "httpOnly",
    "httponly",
    "sameSite",
    "samesite",
    "expires",
    "expiry",
    "expirationDate",
    "hostOnly",
)


def _read_cookie_list(path: Path) -> list[dict[str, Any]]:
    """Accept a JSON list of cookie dicts, or {cookies: [...]}."""
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(raw, list):
        return [c for c in raw if isinstance(c, dict)]
    if isinstance(raw, dict):
        cookies = raw.get("cookies")
        if isinstance(cookies, list):
            return [c for c in cookies if isinstance(c, dict)]
    return []


def session_cookies(name: str = "default") -> list[dict[str, Any]]:
    """Load cookies from load.json, falling back to jar.json."""
    load, jar = session_cookie_paths(name)
    cookies = _read_cookie_list(load)
    if cookies:
        return cookies
    return _read_cookie_list(jar)


def _redact_cookie(cookie: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _COOKIE_META_KEYS:
        if key in cookie:
            dest = "httpOnly" if key.lower() == "httponly" else key
            dest = "sameSite" if dest.lower() == "samesite" else dest
            dest = "expires" if dest in ("expiry", "expirationDate") else dest
            if dest not in out:
                out[dest] = cookie[key]
    out["has_value"] = bool(str(cookie.get("value") or cookie.get("Value") or ""))
    return out


def _cookie_has_value(cookie: dict[str, Any]) -> bool:
    return "value" in cookie or "Value" in cookie


def export_session(name: str = "default", *, reveal: bool = False) -> dict[str, Any]:
    """Export cookies. Values are omitted unless reveal=True."""
    safe = session_name_safe(name)
    d = session_dir(safe)
    if not d.is_dir():
        return {"ok": False, "error": "not_found", "session": safe}
    cookies = session_cookies(safe)
    if reveal:
        exported = list(cookies)
    else:
        exported = [_redact_cookie(c) for c in cookies]
    meta = session_meta(safe)
    return {
        "ok": True,
        "format": "wick-session-v1",
        "session": safe,
        "revealed": bool(reveal),
        "cookie_count": len(exported),
        "cookies": exported,
        "meta": {
            k: meta.get(k)
            for k in ("name", "ephemeral", "promoted", "owner", "ttl", "created")
        },
    }


def write_session_export(payload: dict[str, Any], dest: Path) -> dict[str, Any]:
    """Write an export JSON. Revealed files are 0600."""
    target = Path(dest).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if payload.get("revealed"):
            os.chmod(tmp, 0o600)
        tmp.replace(target)
        if payload.get("revealed"):
            os.chmod(target, 0o600)
    except OSError as e:
        return {"ok": False, "error": "write_failed", "detail": str(e), "path": str(target)}
    mode = oct(target.stat().st_mode & 0o777) if target.is_file() else None
    return {"ok": True, "path": str(target), "mode": mode, "revealed": bool(payload.get("revealed"))}


def import_session(name: str, payload: Any) -> dict[str, Any]:
    """Import a revealed export (or a bare cookie list with values) into load.json."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return {"ok": False, "error": "bad_json"}
    cookies: list[Any]
    if isinstance(payload, list):
        cookies = payload
    elif isinstance(payload, dict):
        if payload.get("revealed") is False:
            return {"ok": False, "error": "redacted_export_not_importable"}
        raw = payload.get("cookies")
        if not isinstance(raw, list):
            return {"ok": False, "error": "bad_export", "detail": "expected cookies list"}
        cookies = raw
    else:
        return {"ok": False, "error": "bad_export"}
    parsed: list[dict[str, Any]] = []
    for item in cookies:
        if not isinstance(item, dict):
            return {"ok": False, "error": "bad_export", "detail": "cookie must be an object"}
        if not _cookie_has_value(item):
            return {"ok": False, "error": "redacted_export_not_importable"}
        parsed.append(item)
    safe = session_name_safe(name)
    session_dir(safe)
    load, _jar = session_cookie_paths(safe)
    try:
        load.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(load, 0o600)
    except OSError as e:
        return {"ok": False, "error": "write_failed", "detail": str(e)}
    return {"ok": True, "session": safe, "imported": len(parsed), "load": str(load)}


def resolve_proxy() -> str | None:
    """Proxy URL from env. Never log credentials."""
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
