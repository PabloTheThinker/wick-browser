# Agent Browser Needs in 2026 (Wick Deep Dive)

This document is a research-grade product/engineering brief for Wick, grounded in the current CLI surface (`snap`, `plan`, `ask`, `act`, `session`, `shields`) and aligned with 2026 agent-browser direction.

Scope constraints for this doc:
- Examples use `https://example.com/` only.
- No credentials, no private endpoints, no secrets.
- Focus is Wick as an agent-first CLI, not a human GUI browser.

---

## 0) Status as of 0.9 (this branch)

Shipped since this brief was written: origin-bound vault + `act login`, ephemeral sessions, capability profiles, `WICK_ALLOW_HOSTS` + **`WICK_BLOCK_HOSTS` (deny wins)**, unified SSRF on both engines, `untrusted_content` on observe, `wick tools` + `wick rpc stdio`, `wick mcp` (Hermes / Claude / Cursor), snapshot profiles (`micro|default|full`), parallel `snap-many`, snap `timing` breakdowns, computer-use (`cu` / `click_n` / `click_xy` / `type`), structured action errors, `--expect-url-fragment` / `--expect-element`, harness **`wick approve`** for login/fill/passkey, and **vault-backed passkeys** via Chromium's CDP virtual authenticator. Chromium fixture tests drive a local page through `cu` → `type_n` → `click_n` → `wait_text` and a localhost WebAuthn assert.

Still open from the original P0/P1 list: `shields --policy` as a file-shaped overlay on the env lists. Independent crypto audit is **not** claimed.

## 1) Where Wick Stands Today (0.6.1 Baseline)

Wick already matches several core 2026 expectations:
- **Accessibility-ish targeting over pixels:** `snap` + `elements` derive actionable `role=...` hints from semantic tree output; `act click/fill/hover` consume those hints.
- **Token-aware observe path:** `snap` gives compact title/excerpt/links/elements; `ask` filters deterministically without LLM calls.
- **Action primitives exist:** `act` includes `click`, `fill`, `scroll`, `wait_url`, plus tabs/PDF/screenshot.
- **Session isolation exists:** `WICK_SESSION` maps to per-session cookie jars and Chromium profile/download dirs.
- **Security posture is explicit:** loopback CDP, private-network blocking on light path, shields honesty, proxy redaction in command tails.
- **Speed primitives exist:** `--fast`, `batch`, HTTP cache, light-vs-heavy engine split.

Wick is already directionally correct. The remaining work for 0.7 is about reliability, guardrails, and integration ergonomics.

---

## 2) 2026 Industry Direction and What It Implies for Wick

## 2.1 Accessibility-tree targeting vs screenshots

2026 trend:
- Agent stacks increasingly treat screenshots as fallback, not primary input.
- Reliable control comes from accessibility/semantic targets (`role`, `name`, state), then visual confirmation only when needed.

Why this wins:
- Lower token and latency cost than vision-first loops.
- Better determinism for click/fill targeting and replay.
- Better explainability in logs/tool outputs.

Wick now:
- Strong first step: semantic tree parsing to interactive elements and `role=...` hints.
- Current limits: selector confidence is implicit, and post-action verification is mostly caller-managed.

Needed:
- Confidence-ranked element targets and optional disambiguation metadata.
- Built-in post-condition actions (`wait_url`, `wait_for_element_state`) as first-class plan suggestions.

---

## 2.2 Token-cheap observe snapshots

2026 trend:
- Agent loops optimize every observation step (short structured JSON, stable fields, deterministic truncation).
- Full markdown/HTML dumps are used on demand, not by default.

Wick now:
- `snap` is compact and useful; `ask` avoids LLM usage.
- `snap` still computes markdown + tree in a single gather path, and payload shaping is fixed (except `--full`).

Needed:
- Snapshot levels (`micro`, `default`, `full`) with hard token budgets and field guarantees.
- Optional hash/delta markers so harnesses can skip repeated context.

---

## 2.3 Act primitives (`click/type/scroll/wait_url`)

2026 trend:
- Primitive sets stay small, but reliability semantics become richer.
- Systems favor idempotent retries, clear failure classes, and post-action checks.

Wick now:
- Primitives exist and are straightforward.
- `wait_url` is a good navigation guard.
- Errors are generic (`action_failed`) with truncated detail; retryability is not explicit.

