# Wick

**The agent browser.** Fast. Precise. Professional.

Not a human browser with a side door for bots — a tool built so **agents** can see the page, pick a target, and finish the job. Headless by default. Full enough when the work gets close: tabs, forms, PDF, downloads, sessions, shields.

*Wick brothers: light recon + heavy contact — one mission, clean tools, no wasted motion.*

```bash
wick snap https://example.com/ --profile micro         # cheapest observe (tree only)
wick plan https://example.com/ --fast                  # suggested next actions (cmd + why)
wick ask  https://example.com/ --q "more information"  # filter targets by query — no LLM
wick act  click 'role=link[name="More information"]'   # act: hints resolve directly
```

**Agents:** start with [AGENTS.md](AGENTS.md). Hermes / Claude / ChatGPT / Grok: [docs/HERMES.md](docs/HERMES.md).

## Why Wick

| Need | Wick |
|------|------|
| Agent-friendly page text | Markdown / semantic tree (Lightpanda) |
| Next-step planning | `plan` (goal-agnostic suggestions), `ask` (fuzzy target filter, no LLM) |
| Less RAM than always-on Chrome | Lightpanda ~tens of MB; Chromium on demand |
| Tracker / ad blocking | EasyList + EasyPrivacy + Fanboy + custom URL blocks |
| Sessions | Isolated cookie jars + Chromium profiles |
| Credentials | Origin-bound vault + `wick act login` (Chrome/Brave-style autofill; Proton Pass / KeePassXC refs) |
| Automation | `act`, multi-tab, PDF, playbooks (`run`) |
| Cost | **MIT orchestration · no paid API required** |

## Honest security scope

Wick aims for **Brave-like network privacy** (list blocking, SSRF guard, privacy headers, session isolation) plus an **open-source agent password vault** (local store, Proton Pass / KeePassXC / AgentMail refs).

It does **not** claim Brave fingerprint farbling (canvas/WebGL) or Camoufox-class anti-bot. Those need specialized engines. See [docs/SECURITY.md](docs/SECURITY.md), [docs/VAULT.md](docs/VAULT.md), and [docs/SHIELDS-AND-ACTIONS.md](docs/SHIELDS-AND-ACTIONS.md).

CDP stays on **loopback** by default. Proxy credentials and vault secrets are never logged. State under `WICK_HOME` is created mode `0700`.

## Install

