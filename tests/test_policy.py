#!/usr/bin/env python3
"""Policy-as-file overlay: host allow/deny plus a few harness knobs."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import approval  # noqa: E402
import capability  # noqa: E402
import origins  # noqa: E402
import policy  # noqa: E402

_ENV = (
    "WICK_POLICY",
    "WICK_HOME",
    "WICK_ALLOW_HOSTS",
    "WICK_BLOCK_HOSTS",
    "WICK_PROFILE",
    "WICK_ALLOW_PRIVATE",
    "WICK_REQUIRE_APPROVAL",
    "WICK_APPROVE",
    "WICK_APPROVE_ONCE",
    "WICK_VAULT_REQUIRE_GRANT",
    "WICK_HALT_ON_CHALLENGE",
    "WICK_PASSKEY_REQUIRE_HSM",
)


class PolicyCase(unittest.TestCase):
    """Every test runs against a throwaway WICK_HOME with a clean env."""

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in _ENV}
        self._tmp = tempfile.TemporaryDirectory(prefix="wick-policy-")
        self.home = Path(self._tmp.name)
        os.environ["WICK_HOME"] = str(self.home)

    def tearDown(self):
        for k in _ENV:
            os.environ.pop(k, None)
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
        self._tmp.cleanup()

    def write(self, obj, name: str = "policy.json", *, raw: str | None = None) -> Path:
        """Write a policy file and point WICK_POLICY at it."""
        path = self.home / name
        path.write_text(
            raw if raw is not None else json.dumps(obj), encoding="utf-8"
        )
        os.environ["WICK_POLICY"] = str(path)
        return path


class TestNoPolicyFile(PolicyCase):
    def test_no_file_is_unrestricted(self):
        eff = policy.effective()
        self.assertEqual(eff["allow_hosts"], [])
        self.assertEqual(eff["block_hosts"], [])
        self.assertEqual(eff["profile"], "full-act")
        self.assertFalse(eff["allow_private"])
        self.assertEqual(eff["require_approval"], [])
        self.assertFalse(eff["vault_require_grant"])
        self.assertTrue(eff["halt_on_challenge"])
        self.assertFalse(eff["passkey_require_hsm"])
        self.assertEqual(eff["source"], "none")
        self.assertIsNone(policy.policy_path())
        self.assertEqual(policy.load_policy(), {})

        ok, reason = capability.host_allowed("https://evil.test/")
        self.assertTrue(ok)
        self.assertEqual(reason, "unrestricted")
        self.assertEqual(capability.current_profile(), "full-act")
        self.assertIsNone(approval.check("login"))
        self.assertFalse(origins.allow_private_override())
        self.assertFalse(policy.vault_require_grant())

    def test_env_only_behavior_survives(self):
        os.environ["WICK_ALLOW_HOSTS"] = "example.com,.github.com"
        os.environ["WICK_BLOCK_HOSTS"] = "evil.test"
        self.assertTrue(capability.host_allowed("https://example.com/")[0])
        self.assertTrue(capability.host_allowed("https://docs.github.com/")[0])
        self.assertFalse(capability.host_allowed("https://other.test/")[0])
        self.assertEqual(capability.host_allowed("https://evil.test/")[1], "blocked")
        self.assertEqual(capability.parse_allow_hosts(), ["example.com", ".github.com"])
        self.assertEqual(capability.parse_block_hosts(), ["evil.test"])

    def test_missing_env_path_is_reported_not_fatal(self):
        os.environ["WICK_POLICY"] = str(self.home / "nope.json")
        eff = policy.effective()
        self.assertEqual(eff["source"], "none")
        self.assertTrue(eff["path"].endswith("nope.json"))
        self.assertTrue(capability.host_allowed("https://evil.test/")[0])

    def test_default_home_file_is_used_without_env(self):
        (self.home / "policy.json").write_text(
            json.dumps({"block_hosts": ["evil.test"]}), encoding="utf-8"
        )
        eff = policy.effective()
        self.assertEqual(eff["source"], "home")
        self.assertEqual(eff["block_hosts"], ["evil.test"])
        self.assertFalse(capability.host_allowed("https://evil.test/")[0])


class TestHosts(PolicyCase):
    def test_file_block_beats_env_allow(self):
        self.write({"block_hosts": ["evil.test", ".ads.example.com"]})
        os.environ["WICK_ALLOW_HOSTS"] = "evil.test,example.com"
        ok, reason = capability.host_allowed("https://evil.test/")
        self.assertFalse(ok)
        self.assertEqual(reason, "blocked")
        self.assertFalse(capability.host_allowed("https://tracker.ads.example.com/")[0])
        self.assertTrue(capability.host_allowed("https://example.com/")[0])
        denied = capability.deny_host("https://evil.test/")
        self.assertIsNotNone(denied)
        self.assertIn("evil.test", denied["block_hosts"])
        self.assertEqual(denied["policy"], os.environ["WICK_POLICY"])

    def test_block_lists_are_unioned(self):
        self.write({"block_hosts": ["evil.test"]})
        os.environ["WICK_BLOCK_HOSTS"] = "tracker.test"
        self.assertEqual(capability.parse_block_hosts(), ["evil.test", "tracker.test"])
        self.assertFalse(capability.host_allowed("https://evil.test/")[0])
        self.assertFalse(capability.host_allowed("https://tracker.test/")[0])

    def test_file_allow_list_restricts(self):
        self.write({"allow_hosts": ["example.com", ".github.com"]})
        self.assertEqual(capability.parse_allow_hosts(), ["example.com", ".github.com"])
        self.assertTrue(capability.host_allowed("https://example.com/login")[0])
        self.assertTrue(capability.host_allowed("https://docs.github.com/")[0])
        self.assertFalse(capability.host_allowed("https://notexample.com/")[0])
        self.assertFalse(capability.host_allowed("https://evil.test/")[0])

    def test_env_allow_hosts_overrides_file_allow(self):
        self.write({"allow_hosts": ["example.com"]})
        os.environ["WICK_ALLOW_HOSTS"] = "other.test"
        self.assertEqual(capability.parse_allow_hosts(), ["other.test"])
        self.assertTrue(capability.host_allowed("https://other.test/")[0])
        self.assertFalse(capability.host_allowed("https://example.com/")[0])

    def test_file_block_still_applies_under_env_allow(self):
        self.write({"allow_hosts": ["example.com"], "block_hosts": ["example.com"]})
        os.environ["WICK_ALLOW_HOSTS"] = "example.com"
        ok, reason = capability.host_allowed("https://example.com/")
        self.assertFalse(ok)
        self.assertEqual(reason, "blocked")


class TestProfile(PolicyCase):
    def test_file_profile_used_when_env_unset(self):
        self.write({"profile": "safe-act"})
        self.assertEqual(capability.current_profile(), "safe-act")
        self.assertIsNone(capability.deny("act", action="click"))
        self.assertIsNotNone(capability.deny("act", action="fill"))
        self.assertIsNotNone(capability.deny("act", action="login"))

    def test_env_profile_wins(self):
        self.write({"profile": "observe-only"})
        os.environ["WICK_PROFILE"] = "full-act"
        self.assertEqual(capability.current_profile(), "full-act")
        self.assertIsNone(capability.deny("act", action="login"))

    def test_file_alias_normalizes(self):
        self.write({"profile": "observe"})
        self.assertEqual(capability.current_profile(), "observe-only")
        self.assertIsNotNone(capability.deny("act", action="click"))


class TestApprovalWiring(PolicyCase):
    def test_file_require_approval_blocks_until_approved(self):
        self.write({"require_approval": ["login", "passkey"]})
        self.assertEqual(policy.require_approval(), ["login", "passkey"])
        denied = approval.check("login")
        self.assertIsNotNone(denied)
        self.assertEqual(denied["error"], "approval_required")
        self.assertIsNone(approval.check("goto"))
        self.assertIsNone(approval.check("fill"))

        os.environ["WICK_APPROVE"] = "login"
        self.assertIsNone(approval.check("login"))
        self.assertIsNotNone(approval.check("passkey"))

    def test_file_true_requires_every_sensitive_action(self):
        self.write({"require_approval": True})
        self.assertEqual(policy.require_approval(), ["*"])
        self.assertEqual(approval.required_actions(), set(approval.SENSITIVE))
        self.assertIsNotNone(approval.check("fill"))
        self.assertIsNotNone(approval.check("eval"))
        self.assertIsNone(approval.check("click"))

    def test_env_and_file_lists_are_unioned(self):
        self.write({"require_approval": ["login"]})
        os.environ["WICK_REQUIRE_APPROVAL"] = "eval"
        self.assertEqual(approval.required_actions(), {"login", "eval"})
        self.assertIsNotNone(approval.check("login"))
        self.assertIsNotNone(approval.check("eval"))
        self.assertIsNone(approval.check("download"))

    def test_env_off_cannot_disable_file_requirement(self):
        self.write({"require_approval": ["login"]})
        os.environ["WICK_REQUIRE_APPROVAL"] = "0"
        self.assertIsNotNone(approval.check("login"))

    def test_unknown_action_names_are_dropped(self):
        self.write({"require_approval": ["login", "nonsense"]})
        self.assertEqual(approval.required_actions(), {"login"})
        self.assertIsNone(approval.check("nonsense"))

    def test_issued_token_satisfies_file_requirement(self):
        self.write({"require_approval": ["login"]})
        issued = approval.issue(["login"], ttl=60)
        self.assertTrue(issued["ok"])
        self.assertIsNone(approval.check("login"))


class TestPrivateAndGrant(PolicyCase):
    def test_file_allow_private(self):
        self.write({"allow_private": True})
        self.assertTrue(policy.effective()["allow_private"])
        self.assertTrue(origins.allow_private_override())
        self.assertIsNone(origins.guard_fetch_url("http://127.0.0.1:8080/"))

    def test_env_private_wins_over_file(self):
        self.write({"allow_private": True})
        os.environ["WICK_ALLOW_PRIVATE"] = "0"
        self.assertFalse(origins.allow_private_override())
        blocked = origins.guard_fetch_url("http://127.0.0.1:8080/")
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked["error"], "private_url")

    def test_private_blocked_by_default(self):
        self.write({"profile": "safe-act"})
        self.assertFalse(origins.allow_private_override())
        self.assertIsNotNone(origins.guard_fetch_url("http://192.168.1.4/"))

    def test_vault_require_grant_file_and_env(self):
        self.write({"vault_require_grant": True})
        self.assertTrue(policy.vault_require_grant())
        os.environ["WICK_VAULT_REQUIRE_GRANT"] = "0"
        self.assertFalse(policy.vault_require_grant())
        os.environ["WICK_VAULT_REQUIRE_GRANT"] = "1"
        self.assertTrue(policy.vault_require_grant())

    def test_halt_and_hsm_file_and_env(self):
        self.write({"halt_on_challenge": False, "passkey_require_hsm": True})
        self.assertFalse(policy.effective()["halt_on_challenge"])
        self.assertTrue(policy.effective()["passkey_require_hsm"])
        os.environ["WICK_HALT_ON_CHALLENGE"] = "1"
        os.environ["WICK_PASSKEY_REQUIRE_HSM"] = "0"
        self.assertTrue(policy.effective()["halt_on_challenge"])
        self.assertFalse(policy.effective()["passkey_require_hsm"])


class TestBadInput(PolicyCase):
    def test_invalid_json_is_ignored(self):
        self.write(None, raw="{not json at all,,,")
        eff = policy.effective()
        self.assertEqual(policy.load_policy(), {})
        self.assertEqual(eff["source"], "none")
        self.assertEqual(eff["allow_hosts"], [])
        self.assertEqual(eff["block_hosts"], [])
        self.assertEqual(eff["profile"], "full-act")
        self.assertTrue(capability.host_allowed("https://evil.test/")[0])
        self.assertIsNone(approval.check("login"))

    def test_non_object_json_is_ignored(self):
        self.write(None, raw='["evil.test"]')
        self.assertEqual(policy.load_policy(), {})
        self.assertTrue(capability.host_allowed("https://evil.test/")[0])

    def test_env_rules_survive_an_invalid_file(self):
        self.write(None, raw="}{")
        os.environ["WICK_BLOCK_HOSTS"] = "evil.test"
        self.assertFalse(capability.host_allowed("https://evil.test/")[0])

    def test_unknown_keys_ignored_and_bad_field_does_not_drop_block_list(self):
        self.write(
            {
                "block_hosts": ["evil.test"],
                "allow_hosts": "not-a-list-but-parseable.test",
                "profile": 42,
                "require_approval": {"bad": "shape"},
                "wat": {"nested": True},
            }
        )
        eff = policy.effective()
        self.assertEqual(eff["block_hosts"], ["evil.test"])
        self.assertEqual(eff["allow_hosts"], ["not-a-list-but-parseable.test"])
        self.assertEqual(eff["profile"], "full-act")
        self.assertEqual(eff["require_approval"], [])
        self.assertFalse(capability.host_allowed("https://evil.test/")[0])

    def test_hosts_are_lowercased_and_deduped(self):
        self.write({"block_hosts": ["EVIL.test", "evil.test.", "  Ads.Example.com "]})
        self.assertEqual(
            policy.effective()["block_hosts"], ["evil.test", "ads.example.com"]
        )


class TestValidateAndWrite(PolicyCase):
    def test_validate_accepts_full_shape(self):
        res = policy.validate(
            {
                "allow_hosts": ["example.com", ".github.com"],
                "block_hosts": ["evil.test"],
                "profile": "safe-act",
                "allow_private": False,
                "require_approval": ["login", "passkey"],
                "vault_require_grant": True,
                "halt_on_challenge": False,
                "passkey_require_hsm": True,
                "extra": 1,
            }
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["ignored"], ["extra"])
        self.assertEqual(res["policy"]["profile"], "safe-act")
        self.assertTrue(res["policy"]["vault_require_grant"])
        self.assertFalse(res["policy"]["halt_on_challenge"])
        self.assertTrue(res["policy"]["passkey_require_hsm"])

    def test_validate_rejects_bad_shapes(self):
        self.assertFalse(policy.validate(["nope"])["ok"])
        self.assertEqual(policy.validate({"profile": "wat"})["error"], "bad_profile")
        self.assertEqual(policy.validate({"allow_hosts": 5})["error"], "bad_allow_hosts")
        self.assertEqual(
            policy.validate({"allow_private": "maybe"})["error"], "bad_allow_private"
        )

    def test_write_policy_is_0600_and_round_trips(self):
        dest = self.home / "sub" / "policy.json"
        res = policy.write_policy({"block_hosts": ["evil.test"], "profile": "safe-act"}, dest)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["mode"], "0600")
        self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o600)
        os.environ["WICK_POLICY"] = str(dest)
        eff = policy.effective()
        self.assertEqual(eff["block_hosts"], ["evil.test"])
        self.assertEqual(eff["profile"], "safe-act")
        self.assertEqual(eff["source"], "env")
        self.assertEqual(capability.current_profile(), "safe-act")

    def test_write_policy_refuses_invalid(self):
        dest = self.home / "bad.json"
        res = policy.write_policy({"profile": "wat"}, dest)
        self.assertFalse(res["ok"])
        self.assertFalse(dest.exists())


if __name__ == "__main__":
    unittest.main()
