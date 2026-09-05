# How headless works here

## What “headless” means

A normal browser is **engine + compositor + chrome UI**.  
Headless drops the human surface and keeps:

1. **Network** (HTTP/TLS, cookies, redirects)  
2. **HTML parse → DOM**  
3. **JavaScript (V8)** so SPAs still render content into the DOM  
4. **Accessibility / semantic tree** for `role=` hints  
5. **Pixels** only when you ask (`cu`, screenshot, PDF)

## Wick policy

```
Agent task
   │
   ├─ search "query"
   │     plain HTTP SERP (DuckDuckGo HTML / lite, or Wikipedia)
   │     structured results — no Chromium, no pixels
   │
   ├─ snap / plan / ask / open / tree / links / fetch
   │     headless Chromium (Playwright daemon, loopback CDP)
   │
   ├─ click / fill / cu / tabs / PDF
   │     same Chromium session (pixels only for cu / shot / PDF)
   │
   └─ never WAN-bind CDP; never paid browser SaaS required
```

### Dump choice (agent cost)

| Dump | When |
|------|------|
| `markdown` | Default reading / briefs |
| `semantic_tree_text` | Structure + roles without pixels (`wick tree`, `snap --profile micro`) |
| `semantic_tree` | Full JSON tree for tooling |
| `html` | Rare — only if you need raw DOM |

Screenshots are the **expensive** path; prefer tree/markdown first.

## Security defaults

- Private-network fetches blocked unless `WICK_ALLOW_PRIVATE=1`  
- CDP **127.0.0.1 only**  
- Per-session Chromium profile under `~/.wick/sessions/<name>/`  
- Proxy credentials never logged  

## Commands

| Wick | Engine |
|------|--------|
| `search` | HTTP SERP (no Chromium). `--chromium` if the HTML interstitial wins |
| `snap` / `plan` / `ask` / `open` / `tree` / `links` / `batch` / `fetch` | Chromium when Playwright is present; static HTTP otherwise (`WICK_OBSERVE=http` to force) |
| `ensure` / `start` | Chromium daemon on `127.0.0.1:9222` |
| `metrics` | Chromium daemon status |
| `act` / `shot` / `goto` / `pdf` / `tabs` | Same Chromium session |

## What we deliberately don’t do

- Ship a second browser engine  
- Always-on headed Chrome  
- Claim fingerprint farbling or anti-bot stealth  
