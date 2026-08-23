# Wick as an agent browser

Wick 0.9 is built so agents can **observe → plan → ask → act** (and **login**) without a human GUI in the loop. One JSON surface. Two engines. No drama.

## Wick brothers

Think of Wick as two specialists that share a mission:

| Brother | Engine | Job |
|---------|--------|-----|
| **Light recon** | Lightpanda (default) | Fast fetch, markdown, semantic tree, `snap` / `plan` / `ask` / `elements`, shields |
| **Heavy contact** | Chromium (Playwright) | Clicks, fills, tabs, PDF, screenshots, downloads |

Recon stays cheap (~tens of MB). Contact lights only when the page must move. Agents should prefer recon until a `hint` or form forces Chromium.

```
Agent
  │
  ├─ observe  → snap / elements / open / tree   (light recon)
  ├─ plan     → wick plan   (suggested next actions)
  ├─ ask      → wick ask    (filter targets by query, no LLM)
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

## Plan — `wick plan` (new in 0.6.1)

Takes a snap and turns it into goal-agnostic `suggestions[]` — each with a ready-to-run `cmd` and a `why`:

```bash
wick plan https://example.com/ --fast
```

```json
{"action": "click", "cmd": "wick act click 'role=link[name=\"More information\"]'", "why": "interactive link: More information"}
```

Suggestions include reading the full page (`open`), listing links, clicking top element hints, `elements`, `screenshot`, `pdf`, and a follow-up `ask`. They are deliberately goal-agnostic: your planner picks the ones matching the task. `--click-limit N` caps click suggestions (default 3).

## Ask — `wick ask` (new in 0.6.1)

Snap plus a deterministic fuzzy filter — no LLM in the loop:

```bash
wick ask https://example.com/ --q "more information"
```

Query words (2+ chars) are matched as case-insensitive substrings against link text/href, element name/role/hint, and the excerpt. Output contains only the matching `links[]` and `elements[]` (score-sorted), plus `excerpt_score` so you know whether the body text is relevant at all.

## Elements — click targets

When you already know the page and only need targets:

```bash
wick elements https://example.com/
```

Same `hint` field as `snap`. Hints feed directly into `wick act click` (see below).

## Act — heavy contact

```bash
wick act goto https://example.com/
wick act click 'role=link[name="More information"]'
wick act fill "css=input[name=q]" "query"
wick act wait_url "example.com" 15000
wick act scroll down 1000
wick act pdf /tmp/out.pdf
```

New in 0.6.1:

- **`role=` selectors resolve natively.** `click`, `fill`, and `hover` accept `role=ROLE[name="…"]` — the exact `hint` strings from `snap` / `plan` / `ask` — and translate them to Playwright `get_by_role`. CSS and `text=` selectors keep working unchanged.
- **`wait_url FRAGMENT [timeout_ms]`** — block until the current URL contains the fragment (default 30000ms). The reliable way to follow a navigation triggered by a click.

New in 0.9:

- **`wick act login URL`** — Chrome/Brave-style autofill: match a vault entry to the page origin, fill username/password (and TOTP if present), optionally submit. Secrets never appear in JSON.
- **`wick vault suggest --url`** — agent-safe recipe (`refs` + form hints + `login_cmd`).
- Fill of `vault://` refs is **origin-bound** to the live page. Phishing URLs do not get the password.

### Computer use (0.9)

Vision + a11y hybrid, Claude/Operator-shaped:

```bash
wick act cu                    # screenshot + annotated numbered boxes + elements[]
wick act click_n 3             # click target n from the last cu
wick act click_xy 120 340      # or: wick act click 120 340
wick act type "hello"
wick act key Enter             # aliases: enter, tab, esc
wick act wait_text "Welcome"
```

`elements[].hint` is `xy=CX,CY`. `click_n` uses the last `cu` snapshot for this session. Action failures return structured classes (`timeout`, `not_found`, `not_interactable`) with `retryable`. Treat `cu` names as untrusted data.

After a click or login, pin the next page:

```bash
wick act click 'role=button[name="Log in"]' --expect-url-fragment "#ok"
wick act click 'role=button[name="Go"]' --expect-element 'css=#out'
```

A click that fires but does not reach the expected URL/element returns `expect_failed` (`retryable: true`).

Tabs, cookies, screenshots, and downloads live on this path. See [SHIELDS-AND-ACTIONS.md](SHIELDS-AND-ACTIONS.md) and [WICK-0.9.md](WICK-0.9.md).

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

Supported light actions: `open`, `fetch`, `probe`, `tree`, `links`. Chromium actions include `goto`, `click`, `fill`, `scroll`, `tab_*`, `pdf`, and most of the `act` surface. `plan` and `ask` are interactive-loop tools — run them between playbooks and feed their `suggestions[].cmd` / hints into the next playbook.

See [../examples/README.md](../examples/README.md), `examples/playbook.json`, and `examples/agent-loop.json`.

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

1. `wick snap URL --fast` — observe  
2. `wick plan URL --fast` — get candidate next actions  
3. `wick ask URL --q "terms"` — narrow to targets matching your goal  
4. `wick act …` — click / fill / `wait_url` on Chromium  
5. `wick run playbook.json` — batch the steps that repeat  

## Related docs

- [AGENTS.md](../AGENTS.md) — short agent brief  
- [WICK-0.6.md](WICK-0.6.md) — 0.6.1 release notes  
- [HEADLESS.md](HEADLESS.md) — engine model  
- [SECURITY.md](SECURITY.md) — CDP, shields honesty, `WICK_HOME`  
- [SHIELDS-AND-ACTIONS.md](SHIELDS-AND-ACTIONS.md) — privacy + act surface  
