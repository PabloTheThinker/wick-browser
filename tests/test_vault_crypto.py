#!/usr/bin/env python3
"""Tests for wickvault2: AES-256-GCM store, key hierarchy, migration, broker."""
from __future__ import annotations

import importlib.util
import json
import os
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_LIB = ROOT / "lib"
PASSWORD = "s3cret-value-xyz"


def _load_lib(name: str):
    path = _LIB / f"{name}.py"
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _clean_env(monkeypatch, home: Path) -> None:
    monkeypatch.setenv("WICK_HOME", str(home))
    for var in (
        "WICK_VAULT_KEY",
        "WICK_VAULT_MASTER",
        "WICK_VAULT_PASSPHRASE",
        "WICK_VAULT_RELOCK_AFTER_FILL",
        "WICK_VAULT_LOCK_TTL",
        "WICK_PROFILE",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    """Fresh vault module bound to an isolated WICK_HOME, file-key mode."""
    home = tmp_path / "wickhome"
    home.mkdir()
    _clean_env(monkeypatch, home)
    mod = _load_lib("vault")
    assert mod.vcrypto is not None, "lib/vault_crypto.py must be importable"
    assert mod.vcrypto.available(), "install the cryptography package (AES-GCM)"
    return mod


def _store_text(vault) -> str:
    return (Path(os.environ["WICK_HOME"]) / "vault" / "store.enc").read_text(encoding="utf-8")


def test_new_store_is_wickvault2_without_plaintext(vault):
    vault.ensure_local_key()
    out = vault.set_entry("demo", password=PASSWORD, username="agent", url="https://example.com/login")
    assert out["ok"] is True

    raw = _store_text(vault)
    doc = json.loads(raw)
    assert '"format": "wickvault2"' in json.dumps(doc, indent=1)
    assert doc["format"] == "wickvault2"
    assert doc["aead"] == "aes-256-gcm"
    assert doc["kdf"] == "filekey"
    assert set(doc["wrapped_vault_key"]) == {"nonce", "ct"}

    item = doc["items"]["demo"]
    assert set(item) >= {"wrapped_item_key", "blob", "updated"}
    # Nothing sensitive survives in cleartext: not the password, not the URL.
    assert PASSWORD not in raw
    assert "example.com" not in raw
    assert "agent" not in raw
    assert vault.crypto_info()["hierarchy"] == "wrap→vault→item"
    assert vault.store_format() == "wickvault2"


def test_roundtrip_with_file_key(vault):
    vault.ensure_local_key()
    vault.set_entry("demo", password=PASSWORD, username="agent", url="https://example.com/login")

    r = vault.resolve("vault://demo/password", reason="test")
    assert r["ok"] is True
    assert r["value"] == PASSWORD
    assert vault.resolve("vault://demo/username", reason="test")["value"] == "agent"

    # Second write must keep the first item readable (vault key is reused).
    vault.set_entry("other", password="second-pw", url="https://example.com/")
    assert vault.resolve("vault://demo/password", reason="test")["value"] == PASSWORD
    assert vault.resolve("vault://other/password", reason="test")["value"] == "second-pw"

    assert vault.delete_entry("other")["ok"] is True
    assert vault.list_entries()["count"] == 1


def test_wickvault1_store_migrates_on_write(vault):
    vault.ensure_local_key()
    store = Path(os.environ["WICK_HOME"]) / "vault" / "store.enc"
    master = (Path(os.environ["WICK_HOME"]) / "vault" / "master.key").read_bytes().strip()

    legacy_entries = {
        "old": {
            "password": PASSWORD,
            "url": "https://example.com/login",
            "updated": "2026-01-01T00:00:00Z",
        }
    }
    store.write_text(vault._seal(master, json.dumps(legacy_entries).encode("utf-8")) + "\n", encoding="utf-8")
    assert vault.store_format() == "wickvault1"
    assert vault.crypto_info()["migrate_on_write"] is True
    assert vault.list_entries()["count"] == 1

    assert vault.set_entry("old", username="agent")["ok"] is True
    assert vault.store_format() == "wickvault2"
    assert vault.crypto_info()["migrate_on_write"] is False

    r = vault.resolve("vault://old/password", reason="test")
    assert r["ok"] is True and r["value"] == PASSWORD
    assert vault.resolve("vault://old/username", reason="test")["value"] == "agent"
    assert PASSWORD not in _store_text(vault)


def test_tampered_blob_fails_closed(vault):
    vault.ensure_local_key()
    vault.set_entry("demo", password=PASSWORD, url="https://example.com/login")
    store = Path(os.environ["WICK_HOME"]) / "vault" / "store.enc"

    doc = json.loads(store.read_text(encoding="utf-8"))
    ct = doc["items"]["demo"]["blob"]["ct"]
    doc["items"]["demo"]["blob"]["ct"] = ("B" if ct[0] != "B" else "C") + ct[1:]
    store.write_text(json.dumps(doc), encoding="utf-8")

    r = vault.resolve("vault://demo/password", reason="test")
    assert r["ok"] is False
    assert r["error"] == "bad_mac_or_key"
    assert PASSWORD not in json.dumps(r)

    listed = vault.list_entries()
    assert listed["ok"] is False
    assert listed["error"] == "bad_mac_or_key"


def test_repeated_unwrap_failures_trigger_cooldown(vault):
    vault.ensure_local_key()
    vault.set_entry("demo", password=PASSWORD, url="https://example.com/")
    store = Path(os.environ["WICK_HOME"]) / "vault" / "store.enc"

    doc = json.loads(store.read_text(encoding="utf-8"))
    ct = doc["wrapped_vault_key"]["ct"]
    doc["wrapped_vault_key"]["ct"] = ("B" if ct[0] != "B" else "C") + ct[1:]
    store.write_text(json.dumps(doc), encoding="utf-8")

    errors = [vault.list_entries()["error"] for _ in range(9)]
    assert errors[:8] == ["bad_mac_or_key"] * 8
    assert errors[8] == "vault_locked_cooldown"
    meta = vault._read_meta()
    assert meta["unwrap_failures"] == 8
    assert PASSWORD not in json.dumps(meta)


def test_grant_scopes_fill_to_one_origin(vault):
    vault.ensure_local_key()
    vault.set_entry("demo", password=PASSWORD, url="https://example.com/login")

    granted = vault.grant("https://example.com/login", ttl=120)
    assert granted["ok"] is True
    assert granted["granted"] == "https://example.com"

    val, meta = vault.resolve_for_fill(
        "vault://demo/password", reason="fill", page_url="https://example.com/login"
    )
    assert val == PASSWORD
    assert meta["granted"] is True
    assert meta["origin_ok"] is True

    with pytest.raises(ValueError) as denied:
        vault.resolve_for_fill("vault://demo/password", reason="fill", page_url="https://evil.test/")
    assert "grant_required" in str(denied.value)

    # Metadata stays available while a grant is active.
    assert vault.match_url("https://example.com/login")["count"] == 1

    # lock() drops the grant; file-key mode is auto-unlocked again afterwards.
    locked = vault.lock()
    assert locked["ok"] is True and locked["grants_cleared"] == 1
    assert vault.session_status()["grant_count"] == 0
    assert vault.resolve("vault://demo/password", reason="test")["value"] == PASSWORD

    assert vault.grant("", ttl=60)["error"] == "missing_url"
    assert vault.grant("https://example.com/", ttl=0)["error"] == "bad_ttl"


def test_passphrase_mode_wrong_passphrase_cannot_open(tmp_path, monkeypatch):
    home = tmp_path / "pp"
    home.mkdir()
    _clean_env(monkeypatch, home)
    monkeypatch.setenv("WICK_VAULT_PASSPHRASE", "correct horse battery staple")
    vault = _load_lib("vault")

    init = vault.ensure_local_key()
    assert init["ok"] is True
    assert init["kdf"] in ("argon2id", "scrypt")
    assert init["key_path"] is None
    assert not (home / "vault" / "master.key").exists()

    assert vault.set_entry("demo", password=PASSWORD, url="https://example.com/")["ok"] is True
    assert vault.resolve("vault://demo/password", reason="test")["value"] == PASSWORD

    raw = _store_text(vault)
    assert "correct horse" not in raw
    assert PASSWORD not in raw

    listed = vault.list_entries()
    assert listed["ok"] is True
    blob = json.dumps(listed)
    assert PASSWORD not in blob
    assert "correct horse" not in blob

    monkeypatch.setenv("WICK_VAULT_PASSPHRASE", "wrong passphrase")
    bad = vault.list_entries()
    assert bad["ok"] is False
    assert bad["error"] == "bad_mac_or_key"
    assert vault.resolve("vault://demo/password", reason="test")["ok"] is False

    # No passphrase and no session: passphrase mode is locked.
    monkeypatch.delenv("WICK_VAULT_PASSPHRASE", raising=False)
    assert vault.list_entries()["error"] == "vault_locked"

    # unlock with the right passphrase keeps the vault usable for the TTL.
    monkeypatch.setenv("WICK_VAULT_PASSPHRASE", "correct horse battery staple")
    unlocked = vault.unlock(120)
    assert unlocked["ok"] is True and unlocked["mode"] == "passphrase"
    monkeypatch.delenv("WICK_VAULT_PASSPHRASE", raising=False)
    assert vault.resolve("vault://demo/password", reason="test")["value"] == PASSWORD
    assert vault.lock()["ok"] is True
    assert vault.list_entries()["error"] == "vault_locked"


def test_metadata_paths_never_leak_password(vault):
    elements = _load_lib("elements")
    vault.ensure_local_key()
    vault.set_entry(
        "demo",
        password=PASSWORD,
        username="agent",
        url="https://example.com/login",
        fields={"totp": "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"},
    )
    tree = "1 document\n  2 textbox 'Email'\n  3 textbox 'Password'\n  4 [i] button 'Log in'\n"
    els = elements.parse_tree_text(tree)

    payloads = [
        vault.list_entries(),
        vault.match_url("https://example.com/login"),
        vault.suggest_login("https://example.com/login", elements=els),
        vault.status(),
        vault.doctor(),
        vault.get_meta("demo"),
        vault.session_status(),
    ]
    for payload in payloads:
        blob = json.dumps(payload)
        assert PASSWORD not in blob
        assert "GEZDGNBVGY3TQOJQ" not in blob


def test_doctor_reports_aead_and_format(vault):
    vault.ensure_local_key()
    out = vault.doctor()
    assert out["format"] == "wickvault2"
    assert out["aead"] == "aes-256-gcm"
    assert out["kdf"] == "filekey"
    assert out["hierarchy"] == "wrap→vault→item"
    checks = {c["name"]: c for c in out["checks"]}
    assert checks["aead_aes_256_gcm"]["ok"] is True
    assert checks["store_format_wickvault2"]["ok"] is True
    local = vault.status()["local"]
    assert local["format"] == "wickvault2"
    assert local["aead"] == "aes-256-gcm"
    assert local["kdf"] == "filekey"


def test_relock_after_fill_clears_grants(vault, monkeypatch):
    vault.ensure_local_key()
    vault.set_entry("demo", password=PASSWORD, url="https://example.com/login")
    assert vault.grant("https://example.com/", ttl=120)["ok"] is True
    monkeypatch.setenv("WICK_VAULT_RELOCK_AFTER_FILL", "1")

    val, meta = vault.resolve_for_fill(
        "vault://demo/password", reason="fill", page_url="https://example.com/login"
    )
    assert val == PASSWORD
    assert meta["relocked"] is True
    assert vault.session_status()["active"] is False
    assert vault.session_status()["grant_count"] == 0


def test_broker_verbs_need_full_act(monkeypatch):
    capability = _load_lib("capability")
    monkeypatch.setenv("WICK_PROFILE", "observe-only")
    for action in ("lock", "unlock", "grant", "passkey-new"):
        denied = capability.deny("vault", vault_action=action)
        assert denied is not None
        assert denied["error"] == "capability_denied"
    for action in ("status", "list", "match", "suggest"):
        assert capability.deny("vault", vault_action=action) is None

    monkeypatch.setenv("WICK_PROFILE", "full-act")
    for action in ("lock", "unlock", "grant", "passkey-new"):
        assert capability.deny("vault", vault_action=action) is None


def test_tools_schema_exposes_broker_actions():
    tools_schema = _load_lib("tools_schema")
    tool = next(
        t for t in tools_schema.tools_export("0.9.0")["tools"] if t["function"]["name"] == "wick_vault"
    )
    actions = tool["function"]["parameters"]["properties"]["action"]["enum"]
    for action in ("lock", "unlock", "grant", "passkey-new"):
        assert action in actions
    assert "ttl" in tool["function"]["parameters"]["properties"]
