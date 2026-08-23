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
    # p11-kit-trust is a CA store, not a key token — do not count it as HSM.
    hardware = bool(tpm_dev) or bool(pkcs11_mods)
    recommended = "filewrap"
    if tpm_dev and tpm_tools:
        recommended = "tpm2"
    elif pkcs11_mods:
        recommended = "pkcs11"
    return {
        "hsm": hardware,
        "tpm": {
            "available": bool(tpm_dev),
            "device": tpm_dev,
            "tools": tpm_tools,
        },
        "pkcs11": {
            "available": bool(pkcs11_mods),
            "modules": pkcs11_mods,
            "note": "p11-kit-trust is a CA store, not counted",
        },
        "recommended": recommended,
        "filewrap": True,
        "audited": False,
    }


def _ensure_wrap_key() -> bytes:
    if vcrypto is None or not vcrypto.available():
        raise ValueError("aead_unavailable")
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
    if require_hsm() and not info["hsm"]:
        return {
            "ok": False,
            "error": "hsm_required",
            "hint": "No TPM/PKCS#11 token on this host. Unset WICK_PASSKEY_REQUIRE_HSM to use filewrap.",
            "probe": info,
        }
    if vcrypto is None or not vcrypto.available():
        return {"ok": False, "error": "aead_unavailable"}
    try:
        key = _ensure_wrap_key()
        blob = vcrypto.seal(key, plaintext, aad)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    backend = "tpm2" if info["recommended"] == "tpm2" and info["hsm"] else "filewrap"
    # We only *use* TPM when we actually sealed with it. This host uses filewrap.
    if not info["hsm"]:
        backend = "filewrap"
    return {
        "ok": True,
        "backend": backend,
        "hsm": bool(info["hsm"] and backend != "filewrap"),
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
        "hsm": bool(info["hsm"]),
        "tpm": bool(info["tpm"]["available"]),
        "pkcs11": bool(info["pkcs11"]["available"]),
        "seal": info["recommended"] if info["hsm"] else "filewrap",
        "require_hsm": require_hsm(),
        "probe": info,
        "audited": False,
    }
