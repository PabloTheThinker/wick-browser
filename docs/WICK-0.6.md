# Wick 0.6.1 — plan, ask, and a smoother act path

Short release notes. Baseline command map lives in [WICK-0.5.md](WICK-0.5.md); agent workflow in [AGENT-BROWSER.md](AGENT-BROWSER.md).

## New commands

### `wick plan URL [--fast]`

Snap the page, then emit goal-agnostic `suggestions[]` — each with a ready-to-run `cmd` and a `why`. Covers reading the full page, listing links, clicking top element hints, screenshots, PDF, and follow-up `ask` queries. `--click-limit N` caps click suggestions (default 3).

### `wick ask URL --q "terms" [--fast]`

Snap plus deterministic fuzzy filter. Query words (2+ chars) match as case-insensitive substrings against link text/href, element name/role/hint, and the excerpt. Returns only matching `links[]` / `elements[]` (score-sorted) and an `excerpt_score`. No LLM in the loop.

Both print the standard one-object JSON contract, honor `--fail-http`, and record history entries.

## Act improvements (Chromium path)

- **`role=` selectors resolve natively.** `wick act click`, `fill`, and `hover` now accept `role=ROLE[name="…"]` — the exact `hint` strings produced by `snap` / `plan` / `ask` / `elements` — translated to Playwright `get_by_role`. CSS and `text=` selectors are unchanged.
- **New `wait_url` action.** `wick act wait_url FRAGMENT [timeout_ms]` blocks until the page URL contains the fragment (default 30000ms). Use it to confirm a navigation after a click.

## Defaults

- `wick open` default `--wait-ms` dropped from 2000 to 1500. `snap` / `plan` / `ask` keep 2000 (or `--fast` for `domcontentloaded` + ~1.2s).

## Recommended loop (0.6.1)

```bash
wick snap https://example.com/ --fast
wick plan https://example.com/ --fast
wick ask  https://example.com/ --q "more information"
wick act  click 'role=link[name="More information"]'
wick act  wait_url "example.com" 15000
```

## Compatibility

- No breaking changes: all 0.6.0 commands, flags, and JSON fields are unchanged.
- Playbooks (`wick run`) are unchanged; `plan` / `ask` are interactive-loop tools — feed their output into your next playbook. Unknown playbook actions remain soft-ignored.
