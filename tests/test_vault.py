#!/usr/bin/env python3
"""Tests for Wick vault (local open-source password store + refs)."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WICK = ROOT / "bin" / "wick"
_LIB = ROOT / "lib"


def _load_lib(name: str):
    path = _LIB / f"{name}.py"
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_vault_local_roundtrip(tmp_path, monkeypatch=None):
    vault = _load_lib("vault")
    home = tmp_path / "wickhome"
    home.mkdir()
    os.environ["WICK_HOME"] = str(home)
    # clear env key so file key is used
    os.environ.pop("WICK_VAULT_KEY", None)
    os.environ.pop("WICK_VAULT_MASTER", None)

    init = vault.ensure_local_key()
    assert init["ok"] is True
    assert (home / "vault" / "master.key").is_file()

    set_out = vault.set_entry(
        "demo",
        password="s3cret-value-xyz",
        username="agent",
        url="https://example.com/login",
    )
    assert set_out["ok"] is True
    assert set_out["revealed"] is False
    assert "s3cret" not in json.dumps(set_out)

    listed = vault.list_entries()
    assert listed["ok"] is True
    assert listed["count"] == 1
    assert listed["entries"][0]["name"] == "demo"
    blob = json.dumps(listed)
    assert "s3cret-value-xyz" not in blob

    matched = vault.match_url("https://example.com/login")
    assert matched["ok"] is True
    assert matched["count"] == 1
    assert matched["matches"][0]["password_ref"] == "vault://demo/password"
    assert "s3cret" not in json.dumps(matched)

    r = vault.resolve("vault://demo/password", reason="test")
    assert r["ok"] is True
    assert r["value"] == "s3cret-value-xyz"

    # agentmail alias
    vault.set_entry("agentmail", fields={"token": "tok_test_abc"})
    am = vault.resolve("agentmail://token", reason="test")
    assert am["ok"] is True
    assert am["value"] == "tok_test_abc"

    # env backend
    os.environ["WICK_TEST_SECRET"] = "from-env"
    er = vault.resolve("env://WICK_TEST_SECRET", reason="test")
    assert er["ok"] is True
    assert er["value"] == "from-env"

    val, meta = vault.resolve_for_fill("vault://demo/password", reason="fill")
    assert val == "s3cret-value-xyz"
    assert meta["resolved"] is True
    assert meta["ref"] == "vault://demo/password"

    plain, meta2 = vault.resolve_for_fill("not-a-ref", reason="fill")
    assert plain == "not-a-ref"
    assert meta2["resolved"] is False

    st = vault.status()
    assert st["ok"] is True
    assert st["local"]["entries"] == 2
    assert "brave_combine" in st


def test_vault_cli_list_no_leak(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    env = os.environ.copy()
    env["WICK_HOME"] = str(home)
    env.pop("WICK_VAULT_KEY", None)
    env.pop("WICK_PROFILE", None)
    env["WICK_VAULT_SET_PASSWORD"] = "cli-secret-should-not-list"

    subprocess.run([sys.executable, str(WICK), "vault", "init"], check=True, env=env, cwd=str(ROOT), capture_output=True)
    proc = subprocess.run(
        [sys.executable, str(WICK), "vault", "set", "cli-demo", "--username", "u", "--url", "https://example.com/"],
        env=env,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    out = json.loads(proc.stdout)
    assert out["ok"] is True
    assert "cli-secret" not in proc.stdout

    proc2 = subprocess.run(
        [sys.executable, str(WICK), "vault", "list"],
        env=env,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert proc2.returncode == 0
    assert "cli-secret" not in proc2.stdout
    data = json.loads(proc2.stdout)
    assert data["count"] >= 1


def test_tools_include_vault():
    tools_schema = _load_lib("tools_schema")
    out = tools_schema.tools_export("0.9.0")
    names = {t["function"]["name"] for t in out["tools"]}
    assert "wick_vault" in names
    assert "wick_act" in names
    # single wick_act
    assert sum(1 for n in names if n == "wick_act") == 1
    vault_tool = next(t for t in out["tools"] if t["function"]["name"] == "wick_vault")
    actions = vault_tool["function"]["parameters"]["properties"]["action"]["enum"]
    assert "suggest" in actions
    assert "autofill" in actions


def test_match_url_rejects_phishing_substring(tmp_path):
    vault = _load_lib("vault")
    os.environ["WICK_HOME"] = str(tmp_path / "wickhome")
    os.environ.pop("WICK_VAULT_KEY", None)
    os.environ.pop("WICK_VAULT_MASTER", None)
    vault.ensure_local_key()
    vault.set_entry(
        "bank",
        password="real-secret",
        username="me",
        url="https://example.com/login",
    )
    phish = vault.match_url("https://evil.test/phish?next=https://example.com/login")
    assert phish["ok"] is True
    assert phish["count"] == 0
    assert "real-secret" not in json.dumps(phish)

    good = vault.match_url("https://example.com/account")
    assert good["count"] == 1
    assert good["matches"][0]["name"] == "bank"
    assert good["matches"][0]["score"] >= 80


def test_https_saved_does_not_match_http_page(tmp_path):
    vault = _load_lib("vault")
    os.environ["WICK_HOME"] = str(tmp_path / "h")
    os.environ.pop("WICK_VAULT_KEY", None)
    os.environ.pop("WICK_VAULT_MASTER", None)
    vault.ensure_local_key()
    vault.set_entry("site", password="pw", url="https://example.com/")
    http_page = vault.match_url("http://example.com/")
    assert http_page["count"] == 0


def test_resolve_for_fill_origin_bound(tmp_path):
    vault = _load_lib("vault")
    os.environ["WICK_HOME"] = str(tmp_path / "h")
    os.environ.pop("WICK_VAULT_KEY", None)
    os.environ.pop("WICK_VAULT_MASTER", None)
    vault.ensure_local_key()
    vault.set_entry("demo", password="s3cret-value-xyz", url="https://example.com/login")
    val, meta = vault.resolve_for_fill(
        "vault://demo/password",
        reason="fill",
        page_url="https://example.com/login",
    )
    assert val == "s3cret-value-xyz"
    assert meta["origin_ok"] is True

    try:
        vault.resolve_for_fill(
            "vault://demo/password",
            reason="fill",
            page_url="https://evil.test/",
        )
        raise AssertionError("expected origin mismatch")
    except ValueError as e:
        assert "origin" in str(e)


def test_suggest_login_never_leaks_secret(tmp_path):
    vault = _load_lib("vault")
    elements = _load_lib("elements")
    os.environ["WICK_HOME"] = str(tmp_path / "h")
    os.environ.pop("WICK_VAULT_KEY", None)
    os.environ.pop("WICK_VAULT_MASTER", None)
    vault.ensure_local_key()
    vault.set_entry(
        "demo",
        password="s3cret-value-xyz",
        username="agent",
        url="https://example.com/login",
    )
    tree = "1 document\n  2 textbox 'Email'\n  3 textbox 'Password'\n  4 [i] button 'Log in'\n"
    els = elements.parse_tree_text(tree)
    out = vault.suggest_login("https://example.com/login", elements=els)
    blob = json.dumps(out)
    assert out["ok"] is True
    assert out["count"] >= 1
    assert "s3cret-value-xyz" not in blob
    rec = out["recipe"]
    assert rec["username_ref"] == "vault://demo/username"
    assert rec["password_ref"] == "vault://demo/password"
    assert rec["cmds"]
    assert any("login" in c or "fill" in c for c in rec["cmds"])


def test_totp_rfc6238_sha1():
    vault = _load_lib("vault")
    # RFC 6238 appendix B: secret ASCII "12345678901234567890"
    secret_b32 = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    code = vault.totp_at(secret_b32, when=59, digits=8, period=30)
    assert code == "94287082"
    six = vault.totp_at(secret_b32, when=59, digits=6, period=30)
    assert six == "287082"


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as td:
        test_vault_local_roundtrip(Path(td))
        test_vault_cli_list_no_leak(Path(td) / "cli")
        test_tools_include_vault()
    print("ok")
