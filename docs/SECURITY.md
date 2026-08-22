# Security notes

Honest, scoped defaults — not a marketing checklist.

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

## `WICK_HOME` permissions

Default state root: `~/.wick` (override with `WICK_HOME`).

On `ensure` / first use, Wick creates this tree and sets the home directory mode to **`0700`** so cookies, sessions, Chromium profiles, and cache stay private to the user.

Do not share `WICK_HOME` across untrusted users. Treat it like a browser profile directory.

## What Wick does not claim

- Full consumer-browser sandbox parity
- Guaranteed CAPTCHA / Cloudflare / bank anti-bot bypass
- Immunity to local malware that already runs as your user

See also [SHIELDS-AND-ACTIONS.md](SHIELDS-AND-ACTIONS.md) and [HEADLESS.md](HEADLESS.md).