Needed:
- Structured action failure taxonomy (`timeout`, `not_found`, `not_interactable`, `navigation_blocked`).
- Optional `act ... --expect-url-fragment` and `--expect-element` inline guards.
- Safer defaults for race-prone actions (retry windows, stabilized waits).

---

## 2.4 Session/login isolation

2026 trend:
- Agent systems isolate auth context per task, often ephemeral-by-default with explicit promotion.
- Cross-task cookie/profile bleed is treated as a major risk.

Wick now:
- Per-session cookie jar and Chromium user-data-dir are present.
- Session lifecycle is manual (`new/use/save/path`) and persistent by default.

Needed:
- Ephemeral session mode (auto-delete on completion unless promoted).
- Session lock metadata (created_at, ttl, owner tag) for safer multi-agent use.
- Explicit export/import controls that redact sensitive fields by default.

---

## 2.5 Security (prompt injection, SSRF, CDP loopback, credential isolation)

2026 threat posture:
- Page content is untrusted input that can attempt prompt injection.
- Browser tooling can be abused for SSRF, local service probing, and credential exfiltration.
- Loopback-only control planes (CDP, RPC) are mandatory but not sufficient.

Wick now:
- Private-network block exists for light path.
- CDP binds 127.0.0.1.
- Proxy credentials are intentionally redacted in command-tail error paths.

Remaining gaps:
- No first-class prompt-injection annotation/sanitization policy in `snap`/`ask` output.
- SSRF controls are weaker on Chromium action path than on Lightpanda fetch path.
- No capability scoping model for which actions are allowed in a given run.

Needed:
- Content trust metadata in observation outputs (for harness policy).
- Optional outbound allowlist policy (host/domain regex) for both engines.
- Capability profiles (`observe-only`, `observe+safe-act`, `full-act`) enforced at CLI/runtime.

---

## 2.6 Speed (batch, cache, fast waits, parallel observe)

2026 trend:
- Throughput matters more than single-call speed: multi-page parallel observe, deterministic cache behavior, and bounded waits.

Wick now:
- Has `batch`, `http-cache-dir`, and `--fast`.
- No explicit parallel observe orchestration primitive beyond multi-URL fetch in one process.

Needed:
- Parallel `snap`/`ask` for URL lists with bounded concurrency.
- Cache mode controls (`off`, `read-through`, `stale-ok`) surfaced in agent-facing commands.
- Stable per-step timing breakdowns for harness optimization.

---

## 2.7 Agent harness integration (JSON tool schemas, JSON-RPC/stdio)

2026 trend:
- Agent tools are consumed through schema-driven interfaces (tool schemas, MCP/JSON-RPC over stdio).
- CLI wrappers remain useful, but direct RPC transport improves reliability and composability.

Wick now:
- Excellent one-object JSON CLI contract.
- No native schema export and no stdio JSON-RPC service mode.

Needed:
- Machine-readable tool schema endpoint/export.
- `wick rpc stdio` mode exposing a stable RPC surface for `snap/plan/ask/act/session`.
- Versioned response envelopes for backward-compatible evolution.

---

## 3) Wick 0.7 Proposal (Concrete, Ranked)

## P0 (must-have for 0.7)

### P0-1: Snapshot Profiles + Budgeted Output
Goal:
- Add `snap --profile micro|default|full` with hard field budgets and deterministic truncation.

Why:
- Reduces token cost and improves harness predictability.

CLI impact:
- New flags on `snap`, shared with `plan`/`ask` where relevant.

Primary file touches:
- `bin/wick` (argparse + `_gather_snap` output shaping).
- `tests/test_wick_cli.py` (profile behavior and truncation tests).
- `docs/AGENT-BROWSER.md` (updated loop and profile guidance).

---

### P0-2: Action Reliability Guards
Goal:
- Add optional inline expectations to `act` actions:
  - `--expect-url-fragment`
  - `--expect-element role=...|css=...`
  - structured error codes.

Why:
- Most flaky agent failures happen after apparently successful clicks/fills.

CLI impact:
- Backward compatible: old calls still work.

Primary file touches:
- `lib/chrome_actions.py` (expectation checks and failure taxonomy).
- `bin/wick` (`act` argument parsing and pass-through).
- `tests/test_wick_cli.py` (argument acceptance and error shape tests).
- `docs/WICK-0.6.md` or new `docs/WICK-0.7.md` (release notes).

---

### P0-3: Unified SSRF/Outbound Policy Across Engines
Goal:
- Enforce shared allow/deny policy for both light fetch and Chromium actions.

