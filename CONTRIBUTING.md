# Contributing to Wick

Thanks for helping make a better free agent browser.

## Ground rules

1. **No secrets** — never commit API keys, cookies, proxy passwords, personal emails, or host paths like `/home/<you>`.
2. **No personal client data** — examples use `example.com` only.
3. **License** — orchestration stays MIT. Do not vendor Chromium/Playwright sources; invoke the installed browser only.
4. **CDP** — keep default bind on loopback (`127.0.0.1`).
5. **No binaries** — do not commit Chromium binaries; use `make install` / `wick install-engine`.

## Dev setup

```bash
make install
wick install-engine    # Playwright Chromium
make smoke
make scrub-check
```

## Pull requests

- Small, focused diffs preferred  
- Update docs when commands change  
- Run `make test` (pytest), `make smoke`, and `make scrub-check` before push
- Describe security impact if touching shields, proxy, or downloads  

## Code layout

- `bin/wick` — CLI  
- `lib/` — engines, shields, history, Chromium actions  
- `docs/` — design notes (see `docs/SECURITY.md`)  
- `examples/` — sample playbooks  
