#!/usr/bin/env python3
"""AEAD + key derivation for the Wick vault (wickvault2).

Real primitives only — no homemade cipher lives here:

- AES-256-GCM (``cryptography`` / OpenSSL) for every wrap and every item blob
- HKDF-SHA256 to stretch master material into the wrap key
- Argon2id (``argon2-cffi``) or scrypt n=2**16,r=8,p=1 for human passphrases

Key hierarchy: ``wrap key -> vault key -> per-item key -> item blob``.
Every sealed value carries a GCM AAD so ciphertext cannot be moved between
items, renamed, or repointed at another origin.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any, Mapping

FORMAT = "wickvault2"
LEGACY_FORMAT = "wickvault1"
AEAD = "aes-256-gcm"
HIERARCHY = "wrap→vault→item"
KEY_BYTES = 32
NONCE_BYTES = 12
SALT_BYTES = 16
WRAP_INFO = b"wick-vault-wrap"

SCRYPT_PARAMS: dict[str, int] = {"n": 2**16, "r": 8, "p": 1}
# 128 * n * r bytes of scratch; give OpenSSL headroom above the 64 MiB working set.
_SCRYPT_MAXMEM = 192 * 1024 * 1024
ARGON2_PARAMS: dict[str, int] = {"time_cost": 3, "memory_cost": 64 * 1024, "parallelism": 4}

try:  # pragma: no cover - import shape depends on host wheels
    from cryptography.exceptions import InvalidTag as _InvalidTag
    from cryptography.hazmat.primitives import hashes as _hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF as _HKDF

    HAVE_AEAD = True
except Exception:  # pragma: no cover
    _InvalidTag = Exception  # type: ignore[assignment,misc]
    _hashes = None  # type: ignore[assignment]
    _AESGCM = None  # type: ignore[assignment]
    _HKDF = None  # type: ignore[assignment]
    HAVE_AEAD = False

try:  # pragma: no cover - optional dependency
    from argon2.low_level import Type as _Argon2Type
    from argon2.low_level import hash_secret_raw as _argon2_raw

    HAVE_ARGON2 = True
except Exception:  # pragma: no cover
    _Argon2Type = None  # type: ignore[assignment]
    _argon2_raw = None  # type: ignore[assignment]
    HAVE_ARGON2 = False

# Passphrase KDFs are deliberately slow; memoize per process so a single agent
# command does not pay Argon2id/scrypt cost on every store read. Never persisted.
_PASSPHRASE_CACHE: dict[tuple[str, str, str], bytes] = {}


def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64d(text: str) -> bytes:
    s = (text or "").strip()
    pad = "=" * (-len(s) % 4)
    try:
        return base64.urlsafe_b64decode(s + pad)
    except Exception as e:
        raise ValueError("bad_b64") from e


def available() -> bool:
    """True when AES-GCM + HKDF are importable."""
    return bool(HAVE_AEAD)


def require_aead() -> None:
    if not HAVE_AEAD:
        raise ValueError("aead_unavailable")


def random_key() -> bytes:
    return secrets.token_bytes(KEY_BYTES)


def random_salt() -> bytes:
    return secrets.token_bytes(SALT_BYTES)


def random_nonce() -> bytes:
    return secrets.token_bytes(NONCE_BYTES)


def derive_wrap_key(material: bytes, salt: bytes, *, info: bytes = WRAP_INFO) -> bytes:
    """HKDF-SHA256(master material, salt, info) -> 32-byte wrap key."""
    require_aead()
    if not material:
        raise ValueError("empty_key_material")
    hkdf = _HKDF(algorithm=_hashes.SHA256(), length=KEY_BYTES, salt=salt or b"", info=info)
    return hkdf.derive(bytes(material))


def passphrase_kdf_name() -> str:
    """Which passphrase KDF this host would use for a new store."""
    return "argon2id" if HAVE_ARGON2 else "scrypt"


def passphrase_key(
    passphrase: str,
    salt: bytes,
    *,
    kdf: str | None = None,
    params: Mapping[str, Any] | None = None,
) -> tuple[bytes, str, dict[str, int]]:
    """Stretch a human passphrase. Returns (key, kdf_name, kdf_params)."""
    if not passphrase:
        raise ValueError("empty_passphrase")
    if not salt:
        raise ValueError("empty_salt")
    name = (kdf or passphrase_kdf_name()).strip().lower()
    if name == "argon2id":
        if not HAVE_ARGON2:
            raise ValueError("argon2_unavailable")
        p = {**ARGON2_PARAMS, **{k: int(v) for k, v in (params or {}).items() if k in ARGON2_PARAMS}}
        cache_key = _cache_key(name, salt, passphrase, p)
        hit = _PASSPHRASE_CACHE.get(cache_key)
        if hit is not None:
            return hit, name, p
        key = _argon2_raw(
            secret=passphrase.encode("utf-8"),
            salt=bytes(salt),
            time_cost=int(p["time_cost"]),
            memory_cost=int(p["memory_cost"]),
            parallelism=int(p["parallelism"]),
            hash_len=KEY_BYTES,
            type=_Argon2Type.ID,
        )
        _PASSPHRASE_CACHE[cache_key] = key
        return key, name, p
    if name == "scrypt":
        p = {**SCRYPT_PARAMS, **{k: int(v) for k, v in (params or {}).items() if k in SCRYPT_PARAMS}}
        cache_key = _cache_key(name, salt, passphrase, p)
        hit = _PASSPHRASE_CACHE.get(cache_key)
        if hit is not None:
            return hit, name, p
        key = hashlib.scrypt(
            passphrase.encode("utf-8"),
            salt=bytes(salt),
            n=int(p["n"]),
            r=int(p["r"]),
            p=int(p["p"]),
            dklen=KEY_BYTES,
            maxmem=_SCRYPT_MAXMEM,
        )
        _PASSPHRASE_CACHE[cache_key] = key
        return key, name, p
    raise ValueError(f"unknown_kdf:{name[:24]}")


def _cache_key(kdf: str, salt: bytes, passphrase: str, params: Mapping[str, Any]) -> tuple[str, str, str]:
    fp = hashlib.sha256(b"wick-vault-cache" + bytes(salt) + passphrase.encode("utf-8")).hexdigest()
    shape = ",".join(f"{k}={params[k]}" for k in sorted(params))
    return (kdf, shape, fp)


def seal(key: bytes, plaintext: bytes, aad: bytes) -> dict[str, str]:
    """AES-256-GCM encrypt. Returns {"nonce": b64url, "ct": b64url}."""
    require_aead()
    if len(key) != KEY_BYTES:
        raise ValueError("bad_key_length")
    nonce = random_nonce()
    ct = _AESGCM(bytes(key)).encrypt(nonce, bytes(plaintext), bytes(aad))
    return {"nonce": b64e(nonce), "ct": b64e(ct)}


def open_sealed(key: bytes, sealed: Mapping[str, Any] | None, aad: bytes) -> bytes:
    """AES-256-GCM decrypt. Any tag/format failure raises ValueError("bad_mac_or_key")."""
    require_aead()
    if len(key) != KEY_BYTES:
        raise ValueError("bad_key_length")
    if not isinstance(sealed, Mapping):
        raise ValueError("bad_mac_or_key")
    nonce_b = sealed.get("nonce")
    ct_b = sealed.get("ct")
    if not isinstance(nonce_b, str) or not isinstance(ct_b, str):
        raise ValueError("bad_mac_or_key")
    try:
        nonce = b64d(nonce_b)
        ct = b64d(ct_b)
    except ValueError as e:
        raise ValueError("bad_mac_or_key") from e
    if len(nonce) != NONCE_BYTES:
        raise ValueError("bad_mac_or_key")
    try:
        return _AESGCM(bytes(key)).decrypt(nonce, ct, bytes(aad))
    except _InvalidTag as e:
        raise ValueError("bad_mac_or_key") from e
    except Exception as e:  # malformed ciphertext length, etc.
        raise ValueError("bad_mac_or_key") from e


def aad_vault_key() -> bytes:
    return b"wickvault2|vault-key"


def aad_item_key(name: str) -> bytes:
    return b"wickvault2|item-key|" + (name or "").encode("utf-8")


def aad_item_origin(name: str) -> bytes:
    return b"wickvault2|item-origin|" + (name or "").encode("utf-8")


def aad_blob(name: str, origin: str) -> bytes:
    return (
        b"wickvault2|blob|"
        + (name or "").encode("utf-8")
        + b"|"
        + (origin or "").encode("utf-8")
    )


def aad_session() -> bytes:
    return b"wickvault2|session-key"


def info() -> dict[str, Any]:
    """Self-description for status/doctor. No secrets."""
    return {
        "format": FORMAT,
        "aead": AEAD,
        "hierarchy": HIERARCHY,
        "kdf_passphrase": passphrase_kdf_name(),
        "aead_available": bool(HAVE_AEAD),
        "argon2_available": bool(HAVE_ARGON2),
        "legacy_read_only": LEGACY_FORMAT,
        "audited": False,
    }
