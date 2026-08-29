# Wick playbook examples

Run any file with:

```bash
wick run examples/playbook.json
wick run examples/agent-loop.json
```

A playbook is a JSON list of steps. Known actions run; **unknown actions are soft-ignored** (`ok: false`, `soft: true`) and never abort the run. That is the note mechanism: JSON has no comments, so files here use `snap_note` steps to carry commentary inline.

## Files

- `playbook.json` — minimal light + Chromium mix: `open`, `links`, `goto`, tabs, PDF.
- `agent-loop.json` — the same shape with inline notes describing the snap → plan → ask → act flow.
- `hermes.yaml` — Hermes Agent MCP snippet (`wick mcp`, `WICK_PROFILE=safe-act`). Copy under `mcp_servers` in `~/.hermes/config.yaml`. See [docs/HERMES.md](../docs/HERMES.md).

## The plan-ask flow

`wick plan` and `wick ask` are interactive-loop tools that run **between** playbooks, not inside them:

```bash
wick snap https://example.com/ --fast                  # observe
wick plan https://example.com/ --fast                  # suggestions[] with ready-to-run cmd
wick ask  https://example.com/ --q "more information"  # filter targets by query, no LLM
```

Take a `hint` (e.g. `role=link[name="More information"]`) from their output and put it into a playbook `click` step, or run it directly:

```bash
wick act click 'role=link[name="More information"]'
wick act wait_url "example.com" 15000
```

## Supported playbook actions

- **Observe:** `open`, `fetch`, `probe`, `tree`, `links`, `snap`
- **Chromium:** `goto`, `click`, `click_xy`, `click_n`, `cu`, `type`, `type_n`, `key`, `fill`, `login`, `select`, `check`, `press`, `wait`, `wait_url`, `wait_text`, `eval`, `content`, `title`, `back`, `forward`, `reload`, `scroll`, `hover`, `pdf`, `screenshot`, `tab_new`, `tab_list`, `cookies`, `shot`
- **Sessions:** `session_new`, `session_save`, `session_drop`, `session_sweep`

Anything else is recorded as soft-ignored and the run continues.
