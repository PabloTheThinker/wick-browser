# How headless works here

Wick's **standalone engine is Chromium** (Playwright). The Lightpanda notes below are historical / opt-in (`WICK_ENGINE=lightpanda`) only.

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
   ├─ read / links / tree / batch  → Lightpanda fetch (default)
   │     strip ui+invisible, wait-ms 3500, private nets blocked, disk cache
   │
   ├─ screenshot / complex form UI → Chromium headless-shell (on demand)
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
- Wick therefore uses **native `lightpanda fetch`** for the light path.  
- Chromium CDP remains the reliable shot/form session.

## Security defaults

- `--block-private-networks` on fetch  
- CDP **127.0.0.1 only**  
- Cookie jar under `~/.wick/cookies/` (local)  
- No Mozilla UA spoof (LP forbids it); we use `User-Agent-Suffix: Wick/0.5`

## Commands mapped to engine features

| Wick | Lightpanda |
|------|------------|
| `open` / `fetch` | `fetch --dump markdown --json` + strip/cache/wait |
| `tree` | `fetch --dump semantic_tree_text` |
| `batch a b c` | `fetch a b c --json` (one process) |
| `links` | markdown dump + parse |
| `ensure` / `start` | `serve --host 127.0.0.1 --port 9333` |
| `metrics` | `GET /metrics` on serve |
| `shot` / `goto` | Chromium Playwright daemon |

## What we deliberately don’t do

- Rewrite a Zig browser (years)  
- Vendor LP AGPL sources into MIT tree  
- Always-on full Chromium  
- Impersonate Chrome UA strings LP rejects  
