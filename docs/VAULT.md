# Wick Vault (0.8)

Open-source password manager **for agents**, wired into Brave-inspired shields and optional Proton Pass + AgentMail.

## Why this exists

Agent browsers that paste real passwords into tool JSON leak credentials into model context, logs, and session transcripts. Wick Vault keeps **refs** in the agent loop and injects secrets only on the Chromium fill path.

## Secret refs

| Ref | Backend | Example |
|-----|---------|---------|
| `vault://name/field` | Local encrypted store under `WICK_HOME/vault` | `vault://github/password` |
| `pass://Vault/Item/field` | Proton Pass CLI (`pass-cli`) agent tokens | `pass://Work/GitHub/password` |
| `env://VAR` | Process environment | `env://CI_BOT_PASSWORD` |
| `kdbx://Entry/field` | KeePassXC-CLI + `WICK_KDBX` | `kdbx://Web/GitHub/password` |
| `agentmail://token` | Alias → `vault://agentmail/token` | Bearer for proton-agent-mail |

Default field is `password` when omitted: `vault://github` → `vault://github/password`.

## CLI

```bash
wick vault init                          # create master.key (0600) + empty store
wick vault status                        # backends + Brave stack honesty
wick vault list                          # metadata only — never secrets
wick vault set github --username me --password '…' --url https://github.com/login
# safer set:
WICK_VAULT_SET_PASSWORD='…' wick vault set github --username me --url https://github.com/login

wick vault unlock --ttl 900                # write session.json (0600), TTL-limited
wick vault grant --url https://example.com/login --ttl 120   # scope resolve/fill to one origin
wick vault lock                            # delete the session and every grant
WICK_VAULT_PASSPHRASE='…' wick vault harden   # delete master.key; passphrase-only unlock

wick vault match --url https://github.com/login
wick vault suggest --url https://github.com/login   # refs + form hints, no secrets
wick vault get github                    # fields present, no values
wick vault gen --length 28               # generate (prints once)

# Agent login — same motion as Chrome/Brave autofill (secret never in JSON)
wick act login https://github.com/login
# after a computer-use click through a widget (does not solve it):
wick act login https://example.com/login --after-challenge 15000

wick vault audit                         # hash-chained log tail — never secrets
WICK_VAULT_BACKUP_PASSPHRASE='…' wick vault backup /tmp/wick-vault.bak
WICK_VAULT_BACKUP_PASSPHRASE='…' wick vault restore /tmp/wick-vault.bak
# or manual, still origin-bound to the live page:
wick act fill 'css=input[name=login]' 'vault://github/username'
wick act fill 'css=input[name=password]' 'vault://github/password'
wick act click 'css=button[type=submit]'

# Passkey (password-manager-as-authenticator — not Touch ID)
wick vault passkey-new github --url https://github.com/login --username me
wick act passkey https://github.com/login
# If WICK_REQUIRE_APPROVAL=1, a human/harness must first:
wick approve login --ttl 120
```

## Origin binding (0.9)

Wick matches credentials the way Chrome and Brave do, not by substring:

| Saved | Page | Autofill |
|-------|------|----------|
| `https://example.com/login` | `https://example.com/account` | yes (exact host) |
| `https://www.example.com/` | `https://example.com/login` | yes (`www` alias) |
| `https://example.com/` | `http://example.com/` | **no** (HTTPS-saved never fills HTTP) |
| `https://example.com/` | `https://evil.test/?next=https://example.com/` | **no** (phishing) |
| `https://example.com/` | `https://app.example.com/` | only if `wick vault set … --allow-subdomains` |

`wick act fill` / `login` resolve refs against the **live page URL**. An unbound entry (no `--url`) is refused unless `WICK_VAULT_REQUIRE_ORIGIN=0`.

TOTP: store a base32 secret or `otpauth://` URL as field `totp`. Agents fill `vault://name/otp` — Wick computes the current code; it is never listed as a stored value.

## Proton Pass + AgentMail

