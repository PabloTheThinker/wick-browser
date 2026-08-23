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
