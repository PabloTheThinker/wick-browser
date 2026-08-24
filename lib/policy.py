"""Policy-as-file overlay for host allow/deny and a few harness knobs.

An outer harness often cannot set env vars on every wick call (MCP servers,
cron wrappers, sandboxes). A policy file gives it one place to pin the rules:

    WICK_POLICY=/etc/wick/policy.json   # explicit path wins
    $WICK_HOME/policy.json              # otherwise this, when it exists

    {
      "allow_hosts": ["example.com", ".github.com"],
      "block_hosts": ["evil.test"],
      "profile": "safe-act",
      "allow_private": false,
      "require_approval": ["login", "passkey"],
      "vault_require_grant": true,
      "halt_on_challenge": true,
      "challenge_computer_use": false,
      "passkey_require_hsm": false
    }

Merge rules (env stays authoritative where it is more explicit, deny wins):

  block_hosts         union of file + WICK_BLOCK_HOSTS
  allow_hosts         WICK_ALLOW_HOSTS replaces the file list when set
  profile             WICK_PROFILE wins when set
  allow_private       WICK_ALLOW_PRIVATE wins when set
  require_approval    union of file + WICK_REQUIRE_APPROVAL (true = all sensitive)
  vault_require_grant WICK_VAULT_REQUIRE_GRANT wins when set
  halt_on_challenge   WICK_HALT_ON_CHALLENGE wins when set (default on)
  challenge_computer_use WICK_CHALLENGE_COMPUTER_USE wins when set
  passkey_require_hsm WICK_PASSKEY_REQUIRE_HSM wins when set

Unknown keys are ignored. A missing or unparseable file is an empty policy —
never a crash, and never a silent loosening of the env-only rules. Values are
read on every call so a harness can rewrite the file mid-session.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

KEYS = (
    "allow_hosts",
    "block_hosts",
    "profile",
    "allow_private",
    "require_approval",
    "vault_require_grant",
    "halt_on_challenge",
    "challenge_computer_use",
    "passkey_require_hsm",
)
FALLBACK_PROFILES = ("observe-only", "safe-act", "full-act")
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def _home() -> Path:
    raw = os.environ.get("WICK_HOME") or str(Path.home() / ".wick")
    return Path(raw).expanduser()


def _env_policy() -> str:
    return (os.environ.get("WICK_POLICY") or "").strip()


def policy_path() -> Path | None:
    """WICK_POLICY when set (even if absent, so errors can name it), else the
    default file only when it exists."""
    raw = _env_policy()
    if raw:
        return Path(raw).expanduser()
    default = _home() / "policy.json"
    return default if default.is_file() else None


def _norm_hosts(value: Any) -> list[str]:
    if isinstance(value, str):
        items: list[Any] = value.split(",")
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return []
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        host = item.strip().lower().rstrip(".")
        if host and host not in out:
            out.append(host)
    return out


def _norm_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in _TRUE:
            return True
        if raw in _FALSE:
            return False
    return None


def _env_bool(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    return _norm_bool(raw)


def _norm_actions(value: Any) -> list[str]:
    """A bare true / "1" means every sensitive action; '*' carries that intent."""
    flag = _norm_bool(value)
    if flag is True:
        return ["*"]
    if flag is False:
        return []
    if isinstance(value, str):
        items: list[Any] = value.split(",")
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return []
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        act = item.strip().lower()
        if act and act not in out:
            out.append(act)
    return out


def _read(path: Path | None) -> tuple[dict[str, Any], str]:
    """Return (policy, status) with status one of ok / missing / invalid."""
    if path is None:
        return {}, "missing"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}, "missing"
    try:
        obj = json.loads(raw)
    except ValueError:
        return {}, "invalid"
    if not isinstance(obj, dict):
        return {}, "invalid"
    return obj, "ok"


def load_policy() -> dict[str, Any]:
    """Parsed policy file, or {} when absent or unparseable."""
    obj, _status = _read(policy_path())
    return obj


def validate(obj: Any) -> dict[str, Any]:
    """Return {'ok': True, 'policy': normalized} or {'ok': False, 'error': ...}."""
    if not isinstance(obj, dict):
        return {"ok": False, "error": "not_an_object", "detail": "policy must be a JSON object"}
    norm: dict[str, Any] = {}
    for key in ("allow_hosts", "block_hosts"):
        if key in obj and obj[key] is not None:
            if not isinstance(obj[key], (list, tuple, str)):
                return {"ok": False, "error": "bad_" + key, "detail": "expected a list of hosts"}
            hosts = _norm_hosts(obj[key])
            if hosts:
                norm[key] = hosts
    if obj.get("profile") is not None:
        prof = obj["profile"]
        if not isinstance(prof, str) or not prof.strip():
            return {"ok": False, "error": "bad_profile", "detail": "expected a profile name"}
        name = prof.strip().lower()
        if name not in _known_profiles():
            return {
                "ok": False,
                "error": "bad_profile",
                "detail": name,
                "hint": "one of " + ", ".join(FALLBACK_PROFILES),
            }
        norm["profile"] = name
    for key in (
        "allow_private",
        "vault_require_grant",
        "halt_on_challenge",
        "challenge_computer_use",
        "passkey_require_hsm",
    ):
        if key in obj and obj[key] is not None:
            flag = _norm_bool(obj[key])
            if flag is None:
                return {"ok": False, "error": "bad_" + key, "detail": "expected a boolean"}
            norm[key] = flag
    if obj.get("require_approval") is not None:
        value = obj["require_approval"]
        if not isinstance(value, (list, tuple, str, bool, int)):
            return {
                "ok": False,
                "error": "bad_require_approval",
                "detail": "expected a list of actions or a boolean",
            }
        acts = _norm_actions(value)
        if acts:
            norm["require_approval"] = acts
    unknown = sorted(k for k in obj if k not in KEYS)
    return {"ok": True, "policy": norm, "ignored": unknown}


def _known_profiles() -> set[str]:
    """Profile names capability accepts, without importing it at module load."""
    names = set(FALLBACK_PROFILES)
    try:
        # Imported here, not at module scope: capability imports this module.
        import capability

        names |= set(getattr(capability, "PROFILES", ()))
        names |= set(getattr(capability, "ALIASES", {}))
    except Exception:
        pass
    return names


def _overlay(obj: dict[str, Any]) -> dict[str, Any]:
    """Lenient read of a parsed file: keep the keys that make sense, drop the rest.

    Deliberately not validate(): one bad field must not discard a block list.
    """
    out: dict[str, Any] = {}
    for key in ("allow_hosts", "block_hosts"):
        hosts = _norm_hosts(obj.get(key))
        if hosts:
            out[key] = hosts
    prof = obj.get("profile")
    if isinstance(prof, str) and prof.strip():
        out["profile"] = prof.strip().lower()
    for key in (
        "allow_private",
        "vault_require_grant",
        "halt_on_challenge",
        "challenge_computer_use",
        "passkey_require_hsm",
    ):
        flag = _norm_bool(obj.get(key))
        if flag is not None:
            out[key] = flag
    acts = _norm_actions(obj.get("require_approval"))
    if acts:
        out["require_approval"] = acts
    return out


def effective() -> dict[str, Any]:
    """Merged view of file policy and env. Env wins where it is more explicit."""
    path = policy_path()
    obj, status = _read(path)
    loaded = status == "ok"
    file_policy = _overlay(obj) if loaded else {}

    env_allow = _norm_hosts(os.environ.get("WICK_ALLOW_HOSTS") or "")
    allow = env_allow if env_allow else list(file_policy.get("allow_hosts") or [])

    block = list(file_policy.get("block_hosts") or [])
    for host in _norm_hosts(os.environ.get("WICK_BLOCK_HOSTS") or ""):
        if host not in block:
            block.append(host)

    env_profile = (os.environ.get("WICK_PROFILE") or "").strip().lower()
    profile = env_profile or str(file_policy.get("profile") or "") or "full-act"

    env_private = _env_bool("WICK_ALLOW_PRIVATE")
    allow_private = (
        env_private if env_private is not None else bool(file_policy.get("allow_private") or False)
    )

    env_grant = _env_bool("WICK_VAULT_REQUIRE_GRANT")
    require_grant = (
        env_grant
        if env_grant is not None
        else bool(file_policy.get("vault_require_grant") or False)
    )

    env_halt = _env_bool("WICK_HALT_ON_CHALLENGE")
    halt_on_challenge = (
        env_halt
        if env_halt is not None
        else bool(file_policy["halt_on_challenge"] if "halt_on_challenge" in file_policy else True)
    )

    env_cu = _env_bool("WICK_CHALLENGE_COMPUTER_USE")
    challenge_computer_use = (
        env_cu
        if env_cu is not None
        else bool(file_policy.get("challenge_computer_use") or False)
    )

    env_hsm = _env_bool("WICK_PASSKEY_REQUIRE_HSM")
    passkey_require_hsm = (
        env_hsm
        if env_hsm is not None
        else bool(file_policy.get("passkey_require_hsm") or False)
    )

    source = "none"
    if loaded:
        source = "env" if _env_policy() else "home"
    return {
        "allow_hosts": allow,
        "block_hosts": block,
        "profile": profile,
        "allow_private": allow_private,
        "require_approval": list(file_policy.get("require_approval") or []),
        "vault_require_grant": require_grant,
        "halt_on_challenge": halt_on_challenge,
        "challenge_computer_use": challenge_computer_use,
        "passkey_require_hsm": passkey_require_hsm,
        "path": str(path) if path else None,
        "source": source,
    }


def require_approval() -> list[str]:
    """Actions the policy file demands approval for (env is unioned by approval)."""
    return list(effective()["require_approval"])


def vault_require_grant() -> bool:
    """True when a vault fill needs a fresh out-of-band grant."""
    return bool(effective()["vault_require_grant"])


def write_policy(obj: Any, dest: Path) -> dict[str, Any]:
    """Validate then write a 0600 policy file. Returns the validation error as-is."""
    checked = validate(obj)
    if not checked.get("ok"):
        return checked
    target = Path(dest).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(checked["policy"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(tmp, 0o600)
        tmp.replace(target)
        os.chmod(target, 0o600)
    except OSError as e:
        return {"ok": False, "error": "write_failed", "detail": str(e), "path": str(target)}
    return {
        "ok": True,
        "path": str(target),
        "mode": "0600",
        "policy": checked["policy"],
        "ignored": checked.get("ignored") or [],
    }
