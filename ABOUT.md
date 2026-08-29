# Wick — the browser for agents

Wick is a free, open-source **agent browser**: a command-line tool built for AI agents that read the web constantly and touch it rarely. One clean JSON surface. Headless Chromium underneath — observe with `snap` / `plan` / `ask`, escalate to click, type, or render only when the page must move.

Everything runs on your machine. No cloud relay, no hosted session, no telemetry.

## Why an agent browser

A human browser optimizes for pixels. An agent needs structure: titles, excerpts, links, interactive elements with stable selectors, and honest metadata about what it's looking at. Bolting an API onto a GUI browser gets you HTML dumps and screenshot loops — token-expensive, slow, and flaky. Wick inverts the design. The primary output is compact JSON built for a model's context window; the full rendered browser is the escalation path, not the default.

## Who it's for

- Builders of local AI agents that **read** the web and occasionally **act** on it
- Harness and framework authors who want tool schemas and stdio RPC, not screen-scraping wrappers
- Operators who want session isolation and honest network guards without assembling a browser stack by hand

## The loop: observe → plan → ask → act

```bash
wick snap https://example.com/ --fast   # situation report: title, excerpt, links, elements
wick plan https://example.com/ --fast   # ranked next steps, each with a ready-to-run cmd
wick ask  https://example.com/ --q "terms"  # deterministic filter — no LLM call
wick act click 'role=link[name="More information"]'  # heavy contact, only when needed
```

`snap` returns interactive elements with `role=` hints that resolve natively to Playwright targets on the act path — the observation *is* the selector. `plan` turns a snapshot into goal-agnostic suggestions with runnable commands. `ask` filters links, elements, and excerpt by substring match, so cheap queries stay cheap. `act` drives real Chromium: click, fill, scroll, tabs, `wait_url` navigation guards, screenshots, PDF. `wick run playbook.json` chains it all into multi-step jobs where unknown actions fail soft instead of killing the run.

## Harness integration (0.7)

Wick 0.7 is built to be a tool, not a destination:

- **`wick tools`** — exports OpenAI-style `tools[]` schemas for `wick_snap`, `wick_plan`, `wick_ask`, `wick_open`, `wick_act`, `wick_session`, and `wick_elements`. Load them into your framework or MCP bridge directly.
- **`wick rpc stdio`** — JSON-lines RPC: one request per stdin line, one JSON response per line. Unknown commands return `ok: false` with `soft: true`, so a harness loop never dies on a bad call.
- **One-object JSON contract** — every command prints exactly one JSON object with `ok`, `http_ok`, `url`, and timing. `--fail-http` gives scripts a clean exit code on bad HTTP.

## Shields, stated honestly

Network blocking is on by default (`WICK_SHIELDS=1`): private-network fetch blocking, CDP bound to loopback only, and per-session Chromium profiles so tasks don't bleed into each other.

What Wick does **not** claim: fingerprint stealth, CAPTCHA bypass, or victory over serious anti-bot systems. Observe outputs are explicitly flagged `untrusted_content: true` with an injection warning — page text is data, never instructions. We label what the shields do and where they stop, because an agent operator making security decisions on marketing copy is a liability, not a customer.

## Speed

- `--fast` uses `domcontentloaded` plus a short settle wait across snap/plan/ask/open
- `wick batch` runs many URLs through one process
- Compact snapshots by design; Chromium stays up for a session so snap then act is cheap

## Non-goals

- **Not a human browser.** No GUI, no extensions, no Chrome replacement.
- **Not a stealth kit.** Shields block private-network probes and isolate sessions; they do not forge fingerprints or apply EasyList as Chromium filters.
- **Not a SaaS.** No hosted browsers, no accounts, no usage meters.
- **Not a framework.** Wick is the browsing layer. Your agent's brain, memory, and goals live in your stack.

## Versus the alternatives

**Browser-Use** couples browsing to a Python agent framework — capable, but you inherit its loop, its LLM plumbing, and its dependency graph. Wick is a standalone CLI with a JSON contract: any language, any framework, any harness that can spawn a process or speak stdio RPC. (Credit where due: Browser-Use's act/session shape was an inspiration.)

**Playwright** is the superior general automation library, and Wick uses it on the heavy path. But raw Playwright hands an agent a low-level API and no opinion: you build the observation format, the selector strategy, the token budgeting, and the security posture yourself, in every project. Wick ships those decisions as the product — semantic snapshots, `role=` hints that flow straight into actions, shields, and session isolation, behind seven tool schemas instead of a hundred API calls.

If you're choosing an agent browser in 2026, the question is not "can it drive a page" — everything can. The question is what an observation costs, whether selectors survive contact, and whether the security story is real. That's the ground Wick is built on.

## Where to go next

- [AGENTS.md](AGENTS.md) — the operating manual: full command surface, JSON contract, RPC examples
- [docs/AGENT-BROWSER-NEEDS-2026.md](docs/AGENT-BROWSER-NEEDS-2026.md) — the research brief behind 0.7: where agent browsers are heading and how Wick maps to it
- [docs/AGENT-BROWSER.md](docs/AGENT-BROWSER.md) — deeper usage guide

## Version and license

Public surface tracks **0.9**: observe + act + sessions + shields + **origin-bound vault** (Chrome/Brave-style autofill via `wick act login`, TOTP, Proton Pass/KeePassXC/AgentMail refs), plus `wick tools` and `wick rpc stdio`. MIT-licensed CLI; Chromium via Playwright. Contributions welcome.
