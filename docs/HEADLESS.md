# How headless works here (Wick × Lightpanda study)

## What “headless” means

A normal browser is **engine + compositor + chrome UI**.  
Headless drops the human surface and keeps:

1. **Network** (HTTP/TLS, cookies, redirects)  
2. **HTML parse → DOM**  
3. **JavaScript (V8)** so SPAs still render content into the DOM  
4. **Optional** accessibility / semantic tree  

It does **not** need GPU pixels unless you ask for a screenshot.

## Lightpanda model (external engine we invoke)

Built in **Zig** for machines, not a Chromium fork:

| Piece | Role |
|--------|------|
| No paint pipeline | Huge RAM/CPU win vs headless Chrome |
| V8 | Real JS for modern sites |
| CDP `serve` | Playwright/Puppeteer-shaped clients (coverage still growing) |
| `fetch --dump` | **Agent gold**: markdown / semantic_tree after JS |
| strip-mode | Drop ui/css/js noise before the model sees it |
| wait-until / wait-ms / wait-selector | Control “when is the page done?” |
| block-private-networks | SSRF guard for agent loops |
| http-cache-dir | Repeat reads cheap |
| metrics | Prometheus on serve |

Empirically on this host: **~20 MB RSS** serve, **~0.3–0.6 s** simple fetch, multi-URL batch in one process.

## Wick policy (our MIT layer)

```
Agent task
   │
   ├─ snap / plan / ask / open / tree / links
   │     Lightpanda fetch when the binary is present (default)
   │     else headless Chromium (same JSON: title, excerpt, role= hints)
   │
   ├─ screenshot / click / fill / forms → Chromium (on demand)
   │
   └─ never WAN-bind CDP; never paid browser SaaS required
```

### Dump choice (agent cost)

| Dump | When |
|------|------|
| `markdown` | Default reading / briefs |
| `semantic_tree_text` | Structure + roles without pixels (`wick tree`) |
| `semantic_tree` | Full JSON tree for tooling |
| `html` | Rare — only if you need raw DOM |

Screenshots are the **expensive** path; prefer tree/markdown first (LP docs + agent-browser pattern).

## CDP reality check

- LP `/json/version` works; Playwright `goto` over LP CDP still flaky on some sites.  
- Wick therefore uses **native `lightpanda fetch`** for the light path when the binary is present.  
- Without Lightpanda, `observe_fetch` drives headless Chromium and emits the same JSON (`engine: "chromium"`, `fallback: "chromium"`).  
- Chromium CDP remains the reliable shot/form session.

## Security defaults

- `--block-private-networks` on fetch  
- CDP **127.0.0.1 only**  
- Cookie jar under `~/.wick/cookies/` (local)  
- No Mozilla UA spoof (LP forbids it); we use `User-Agent-Suffix: Wick/0.5`

## Commands mapped to engine features

| Wick | Engine |
|------|--------|
| `snap` / `plan` / `ask` / `open` / `tree` / `links` / `batch` | Lightpanda `fetch` when present; else Chromium observe |
| `fetch` | Lightpanda only (`lightpanda_not_found` if absent) |
| `ensure` / `start` | Lightpanda `serve` on `127.0.0.1:9333` |
| `metrics` | `GET /metrics` on Lightpanda serve |
| `act` / `shot` / `goto` / `pdf` / `tabs` | Chromium Playwright daemon |

## What we deliberately don’t do

- Rewrite a Zig browser (years)  
- Vendor LP AGPL sources into MIT tree  
- Always-on full Chromium  
- Impersonate Chrome UA strings LP rejects  