**Proton Pass** (official): create an AI agent token with scoped vault access and audit logging, install `pass-cli`, then fill with `pass://…` refs. See [Proton Pass developer features](https://proton.me/pass/developer-features).

**AgentMail / proton-agent-mail**: store the loopback bearer token once:

```bash
WICK_VAULT_SET_PASSWORD="$TOKEN" wick vault set agentmail/token --field token="$TOKEN"
# or:
wick vault set agentmail --field token="$TOKEN"
```

Agents request mail via the token-gated local API; Wick only holds the token as a ref (`agentmail://token`). Same compartment story as Bridge on `127.0.0.1`.

## Brave-inspired security stack

| Layer | Wick |
|-------|------|
| Tracker / ad lists | `wick shields` (EasyList / EasyPrivacy / Fanboy) |
| SSRF / private net | Lightpanda path block (default on) |
| Privacy headers | DNT / Sec-GPC |
| Session isolation | `WICK_SESSION` cookie jars + Chromium profiles |
| Credentials | **Vault refs** — not page cookies alone |
| Fingerprint farbling | **Not claimed** (needs Brave/Camoufox-class engine) |

Together: observe with shields, act in an isolated session, fill only via vault refs.

## Crypto (wickvault2)

Same primitive class as Proton Pass and Bitwarden, run locally. Full spec: [VAULT-CRYPTO.md](VAULT-CRYPTO.md).

| Layer | What Wick does |
|-------|----------------|
| AEAD | **AES-256-GCM** (`cryptography` / OpenSSL) for every wrap and every item blob |
| Wrap key | **HKDF-SHA256**(master material, per-store salt, `info="wick-vault-wrap"`) |
| Vault key | 32 CSPRNG bytes, GCM-wrapped by the wrap key |
| Item key | 32 CSPRNG bytes **per entry**, GCM-wrapped by the vault key |
| Item blob | GCM of the whole entry JSON (password, username, url, notes, totp, tags, extra fields) |
| AAD | `wickvault2\|blob\|{name}\|{saved_origin}` — ciphertext cannot be renamed or repointed |
| Master material | 32-byte `master.key` (agent default) **or** `WICK_VAULT_PASSPHRASE` |
| Passphrase KDF | Argon2id (`argon2-cffi`) if installed, else scrypt n=2^16, r=8, p=1 |

Entry **names** are identifiers (`vault://demo`); nothing else is cleartext on disk — not even the saved URL. A failed GCM unwrap returns `bad_mac_or_key`, and after 8 failures the vault refuses for 30 seconds (`vault_locked_cooldown`).

`wick vault doctor` / `status` report `format`, `aead`, `kdf`, `hierarchy`, plus honesty flags: `standing_key`, `audited: false`, `hsm: false`, `sync: false`. Doctor also verifies the local audit hash chain and hints `wick vault harden` while a standing `master.key` is present.

`wickvault1` (SHA-256 counter XOR + HMAC, scrypt n=2^14) is **read-only**: an old store opens once and the next write rewrites it as wickvault2.

## Lock, unlock, grant

These three need `WICK_PROFILE=full-act`; `status` / `list` / `match` / `suggest` stay observe-safe.

| Env | Meaning |
|-----|---------|
| `WICK_VAULT_PASSPHRASE` | Human unlock — never logged, never audited, never in JSON |
| `WICK_VAULT_KEY` | File-key material (HKDF input, not used raw as an AES key) |
| `WICK_VAULT_LOCK_TTL` | Session seconds, default `900` |
| `WICK_VAULT_RELOCK_AFTER_FILL=1` | `lock()` right after a successful local fill |
| `WICK_VAULT_REQUIRE_GRANT=1` | Empty grants deny every local resolve/fill/passkey export (`grant_required:missing_grant`) |
| `WICK_VAULT_STRICT=1` | Grant-required **and** relock after fill (standing file keys stay off the fill path) |
| `WICK_VAULT_BACKUP_PASSPHRASE` | Encrypts `wick vault backup` / decrypts `restore` — never logged, never in JSON |

- **File-key mode (default):** `master.key` on disk means the vault is effectively auto-unlocked. `lock` clears the session and its grants; it cannot un-know a key that is still sitting in a file.
- **Passphrase mode:** without `WICK_VAULT_PASSPHRASE` and without a live session, `resolve` / `list` fail with `vault_locked`. `unlock` stores a short-TTL GCM wrap of the vault key next to a 32-byte session key in `session.json` (`0600`) — a TTL convenience, not a hardware keystore.
- **Grants:** while any grant is active, local `resolve` / `resolve_for_fill` are denied unless the saved origin *and* the live page origin match a non-expired grant (`grant_required:…`). `WICK_VAULT_REQUIRE_GRANT=1` (or policy `vault_require_grant: true`) also denies when **no** grant is active. `WICK_VAULT_STRICT=1` (or policy `vault_strict: true`) turns on grant-required **and** relock-after-fill. Off by default. `match` / `suggest` keep returning metadata only.
- **Backup / restore:** encrypted file snapshot (`wick-vault-backup-1`). Not live sync, not multi-device vault. `audit` is a hash-chained local log (`chain_ok`); `audited: false` still means no third-party review.

## Storage layout

```
~/.wick/vault/          # mode 0700
  master.key            # 0600 (or WICK_VAULT_KEY env; absent in passphrase mode)
  store.enc             # 0600 JSON — wickvault2: AES-256-GCM, wrap→vault→item keys
  session.json          # 0600, TTL — unlock state + origin grants (deleted by lock)
  audit.jsonl           # hash-chained actions + redacted refs — never secret values
  passkey.wrap.enc      # 0600 — passkey filewrap key sealed under the vault wrap key
  config.json           # backend paths
  meta.json             # format + unwrap-failure counter (no secrets)
```

## Agent rules

1. Prefer `wick vault list` / `match` / `suggest` — never `--reveal` in harnesses.
2. Prefer `wick act login URL` (human autofill). Manual: `wick act fill SELECTOR 'vault://…'` — response includes `vault.ref` + `chars`, not the password.
3. Playbooks: `{"action":"login","url":"https://example.com/login"}` or `"secret_ref": "vault://name/password"`.
4. RPC: `{"cmd":"vault","args":{"action":"suggest","url":"https://example.com/login"}}` then `{"cmd":"act","args":{"action":"login","rest":["https://example.com/login"]}}`.

## Honest limits

- Local crypto is open and reviewable (`lib/vault_crypto.py`, `lib/vault.py`): AES-256-GCM + HKDF-SHA256 with a vault/item key hierarchy. It is **not** Proton cloud sync, **not** third-party audited, and **not** an HSM.
- File-key mode keeps a standing 32-byte key in `master.key` — comparable to an unlocked browser profile. `wick vault harden` (with `WICK_VAULT_PASSPHRASE`) deletes `master.key` and re-seals the store. Prefer that, or `WICK_VAULT_STRICT=1`, on shared machines. There is no cloud sync.
- Same-user malware can read `WICK_HOME`; `0700` is isolation, not magic.
- Proton Pass and KeePassXC require their CLIs on `PATH`.
- TOTP can be stored as a field (`vault://name/otp`).
- Passkeys: Wick can *be* the authenticator (Bitwarden / Proton Pass model) via a vault-stored P-256 resident key and Chromium's CDP virtual authenticator. It cannot press Touch ID, Windows Hello, or a hardware key. See [PASSKEYS.md](PASSKEYS.md).
- Page content remains untrusted (`observe_security` annotations).
