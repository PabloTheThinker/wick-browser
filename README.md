# Wick

**Free agent browser.** A thin flame for machines.

CLI for AI agents and scripts: a fast headless read path, optional Chromium for clicks/tabs/PDF/screenshots — no paid browser SaaS.

```bash
wick open https://example.com/
wick probe https://example.com/ --tree
wick act goto https://example.com/
wick pdf --url https://example.com/ -o page.pdf
```

## Why Wick

| Need | Wick |
|------|------|
| Agent-friendly page text | Markdown / semantic tree (Lightpanda) |
| Less RAM than always-on Chrome | Lightpanda ~tens of MB; Chromium on demand |
| Tracker / ad blocking | EasyList + EasyPrivacy + Fanboy + custom URL blocks |
| Sessions | Isolated cookie jars + Chromium profiles |
| Automation | `act`, multi-tab, PDF, playbooks (`run`) |
| Cost | **MIT orchestration · no paid API required** |

## Honest security scope

Wick aims for **Brave-like network privacy** (list blocking, SSRF guard, privacy headers, session isolation).

It does **not** claim Brave fingerprint farbling (canvas/WebGL) or Camoufox-class anti-bot. Those need specialized engines. See [docs/SECURITY.md](docs/SECURITY.md) and [docs/SHIELDS-AND-ACTIONS.md](docs/SHIELDS-AND-ACTIONS.md).

CDP stays on **loopback** by default. Proxy credentials are never logged. State under `WICK_HOME` is created mode `0700`.

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
# Read path (Lightpanda)
wick ensure
wick open URL                 # markdown
wick tree URL                 # semantic tree
wick batch URL URL…           # multi-fetch
wick links URL --limit 20
wick probe URL --tree

# Shields & sessions
wick shields [--update]
wick session new myjob
WICK_SESSION=myjob wick open URL
wick session save myjob

# Chromium path (forms, tabs, PDF)
wick act goto URL
wick act click "css=button.submit"
wick act fill "css=input[name=q]" "hello"
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
| `WICK_PRIVACY_HEADERS` | `1` | DNT / Sec-GPC |
| `WICK_LP_PORT` | `9333` | Lightpanda CDP |
| `WICK_CHROME_PORT` | `9222` | Chromium CDP |

## Project layout

```
wick-browser/
  bin/wick           # CLI entrypoint
  lib/               # daemon, shields, history, chrome actions
  scripts/install.sh
  tests/smoke.sh
  docs/              # security, headless model, shields, command map
  examples/          # sample playbooks
  Makefile
  ABOUT.md
  LICENSE            # MIT (+ third-party engine note)
```

## Documentation

- [ABOUT.md](ABOUT.md) — product story & non-goals  
- [docs/SECURITY.md](docs/SECURITY.md) — CDP, shields honesty, proxy, `WICK_HOME`  
- [docs/HEADLESS.md](docs/HEADLESS.md) — how headless works here  
- [docs/SHIELDS-AND-ACTIONS.md](docs/SHIELDS-AND-ACTIONS.md) — privacy + act surface  
- [docs/WICK-0.5.md](docs/WICK-0.5.md) — full command map  

## License

MIT for Wick orchestration. Optional Lightpanda engine is AGPL — see [LICENSE](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Run `make scrub-check` before opening PRs.
