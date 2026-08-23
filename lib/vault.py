#!/usr/bin/env python3
"""Wick Vault — agent-safe secret refs for fill/login (open local + Proton Pass + bridges).

Design (security-first for agents):
- Secrets never appear in list/status/match/doctor JSON.
- Agents pass *refs* (vault://…, pass://…, env://…, kdbx://…); only the fill path resolves.
- Local backend is open-source, file-based under WICK_HOME/vault (mode 0700).
- Proton Pass uses official pass-cli agent tokens (scoped + audited by Proton).
- AgentMail / proton-agent-mail tokens are stored as ordinary entries (never in git).

Refs:
  vault://NAME[/FIELD]          local encrypted store (default field: password)
  pass://VAULT/ITEM[/FIELD]     Proton Pass CLI (field default: password)
  env://VAR                     process environment (never logged)
  kdbx://ENTRY[/FIELD]          KeePassXC-CLI against WICK_KDBX / config path
  agentmail://token             alias → vault://agentmail/token (local)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

try:
    import origins as wick_origins
except Exception:
    wick_origins = None  # type: ignore
try:
    import login_form as wick_login_form
except Exception:
    wick_login_form = None  # type: ignore

VAULT_FORMAT = "wickvault1"
DEFAULT_FIELD = "password"
REF_RE = re.compile(
    r"^(?P<scheme>vault|pass|env|kdbx|agentmail)://(?P<body>.+)$",
    re.IGNORECASE,
)


def wick_home() -> Path:
    raw = os.environ.get("WICK_HOME") or str(Path.home() / ".wick")
    return Path(raw).expanduser()


def vault_dir() -> Path:
    d = wick_home() / "vault"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
        os.chmod(wick_home(), 0o700)
    except OSError:
        pass
    return d


def _paths() -> dict[str, Path]:
    root = vault_dir()
    return {
        "root": root,
        "store": root / "store.enc",
        "key": root / "master.key",
        "meta": root / "meta.json",
        "audit": root / "audit.jsonl",
        "config": root / "config.json",
    }


def _audit(action: str, ref: str = "", ok: bool = True, detail: str = "") -> None:
    """Append audit line — never includes secret material."""
    try:
        p = _paths()["audit"]
        line = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "action": action,
            "ref": _redact_ref(ref) if ref else "",
            "ok": bool(ok),
            "detail": (detail or "")[:160],
        }
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    except OSError:
        pass


def _redact_ref(ref: str) -> str:
    """Keep scheme + path shape; drop query-like secret material."""
    s = (ref or "").strip()
    if not s:
        return ""
    if "://" not in s:
        return s[:80]
    scheme, _, body = s.partition("://")
    # Never echo env values if someone pasted env://SECRETVALUE by mistake
    if scheme.lower() == "env":
        return f"env://{body.split('=', 1)[0][:64]}"
    return f"{scheme.lower()}://{body[:120]}"


def is_secret_ref(value: str | None) -> bool:
    if not value or not isinstance(value, str):
        return False
    return bool(REF_RE.match(value.strip()))


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _derive_key(master: bytes, salt: bytes) -> bytes:
    return hashlib.scrypt(master, salt=salt, n=2**14, r=8, p=1, dklen=32)


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _seal(master: bytes, plaintext: bytes) -> str:
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    key = _derive_key(master, salt)
    ct = bytes(a ^ b for a, b in zip(plaintext, _keystream(key, nonce, len(plaintext))))
    mac = hmac.new(key, salt + nonce + ct, hashlib.sha256).digest()
    return "$".join([VAULT_FORMAT, _b64e(salt), _b64e(nonce), _b64e(ct), _b64e(mac)])


def _open_seal(master: bytes, blob: str) -> bytes:
    parts = blob.strip().split("$")
    if len(parts) != 5 or parts[0] != VAULT_FORMAT:
        raise ValueError("bad_vault_format")
    _, salt_b, nonce_b, ct_b, mac_b = parts
    salt, nonce, ct, mac = _b64d(salt_b), _b64d(nonce_b), _b64d(ct_b), _b64d(mac_b)
    key = _derive_key(master, salt)
    expect = hmac.new(key, salt + nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(expect, mac):
        raise ValueError("bad_mac_or_key")
    return bytes(a ^ b for a, b in zip(ct, _keystream(key, nonce, len(ct))))


def _load_master() -> bytes | None:
    env = os.environ.get("WICK_VAULT_KEY") or os.environ.get("WICK_VAULT_MASTER")
    if env:
        return env.encode("utf-8")
    key_path = _paths()["key"]
    if key_path.is_file():
        return key_path.read_bytes().strip()
    return None


def ensure_local_key(*, rotate: bool = False) -> dict[str, Any]:
    """Create master.key (0600) if missing. Never prints the key."""
    paths = _paths()
    key_path = paths["key"]
    created = False
    if rotate or not key_path.is_file():
        key = secrets.token_bytes(32)
        key_path.write_bytes(key)
        os.chmod(key_path, 0o600)
        created = True
        _audit("key_create" if created else "key_rotate", ok=True)
    meta = {
        "format": VAULT_FORMAT,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "backend": "local",
    }
    if not paths["meta"].is_file() or created:
        paths["meta"].write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        os.chmod(paths["meta"], 0o600)
    if not paths["store"].is_file():
        _write_store({})
    return {"ok": True, "created": created, "key_path": str(key_path), "mode": "0600"}


def _read_store() -> dict[str, Any]:
    master = _load_master()
    if master is None:
        raise ValueError("vault_locked")
    store_path = _paths()["store"]
    if not store_path.is_file():
        return {}
    raw = store_path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    data = _open_seal(master, raw)
    obj = json.loads(data.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("corrupt_store")
    return obj


def _write_store(entries: dict[str, Any]) -> None:
    master = _load_master()
    if master is None:
        raise ValueError("vault_locked")
    blob = _seal(master, json.dumps(entries, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    path = _paths()["store"]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(blob + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def load_config() -> dict[str, Any]:
    p = _paths()["config"]
    if not p.is_file():
        return {
            "default_backend": "local",
            "proton_pass": {"enabled": True, "bin": "pass-cli"},
            "keepassxc": {"enabled": True, "bin": "keepassxc-cli", "db": os.environ.get("WICK_KDBX", "")},
            "agentmail": {"entry": "agentmail/token", "bridge_hint": "proton-agent-mail on loopback"},
            "brave_stack": {
                "shields": True,
                "session_isolation": True,
                "vault_refs_for_fill": True,
                "fingerprint_farbling": False,
            },
        }
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    p = _paths()["config"]
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(p, 0o600)
    _audit("config_save", ok=True)
    return {"ok": True, "path": str(p)}


def backends_status() -> dict[str, Any]:
    cfg = load_config()
    local_key = _paths()["key"].is_file() or bool(os.environ.get("WICK_VAULT_KEY"))
    store = _paths()["store"].is_file()
    pp_bin = (cfg.get("proton_pass") or {}).get("bin") or "pass-cli"
    kdbx_bin = (cfg.get("keepassxc") or {}).get("bin") or "keepassxc-cli"
    pp_path = shutil.which(pp_bin)
    kdbx_path = shutil.which(kdbx_bin)
    kdbx_db = os.environ.get("WICK_KDBX") or (cfg.get("keepassxc") or {}).get("db") or ""
    return {
        "ok": True,
        "product": "wick",
        "component": "vault",
        "local": {
            "available": True,
            "unlocked": bool(local_key),
            "store": store,
            "path": str(_paths()["root"]),
            "open_source": True,
            "format": VAULT_FORMAT,
        },
        "proton_pass": {
            "available": bool(pp_path),
            "bin": pp_path or pp_bin,
            "agent_tokens": True,
            "note": "Official pass-cli; AI agent tokens are scoped + audited by Proton",
        },
        "keepassxc": {
            "available": bool(kdbx_path),
            "bin": kdbx_path or kdbx_bin,
            "db_configured": bool(kdbx_db),
            "db": kdbx_db if kdbx_db else None,
        },
        "agentmail": {
            "bridge": "proton-agent-mail / AgentMail-shaped loopback",
            "ref": "agentmail://token or vault://agentmail/token",
            "note": "Store the bearer token in local vault; never commit it",
        },
        "brave_combine": {
            "shields": "wick shields (EasyList/EasyPrivacy, SSRF block, privacy headers)",
            "sessions": "WICK_SESSION cookie + Chromium profile isolation",
            "vault": "secret refs for fill — secrets stay out of agent context",
            "not_claimed": "Brave fingerprint farbling / Camoufox anti-bot",
        },
    }


def status() -> dict[str, Any]:
    st = backends_status()
    n = 0
    if st["local"]["unlocked"] and st["local"]["store"]:
        try:
            n = len(_read_store())
        except Exception:
            n = -1
    st["local"]["entries"] = n if n >= 0 else None
    st["local"]["entries_error"] = None if n >= 0 else "unlock_or_corrupt"
    return st


def list_entries(*, backend: str = "local") -> dict[str, Any]:
    if backend != "local":
        return {
            "ok": False,
            "error": "list_local_only",
            "hint": "Proton Pass / KeePassXC list via their CLIs; Wick only lists local metadata",
        }
    try:
        ensure_local_key()
        store = _read_store()
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    items = []
    for name, ent in sorted(store.items()):
        if not isinstance(ent, dict):
            continue
        fields = sorted(k for k in ent.keys() if k not in ("url", "notes", "tags", "updated"))
        items.append(
            {
                "name": name,
                "fields": fields,
                "url": ent.get("url") or None,
                "tags": ent.get("tags") or [],
                "updated": ent.get("updated"),
                "ref": f"vault://{name}/password" if "password" in ent else f"vault://{name}",
            }
        )
    _audit("list", ok=True, detail=f"n={len(items)}")
    return {"ok": True, "backend": "local", "count": len(items), "entries": items}


def totp_at(secret: str, when: int, *, digits: int = 6, period: int = 30) -> str:
    """RFC 6238 HOTP-SHA1 at a fixed unix time. Secret is base32 or otpauth://."""
    raw = _totp_secret_bytes(secret)
    digits = max(6, min(8, int(digits)))
    period = max(1, int(period))
    counter = int(when) // period
    msg = counter.to_bytes(8, "big")
    digest = hmac.new(raw, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (
        ((digest[offset] & 0x7F) << 24)
        | (digest[offset + 1] << 16)
        | (digest[offset + 2] << 8)
        | digest[offset + 3]
    ) % (10**digits)
    return f"{code:0{digits}d}"


def totp_now(secret: str, *, digits: int = 6, period: int = 30) -> str:
    return totp_at(secret, int(time.time()), digits=digits, period=period)


def _totp_secret_bytes(secret: str) -> bytes:
    s = (secret or "").strip().replace(" ", "")
    if s.lower().startswith("otpauth://"):
        q = parse_qs(urlparse(s).query)
        s = (q.get("secret") or [""])[0].replace(" ", "")
        if not s:
            raise ValueError("otpauth_missing_secret")
    pad = "=" * ((8 - len(s) % 8) % 8)
    try:
        return base64.b32decode(s.upper() + pad, casefold=True)
    except Exception as e:
        raise ValueError("bad_totp_secret") from e


def set_entry(
    name: str,
    *,
    password: str | None = None,
    username: str | None = None,
    url: str | None = None,
    notes: str | None = None,
    fields: dict[str, str] | None = None,
    tags: list[str] | None = None,
    allow_subdomains: bool | None = None,
) -> dict[str, Any]:
    name = (name or "").strip().strip("/")
    if not name or "/" in name and name.count("/") > 3:
        return {"ok": False, "error": "bad_name"}
    try:
        ensure_local_key()
        store = _read_store()
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    ent = dict(store.get(name) or {})
    if password is not None:
        ent["password"] = password
    if username is not None:
        ent["username"] = username
    if url is not None:
        ent["url"] = url
    if notes is not None:
        ent["notes"] = notes
    if tags is not None:
        ent["tags"] = list(tags)
    if allow_subdomains is not None:
        ent["allow_subdomains"] = bool(allow_subdomains)
    if fields:
        for k, v in fields.items():
            if k in ("name",):
                continue
            ent[str(k)] = str(v)
    if "password" not in ent and not any(k not in ("url", "notes", "tags", "updated", "username") for k in ent):
        return {"ok": False, "error": "nothing_to_store"}
    ent["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    store[name] = ent
    _write_store(store)
    _audit("set", ref=f"vault://{name}", ok=True)
    return {
        "ok": True,
        "name": name,
        "fields": sorted(k for k in ent if k not in ("notes",)),
        "ref": f"vault://{name}/password" if "password" in ent else f"vault://{name}",
        "revealed": False,
    }


def delete_entry(name: str) -> dict[str, Any]:
    name = (name or "").strip()
    try:
        ensure_local_key()
        store = _read_store()
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if name not in store:
        return {"ok": False, "error": "not_found", "name": name}
    del store[name]
    _write_store(store)
    _audit("delete", ref=f"vault://{name}", ok=True)
    return {"ok": True, "deleted": name}


def _entry_has_totp(ent: dict[str, Any]) -> bool:
    for k in ("totp", "otp_secret", "otpauth"):
        v = ent.get(k)
        if isinstance(v, str) and v.strip():
            return True
    return False


def _entry_totp_secret(ent: dict[str, Any]) -> str | None:
    for k in ("totp", "otp_secret", "otpauth"):
        v = ent.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def match_url(url: str) -> dict[str, Any]:
    """Return local entries whose *origin* matches the page — metadata only.

    Chrome/Brave rule: exact host (plus www alias). HTTPS-saved never matches HTTP.
    Optional per-entry allow_subdomains (saved parent may fill app.saved).
    """
    try:
        ensure_local_key()
        store = _read_store()
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    hits = []
    for name, ent in store.items():
        if not isinstance(ent, dict):
            continue
        eu = str(ent.get("url") or "")
        if not eu:
            continue
        allow_sub = bool(ent.get("allow_subdomains"))
        if wick_origins is None:
            # Fail closed: never substring-match if origins module is missing.
            continue
        ok, reason, score = wick_origins.origins_compatible(
            eu, url, allow_subdomains=allow_sub
        )
        if not ok:
            continue
        hits.append(
            {
                "name": name,
                "url": ent.get("url"),
                "reason": reason,
                "score": score,
                "allow_subdomains": allow_sub,
                "has_username": bool(ent.get("username")),
                "has_password": bool(ent.get("password")),
                "has_otp": _entry_has_totp(ent),
                "username_ref": f"vault://{name}/username" if ent.get("username") else None,
                "password_ref": f"vault://{name}/password" if ent.get("password") else None,
                "otp_ref": f"vault://{name}/otp" if _entry_has_totp(ent) else None,
            }
        )
    hits.sort(key=lambda h: (-int(h.get("score") or 0), h.get("name") or ""))
    _audit("match", ref=url[:120], ok=True, detail=f"hits={len(hits)}")
    return {"ok": True, "url": url, "matches": hits, "count": len(hits)}


def _parse_ref(ref: str) -> tuple[str, str]:
    m = REF_RE.match((ref or "").strip())
    if not m:
        raise ValueError("not_a_ref")
    return m.group("scheme").lower(), m.group("body")


def resolve(ref: str, *, reason: str = "resolve") -> dict[str, Any]:
    """Resolve a secret ref to a value. Caller must not print value to agent logs."""
    scheme, body = _parse_ref(ref)
    try:
        if scheme == "agentmail":
            # agentmail://token → vault://agentmail/token
            field = body.strip("/") or "token"
            return resolve(f"vault://agentmail/{field}", reason=reason)
        if scheme == "env":
            var = body.split("/", 1)[0].strip()
            if not var or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", var):
                raise ValueError("bad_env_name")
            val = os.environ.get(var)
            if val is None:
                raise ValueError("env_missing")
            _audit("resolve_env", ref=f"env://{var}", ok=True, detail=reason[:80])
            return {"ok": True, "backend": "env", "ref": f"env://{var}", "value": val, "chars": len(val)}
        if scheme == "vault":
            return _resolve_local(body, reason=reason)
        if scheme == "pass":
            return _resolve_proton_pass(body, reason=reason)
        if scheme == "kdbx":
            return _resolve_kdbx(body, reason=reason)
        raise ValueError("unknown_scheme")
    except ValueError as e:
        _audit("resolve", ref=ref, ok=False, detail=str(e))
        return {"ok": False, "error": str(e), "ref": _redact_ref(ref)}


def _resolve_local(body: str, *, reason: str) -> dict[str, Any]:
    parts = [unquote(p) for p in body.split("/") if p]
    if not parts:
        raise ValueError("empty_ref")
    if len(parts) == 1:
        name, field = parts[0], DEFAULT_FIELD
    else:
        name, field = "/".join(parts[:-1]), parts[-1]
    ensure_local_key()
    store = _read_store()
    ent = store.get(name)
    if not isinstance(ent, dict):
        # try last segment only as name
        ent = store.get(parts[0])
        if isinstance(ent, dict) and len(parts) == 2:
            name, field = parts[0], parts[1]
        else:
            raise ValueError("not_found")
    if field in ("otp", "totp_code"):
        secret = _entry_totp_secret(ent)
        if not secret:
            raise ValueError("field_missing")
        val = totp_now(secret)
        field = "otp"
    elif field not in ent:
        raise ValueError("field_missing")
    else:
        val = str(ent[field])
    _audit("resolve_local", ref=f"vault://{name}/{field}", ok=True, detail=reason[:80])
    return {
        "ok": True,
        "backend": "local",
        "ref": f"vault://{name}/{field}",
        "value": val,
        "chars": len(val),
        "name": name,
        "field": field,
    }


def _resolve_proton_pass(body: str, *, reason: str) -> dict[str, Any]:
    parts = [unquote(p) for p in body.split("/") if p]
    if len(parts) < 2:
        raise ValueError("pass_ref_need_vault_item")
    field = DEFAULT_FIELD
    if len(parts) >= 3:
        vault_name, item_name, field = parts[0], parts[1], parts[2]
    else:
        vault_name, item_name = parts[0], parts[1]
    cfg = load_config()
    bin_name = (cfg.get("proton_pass") or {}).get("bin") or "pass-cli"
    exe = shutil.which(bin_name)
    if not exe:
        raise ValueError("pass_cli_missing")
    env = os.environ.copy()
    # Prefer agent path when reason set
    env.setdefault("PROTON_PASS_AGENT_REASON", reason[:200] or "wick vault fill")
    cmd = [
        exe,
        "item",
        "view",
        "--vault-name",
        vault_name,
        "--item-name",
        item_name,
        "--field",
        field,
    ]
    # Newer CLI may use `agent item view`
    agent_cmd = [
        exe,
        "agent",
        "item",
        "view",
        "--vault-name",
        vault_name,
        "--item-name",
        item_name,
        "--field",
        field,
    ]
    val = None
    err = ""
    for attempt in (agent_cmd, cmd):
        try:
            proc = subprocess.run(
                attempt,
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )
        except Exception as e:
            err = str(e)[:120]
            continue
        if proc.returncode == 0 and (proc.stdout or "").strip():
            val = (proc.stdout or "").strip()
            # pass-cli sometimes wraps JSON
            if val.startswith("{"):
                try:
                    obj = json.loads(val)
                    if isinstance(obj, dict):
                        val = str(obj.get("value") or obj.get(field) or obj.get("password") or val)
                except Exception:
                    pass
            break
        err = ((proc.stderr or proc.stdout or "")[:160]).strip()
    if val is None:
        raise ValueError(f"pass_cli_failed:{err or 'no_output'}")
    _audit(
        "resolve_pass",
        ref=f"pass://{vault_name}/{item_name}/{field}",
        ok=True,
        detail=reason[:80],
    )
    return {
        "ok": True,
        "backend": "proton_pass",
        "ref": f"pass://{vault_name}/{item_name}/{field}",
        "value": val,
        "chars": len(val),
    }


def _resolve_kdbx(body: str, *, reason: str) -> dict[str, Any]:
    parts = [unquote(p) for p in body.split("/") if p]
    if not parts:
        raise ValueError("empty_kdbx_ref")
    field = DEFAULT_FIELD
    if len(parts) >= 2 and parts[-1].lower() in ("password", "username", "url", "notes", "totp"):
        entry = "/".join(parts[:-1])
        field = parts[-1].lower()
    else:
        entry = "/".join(parts)
    cfg = load_config()
    bin_name = (cfg.get("keepassxc") or {}).get("bin") or "keepassxc-cli"
    exe = shutil.which(bin_name)
    if not exe:
        raise ValueError("keepassxc_cli_missing")
    db = os.environ.get("WICK_KDBX") or (cfg.get("keepassxc") or {}).get("db") or ""
    if not db or not Path(db).is_file():
        raise ValueError("kdbx_db_missing")
    attr = {"password": "Password", "username": "UserName", "url": "URL", "notes": "Notes"}.get(field, field)
    cmd = [exe, "show", "-s", "-a", attr, db, entry]
    env = os.environ.copy()
    # Optional: WICK_KDBX_PASSWORD or empty for unlocked keyfile setups
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            input=(os.environ.get("WICK_KDBX_PASSWORD") or "") + "\n",
        )
    except Exception as e:
        raise ValueError(f"kdbx_failed:{e}") from e
    if proc.returncode != 0:
        raise ValueError(f"kdbx_failed:{(proc.stderr or proc.stdout or '')[:120]}")
    val = (proc.stdout or "").strip()
    if not val:
        raise ValueError("kdbx_empty")
    _audit("resolve_kdbx", ref=f"kdbx://{entry}/{field}", ok=True, detail=reason[:80])
    return {
        "ok": True,
        "backend": "keepassxc",
        "ref": f"kdbx://{entry}/{field}",
        "value": val,
        "chars": len(val),
    }


def resolve_for_fill(
    text: str,
    *,
    reason: str = "act_fill",
    page_url: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """If text is a secret ref, resolve it; else return text unchanged.

    Local vault refs are origin-bound when page_url is set (Chrome autofill rule).
    """
    if not is_secret_ref(text):
        return text, {"resolved": False}
    r = resolve(text, reason=reason)
    if not r.get("ok"):
        raise ValueError(r.get("error") or "resolve_failed")
    origin_ok = True
    origin_reason = "not_checked"
    if page_url and r.get("backend") == "local":
        name = r.get("name")
        if not name:
            scheme, body = _parse_ref(r.get("ref") or text)
            parts = [p for p in body.split("/") if p]
            name = "/".join(parts[:-1]) if len(parts) > 1 else (parts[0] if parts else "")
        try:
            store = _read_store()
        except ValueError as e:
            raise ValueError(str(e)) from e
        ent = store.get(name) if isinstance(store.get(name), dict) else {}
        saved = (ent or {}).get("url")
        allow_sub = bool((ent or {}).get("allow_subdomains"))
        if saved:
            if wick_origins is None:
                raise ValueError("origin_mismatch:no_origins_module")
            origin_ok, origin_reason, _score = wick_origins.origins_compatible(
                str(saved), page_url, allow_subdomains=allow_sub
            )
            if not origin_ok:
                _audit("resolve_denied", ref=r.get("ref") or text, ok=False, detail=origin_reason)
                raise ValueError(f"origin_mismatch:{origin_reason}")
        elif os.environ.get("WICK_VAULT_REQUIRE_ORIGIN", "1") != "0":
            _audit("resolve_denied", ref=r.get("ref") or text, ok=False, detail="unbound")
            raise ValueError("origin_unbound")
        else:
            origin_reason = "unbound_allowed"
    return str(r["value"]), {
        "resolved": True,
        "backend": r.get("backend"),
        "ref": r.get("ref"),
        "chars": r.get("chars"),
        "origin_ok": origin_ok,
        "origin_reason": origin_reason,
    }


def suggest_login(
    url: str,
    *,
    elements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Agent-safe autofill recipe: refs + selectors, never secret values."""
    matched = match_url(url)
    if not matched.get("ok"):
        return matched
    form = None
    if elements is not None and wick_login_form is not None:
        form = wick_login_form.detect_login_fields(elements)
    recipe = None
    hits = matched.get("matches") or []
    if hits:
        m = hits[0]
        cmds = [f"wick act login {url!r}"]
        user_hint = (form or {}).get("username") or {}
        pass_hint = (form or {}).get("password") or {}
        otp_hint = (form or {}).get("otp") or {}
        if user_hint.get("hint") and m.get("username_ref"):
            cmds.append(f"wick act fill {user_hint['hint']!r} {m['username_ref']!r}")
        if pass_hint.get("hint") and m.get("password_ref"):
            cmds.append(f"wick act fill {pass_hint['hint']!r} {m['password_ref']!r}")
        if otp_hint.get("hint") and m.get("otp_ref"):
            cmds.append(f"wick act fill {otp_hint['hint']!r} {m['otp_ref']!r}")
        recipe = {
            "name": m.get("name"),
            "username_ref": m.get("username_ref"),
            "password_ref": m.get("password_ref"),
            "otp_ref": m.get("otp_ref"),
            "username_hint": user_hint.get("hint"),
            "password_hint": pass_hint.get("hint"),
            "otp_hint": otp_hint.get("hint"),
            "submit_hint": ((form or {}).get("submit") or {}).get("hint"),
            "login_cmd": f"wick act login {url!r}",
            "cmds": cmds,
            "reason": m.get("reason"),
            "score": m.get("score"),
        }
    return {
        "ok": True,
        "product": "wick",
        "component": "vault",
        "mode": "suggest_login",
        "url": url,
        "matches": hits,
        "count": len(hits),
        "form": form,
        "recipe": recipe,
        "revealed": False,
        "hint": "Secrets stay in the vault. Run recipe.login_cmd or wick act login. Never --reveal.",
    }


def get_meta(ref_or_name: str, *, reveal: bool = False) -> dict[str, Any]:
    """Metadata about a local entry or ref. reveal=True returns value (CLI only; still audited)."""
    ref = ref_or_name
    if "://" not in ref:
        ref = f"vault://{ref_or_name}/password"
    if not reveal:
        scheme, body = _parse_ref(ref)
        if scheme != "vault":
            return {
                "ok": True,
                "ref": _redact_ref(ref),
                "backend": scheme,
                "revealed": False,
                "hint": "pass --reveal only for local debug; agents should use fill with refs",
            }
        try:
            ensure_local_key()
            store = _read_store()
            parts = [p for p in body.split("/") if p]
            name = parts[0] if parts else ""
            ent = store.get(name) or {}
            return {
                "ok": True,
                "name": name,
                "fields": sorted(ent.keys()) if isinstance(ent, dict) else [],
                "url": ent.get("url") if isinstance(ent, dict) else None,
                "ref": f"vault://{name}/password",
                "revealed": False,
            }
        except ValueError as e:
            return {"ok": False, "error": str(e)}
    r = resolve(ref, reason="cli_reveal")
    if not r.get("ok"):
        return r
    return {
        "ok": True,
        "ref": r.get("ref"),
        "backend": r.get("backend"),
        "chars": r.get("chars"),
        "value": r.get("value"),
        "revealed": True,
        "warning": "Secret printed. Prefer act fill with refs so agents never see values.",
    }


def generate_password(length: int = 24) -> dict[str, Any]:
    length = max(8, min(128, int(length)))
    # ambiguous-safe alphabet
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*-_"
    pw = "".join(secrets.choice(alphabet) for _ in range(length))
    return {"ok": True, "password": pw, "length": length, "revealed": True}


def doctor() -> dict[str, Any]:
    st = status()
    checks = []
    root = _paths()["root"]
    mode = oct(root.stat().st_mode & 0o777) if root.is_dir() else None
    checks.append({"name": "vault_dir_0700", "ok": mode == "0o700", "mode": mode})
    key = _paths()["key"]
    if key.is_file():
        km = oct(key.stat().st_mode & 0o777)
        checks.append({"name": "master_key_0600", "ok": km == "0o600", "mode": km})
    else:
        checks.append({"name": "master_key", "ok": bool(os.environ.get("WICK_VAULT_KEY")), "mode": "env_or_missing"})
    checks.append({"name": "local_backend", "ok": True})
    checks.append({"name": "proton_pass_cli", "ok": bool(st["proton_pass"]["available"])})
    checks.append({"name": "keepassxc_cli", "ok": bool(st["keepassxc"]["available"])})
    return {
        "ok": all(c.get("ok") for c in checks if c["name"] in ("vault_dir_0700", "local_backend")),
        "product": "wick",
        "component": "vault",
        "checks": checks,
        "backends": st,
    }
