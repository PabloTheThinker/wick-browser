# Wick as an agent browser

Wick is built so agents can **observe → decide → act** without a human GUI in the loop. One JSON surface. Two engines. No drama.

## Wick brothers

Think of Wick as two specialists that share a mission:

| Brother | Engine | Job |
|---------|--------|-----|
| **Light recon** | Lightpanda (default) | Fast fetch, markdown, semantic tree, `snap` / `elements`, shields |
| **Heavy contact** | Chromium (Playwright) | Clicks, fills, tabs, PDF, screenshots, downloads |

Recon stays cheap (~tens of MB). Contact lights only when the page must move. Agents should prefer recon until a `hint` or form forces Chromium.

```
Agent
  │
  ├─ observe  → snap / elements / open / tree   (light recon)
  ├─ decide   → pick hint / selector / next URL
  ├─ act      → wick act …                      (heavy contact)
  └─ batch    → wick run playbook.json
```

## Observe — `snap`

Primary situation report. Prefer this over dumping full markdown every turn.

```bash
wick snap https://example.com/ --fast
```

Returns one JSON object with:

- `title`, `excerpt`, `links[]`
- `elements[]` — interactive targets with `hint` selectors
- `http_ok`, timings (`ms`)

Example element:

```json
{"id": 12, "role": "link", "name": "More information", "hint": "role=link[name=\"More information\"]", "interactive": true}
```

Use `--fast` for agent loops (`domcontentloaded` + short wait).

## Elements — click targets

When you already know the page and only need targets:

```bash
wick elements https://example.com/
```

Same `hint` field as `snap`. On Chromium, map `hint` to Playwright-style click (or use CSS from your planner).

## Act — heavy contact

```bash
wick act goto https://example.com/
wick act click "text=More information"
wick act fill "css=input[name=q]" "query"
wick act scroll down 1000
wick act pdf /tmp/out.pdf
```

Tabs, cookies, screenshots, and downloads live on this path. See [SHIELDS-AND-ACTIONS.md](SHIELDS-AND-ACTIONS.md) and [WICK-0.5.md](WICK-0.5.md).

## Session

Isolated cookie jar + Chromium profile under `~/.wick/sessions/<name>/`.

```bash
wick session new job42
export WICK_SESSION=job42
wick snap https://example.com/
wick session save job42
```

Default session is `default`. Shields stay on unless `WICK_SHIELDS=0`.

## Playbook — `wick run`

Multi-step jobs as a JSON list. Known actions run; **unknown actions are soft-ignored** (`ok: false`, `soft: true`) so notes and future ops do not abort the whole run.

```bash
wick run examples/agent-loop.json
```

Supported light actions include `open`, `fetch`, `probe`, `tree`, `links`. Chromium actions include `goto`, `click`, `fill`, `scroll`, `tab_*`, `pdf`, and the rest of the `act` surface.

See `examples/playbook.json` and `examples/agent-loop.json`.

## JSON contract

Every command prints **one JSON object** (unless human help text).

```json
{
  "ok": true,
  "product": "wick",
  "http_ok": true,
  "url": "https://example.com/",
  "ms": 400
}
```

- `ok` — transport/parse succeeded  
- `http_ok` — HTTP status is 2xx/3xx  
- `--fail-http` — exit `2` on bad HTTP in scripts  

## Recommended loop

1. `wick snap URL --fast`  
2. `wick elements URL` (if you need a denser target list)  
3. `wick open URL --fast` (full markdown only when needed)  
4. `wick act …` (Chromium)  
5. `wick run playbook.json` (multi-step)  

## Related docs

- [AGENTS.md](../AGENTS.md) — short agent brief  
- [HEADLESS.md](HEADLESS.md) — engine model  
- [SECURITY.md](SECURITY.md) — CDP, shields honesty, `WICK_HOME`  
- [SHIELDS-AND-ACTIONS.md](SHIELDS-AND-ACTIONS.md) — privacy + act surface  
