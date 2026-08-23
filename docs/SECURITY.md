# Security notes

Honest, scoped defaults — not a marketing checklist.

## Password vault (0.8+, origin-bound in 0.9)

Wick includes an **open-source local vault** plus bridges to Proton Pass CLI, KeePassXC-CLI, and AgentMail-style tokens.

- Secret **refs** (`vault://`, `pass://`, `env://`, `kdbx://`, `agentmail://`) are what agents should see.
- `wick act fill` / `wick act login` resolve refs in-process against the **live page origin**; responses report `vault.ref` and length, **not** the secret.
- Origin match is Chrome/Brave-style: exact host (plus `www` alias). Substring URL matching is rejected (phishing). HTTPS-saved logins never fill on HTTP.
- Store lives under `WICK_HOME/vault` (`0700`); master key `0600` or `WICK_VAULT_KEY`.
- Audit log records actions with redacted refs only.

See [VAULT.md](VAULT.md). Combine with shields + session isolation for the Brave-inspired stack — still **no** fingerprint farbling claim.

## Capability profiles (0.9)

`WICK_PROFILE=observe-only` / `safe-act` / `full-act` is enforced at the CLI and RPC layer. A read-only harness cannot fill passwords or eval JS even if a page (or a confused planner) asks it to.

`WICK_ALLOW_HOSTS` is an optional outbound allowlist for fetch/goto/login.

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

Wick does **not** provide Brave-class fingerprint farbling (canvas / WebGL / audio) or Camoufox-class anti-bot. Those need specialized browser engines. `wick shields` and the docs state this clearly — treat shields as request filtering and isolation, not “undetectable browsing.”

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
