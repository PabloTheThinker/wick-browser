# Wick 0.9 — Agent password manager + origin-bound login

## Headline

The vault now behaves like a human password manager for agents: **suggest** a login, **autofill** only on a matching origin, **never** put the secret in model context. Observe loops are faster. Chromium gets the same private-network / dangerous-URL guards as the light path.

## New

- `wick vault suggest --url` / `autofill` — recipe with refs, form hints, and `wick act login` (no secrets)
- `wick act login URL` — goto + origin-bound username/password/(otp) fill + submit
- Origin matching: exact host + `www` alias; optional `--allow-subdomains` on `vault set`
- HTTPS-saved credentials never fill on HTTP pages
- RFC 6238 TOTP: store `totp` / `otpauth://…`, fill `vault://name/otp`
- `javascript:` / `data:` / private-URL rejection on fetch and Chromium goto/login
- Short-TTL observe cache (default 8s) so snap → plan → ask does not triple-fetch
- Privacy headers: Referrer-Policy + Chromium DNT / Sec-GPC
- `plan` suggests `wick act login` when a password field is present
- Playbook action `login`
- Ephemeral sessions: `wick session new NAME --ephemeral --ttl 1800 --owner agent`
- `wick session promote` / `save` keeps cookies; `drop` / `sweep` deletes unpromoted TTL sessions
- Capability profiles: `WICK_PROFILE=observe-only|safe-act|full-act`
- Outbound allowlist: `WICK_ALLOW_HOSTS=example.com,.github.com`
- Computer use: `wick act cu` (screenshot + numbered a11y boxes), `click_xy` / `click_n`, `type` / `type_n`, `key`, `move` / `drag`, structured action errors
- Post-action guards: `wick act click … --expect-url-fragment welcome` / `--expect-element 'role=heading[name="Hi"]'`

## Security contract (additions)

- Substring URL matching is gone (that was a phishing bug)
- Vault refs resolve on the **live page origin**, not in the CLI before navigation
- Unbound local entries (no `--url`) refuse fill unless `WICK_VAULT_REQUIRE_ORIGIN=0`
- Private hosts blocked unless `WICK_ALLOW_PRIVATE=1`

## Compatibility

- 0.8 refs, list/status/match metadata shape kept; `match` now includes `score` / `reason` and may return fewer hits
- VERSION `0.9.0`

## Agent loop

```bash
wick vault set example --username me --url https://example.com/login
wick snap https://example.com/login --fast
wick vault suggest --url https://example.com/login
wick act login https://example.com/login
```

## Computer use

```bash
wick act goto https://example.com/
wick act cu
wick act click_n 1
wick act type "hello"
wick act key Enter
```

`cu` returns `screenshot`, `annotated` (numbered badges), and `elements[]` with `n` / `cx` / `cy`. Names are untrusted. `click_n` reads the last snapshot for the current session.
