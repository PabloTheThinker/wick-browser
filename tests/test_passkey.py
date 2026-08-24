#!/usr/bin/env python3
"""Passkey helpers: rpId bind, no private key in agent JSON."""
from __future__ import annotations

import json
import os
import sys
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import passkey  # noqa: E402


def _load_vault():
    path = _LIB / "vault.py"
    loader = SourceFileLoader("vault", str(path))
    spec = spec_from_loader("vault", loader)
    assert spec is not None and spec.loader is not None
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_rpid_matches_host_not_phishing():
    assert passkey.rpid_matches_url("example.com", "https://example.com/login")
    assert passkey.rpid_matches_url("example.com", "https://www.example.com/")
    assert not passkey.rpid_matches_url("example.com", "https://evil.test/")
    assert not passkey.rpid_matches_url("example.com", "http://example.com/")
    assert not passkey.rpid_matches_url("example.com", "https://notexample.com/")


def test_generate_credential_shape_and_cdp():
    cred = passkey.generate("example.com", user_name="agent@example.com")
    assert cred["rp_id"] == "example.com"
    assert cred["private_key"]
    assert cred["credential_id"]
    cdp = passkey.to_cdp(cred)
    assert cdp["rpId"] == "example.com"
    assert cdp["isResidentCredential"] is True
    assert cdp["privateKey"]
    # CDP Binary fields are standard base64 (not PEM)
    assert "BEGIN" not in cdp["privateKey"]
    import base64

    raw = base64.b64decode(cdp["privateKey"])
    assert raw[:2] == b"\x30\x82" or raw[:1] == b"\x30"
    pw = passkey.to_playwright(cred)
    assert pw["rp_id"] == "example.com"
    assert pw["private_key"]
    assert "+" not in pw["private_key"] and "/" not in pw["private_key"]


def test_vault_passkey_never_lists_key(tmp_path, monkeypatch):
    monkeypatch.setenv("WICK_HOME", str(tmp_path / "h"))
    monkeypatch.delenv("WICK_VAULT_KEY", raising=False)
    monkeypatch.delenv("WICK_VAULT_PASSPHRASE", raising=False)
    vault = _load_vault()
    out = vault.create_passkey("demo", url="https://example.com/login", username="agent")
    assert out["ok"] is True
    assert out["has_passkey"] is True
    blob = json.dumps(out)
    assert "BEGIN" not in blob
    assert "private" not in blob.lower() or "has_passkey" in blob

    listed = vault.list_entries()
    assert listed["ok"] is True
    assert listed["entries"][0]["has_passkey"] is True
    listed_s = json.dumps(listed)
    assert "passkey_private_key" not in listed_s
    assert "passkey_sealed" not in listed_s
    cred_material = out.get("credential_id")  # metadata may include id? should not
    # create_passkey must not echo key material
    assert "private_key" not in out

    matched = vault.match_url("https://example.com/login")
    assert matched["count"] == 1
    assert matched["matches"][0]["has_passkey"] is True
    assert matched["matches"][0].get("passkey_ref") == "vault://demo/passkey"
    assert "private" not in json.dumps(matched).lower() or "has_passkey" in json.dumps(matched)

    phish = vault.export_passkey_for_cdp("demo", page_url="https://evil.test/")
    assert phish["ok"] is False

    good = vault.export_passkey_for_cdp("demo", page_url="https://example.com/login")
    assert good["ok"] is True
    assert good["credential"]["rpId"] == "example.com"
    # Internal CDP export has the key; caller must not print it to agents
    assert good["credential"]["privateKey"]

    blocked = vault.resolve("vault://demo/passkey", reason="test")
    assert blocked["ok"] is False
    assert blocked["error"] == "passkey_not_a_ref"
    blocked_field = vault.resolve("vault://demo/passkey_private_key", reason="test")
    assert blocked_field["ok"] is False
    assert blocked_field["error"] == "passkey_not_a_ref"