Why:
- Current strongest SSRF controls are concentrated in light path; heavy path should match policy.

CLI impact:
- Add optional global policy env/flags, for example:
  - `WICK_ALLOW_HOSTS`
  - `WICK_BLOCK_HOSTS`
  - `wick shields --policy`

Primary file touches:
- `lib/shields.py` (policy parser/helpers).
- `bin/wick` (policy wiring for `lp_fetch` and Chromium startup/action calls).
- `lib/chrome_actions.py` (pre-action URL checks where applicable).
- `docs/SECURITY.md` (threat model and policy examples).
- `tests/test_wick_cli.py` (policy enforcement tests).

---

### P0-4: JSON Tool Schema Export + Stdio RPC Mode
Goal:
- Add:
  - `wick schema` (machine-readable tool definitions),
  - `wick rpc stdio` (JSON-RPC methods for `snap/plan/ask/act/session/shields/status`).

Why:
- Removes fragile CLI parsing wrappers in agent harnesses.

CLI impact:
- New subcommands only; no breaking changes.

Primary file touches:
- `bin/wick` (new subcommands and method routing).
- `lib/` new module, e.g. `lib/rpc_stdio.py` (RPC loop, method handlers, validation).
- `docs/AGENT-BROWSER.md` (integration section).
- `docs/AGENT-BROWSER-NEEDS-2026.md` (this doc can later link to shipped design).
- `tests/` new RPC tests (e.g. `tests/test_rpc_stdio.py`).

---

## P1 (high-value follow-ups)

### P1-1: Ephemeral Sessions + Promote Flow
Goal:
- `wick session new <name> --ephemeral` and `wick session promote <name>`.

Why:
- Safer default for one-off agent jobs and CI runs.

Primary file touches:
- `bin/wick` (`session` subcommands/flags).
- `lib/shields.py` (session metadata + cleanup helpers).
- `docs/SECURITY.md`, `docs/AGENT-BROWSER.md`.
- `tests/test_wick_cli.py`.

---

### P1-2: Prompt-Injection Risk Signals in Observe Output
Goal:
- Add non-blocking risk annotations in `snap`/`ask` output (for harness policy), not autonomous filtering.

Why:
- Lets orchestrators apply guardrails without hiding raw page content.

Primary file touches:
- `bin/wick` (`_gather_snap` annotation stage).
- `lib/elements.py` (optional helper heuristics for suspicious instruction patterns).
- `docs/SECURITY.md` (how to treat untrusted content).
- `tests/test_elements.py` (heuristic scoring behavior).

---

### P1-3: Parallel Observe Command
Goal:
- New command for bounded-concurrency observe on multiple URLs, e.g. `wick snap-many`.

Why:
- Better throughput for agent planners than serial loops.

Primary file touches:
- `bin/wick` (new command + concurrency orchestration).
- `docs/AGENT-BROWSER.md` (parallel observe examples).
- `tests/test_wick_cli.py` (result shape and failure handling).

---

### P1-4: Performance Telemetry for Harness Feedback Loops
Goal:
- Standardize timing breakdown fields (fetch_ms, parse_ms, tree_ms, total_ms, cache_hit guess).

Why:
- Makes automatic wait/cache tuning possible in agent harnesses.

Primary file touches:
- `bin/wick` (timing fields from `lp_fetch`/`_gather_snap`).
- `docs/HEADLESS.md` (measurement guidance).
- `tests/test_wick_cli.py`.

---

## 4) Suggested 0.7 Delivery Sequence

1. **P0-1 + P0-2** first (token cost + action reliability).
2. **P0-3** next (security parity across engines).
3. **P0-4** after contract fields settle (avoid schema churn).
4. P1 features in this order: **ephemeral sessions**, **prompt-injection signals**, **parallel observe**, **telemetry enrichments**.

This order minimizes rework: schema/RPC should crystallize after core output and error envelopes stabilize.

---

## 5) Definition of Done for Wick 0.7

Minimum bar for release:
- All P0 features implemented with backward-compatible CLI behavior.
- Security docs updated with clear threat model and policy examples.
- Tests cover:
  - snapshot profile output budgets,
  - action expectation guards and structured errors,
  - unified outbound/SSRF policy enforcement,
  - schema export and basic stdio RPC flow.
- `example.com`-only examples for all new docs and tests that hit networked pages.

If these are met, Wick 0.7 becomes a stronger 2026-ready agent browser without abandoning its current lightweight CLI identity.
