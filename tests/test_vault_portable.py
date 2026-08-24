#!/usr/bin/env python3
"""Encrypted backup, hash-chained audit, and WICK_VAULT_STRICT."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))


def _load_vault():
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader

    path = _LIB / "vault.py"
    loader = SourceFileLoader("vault_portable_test", str(path))
    spec = spec_from_loader("vault_portable_test", loader)
    assert spec is not None and spec.loader is not None
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class VaultPortable(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="wick-port-")
        os.environ["WICK_HOME"] = self._tmp.name
        os.environ.pop("WICK_VAULT_KEY", None)
        os.environ.pop("WICK_VAULT_PASSPHRASE", None)
        os.environ.pop("WICK_VAULT_STRICT", None)
        os.environ.pop("WICK_VAULT_REQUIRE_GRANT", None)
        os.environ.pop("WICK_VAULT_RELOCK_AFTER_FILL", None)
        os.environ.pop("WICK_VAULT_BACKUP_PASSPHRASE", None)
        self.vault = _load_vault()

    def tearDown(self):
        for k in (
            "WICK_HOME",
            "WICK_VAULT_STRICT",
            "WICK_VAULT_REQUIRE_GRANT",
            "WICK_VAULT_RELOCK_AFTER_FILL",
            "WICK_VAULT_BACKUP_PASSPHRASE",
            "WICK_VAULT_PASSPHRASE",
        ):
            os.environ.pop(k, None)
        self._tmp.cleanup()

    def test_strict_requires_grant_and_relock(self):
        os.environ["WICK_VAULT_STRICT"] = "1"
        self.assertTrue(self.vault.vault_strict())
        self.assertTrue(self.vault._require_grant())
        self.assertTrue(self.vault._relock_after_fill())

    def test_audit_is_hash_chained_and_secret_free(self):
        self.vault.ensure_local_key()
        self.vault.set_entry("demo", password="s3cret-value-xyz", url="https://example.com/")
        log = self.vault.read_audit(limit=20)
        self.assertTrue(log["ok"])
        self.assertTrue(log["chain_ok"])
        blob = json.dumps(log)
        self.assertNotIn("s3cret-value-xyz", blob)
        self.assertGreaterEqual(log["count"], 1)
        self.assertTrue(all(e.get("hash") for e in log["entries"]))

    def test_backup_restore_roundtrip_without_plaintext_in_file(self):
        self.vault.ensure_local_key()
        self.vault.set_entry(
            "demo",
            password="s3cret-value-xyz",
            username="agent",
            url="https://example.com/login",
        )
        dest = Path(self._tmp.name) / "backup.wick"
        os.environ["WICK_VAULT_BACKUP_PASSPHRASE"] = "backup-phrase-for-tests"
        out = self.vault.backup(str(dest))
        self.assertTrue(out["ok"], out)
        self.assertFalse(out["sync"])
        raw = dest.read_text(encoding="utf-8")
        self.assertNotIn("s3cret-value-xyz", raw)
        self.assertEqual(oct(dest.stat().st_mode & 0o777), "0o600")

        other = Path(self._tmp.name) / "other"
        os.environ["WICK_HOME"] = str(other)
        restored = self.vault.restore(str(dest), passphrase="backup-phrase-for-tests")
        self.assertTrue(restored["ok"], restored)
        listed = self.vault.list_entries()
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["entries"][0]["name"], "demo")
        self.assertNotIn("s3cret-value-xyz", json.dumps(listed))

    def test_backup_refuses_without_passphrase(self):
        self.vault.ensure_local_key()
        dest = Path(self._tmp.name) / "nope.wick"
        out = self.vault.backup(str(dest))
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "missing_backup_passphrase")
        self.assertFalse(dest.exists())

    def test_passkey_wrap_is_vault_sealed_not_raw_32(self):
        self.vault.ensure_local_key()
        out = self.vault.create_passkey("pk", url="https://example.com/login")
        self.assertTrue(out["ok"], out)
        raw = Path(self._tmp.name) / "vault" / "passkey.wrap"
        enc = Path(self._tmp.name) / "vault" / "passkey.wrap.enc"
        self.assertTrue(enc.is_file())
        self.assertEqual(oct(enc.stat().st_mode & 0o777), "0o600")
        self.assertFalse(raw.is_file())

    def test_harden_deletes_master_key_keeps_secret(self):
        self.vault.ensure_local_key()
        self.vault.set_entry("demo", password="s3cret-value-xyz", url="https://example.com/login")
        key = Path(self._tmp.name) / "vault" / "master.key"
        self.assertTrue(key.is_file())
        self.assertTrue(self.vault.session_status()["standing_key"])
        os.environ["WICK_VAULT_PASSPHRASE"] = "agent-harden-pass-32"
        out = self.vault.harden()
        self.assertTrue(out["ok"], out)
        self.assertFalse(out["standing_key"])
        self.assertFalse(key.is_file())
        self.assertNotIn("agent-harden-pass-32", json.dumps(out))
        listed = self.vault.list_entries()
        self.assertEqual(listed["count"], 1)
        val, meta = self.vault.resolve_for_fill(
            "vault://demo/password",
            reason="test",
            page_url="https://example.com/login",
        )
        self.assertEqual(val, "s3cret-value-xyz")
        self.assertTrue(meta["resolved"])

    def test_harden_refuses_without_passphrase(self):
        self.vault.ensure_local_key()
        out = self.vault.harden()
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "missing_passphrase")
        self.assertTrue((Path(self._tmp.name) / "vault" / "master.key").is_file())

    def test_restore_refuses_to_clobber_existing_store(self):
        self.vault.ensure_local_key()
        self.vault.set_entry("demo", password="s3cret-value-xyz", url="https://example.com/")
        dest = Path(self._tmp.name) / "backup.wick"
        os.environ["WICK_VAULT_BACKUP_PASSPHRASE"] = "backup-phrase-for-tests"
        self.assertTrue(self.vault.backup(str(dest))["ok"])
        other = Path(self._tmp.name) / "other"
        os.environ["WICK_HOME"] = str(other)
        self.vault.ensure_local_key()
        self.vault.set_entry("keep", password="do-not-lose", url="https://example.com/")
        denied = self.vault.restore(str(dest), passphrase="backup-phrase-for-tests")
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"], "vault_exists")
        self.assertEqual(self.vault.list_entries()["entries"][0]["name"], "keep")
        forced = self.vault.restore(str(dest), passphrase="backup-phrase-for-tests", force=True)
        self.assertTrue(forced["ok"], forced)
        names = [e["name"] for e in self.vault.list_entries()["entries"]]
        self.assertEqual(names, ["demo"])

    def test_backup_carries_audit_and_doctor_verifies_chain(self):
        self.vault.ensure_local_key()
        self.vault.set_entry("demo", password="s3cret-value-xyz", url="https://example.com/")
        dest = Path(self._tmp.name) / "backup.wick"
        os.environ["WICK_VAULT_BACKUP_PASSPHRASE"] = "backup-phrase-for-tests"
        self.assertTrue(self.vault.backup(str(dest))["ok"])
        other = Path(self._tmp.name) / "other"
        os.environ["WICK_HOME"] = str(other)
        restored = self.vault.restore(str(dest), passphrase="backup-phrase-for-tests")
        self.assertTrue(restored["ok"], restored)
        log = self.vault.read_audit(limit=50)
        self.assertTrue(log["chain_ok"])
        self.assertGreaterEqual(log["total"], 1)
        doc = self.vault.doctor()
        checks = {c["name"]: c for c in doc["checks"]}
        self.assertTrue(checks["audit_chain"]["ok"])
        self.assertFalse(doc["sync"])
        self.assertFalse(doc["audited"])
        self.assertIn("harden", (checks.get("standing_key") or {}).get("hint") or "")


if __name__ == "__main__":
    unittest.main()
