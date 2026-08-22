# Wick for agents

Wick is a **browser for agents** — not a human GUI with an API bolted on.

**Wick brothers:** light recon (Lightpanda) for observe, heavy contact (Chromium) when you must click. One clean JSON surface. See [docs/AGENT-BROWSER.md](docs/AGENT-BROWSER.md).

## Recommended tool order

1. **`wick snap URL --fast`** — situation report (title, excerpt, links, interactive elements)  
2. **`wick elements URL`** — click targets with `hint` selectors  
3. **`wick open URL --fast`** — full markdown when you need the long read  
4. **`wick act …`** — Chromium when you must click, type, tab, PDF  
5. **`wick run playbook.json`** — multi-step jobs (unknown actions soft-ignored)  

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
- Use `--fail-http` in scripts to exit `2` on bad HTTP  

## `snap` (primary observe tool)

```bash
wick snap https://example.com/ --fast
```

Returns: `title`, `excerpt`, `links[]`, `elements[]` (interactive), timings.

```json
{"id": 12, "role": "link", "name": "More information", "hint": "role=link[name=\"More information\"]", "interactive": true}
```

Map `hint` to Playwright-style click on Chromium (or CSS from your planner).

## Act loop (Chromium)

```bash
wick act goto https://example.com/
wick act click "text=More information"
wick act fill "css=input[name=q]" "query"
wick act scroll down 1000
wick act pdf /tmp/out.pdf
```

## Sessions

```bash
wick session new job42
export WICK_SESSION=job42
wick snap https://example.com/
wick session save job42
```

## Shields

Network blocking on by default (`WICK_SHIELDS=1`). Not full fingerprint stealth.

## Speed

| Flag | Effect |
|------|--------|
| `--fast` | `domcontentloaded` + ~1.2s wait |
| default wait | 2000ms |
| `wick batch` | many URLs one process |

## Playbook

Unknown actions (`snap_note`, …) record `ok: false` with `soft: true` and **do not** fail the run.

See `examples/playbook.json` and `examples/agent-loop.json`.
