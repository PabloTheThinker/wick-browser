"""Password-manager passkeys for agents (not Touch ID / hardware keys).

Wick stores a discoverable WebAuthn credential (rpId + P-256 key) in the
vault and injects it into Chromium via the CDP virtual authenticator — the
same model Bitwarden / Proton Pass / 1Password use when the manager *is*
the authenticator.

Honest limits:
- Platform biometrics (Touch ID, Windows Hello) cannot be pressed by an agent.
- Hardware security keys cannot be tapped by an agent.
- This is origin-bound resident-key assertion, UV=true, presence simulated.
"""
from __future__ import annotations

import base64
import secrets
from typing import Any
from urllib.parse import urlsplit

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    HAVE_EC = True
except Exception:  # pragma: no cover
    serialization = None  # type: ignore[assignment]
    ec = None  # type: ignore[assignment]
    HAVE_EC = False

try:
    import origins as wick_origins
except Exception:
    wick_origins = None  # type: ignore


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    s = (text or "").strip()
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _b64url(text: str) -> str:
    """Normalize any base64 flavor to unpadded base64url (Playwright credentials)."""
    if not text:
        return ""
    return _b64e(_b64d(text))


def _b64std(text: str) -> str:
    """Normalize any base64 flavor to padded standard base64 (CDP Binary fields)."""
    if not text:
        return ""
    return base64.b64encode(_b64d(text)).decode("ascii")


def rp_id_from_url(url: str | None) -> str | None:
    s = (url or "").strip()
    if not s:
        return None
    if "://" not in s:
        s = "https://" + s.lstrip("/")
    host = (urlsplit(s).hostname or "").lower().rstrip(".")
    if host.startswith("www.") and host.count(".") >= 2:
        host = host[4:]
    return host or None


def rpid_matches_url(rp_id: str, url: str | None) -> bool:
    """Passkey rpId must match the page host (www alias). HTTPS-saved never on HTTP."""
    rid = (rp_id or "").strip().lower().rstrip(".")
    if not rid or not url:
        return False
    if wick_origins is not None:
        parsed = wick_origins.parse_origin(url)
        if not parsed:
            return False
        if parsed["scheme"] != "https" and rid not in {"localhost", "127.0.0.1"}:
            return False
        host = parsed["host"]
        if host == rid or host == "www." + rid or (host.startswith("www.") and host[4:] == rid):
            return True
        return False
    page_rid = rp_id_from_url(url)
    return page_rid == rid


def generate(rp_id: str, *, user_name: str = "agent", user_handle: bytes | None = None) -> dict[str, str]:
    """Create a discoverable P-256 credential. Caller stores it in the vault."""
    if not HAVE_EC:
        raise ValueError("aead_unavailable")
    rid = (rp_id or "").strip().lower().rstrip(".")
    if not rid:
        raise ValueError("missing_rpid")
    key = ec.generate_private_key(ec.SECP256R1())
    pkcs8 = key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    cred_id = secrets.token_bytes(32)
    handle = user_handle if user_handle is not None else secrets.token_bytes(32)
    return {
        "rp_id": rid,
        "credential_id": _b64e(cred_id),
        "user_handle": _b64e(handle),
        "user_name": (user_name or "agent")[:120],
        "private_key": _b64e(pkcs8),
        "public_key": _b64e(pub),
        "sign_count": "1",
    }


def to_cdp(cred: dict[str, Any]) -> dict[str, Any]:
    """Shape for WebAuthn.addCredential. Contains the private key — Chromium only.

    CDP Binary fields (credentialId, privateKey, userHandle) must be standard
    base64. publicKey is for Playwright's credentials.create import path and
    must be stripped before the CDP send.
    """
    return {
        "credentialId": _b64std(str(cred.get("credential_id") or "")),
        "isResidentCredential": True,
        "rpId": str(cred.get("rp_id") or ""),
        "privateKey": _b64std(str(cred.get("private_key") or "")),
        "userHandle": _b64std(str(cred.get("user_handle") or "")),
        "signCount": int(cred.get("sign_count") or 1),
        "publicKey": _b64std(str(cred.get("public_key") or "")),
    }


def to_playwright(cred: dict[str, Any]) -> dict[str, str]:
    """Import shape for Playwright context.credentials.create (base64url)."""
    return {
        "rp_id": str(cred.get("rp_id") or ""),
        "id": _b64url(str(cred.get("credential_id") or "")),
        "user_handle": _b64url(str(cred.get("user_handle") or "")),
        "private_key": _b64url(str(cred.get("private_key") or "")),
        "public_key": _b64url(str(cred.get("public_key") or "")),
    }


def from_cdp(raw: dict[str, Any], *, rp_id: str | None = None) -> dict[str, str]:
    """Normalize a CDP getCredentials item into vault fields."""
    rid = rp_id or str(raw.get("rpId") or "")
    return {
        "rp_id": rid,
        "credential_id": _b64url(str(raw.get("credentialId") or raw.get("id") or "")),
        "user_handle": _b64url(str(raw.get("userHandle") or "")),
        "private_key": _b64url(str(raw.get("privateKey") or raw.get("private_key") or "")),
        "public_key": _b64url(str(raw.get("publicKey") or raw.get("public_key") or "")),
        "sign_count": str(int(raw.get("signCount") or raw.get("sign_count") or 1)),
        "user_name": str(raw.get("userName") or raw.get("user_name") or "agent")[:120],
    }


def vault_fields(cred: dict[str, Any]) -> dict[str, str]:
    return {
        "passkey_rpid": str(cred.get("rp_id") or ""),
        "passkey_id": str(cred.get("credential_id") or ""),
        "passkey_user_handle": str(cred.get("user_handle") or ""),
        "passkey_private_key": str(cred.get("private_key") or ""),
        "passkey_public_key": str(cred.get("public_key") or ""),
        "passkey_sign_count": str(cred.get("sign_count") or "1"),
        "passkey_user": str(cred.get("user_name") or "agent")[:120],
    }


def from_entry(ent: dict[str, Any] | None, *, name: str = "") -> dict[str, str] | None:
    if not isinstance(ent, dict):
        return None
    rp_id = str(ent.get("passkey_rpid") or "")
    raw_priv = str(ent.get("passkey_private_key") or "")
    sealed = ent.get("passkey_sealed")
    if sealed and not raw_priv:
        try:
            import json

            import hsm as wick_hsm

            blob = json.loads(sealed) if isinstance(sealed, str) else sealed
            raw_priv = wick_hsm.unwrap_private_key(
                blob, name=name or str(ent.get("name") or ""), rp_id=rp_id
            )
        except Exception:
            return None
    if not raw_priv or not rp_id:
        return None
    return {
        "rp_id": rp_id,
        "credential_id": str(ent.get("passkey_id") or ""),
        "user_handle": str(ent.get("passkey_user_handle") or ""),
        "private_key": raw_priv,
        "public_key": str(ent.get("passkey_public_key") or ""),
        "sign_count": str(ent.get("passkey_sign_count") or "1"),
        "user_name": str(ent.get("passkey_user") or ent.get("username") or "agent"),
    }


PASSKEY_FIELD_NAMES = frozenset(set(vault_fields({}).keys()) | {"passkey_sealed", "passkey_seal"})