**Requirements:** Linux x86_64 (primary), Python 3.10+, curl. Optional: [Lightpanda](https://github.com/lightpanda-io/browser) for the fast path.

```bash
git clone https://github.com/PabloTheThinker/wick-browser.git
cd wick-browser
make install                 # or ./scripts/install.sh
wick install-engine          # optional Lightpanda nightly
make doctor
wick open https://example.com/
```

Data directory: `~/.wick/` (override with `WICK_HOME`).

## Quick commands

```bash
# Observe & plan (Lightpanda — light recon)
wick ensure
wick snap URL --profile micro # cheapest situation report (tree only)
wick snap URL --fast          # tree + excerpt in parallel
wick snap-many URL URL…       # parallel observe
wick plan URL --fast          # suggested next actions
wick ask URL --q "terms"      # filter links/elements by query
wick elements URL             # interactive hints
wick open URL                 # full markdown
wick mcp                      # MCP stdio (Hermes, Claude, Cursor)
wick tools                    # OpenAI tools[] (ChatGPT, Grok)
wick rpc stdio                # JSON-lines RPC
wick tree URL                 # semantic tree
wick batch URL URL…           # multi-fetch
wick links URL --limit 20
wick probe URL --tree

# Shields & sessions
wick shields [--update]
wick shields --policy              # effective allow/deny + harness knobs
wick session new myjob
WICK_SESSION=myjob wick open URL
wick session save myjob
wick session export myjob          # cookie names/domains only
# wick session export myjob --reveal --out /tmp/sess.json   # values, 0600, full-act

# Vault (passwords without leaking into agent context)
wick vault init
wick vault set mysite --username me --password '…' --url https://example.com/login
wick vault suggest --url https://example.com/login
wick act login https://example.com/login
wick act login https://example.com/login --after-challenge 15000   # wait until widget gone, then fill
wick challenge https://github.com/login                            # observe-only detect; never login
WICK_VAULT_PASSPHRASE='…' wick vault harden                        # delete standing master.key
WICK_VAULT_BACKUP_PASSPHRASE='…' wick vault backup /tmp/wick-vault.bak
wick vault audit
# or: wick act fill 'css=input[type=password]' 'vault://mysite/password'

# Act (Chromium — heavy contact)
wick act goto URL
wick act click 'role=link[name="More information"]'   # role= hints from snap/plan/ask
wick act click "css=button.submit"
wick act fill "css=input[name=q]" "hello"
wick act cu                                           # screenshot + numbered targets
wick act click_n 3                                    # or click_xy 120 340
wick act type "hello"
wick act wait_url "fragment" 15000                    # wait for navigation
wick tabs new --url URL
wick tabs list
wick pdf --url URL -o out.pdf
wick get URL -o file.bin

# Playbooks & ops
wick run examples/playbook.json
wick history
wick metrics
wick doctor | version | status
```

## Engines

| Engine | Role | Port (loopback) |
|--------|------|------------------|
| **Lightpanda** (default) | Fetch, markdown, tree, shields | `9333` |
| **Chromium** (Playwright) | Clicks, tabs, PDF, screenshots | `9222` |

Lightpanda is **AGPL** third-party software invoked as an external binary — not vendored into this MIT repo. Chromium comes via Playwright into a local venv.

## Configuration (env)

| Variable | Default | Meaning |
|----------|---------|---------|
| `WICK_HOME` | `~/.wick` | State root (`0700`) |
| `WICK_SHIELDS` | `1` | Ad/tracker blocking |
| `WICK_SESSION` | `default` | Cookie + Chrome profile name |
| `WICK_HISTORY` | `1` | JSONL history |
| `WICK_PROXY` / `HTTPS_PROXY` | — | HTTP(S) proxy (creds never logged) |
| `WICK_PRIVACY_HEADERS` | `1` | DNT / Sec-GPC / Referrer-Policy |
| `WICK_OBSERVE_CACHE` | `1` | Reuse snap gather for ~8s (plan/ask) |
| `WICK_SNAP_PROFILE` | `default` | Observe budget when `--profile` is omitted (`micro`/`default`/`full`) |
| `WICK_VAULT_REQUIRE_ORIGIN` | `1` | Refuse fill for entries with no saved URL |
| `WICK_ALLOW_PRIVATE` | `0` | Allow localhost / RFC1918 fetches |
| `WICK_PROFILE` | `full-act` | `observe-only` / `safe-act` / `full-act` |
| `WICK_ALLOW_HOSTS` | — | Comma-separated host allowlist (`.suffix` ok) |
| `WICK_BLOCK_HOSTS` | — | Comma-separated host denylist (deny wins) |
| `WICK_REQUIRE_APPROVAL` | — | Require `wick approve` / `WICK_APPROVE` for login/fill/passkey |
| `WICK_APPROVE` | — | Harness-granted actions (`login`, `passkey`, `*`) |
| `WICK_POLICY` | `$WICK_HOME/policy.json` | Policy file: host allow/deny, profile, approvals, vault grant (env wins; deny unions) |
| `WICK_VAULT_REQUIRE_GRANT` | `0` | Deny vault resolve/fill unless `wick vault grant --url` is active |
| `WICK_VAULT_STRICT` | `0` | Grant-required **and** relock after fill (standing file keys stay off the fill path) |
| `WICK_HALT_ON_CHALLENGE` | `1` | Halt vault login/secret fill/passkey on a CAPTCHA/bot-wall |
| `WICK_CHALLENGE_COMPUTER_USE` | `0` | Allow `cu` / click / type on a challenge (desktop Hermes / Grokbot). Secrets stay blocked. Auto-on when headed or an XDG user seat. |
| `WICK_WEBRTC_IP_GUARD` | `1` | Chromium: no LAN ICE candidates |
| `WICK_REDUCE_CLIENT_HINTS` | `1` | Drop User-Agent Client Hints (privacy, not UA spoof) |
| `WICK_PASSKEY_REQUIRE_HSM` | `0` | Refuse passkey create unless a TPM/PKCS#11 token is present |
| `WICK_SESSION_AUTO_DROP` | `0` | Drop ephemeral session on process exit |
| `WICK_LP_PORT` | `9333` | Lightpanda CDP |
| `WICK_CHROME_PORT` | `9222` | Chromium CDP |

## Project layout

```
wick-browser/
  bin/wick           # CLI entrypoint
  lib/               # daemon, shields, vault, origins, login_form, chrome actions
  scripts/install.sh
  tests/smoke.sh
  docs/              # agent browser, security, headless, shields
  examples/          # sample playbooks
  Makefile
  ABOUT.md
  AGENTS.md          # agent brief
  LICENSE            # MIT (+ third-party engine note)
```

## Documentation

- [AGENTS.md](AGENTS.md) — **start here if you are an agent**
- [docs/HERMES.md](docs/HERMES.md) — Hermes, Claude, ChatGPT, Grok (MCP + tools)
- [docs/AGENT-BROWSER.md](docs/AGENT-BROWSER.md) — observe / act / session / playbook architecture  
- [ABOUT.md](ABOUT.md) — product story & non-goals  
- [docs/SECURITY.md](docs/SECURITY.md) — CDP, shields honesty, proxy, `WICK_HOME`  
- [docs/HEADLESS.md](docs/HEADLESS.md) — how headless works here  
- [docs/SHIELDS-AND-ACTIONS.md](docs/SHIELDS-AND-ACTIONS.md) — privacy + act surface  
- [docs/WICK-0.9.md](docs/WICK-0.9.md) — 0.9 agent login + origin-bound vault  
- [docs/PASSKEYS.md](docs/PASSKEYS.md) — vault-backed WebAuthn for agents  
- [docs/VAULT.md](docs/VAULT.md) — refs, wickvault2, grant/lock
- [docs/WICK-0.6.md](docs/WICK-0.6.md) — 0.6.1 release notes  
- [docs/WICK-0.5.md](docs/WICK-0.5.md) — full command map  

## License

MIT for Wick orchestration. Optional Lightpanda engine is AGPL — see [LICENSE](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Run `make scrub-check` before opening PRs.
