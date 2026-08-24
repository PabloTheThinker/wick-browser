"""Honest HSM / TPM probe and a passkey seal layer.

Hardware on this path is optional. Most agent hosts (including this image)
have no `/dev/tpmrm0` and no PKCS#11 token. We still:

  - Probe and report what is actually present (`hsm: false` here)
  - Wrap passkey PKCS#8 with a dedicated AES-256-GCM key (filewrap, 0600)
  - Bind the wrap to rpId + entry name via AAD
  - Refuse create/export when `WICK_PASSKEY_REQUIRE_HSM=1` and no hardware

Filewrap is defense-in-depth on top of wickvault2, not a TPM. Never set
`hsm: true` unless a TPM device or a real PKCS#11 token is present.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

_TRUE = frozenset({"1", "true", "yes", "on"})

try:
    import vault_crypto as vcrypto
except Exception:
    vcrypto = None  # type: ignore


def _home() -> Path:
    raw = os.environ.get("WICK_HOME") or str(Path.home() / ".wick")
    return Path(raw).expanduser()


def _wrap_path() -> Path:
    return _home() / "vault" / "passkey.wrap"


def require_hsm() -> bool:
    raw = (os.environ.get("WICK_PASSKEY_REQUIRE_HSM") or "").strip().lower()
    if raw in _TRUE:
        return True
    try:
        import policy

        return bool(policy.effective().get("passkey_require_hsm"))
    except Exception:
        return False


def probe() -> dict[str, Any]:
    tpm_dev = None
    for cand in ("/dev/tpmrm0", "/dev/tpm0"):
        if Path(cand).exists():
            tpm_dev = cand
            break
    tpm_tools = bool(shutil.which("tpm2_create") and shutil.which("tpm2_unseal"))
    pkcs11_mods = [
        p
        for p in (
            "/usr/lib/x86_64-linux-gnu/pkcs11/opensc-pkcs11.so",
            "/usr/lib/x86_64-linux-gnu/libykcs11.so",
            "/usr/lib/libtpm2_pkcs11.so",
        )
        if Path(p).is_file()
    ]
    # Inventory only. A device node or .so on disk is not a usable token,
    # and this build never seals with TPM2/PKCS#11 — only filewrap.
    return {
        "hsm": False,
        "hardware_seal": False,
        "tpm": {
            "available": bool(tpm_dev),
            "device": tpm_dev,
            "tools": tpm_tools,
            "used": False,
        },
        "pkcs11": {
            "available": False,
            "modules": pkcs11_mods,
            "used": False,
            "note": "module file is not a token; p11-kit-trust is a CA store; this build does not use PKCS#11",
        },
        "recommended": "filewrap",
        "filewrap": True,
        "audited": False,
    }


def hardware_seal_available() -> bool:
    """True only if this process can seal with a TPM/PKCS#11 token.

    This build has no TPM2 unseal or PKCS#11 wrap path. Never claim hsm.
    """
    return False


def _ensure_wrap_key() -> bytes:
    """Prefer the vault-sealed wrap key; fall back to a 0600 file if no vault."""
    if vcrypto is None or not vcrypto.available():
        raise ValueError("aead_unavailable")
    try:
        import vault as wick_vault

        return wick_vault.passkey_wrap_key()
    except ValueError:
        raise
    except Exception:
        pass
    path = _wrap_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    if path.is_file():
        raw = path.read_bytes()
        if len(raw) == 32:
            return raw
    key = vcrypto.random_key()
    tmp = path.with_suffix(".wrap.tmp")
    tmp.write_bytes(key)
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)
    return key


def wrap(plaintext: bytes, *, aad: bytes) -> dict[str, Any]:
    """Seal passkey bytes. Hardware required only when require_hsm() is on."""
    info = probe()
    if require_hsm() and not hardware_seal_available():
        return {
            "ok": False,
            "error": "hsm_required",
            "hint": "No TPM/PKCS#11 seal path in this build. Unset WICK_PASSKEY_REQUIRE_HSM to use filewrap.",
            "probe": info,
        }
    if vcrypto is None or not vcrypto.available():
        return {"ok": False, "error": "aead_unavailable"}
    try:
        key = _ensure_wrap_key()
        blob = vcrypto.seal(key, plaintext, aad)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "backend": "filewrap",
        "hsm": False,
        "blob": blob,
        "alg": "aes-256-gcm",
    }


def unwrap(blob: Any, *, aad: bytes) -> bytes:
    if vcrypto is None or not vcrypto.available():
        raise ValueError("aead_unavailable")
    if isinstance(blob, dict) and "nonce" in blob and "ct" in blob:
        sealed = blob
    elif isinstance(blob, dict) and isinstance(blob.get("blob"), dict):
        sealed = blob["blob"]
    else:
        raise ValueError("bad_mac_or_key")
    key = _ensure_wrap_key()
    return vcrypto.open_sealed(key, sealed, aad)


def aad_passkey(name: str, rp_id: str) -> bytes:
    return b"wick-passkey-wrap|" + (name or "").encode("utf-8") + b"|" + (rp_id or "").encode("utf-8")


def wrap_private_key(private_key: str, *, name: str, rp_id: str) -> dict[str, Any]:
    """Wrap a base64url PKCS#8 string for vault storage."""
    raw = (private_key or "").encode("utf-8")
    return wrap(raw, aad=aad_passkey(name, rp_id))


def unwrap_private_key(blob: Any, *, name: str, rp_id: str) -> str:
    return unwrap(blob, aad=aad_passkey(name, rp_id)).decode("utf-8")


def status() -> dict[str, Any]:
    info = probe()
    return {
        "hsm": False,
        "tpm": bool(info["tpm"]["available"]),
        "pkcs11": False,
        "seal": "filewrap",
        "hardware_seal": False,
        "require_hsm": require_hsm(),
        "probe": info,
        "audited": False,
    }
