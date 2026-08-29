# Wick 0.4 — Shields + browser-class actions

## Honest security (vs Brave)

| Brave | Wick 0.4 |
|-------|----------|
| EasyList / EasyPrivacy style blocking | **Download only** — Chromium does not parse ABP lists |
| Tracker URL blocks | **Yes (small)** — built-in needles + `wick-block-urls.txt` aborted on Chromium routes |
| Private / internal net block | **Yes** — SSRF default |
| Fingerprint farbling (canvas/WebGL/audio) | **No** — needs engine-level patches (Brave/Camoufox). Wick states this in `wick shields` |
| HTTPS / first-party isolation | Session cookie jars (`wick session`) — not full site-isolation browser |
| Stealth anti-bot | Chromium: automation flags only. **Not** Camoufox/nodriver-class |

Wick optimizes for **agent safety + utility on a local machine**, not “undetectable scraper.”

## Browser-Use-like surface

| Capability | Command |
|------------|---------|
| Read page → markdown | `wick open` / `fetch` |
| Semantic tree | `wick tree` |
| Links | `wick links` |
| Batch tabs metaphor | `wick batch` |
| Compact brief | `wick probe` |
| Sessions / cookies | `wick session new\|save\|list\|export\|import` + `WICK_SESSION=` |
| Policy overlay | `wick shields --policy` / `WICK_POLICY` |
| Click / fill / goto | `wick act …` (Chromium) |
| Computer use | `wick act cu` then `click_n` / `click_xy` / `type` |
| Playbooks | `wick run playbook.json` |
| Screenshots | `wick open --shot` / `act` + shot |
| Shields status | `wick shields [--update]` |
| Disable shields | `WICK_SHIELDS=0` |

## Example playbook

```json
[
  {"action": "open", "url": "https://example.com/", "max": 2000},
  {"action": "links", "url": "https://example.com/"},
  {"action": "goto", "url": "https://example.com/"},
  {"action": "content", "max": 1000}
]
```

## Defaults

- Shields **on**
- Session **default** (override `WICK_SESSION`)
- Headless Chromium for observe and act


## 0.4.1 additions
- Fanboy social list + expanded tracker URL blocks (44 patterns)
- Privacy headers: DNT, Sec-GPC, Upgrade-Insecure-Requests
- `wick open --stats` → reports `stats_unavailable` (no Chromium request counters)
- `wick open --save-session` → persist cookies into session load
- Chromium init: hide `navigator.webdriver` + hardening flags


## 0.4.2 — more regular-browser
- `wick get URL` downloads into session folder (curl; `--browser` for Chromium)
- `WICK_PROXY` / `HTTPS_PROXY` → proxy env (credentials never logged)
- Per-session Chromium profile: `~/.wick/sessions/<name>/chrome-profile`
- Per-session downloads dir
- `wick shields-bench URL` reports `shields_bench_unavailable` (no Chromium request-count A/B)
