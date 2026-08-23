#!/usr/bin/env python3
"""HSM/TPM probe + passkey seal. Never claim hardware that is not there."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import hsm  # noqa: E402


class HsmCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="wick-hsm-")
        os.environ["WICK_HOME"] = self._tmp.name
        os.environ.pop("WICK_PASSKEY_REQUIRE_HSM", None)
        os.environ.pop("WICK_HSM_WRAP", None)

    def tearDown(self):
        os.environ.pop("WICK_HOME", None)
        os.environ.pop("WICK_PASSKEY_REQUIRE_HSM", None)
        os.environ.pop("WICK_HSM_WRAP", None)
        self._tmp.cleanup()


class TestHsmProbe(HsmCase):
    def test_probe_is_honest_on_this_host(self):
        p = hsm.probe()
        self.assertIn("tpm", p)
        self.assertIn("pkcs11", p)
        self.assertFalse(p["hsm"])
        self.assertFalse(p["tpm"]["available"])
        self.assertIn(p["recommended"], ("filewrap", "tpm2", "pkcs11"))
        # This cloud image has no /dev/tpmrm0.
        self.assertFalse(p["tpm"]["device"])

    def test_require_hsm_defaults_off(self):
        self.assertFalse(hsm.require_hsm())
        os.environ["WICK_PASSKEY_REQUIRE_HSM"] = "1"
        self.assertTrue(hsm.require_hsm())


class TestFilewrapSeal(HsmCase):
    def test_roundtrip_and_aad_bind(self):
        raw = b"pkcs8-passkey-bytes"
        sealed = hsm.wrap(raw, aad=b"example.com|demo")
        self.assertTrue(sealed["ok"])
        self.assertEqual(sealed["backend"], "filewrap")
        self.assertFalse(sealed["hsm"])
        self.assertNotIn("pkcs8", str(sealed.get("blob")))
        opened = hsm.unwrap(sealed["blob"], aad=b"example.com|demo")
        self.assertEqual(opened, raw)
        with self.assertRaises(ValueError) as err:
            hsm.unwrap(sealed["blob"], aad=b"evil.test|demo")
        self.assertIn("bad_mac", str(err.exception))

    def test_wrap_key_is_0600(self):
        hsm.wrap(b"abc", aad=b"aad")
        key = Path(self._tmp.name) / "vault" / "passkey.wrap"
        self.assertTrue(key.is_file())
        self.assertEqual(oct(key.stat().st_mode & 0o777), "0o600")

    def test_require_hsm_refuses_filewrap(self):
        os.environ["WICK_PASSKEY_REQUIRE_HSM"] = "1"
        denied = hsm.wrap(b"abc", aad=b"aad")
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"], "hsm_required")


class TestVaultPasskeySeal(HsmCase):
    def test_create_stores_sealed_not_raw_pkcs8_field_plaintext(self):
        import json

        vault = _load_vault()
        vault.ensure_local_key()
        out = vault.create_passkey("pk", url="https://example.com/login", username="agent")
        self.assertTrue(out["ok"], out)
        self.assertNotIn("private_key", out)
        store_path = Path(self._tmp.name) / "vault" / "store.enc"
        raw = store_path.read_text(encoding="utf-8")
        # Ciphertext store must not contain a raw PKCS#8 marker in cleartext.
        self.assertNotIn("BEGIN PRIVATE", raw)
        exported = vault.export_passkey_for_cdp("pk", "https://example.com/login")
        self.assertTrue(exported.get("ok"), exported)
        cred = exported.get("credential") or {}
        self.assertTrue(cred.get("privateKey"))
        self.assertEqual((exported.get("seal") or {}).get("backend"), "filewrap")
        self.assertFalse((exported.get("seal") or {}).get("hsm"))
        self.assertNotIn("BEGIN PRIVATE", json.dumps(exported.get("seal") or {}))

    def test_require_hsm_blocks_export(self):
        import json

        vault = _load_vault()
        vault.ensure_local_key()
        out = vault.create_passkey("pk", url="https://example.com/login")
        self.assertTrue(out["ok"], out)
        os.environ["WICK_PASSKEY_REQUIRE_HSM"] = "1"
        denied = vault.export_passkey_for_cdp("pk", "https://example.com/login")
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"], "hsm_required")
        self.assertNotIn("privateKey", json.dumps(denied))

    def test_require_hsm_blocks_create(self):
        os.environ["WICK_PASSKEY_REQUIRE_HSM"] = "1"
        vault = _load_vault()
        vault.ensure_local_key()
        out = vault.create_passkey("pk", url="https://example.com/login")
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "hsm_required")


def _load_vault():
    from importlib.machinery import SourceFileLoader
    import importlib.util

    path = _LIB / "vault.py"
    loader = SourceFileLoader("vault_hsm_test", str(path))
    spec = importlib.util.spec_from_loader("vault_hsm_test", loader)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    unittest.main()
