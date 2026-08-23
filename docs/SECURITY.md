# Security notes

Honest, scoped defaults — not a marketing checklist.

## Password vault (0.8+, origin-bound in 0.9)

Wick includes an **open-source local vault** plus bridges to Proton Pass CLI, KeePassXC-CLI, and AgentMail-style tokens.

- Secret **refs** (`vault://`, `pass://`, `env://`, `kdbx://`, `agentmail://`) are what agents should see.
- `wick act fill` / `wick act login` resolve refs in-process against the **live page origin**; responses report `vault.ref` and length, **not** the secret.
- Origin match is Chrome/Brave-style: exact host (plus `www` alias). Substring URL matching is rejected (phishing). HTTPS-saved logins never fill on HTTP.
- Store lives under `WICK_HOME/vault` (`0700`); master key `0600` or `WICK_VAULT_KEY`.
- Audit log records actions with redacted refs only.

### Local crypto (wickvault2)

- **AES-256-GCM** via the `cryptography` package (OpenSSL) for every wrap and every item blob — no homemade stream cipher on the write path.
- Key hierarchy **wrap → vault → item**: `HKDF-SHA256(master material, salt, "wick-vault-wrap")` wraps a random vault key, which wraps a random per-entry key, which encrypts the entry JSON. GCM AAD binds each blob to its entry name and saved origin.
- Master material is a 32-byte `master.key` (agent default) or `WICK_VAULT_PASSPHRASE` stretched with Argon2id (`argon2-cffi`) or scrypt n=2^16, r=8, p=1. The passphrase is never logged, audited, or returned in JSON.
- Only entry **names** are cleartext on disk; passwords, usernames, URLs, notes, and TOTP secrets live inside the blob. Failed unwrap → `bad_mac_or_key`, and 8 failures trigger a 30-second `vault_locked_cooldown`.
- `wick vault unlock` / `lock` / `grant` (full-act only) issue just-in-time, origin-scoped access; `WICK_VAULT_RELOCK_AFTER_FILL=1` drops the session after a fill.
- `WICK_VAULT_REQUIRE_GRANT=1` (or policy `vault_require_grant`) treats an empty grant list as deny (`grant_required:missing_grant`). Off by default so file-key agents keep working.
- Honest limits: file-key mode keeps a standing key on disk (like an unlocked browser profile), `session.json` holds its session key in a `0600` file, and none of this is Proton cloud sync, third-party audited, or HSM-backed. `wick vault doctor` reports `standing_key`, `audited: false`, `hsm: false`, `sync: false`. `wickvault1` is read-only and migrates on the next write.

See [VAULT.md](VAULT.md) and [VAULT-CRYPTO.md](VAULT-CRYPTO.md). Combine with shields + session isolation for the Brave-inspired stack — still **no** fingerprint farbling claim.

## Capability profiles (0.9)

`WICK_PROFILE=observe-only` / `safe-act` / `full-act` is enforced at the CLI and RPC layer. A read-only harness cannot fill passwords or eval JS even if a page (or a confused planner) asks it to.

`WICK_ALLOW_HOSTS` is an optional outbound allowlist for fetch/goto/login. `WICK_BLOCK_HOSTS` is the matching denylist; **deny wins**. The same knobs can live in a policy file (`WICK_POLICY` or `$WICK_HOME/policy.json`); `wick shields --policy` prints the merged view. Env wins for allowlist/profile/private; block lists and approval requirements are unioned so deny always wins.

`WICK_REQUIRE_APPROVAL=1` blocks `login` / `fill` / `passkey` / `eval` / `download` until a human or outer harness runs `wick approve …` or sets `WICK_APPROVE`. A page cannot mint this token.

Passkeys: vault-stored resident keys, PKCS#8 wrapped with a dedicated AES-256-GCM filewrap key (`$WICK_HOME/vault/passkey.wrap`, `0600`) on top of wickvault2. Injected via Chromium's CDP virtual authenticator. Not Touch ID / hardware keys. `wick vault doctor` / `wick shields` report `hsm: false` unless `/dev/tpmrm0` or a real PKCS#11 token is present. `WICK_PASSKEY_REQUIRE_HSM=1` refuses create when no hardware. Private keys never appear in agent JSON. See [PASSKEYS.md](PASSKEYS.md).

## Fetch / navigation guards (0.9)

Lightpanda `fetch` and Chromium `goto`/`login` reject `javascript:`, `data:`, `file:`, `blob:`, and (by default) private-network hosts (`127.0.0.1`, RFC1918, link-local, localhost). Override only with `WICK_ALLOW_PRIVATE=1`.

## Loopback CDP

Lightpanda and Chromium expose Chrome DevTools Protocol on **127.0.0.1 only** by default:

| Engine | Env | Default |
|--------|-----|---------|
| Lightpanda | `WICK_LP_PORT` | `9333` |
| Chromium | `WICK_CHROME_PORT` | `9222` |

Do not WAN-bind these ports. Anyone who can reach CDP can drive the browser as you.

## Shields honesty

Wick provides **network-layer** privacy inspired by Brave:

- EasyList / EasyPrivacy / Fanboy list blocking (when installed)
- Custom tracker URL blocks
- Private-network / SSRF blocking on the Lightpanda fetch path
- Optional DNT / Sec-GPC headers
- Per-session cookie jars and Chromium profiles
- `wick session export` redacts cookie values by default (`--reveal` is full-act only; redacted exports are not importable)

Wick does **not** provide Brave-class fingerprint farbling (canvas / WebGL / audio) or Camoufox-class anti-bot. Those need specialized browser engines. What it *does* do on the privacy side:

- WebRTC LAN/CGNAT IP guard (`WICK_WEBRTC_IP_GUARD=1`, Chromium `disable_non_proxied_udp`)
- Reduce User-Agent Client Hints (`WICK_REDUCE_CLIENT_HINTS=1`) — less entropy, not a forged UA
- Report known fingerprinting hosts/scripts on observe (`security.fingerprint_probes`)
- Detect CAPTCHA / Cloudflare / Turnstile / hCaptcha / reCAPTCHA and **halt** login/fill/passkey (`human_challenge`). Wick will not solve or auto-click challenges.

Treat shields as request filtering, isolation, and honest halt — not “undetectable browsing.”

## Proxy credentials

`WICK_PROXY`, `HTTPS_PROXY`, and `HTTP_PROXY` may contain passwords.

- Credentials are passed to the engine / curl as needed.
- Wick must **never** print, log, or write proxy passwords (history, doctor, error `cmd_tail`, metrics, etc.).
- Prefer a secrets manager or a scrubbed env for shared machines.
- Prefer vault refs for site logins: `wick act fill … 'vault://…'`.

## `WICK_HOME` permissions

Default state root: `~/.wick` (override with `WICK_HOME`).

On `ensure` / first use, Wick creates this tree and sets the home directory mode to **`0700`** so cookies, sessions, Chromium profiles, vault, and cache stay private to the user.

Do not share `WICK_HOME` across untrusted users. Treat it like a browser profile directory.

## What Wick does not claim

- Full consumer-browser sandbox parity
- Guaranteed CAPTCHA / Cloudflare / bank anti-bot bypass
- Immunity to local malware that already runs as your user
- Brave fingerprint farbling without a farbling engine

See also [SHIELDS-AND-ACTIONS.md](SHIELDS-AND-ACTIONS.md), [VAULT.md](VAULT.md), and [HEADLESS.md](HEADLESS.md).
