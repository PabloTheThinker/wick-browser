#!/usr/bin/env python3
"""Wick Vault — agent-safe secret refs for fill/login (open local + Proton Pass + bridges).

Design (security-first for agents):
- Secrets never appear in list/status/match/doctor JSON.
- Agents pass *refs* (vault://…, pass://…, env://…, kdbx://…); only the fill path resolves.
- Local backend is open-source, file-based under WICK_HOME/vault (mode 0700).
- Local crypto is wickvault2: AES-256-GCM with HKDF-SHA256 wrap key → vault key →
  per-item key (see lib/vault_crypto.py and docs/VAULT-CRYPTO.md). wickvault1
  (SHA-256 XOR stream) is read-only and migrates on the next write.
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


wick_origins = _sibling_module("origins")
wick_login_form = _sibling_module("login_form")
vcrypto = _sibling_module("vault_crypto")
wick_passkey = _sibling_module("passkey")

VAULT_FORMAT = "wickvault2"
LEGACY_VAULT_FORMAT = "wickvault1"
DEFAULT_LOCK_TTL = 900
DEFAULT_GRANT_TTL = 120
MAX_UNLOCK_FAILURES = 8
FAILURE_COOLDOWN_S = 30
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
        "session": root / "session.json",
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


# --------------------------------------------------------------------------
# wickvault1 (legacy, read + migrate only)
#
# SHA-256 counter XOR + HMAC. Kept so an existing store can be opened once and
# rewritten as wickvault2. Nothing on the write path calls _seal().
# --------------------------------------------------------------------------
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
    """Legacy wickvault1 writer — migration fixtures and tests only."""
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    key = _derive_key(master, salt)
    ct = bytes(a ^ b for a, b in zip(plaintext, _keystream(key, nonce, len(plaintext))))
    mac = hmac.new(key, salt + nonce + ct, hashlib.sha256).digest()
    return "$".join([LEGACY_VAULT_FORMAT, _b64e(salt), _b64e(nonce), _b64e(ct), _b64e(mac)])


def _open_seal(master: bytes, blob: str) -> bytes:
    parts = blob.strip().split("$")
    if len(parts) != 5 or parts[0] != LEGACY_VAULT_FORMAT:
        raise ValueError("bad_vault_format")
    _, salt_b, nonce_b, ct_b, mac_b = parts
    salt, nonce, ct, mac = _b64d(salt_b), _b64d(nonce_b), _b64d(ct_b), _b64d(mac_b)
    key = _derive_key(master, salt)
    expect = hmac.new(key, salt + nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(expect, mac):
        raise ValueError("bad_mac_or_key")
    return bytes(a ^ b for a, b in zip(ct, _keystream(key, nonce, len(ct))))


# --------------------------------------------------------------------------
# wickvault2 — AES-256-GCM with wrap -> vault -> item keys
# --------------------------------------------------------------------------
def _now() -> int:
    return int(time.time())


def _iso(when: int | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(when if when is not None else _now()))


def _require_crypto() -> Any:
    if vcrypto is None or not vcrypto.available():
        raise ValueError("aead_unavailable")
    return vcrypto


def _load_master() -> bytes | None:
    """File/env key material. Never used raw as an AES key — HKDF stretches it."""
    env = os.environ.get("WICK_VAULT_KEY") or os.environ.get("WICK_VAULT_MASTER")
    if env:
        return env.encode("utf-8")
    key_path = _paths()["key"]
    if key_path.is_file():
        return key_path.read_bytes().strip()
    return None


def _passphrase() -> str | None:
    """WICK_VAULT_PASSPHRASE — never logged, never audited, never returned."""
    pw = os.environ.get("WICK_VAULT_PASSPHRASE")
    return pw if pw else None


def _lock_ttl() -> int:
    raw = (os.environ.get("WICK_VAULT_LOCK_TTL") or "").strip()
    try:
        ttl = int(raw) if raw else DEFAULT_LOCK_TTL
    except ValueError:
        ttl = DEFAULT_LOCK_TTL
    return max(10, min(86400, ttl))


def store_format() -> str:
    """On-disk format without decrypting: wickvault2 | wickvault1 | none."""
    path = _paths()["store"]
    if not path.is_file():
        return "none"
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return "none"
    if not raw:
        return "none"
    if raw.startswith(LEGACY_VAULT_FORMAT + "$"):
        return LEGACY_VAULT_FORMAT
    try:
        obj = json.loads(raw)
    except ValueError:
        return "unknown"
    if isinstance(obj, dict) and obj.get("format") == VAULT_FORMAT:
        return VAULT_FORMAT
    return "unknown"


def _read_doc() -> dict[str, Any] | None:
    """Parsed wickvault2 document, or None for legacy/absent/unreadable stores."""
    path = _paths()["store"]
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw or raw.startswith(LEGACY_VAULT_FORMAT + "$"):
        return None
    try:
        obj = json.loads(raw)
    except ValueError:
        return None
    if isinstance(obj, dict) and obj.get("format") == VAULT_FORMAT:
        return obj
    return None


def _read_header() -> dict[str, Any] | None:
    doc = _read_doc()
    if doc is None:
        return None
    return {k: doc[k] for k in ("format", "aead", "kdf", "kdf_params", "salt", "wrapped_vault_key") if k in doc}


def _planned_kdf() -> str:
    """KDF a brand-new store would use on this host."""
    if _passphrase() is not None and _load_master() is None:
        return vcrypto.passphrase_kdf_name() if vcrypto is not None else "scrypt"
    return "filekey"


def kdf_mode() -> str:
    """'filekey' or the passphrase KDF name for the current store."""
    header = _read_header()
    if header and header.get("kdf"):
        return str(header["kdf"])
    return _planned_kdf()


def _read_meta() -> dict[str, Any]:
    p = _paths()["meta"]
    if not p.is_file():
        return {}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _write_meta(meta: dict[str, Any]) -> None:
    p = _paths()["meta"]
    try:
        p.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(p, 0o600)
    except OSError:
        pass


def _check_cooldown() -> None:
    """Refuse briefly after repeated bad unwraps. Counter only — no secrets."""
    meta = _read_meta()
    fails = int(meta.get("unwrap_failures") or 0)
    if fails < MAX_UNLOCK_FAILURES:
        return
    last = int(meta.get("unwrap_failed_at") or 0)
    if _now() - last < FAILURE_COOLDOWN_S:
        raise ValueError("vault_locked_cooldown")
    meta["unwrap_failures"] = 0
    _write_meta(meta)


def _note_failure() -> None:
    meta = _read_meta()
    meta["unwrap_failures"] = int(meta.get("unwrap_failures") or 0) + 1
    meta["unwrap_failed_at"] = _now()
    _write_meta(meta)


def _clear_failures() -> None:
    meta = _read_meta()
    if meta.get("unwrap_failures"):
        meta["unwrap_failures"] = 0
        _write_meta(meta)


def _entry_origin(ent: dict[str, Any]) -> str:
    """Saved origin for the blob AAD ('' when the entry is unbound)."""
    url = str((ent or {}).get("url") or "").strip()
    if not url or wick_origins is None:
        return ""
    parsed = wick_origins.parse_origin(url)
    return str((parsed or {}).get("origin") or "")


def _wrap_key_from_header(header: dict[str, Any]) -> bytes:
    crypto = _require_crypto()
    kdf = str(header.get("kdf") or "filekey")
    salt = _b64d(str(header.get("salt") or ""))
    if not salt:
        raise ValueError("corrupt_store")
    if kdf == "filekey":
        master = _load_master()
        if master is None:
            raise ValueError("vault_locked")
        return crypto.derive_wrap_key(master, salt)
    pw = _passphrase()
    if pw is None:
        raise ValueError("vault_locked")
    params = header.get("kdf_params") if isinstance(header.get("kdf_params"), dict) else {}
    stretched, _name, _params = crypto.passphrase_key(pw, salt, kdf=kdf, params=params)
    return crypto.derive_wrap_key(stretched, salt)


def _open_vault_key(header: dict[str, Any]) -> bytes:
    """Unwrap the vault key from the store header (or an unexpired session)."""
    crypto = _require_crypto()
    _check_cooldown()
    kdf = str(header.get("kdf") or "filekey")
    if kdf != "filekey" and _passphrase() is None:
        from_session = _session_vault_key()
        if from_session is not None:
            return from_session
    try:
        wrap = _wrap_key_from_header(header)
        vault_key = crypto.open_sealed(wrap, header.get("wrapped_vault_key"), crypto.aad_vault_key())
    except ValueError as e:
        if str(e) == "bad_mac_or_key":
            _note_failure()
        raise
    _clear_failures()
    return vault_key


def _new_header() -> tuple[dict[str, Any], bytes]:
    """Fresh salt + vault key. Passphrase mode when WICK_VAULT_PASSPHRASE is set."""
    crypto = _require_crypto()
    salt = crypto.random_salt()
    pw = _passphrase()
    if pw is not None and _load_master() is None:
        material, kdf, params = crypto.passphrase_key(pw, salt)
    else:
        master = _load_master()
        if master is None:
            raise ValueError("vault_locked")
        material, kdf, params = master, "filekey", {}
    wrap = crypto.derive_wrap_key(material, salt)
    vault_key = crypto.random_key()
    header = {
        "format": VAULT_FORMAT,
        "aead": crypto.AEAD,
        "kdf": kdf,
        "kdf_params": dict(params),
        "salt": _b64e(salt),
        "wrapped_vault_key": crypto.seal(wrap, vault_key, crypto.aad_vault_key()),
    }
    return header, vault_key


def _seal_item(vault_key: bytes, name: str, ent: dict[str, Any]) -> dict[str, Any]:
    """Per-item key wrapped by the vault key; blob bound to name + saved origin."""
    crypto = _require_crypto()
    item_key = crypto.random_key()
    origin = _entry_origin(ent)
    blob = json.dumps(ent, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "wrapped_item_key": crypto.seal(vault_key, item_key, crypto.aad_item_key(name)),
        "origin": crypto.seal(item_key, origin.encode("utf-8"), crypto.aad_item_origin(name)),
        "blob": crypto.seal(item_key, blob, crypto.aad_blob(name, origin)),
        "updated": str(ent.get("updated") or _iso()),
    }


def _open_item(vault_key: bytes, name: str, rec: dict[str, Any]) -> dict[str, Any]:
    crypto = _require_crypto()
    if not isinstance(rec, dict):
        raise ValueError("corrupt_store")
    item_key = crypto.open_sealed(vault_key, rec.get("wrapped_item_key"), crypto.aad_item_key(name))
    origin = ""
    if rec.get("origin"):
        origin = crypto.open_sealed(item_key, rec.get("origin"), crypto.aad_item_origin(name)).decode("utf-8")
    raw = crypto.open_sealed(item_key, rec.get("blob"), crypto.aad_blob(name, origin))
    try:
        ent = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        raise ValueError("corrupt_store") from e
    if not isinstance(ent, dict):
        raise ValueError("corrupt_store")
    if rec.get("updated") and not ent.get("updated"):
        ent["updated"] = str(rec["updated"])
    return ent


def ensure_local_key(*, rotate: bool = False) -> dict[str, Any]:
    """Create master.key (0600) if missing. Never prints the key.

    Passphrase mode (WICK_VAULT_PASSPHRASE with no existing key file) writes no
    key material to disk — the wrap key is derived on each use.
    """
    paths = _paths()
    key_path = paths["key"]
    created = False
    passphrase_mode = kdf_mode() != "filekey"
    if not passphrase_mode and (rotate or not key_path.is_file()):
        key = secrets.token_bytes(32)
        key_path.write_bytes(key)
        os.chmod(key_path, 0o600)
        created = True
        _audit("key_rotate" if rotate else "key_create", ok=True)
    meta = _read_meta()
    if not paths["meta"].is_file() or created:
        meta.update(
            {
                "format": VAULT_FORMAT,
                "aead": vcrypto.AEAD if vcrypto is not None else "unavailable",
                "created": _iso(),
                "backend": "local",
            }
        )
        _write_meta(meta)
    if not paths["store"].is_file():
        _write_store({})
    return {
        "ok": True,
        "created": created,
        "key_path": str(key_path) if not passphrase_mode else None,
        "mode": "passphrase" if passphrase_mode else "0600",
        "format": store_format() if store_format() != "none" else VAULT_FORMAT,
        "kdf": kdf_mode(),
        "aead": vcrypto.AEAD if vcrypto is not None else "unavailable",
    }


def _read_store() -> dict[str, Any]:
    """Decrypt the store into {name: entry-dict}. Opens wickvault1 for migration."""
    store_path = _paths()["store"]
    raw = ""
    if store_path.is_file():
        try:
            raw = store_path.read_text(encoding="utf-8").strip()
        except OSError as e:
            raise ValueError("corrupt_store") from e
    if not raw:
        if _load_master() is None and _passphrase() is None and _session_vault_key() is None:
            raise ValueError("vault_locked")
        return {}
    if raw.startswith(LEGACY_VAULT_FORMAT + "$"):
        return _read_store_legacy(raw)
    try:
        doc = json.loads(raw)
    except ValueError as e:
        raise ValueError("corrupt_store") from e
    if not isinstance(doc, dict) or doc.get("format") != VAULT_FORMAT:
        raise ValueError("bad_vault_format")
    _require_crypto()
    vault_key = _open_vault_key(doc)
    items = doc.get("items")
    if not isinstance(items, dict):
        raise ValueError("corrupt_store")
    entries: dict[str, Any] = {}
    try:
        for name, rec in items.items():
            entries[str(name)] = _open_item(vault_key, str(name), rec)
    except ValueError as e:
        if str(e) == "bad_mac_or_key":
            _note_failure()
        raise
    return entries


def _read_store_legacy(raw: str) -> dict[str, Any]:
    master = _load_master()
    if master is None:
        raise ValueError("vault_locked")
    _check_cooldown()
    try:
        data = _open_seal(master, raw)
    except ValueError as e:
        if str(e) == "bad_mac_or_key":
            _note_failure()
        raise
    try:
        obj = json.loads(data.decode("utf-8"))
    except ValueError as e:
        raise ValueError("corrupt_store") from e
    if not isinstance(obj, dict):
        raise ValueError("corrupt_store")
    _clear_failures()
    return obj


def _write_store(entries: dict[str, Any]) -> None:
    """Always writes wickvault2. Reuses the existing vault key when openable."""
    crypto = _require_crypto()
    header: dict[str, Any] | None = None
    vault_key: bytes | None = None
    doc = _read_doc()
    if doc is not None:
        try:
            vault_key = _open_vault_key(doc)
            header = _read_header()
        except ValueError:
            header, vault_key = None, None
    if header is None or vault_key is None:
        header, vault_key = _new_header()
    items: dict[str, Any] = {}
    for name, ent in entries.items():
        if not isinstance(ent, dict):
            continue
        items[str(name)] = _seal_item(vault_key, str(name), ent)
    out = dict(header)
    out["aead"] = crypto.AEAD
    out["items"] = items
    path = _paths()["store"]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


# --------------------------------------------------------------------------
# Session broker: unlock / lock / origin grants
# --------------------------------------------------------------------------
def _read_session() -> dict[str, Any] | None:
    p = _paths()["session"]
    if not p.is_file():
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    if int(obj.get("exp") or 0) <= _now():
        try:
            p.unlink()
        except OSError:
            pass
        return None
    return obj


def _write_session(sess: dict[str, Any]) -> None:
    p = _paths()["session"]
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(sess, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(p)
    os.chmod(p, 0o600)


def _session_vault_key() -> bytes | None:
    """Vault key held by an unexpired passphrase-mode session, if any."""
    if vcrypto is None or not vcrypto.available():
        return None
    sess = _read_session()
    if not sess:
        return None
    sk = sess.get("session_key")
    wrapped = sess.get("wrapped_vault_key")
    if not isinstance(sk, str) or not isinstance(wrapped, dict):
        return None
    try:
        return vcrypto.open_sealed(_b64d(sk), wrapped, vcrypto.aad_session())
    except ValueError:
        return None


def _active_grants() -> list[dict[str, Any]]:
    sess = _read_session()
    if not sess:
        return []
    now = _now()
    out = []
    for g in sess.get("grants") or []:
        if isinstance(g, dict) and str(g.get("origin") or "") and int(g.get("exp") or 0) > now:
            out.append(g)
    return out


def _grant_allows(url: str | None) -> tuple[bool, str]:
    """True when no grants are active, or one covers this URL."""
    grants = _active_grants()
    if not grants:
        return True, "no_grants"
    u = (url or "").strip()
    if not u:
        return False, "no_url"
    if wick_origins is None:
        return False, "no_origins_module"
    for g in grants:
        ok, reason, _score = wick_origins.origins_compatible(
            str(g.get("origin") or ""), u, allow_subdomains=False
        )
        if ok:
            return True, reason
    return False, "not_granted"


def unlock(ttl: int | None = None) -> dict[str, Any]:
    """Verify the vault key opens and write a TTL-limited session (0600)."""
    if ttl is None:
        seconds = _lock_ttl()
    else:
        try:
            seconds = int(ttl)
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad_ttl"}
        if seconds <= 0:
            return {"ok": False, "error": "bad_ttl"}
    seconds = min(86400, seconds)
    try:
        ensure_local_key()
        header = _read_header()
        vault_key: bytes | None = None
        if header is not None:
            vault_key = _open_vault_key(header)
        else:
            _read_store()
    except ValueError as e:
        _audit("unlock", ok=False, detail=str(e))
        return {"ok": False, "error": str(e)}
    kdf = str((header or {}).get("kdf") or kdf_mode())
    mode = "filekey" if kdf == "filekey" else "passphrase"
    exp = _now() + seconds
    sess: dict[str, Any] = {
        "exp": exp,
        "mode": mode,
        "kdf": kdf,
        "grants": [],
        "created": _iso(),
    }
    note = None
    if mode == "passphrase" and vault_key is not None and vcrypto is not None:
        session_key = vcrypto.random_key()
        sess["session_key"] = _b64e(session_key)
        sess["wrapped_vault_key"] = vcrypto.seal(session_key, vault_key, vcrypto.aad_session())
        note = "session key lives in this 0600 file until exp — TTL convenience, not a hardware keystore"
        sess["note"] = note
    _write_session(sess)
    _audit("unlock", ok=True, detail=f"mode={mode} ttl={seconds}")
    return {
        "ok": True,
        "unlocked": True,
        "mode": mode,
        "kdf": kdf,
        "ttl": seconds,
        "exp": exp,
        "expires": _iso(exp),
        "grants": 0,
        "session": str(_paths()["session"]),
        "note": note,
    }


def lock() -> dict[str, Any]:
    """Delete the session (and any origin grants with it)."""
    p = _paths()["session"]
    grants = len(_active_grants())
    existed = p.is_file()
    try:
        p.unlink()
    except FileNotFoundError:
        existed = False
    except OSError as e:
        return {"ok": False, "error": "session_unlink_failed", "detail": str(e)[:80]}
    mode = "filekey" if kdf_mode() == "filekey" else "passphrase"
    _audit("lock", ok=True, detail=f"mode={mode} grants={grants}")
    return {
        "ok": True,
        "locked": True,
        "session_cleared": existed,
        "grants_cleared": grants,
        "mode": mode,
        "note": (
            "file-key mode stays readable while master.key exists — lock clears grants/session only"
            if mode == "filekey"
            else "passphrase mode: resolve now needs WICK_VAULT_PASSPHRASE or a new unlock"
        ),
    }


def grant(url: str, ttl: int | None = DEFAULT_GRANT_TTL) -> dict[str, Any]:
    """Allow resolve/fill for one origin until TTL. Other origins are denied."""
    u = (url or "").strip()
    if not u:
        return {"ok": False, "error": "missing_url", "hint": "wick vault grant --url https://example.com/login"}
    if wick_origins is None:
        return {"ok": False, "error": "no_origins_module"}
    parsed = wick_origins.parse_origin(u)
    origin = str((parsed or {}).get("origin") or "")
    if not origin:
        return {"ok": False, "error": "bad_url"}
    if ttl is None:
        seconds = DEFAULT_GRANT_TTL
    else:
        try:
            seconds = int(ttl)
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad_ttl"}
        if seconds <= 0:
            return {"ok": False, "error": "bad_ttl"}
    seconds = min(86400, seconds)
    sess = _read_session()
    if sess is None:
        opened = unlock()
        if not opened.get("ok"):
            return opened
        sess = _read_session() or {}
    exp = _now() + seconds
    grants = [g for g in _active_grants() if str(g.get("origin")) != origin]
    grants.append({"origin": origin, "exp": exp})
    sess["grants"] = grants
    if int(sess.get("exp") or 0) < exp:
        sess["exp"] = exp
    _write_session(sess)
    _audit("grant", ref=origin, ok=True, detail=f"ttl={seconds}")
    return {
        "ok": True,
        "granted": origin,
        "ttl": seconds,
        "exp": exp,
        "expires": _iso(exp),
        "grants": [{"origin": str(g.get("origin")), "expires": _iso(int(g.get("exp") or 0))} for g in grants],
        "note": "while a grant is active, local resolve/fill is denied for every other origin",
    }


def session_status() -> dict[str, Any]:
    """Session + grant metadata. Never includes key material."""
    sess = _read_session()
    grants = _active_grants()
    mode = "filekey" if kdf_mode() == "filekey" else "passphrase"
    unlocked = bool(_load_master()) or _passphrase() is not None or _session_vault_key() is not None
    return {
        "active": bool(sess),
        "mode": mode,
        "exp": int((sess or {}).get("exp") or 0) or None,
        "expires": _iso(int(sess["exp"])) if sess and sess.get("exp") else None,
        "unlocked": unlocked,
        "grants": [{"origin": str(g.get("origin")), "expires": _iso(int(g.get("exp") or 0))} for g in grants],
        "grant_count": len(grants),
        "relock_after_fill": os.environ.get("WICK_VAULT_RELOCK_AFTER_FILL") == "1",
        "lock_ttl": _lock_ttl(),
    }


def crypto_info() -> dict[str, Any]:
    """Format/AEAD/KDF/hierarchy for status + doctor. No secrets."""
    fmt = store_format()
    return {
        "format": fmt if fmt not in ("none", "unknown") else VAULT_FORMAT,
        "store_format": fmt,
        "aead": vcrypto.AEAD if vcrypto is not None else "unavailable",
        "kdf": kdf_mode(),
        "hierarchy": vcrypto.HIERARCHY if vcrypto is not None else "wrap→vault→item",
        "aead_available": bool(vcrypto is not None and vcrypto.available()),
        "argon2_available": bool(vcrypto is not None and vcrypto.HAVE_ARGON2),
        "legacy_read_only": LEGACY_VAULT_FORMAT,
        "migrate_on_write": fmt == LEGACY_VAULT_FORMAT,
        "audited": False,
    }


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
    info = crypto_info()
    sess = session_status()
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
            "unlocked": bool(sess.get("unlocked")),
            "store": store,
            "path": str(_paths()["root"]),
            "open_source": True,
            "format": info["format"],
            "aead": info["aead"],
            "kdf": info["kdf"],
            "hierarchy": info["hierarchy"],
            "key_file": bool(local_key),
            "migrate_on_write": info["migrate_on_write"],
            "session": sess,
            "not_claimed": "no Proton cloud sync, no third-party audit, no HSM",
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


def _passkey_field_names() -> frozenset[str]:
    if wick_passkey is not None:
        return frozenset(getattr(wick_passkey, "PASSKEY_FIELD_NAMES", ()) or ())
    return frozenset(
        {
            "passkey_rpid",
            "passkey_id",
            "passkey_user_handle",
            "passkey_private_key",
            "passkey_public_key",
            "passkey_sign_count",
            "passkey_user",
        }
    )


def _entry_has_passkey(ent: dict[str, Any] | None) -> bool:
    if not isinstance(ent, dict):
        return False
    if wick_passkey is not None:
        return wick_passkey.from_entry(ent) is not None
    return bool(ent.get("passkey_private_key") and ent.get("passkey_rpid"))


def _visible_field_names(ent: dict[str, Any]) -> list[str]:
    hide = _passkey_field_names() | {"url", "notes", "tags", "updated"}
    names = [k for k in ent if k not in hide]
    if _entry_has_passkey(ent):
        names.append("has_passkey")
    return sorted(set(names))


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
        items.append(
            {
                "name": name,
                "fields": _visible_field_names(ent),
                "url": ent.get("url") or None,
                "tags": ent.get("tags") or [],
                "updated": ent.get("updated"),
                "has_passkey": _entry_has_passkey(ent),
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
    meta_keys = {"url", "notes", "tags", "updated", "username", "allow_subdomains"}
    if "password" not in ent and not any(k not in meta_keys for k in ent):
        return {"ok": False, "error": "nothing_to_store"}
    ent["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    store[name] = ent
    _write_store(store)
    _audit("set", ref=f"vault://{name}", ok=True)
    return {
        "ok": True,
        "name": name,
        "fields": _visible_field_names(ent),
        "has_passkey": _entry_has_passkey(ent),
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
                "has_passkey": _entry_has_passkey(ent),
                "username_ref": f"vault://{name}/username" if ent.get("username") else None,
                "password_ref": f"vault://{name}/password" if ent.get("password") else None,
                "otp_ref": f"vault://{name}/otp" if _entry_has_totp(ent) else None,
                "passkey_ref": f"vault://{name}/passkey" if _entry_has_passkey(ent) else None,
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
    if _active_grants():
        allowed, why = _grant_allows(str(ent.get("url") or ""))
        if not allowed:
            _audit("resolve_denied", ref=f"vault://{name}/{field}", ok=False, detail=f"grant:{why}")
            raise ValueError(f"grant_required:{why}")
    if field in ("otp", "totp_code"):
        secret = _entry_totp_secret(ent)
        if not secret:
            raise ValueError("field_missing")
        val = totp_now(secret)
        field = "otp"
    elif field == "passkey" or field in _passkey_field_names():
        raise ValueError("passkey_not_a_ref")
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
    grants = _active_grants()
    if grants and r.get("backend") == "local":
        allowed, why = _grant_allows(page_url)
        if not allowed:
            _audit("resolve_denied", ref=r.get("ref") or text, ok=False, detail=f"grant:{why}")
            raise ValueError(f"grant_required:{why}")
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
    relocked = False
    if r.get("backend") == "local" and os.environ.get("WICK_VAULT_RELOCK_AFTER_FILL") == "1":
        lock()
        relocked = True
    return str(r["value"]), {
        "resolved": True,
        "backend": r.get("backend"),
        "ref": r.get("ref"),
        "chars": r.get("chars"),
        "origin_ok": origin_ok,
        "origin_reason": origin_reason,
        "granted": bool(grants),
        "relocked": relocked,
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
            "passkey_ref": m.get("passkey_ref"),
            "username_hint": user_hint.get("hint"),
            "password_hint": pass_hint.get("hint"),
            "otp_hint": otp_hint.get("hint"),
            "submit_hint": ((form or {}).get("submit") or {}).get("hint"),
            "login_cmd": f"wick act login {url!r}",
            "passkey_cmd": f"wick act passkey {url!r}" if m.get("has_passkey") else None,
            "cmds": cmds + ([f"wick act passkey {url!r}"] if m.get("has_passkey") else []),
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


def create_passkey(
    name: str,
    *,
    url: str,
    username: str | None = None,
) -> dict[str, Any]:
    """Mint a discoverable P-256 passkey and store it. Never returns key material."""
    if wick_passkey is None:
        return {"ok": False, "error": "passkey_module_missing"}
    if not getattr(wick_passkey, "HAVE_EC", False):
        return {"ok": False, "error": "aead_unavailable"}
    name = (name or "").strip().strip("/")
    if not name:
        return {"ok": False, "error": "bad_name"}
    rid = wick_passkey.rp_id_from_url(url)
    if not rid:
        return {"ok": False, "error": "missing_rpid"}
    try:
        cred = wick_passkey.generate(rid, user_name=username or "agent")
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    out = set_entry(
        name,
        username=username,
        url=url,
        fields=wick_passkey.vault_fields(cred),
    )
    if not out.get("ok"):
        return out
    _audit("passkey_create", ref=f"vault://{name}/passkey", ok=True, detail=rid)
    return {
        "ok": True,
        "name": name,
        "url": url,
        "rp_id": rid,
        "has_passkey": True,
        "revealed": False,
    }


def save_passkey_from_cdp(
    name: str,
    url: str,
    raw: dict[str, Any],
    *,
    username: str | None = None,
) -> dict[str, Any]:
    """Persist a Chromium getCredentials item. Response is metadata only."""
    if wick_passkey is None:
        return {"ok": False, "error": "passkey_module_missing"}
    rid = wick_passkey.rp_id_from_url(url)
    cred = wick_passkey.from_cdp(raw, rp_id=rid)
    if not cred.get("private_key") or not cred.get("rp_id"):
        return {"ok": False, "error": "incomplete_credential"}
    out = set_entry(
        name,
        username=username or cred.get("user_name"),
        url=url,
        fields=wick_passkey.vault_fields(cred),
    )
    if not out.get("ok"):
        return out
    _audit("passkey_save", ref=f"vault://{name}/passkey", ok=True, detail=cred["rp_id"])
    return {
        "ok": True,
        "name": name,
        "url": url,
        "rp_id": cred["rp_id"],
        "has_passkey": True,
        "revealed": False,
    }


def export_passkey_for_cdp(name: str, page_url: str) -> dict[str, Any]:
    """Origin-bound CDP credential. Caller must not print credential to agents."""
    name = (name or "").strip()
    if wick_passkey is None:
        return {"ok": False, "error": "passkey_module_missing"}
    try:
        ensure_local_key()
        store = _read_store()
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    ent = store.get(name)
    if not isinstance(ent, dict):
        return {"ok": False, "error": "not_found", "name": name}
    cred = wick_passkey.from_entry(ent)
    if cred is None:
        return {"ok": False, "error": "no_passkey", "name": name}
    grants = _active_grants()
    if grants:
        allowed, why = _grant_allows(page_url)
        if not allowed:
            _audit("passkey_denied", ref=f"vault://{name}/passkey", ok=False, detail=f"grant:{why}")
            return {"ok": False, "error": f"grant_required:{why}"}
        saved_ok, saved_why = _grant_allows(str(ent.get("url") or ""))
        if not saved_ok:
            _audit("passkey_denied", ref=f"vault://{name}/passkey", ok=False, detail=f"grant:{saved_why}")
            return {"ok": False, "error": f"grant_required:{saved_why}"}
    saved = ent.get("url")
    if saved and wick_origins is not None:
        origin_ok, origin_reason, _score = wick_origins.origins_compatible(
            str(saved), page_url, allow_subdomains=bool(ent.get("allow_subdomains"))
        )
        if not origin_ok:
            _audit("passkey_denied", ref=f"vault://{name}/passkey", ok=False, detail=origin_reason)
            return {"ok": False, "error": f"origin_mismatch:{origin_reason}"}
    elif os.environ.get("WICK_VAULT_REQUIRE_ORIGIN", "1") != "0":
        _audit("passkey_denied", ref=f"vault://{name}/passkey", ok=False, detail="unbound")
        return {"ok": False, "error": "origin_unbound"}
    if not wick_passkey.rpid_matches_url(cred["rp_id"], page_url):
        _audit("passkey_denied", ref=f"vault://{name}/passkey", ok=False, detail="rpid_mismatch")
        return {"ok": False, "error": "rpid_mismatch"}
    _audit("export_passkey", ref=f"vault://{name}/passkey", ok=True, detail="cdp")
    return {
        "ok": True,
        "name": name,
        "rp_id": cred["rp_id"],
        "credential": wick_passkey.to_cdp(cred),
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
                "fields": _visible_field_names(ent) if isinstance(ent, dict) else [],
                "url": ent.get("url") if isinstance(ent, dict) else None,
                "has_passkey": _entry_has_passkey(ent) if isinstance(ent, dict) else False,
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
    sess_path = _paths()["session"]
    if sess_path.is_file():
        sm = oct(sess_path.stat().st_mode & 0o777)
        checks.append({"name": "session_0600", "ok": sm == "0o600", "mode": sm})
    checks.append({"name": "local_backend", "ok": True})
    info = crypto_info()
    checks.append({"name": "aead_aes_256_gcm", "ok": bool(info["aead_available"]), "detail": info["aead"]})
    checks.append(
        {
            "name": "store_format_wickvault2",
            "ok": info["store_format"] in (VAULT_FORMAT, "none"),
            "detail": info["store_format"],
            "hint": "wickvault1 store migrates to wickvault2 on the next write" if info["migrate_on_write"] else None,
        }
    )
    checks.append({"name": "key_hierarchy", "ok": True, "detail": info["hierarchy"]})
    checks.append({"name": "proton_pass_cli", "ok": bool(st["proton_pass"]["available"])})
    checks.append({"name": "keepassxc_cli", "ok": bool(st["keepassxc"]["available"])})
    required = ("vault_dir_0700", "local_backend", "aead_aes_256_gcm")
    return {
        "ok": all(c.get("ok") for c in checks if c["name"] in required),
        "product": "wick",
        "component": "vault",
        "format": info["format"],
        "aead": info["aead"],
        "kdf": info["kdf"],
        "hierarchy": info["hierarchy"],
        "crypto": info,
        "session": session_status(),
        "checks": checks,
        "backends": st,
    }
