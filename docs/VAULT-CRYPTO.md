# Wick Vault crypto (wickvault2)

Local store must use the **same primitive class** as Proton Pass and Bitwarden — not a homemade stream cipher. This is still a **local, single-user** vault. We do **not** claim Proton Secure Core, Bitwarden cloud sync, third-party audits, or HSM.

## What 0.8/0.9 did wrong

`wickvault1` (`lib/vault.py`):

- SHA-256 counter XOR as a stream cipher (not AES, not ChaCha20)
- scrypt n=2^14 only
- `master.key` used directly as the wrapping secret with no vault-key hierarchy
- Whole store is one blob (one item leak = whole vault once opened)

## Target model (Proton + Bitwarden, local)

| Layer | Proton Pass | Bitwarden | Wick wickvault2 |
|-------|-------------|-----------|-----------------|
| KDF (human passphrase) | Argon2id | Argon2id (or PBKDF2 600k) | Argon2id if `argon2-cffi`; else scrypt n=2^16,r=8,p=1 |
| KDF (agent file key) | n/a | n/a | None — 256-bit CSPRNG file key + HKDF-SHA256 |
| Key hierarchy | user key → vault key → item key | master → stretched (HKDF) → protected symmetric key | wrap key → vault key → per-item key |
| Item encryption | AES-256-GCM | AES-256-CBC+HMAC (or XChaCha20) | AES-256-GCM |
| AAD | GCM tags | HMAC over ciphertext | GCM AAD = `wickvault2\|{name}\|{saved_origin}` |
| Secrets in agent JSON | never | never | never (unchanged) |
| Origin fill | n/a | URI match | Chrome/Brave origin bind (unchanged) |

Honest limits (keep in docs):

- A `master.key` file on disk is equivalent to an unlocked Bitwarden key sitting in a profile. Prefer passphrase + session TTL on shared machines.
- Same-user malware can still read `WICK_HOME`. Mode `0700` is isolation, not magic.
- No remote 2FA / SRP / audited mobile clients.

## On-disk format

`~/.wick/vault/store.enc` is JSON (0600):

```json
{
  "format": "wickvault2",
  "aead": "aes-256-gcm",
  "kdf": "filekey",
  "kdf_params": {},
  "salt": "<b64url 16+ bytes>",
  "wrapped_vault_key": {"nonce": "<b64url 12>", "ct": "<b64url>"},
  "items": {
    "demo": {
      "wrapped_item_key": {"nonce": "...", "ct": "..."},
      "origin": {"nonce": "...", "ct": "..."},
      "blob": {"nonce": "...", "ct": "..."},
      "updated": "2026-08-23T00:00:00Z"
    }
  }
}
```

- **Vault key**: 32 random bytes, wrapped with AES-GCM using `HKDF-SHA256(master, salt, info="wick-vault-wrap")`.
- **Item key**: 32 random bytes per entry, wrapped with the vault key (`info` / AAD includes item name).
- **Item blob**: AES-GCM of JSON `{username, password, url, notes, tags, totp, allow_subdomains, fields…}`.
- Entry **names** are identifiers (like `vault://demo`), not secrets. All secret **fields and URLs** live in the blob.
- **`origin`**: the saved origin, encrypted with the item key (AAD `wickvault2|item-origin|{name}`). It is read first so the blob AAD can be reconstructed without keeping any URL in cleartext.

`wickvault1` blobs (`wickvault1$salt$nonce$ct$mac`) are opened once and rewritten as wickvault2 on the next successful write.

## Unlock / lock / grant (agent broker)

2026 agent-browser research: never leave a standing password in model context; issue **just-in-time, origin-scoped** access from a broker outside the model.

| Command | Effect |
|---------|--------|
| `wick vault init` | Create 32-byte `master.key` (0600) + empty wickvault2 (default agent mode) |
| `wick vault init --passphrase` | Argon2id/scrypt from `WICK_VAULT_PASSPHRASE`; **no** raw key file |
| `wick vault unlock` | Decrypt vault key; write `session` (0600) with TTL (default 900s) |
| `wick vault lock` | Delete session; further resolve fails with `vault_locked` |
| `wick vault grant --url URL [--ttl 120]` | Session may `resolve`/`fill` only for that origin until TTL |

Env:

- `WICK_VAULT_PASSPHRASE` — human unlock (never logged)
- `WICK_VAULT_KEY` — still accepted as file-key material (HKDF, not used raw as AES key)
- `WICK_VAULT_LOCK_TTL` — default session seconds (900)
- `WICK_VAULT_RELOCK_AFTER_FILL=1` — drop session after a successful fill/login
- `WICK_VAULT_STRICT=1` — grant-required + relock after fill (off by default)
- `WICK_VAULT_BACKUP_PASSPHRASE` — encrypts `wick vault backup` / decrypts `restore` (file snapshot, not sync)
- File-key mode without an explicit lock stays auto-unlocked (agent default). `lock` in file-key mode is a no-op unless a session grant is active.

Failed unwrap: `hmac`/`GCM` fail closed (`bad_mac_or_key`). Count failures in `meta.json` (no secrets). After 8 failures, refuse for 30s.

## Public API (must not break)

Keep: `ensure_local_key`, `set_entry`, `delete_entry`, `list_entries`, `match_url`, `resolve`, `resolve_for_fill`, `suggest_login`, `get_meta`, `status`, `doctor`, `totp_*`, Proton/KeePass/env refs.

`list` / `match` / `suggest` still metadata-only. Decrypt happens in-process; JSON must never contain password/totp/username values except `get --reveal` and `resolve` (CLI debug / Chromium fill only).

## Tests that must stay green

Existing `tests/test_vault.py` (file-key roundtrip, no leak, origin bind, TOTP RFC 6238).

Add: wickvault2 header, migration from wickvault1, wrong passphrase, item AAD mismatch, grant origin deny, lock blocks resolve in passphrase mode, doctor reports `format=wickvault2` and `aead=aes-256-gcm`.
