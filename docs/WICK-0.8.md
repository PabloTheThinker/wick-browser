# Wick 0.8 — Vault + Brave stack + Proton Pass / AgentMail

## Headline

First-class **open-source password vault** for agents, combined with existing Brave-inspired shields and optional **Proton Pass** / **KeePassXC** / **AgentMail** secret backends.

## New

- `wick vault` — init, status, list, set, get, rm, match, gen, doctor, resolve
- Secret refs on `act fill` / `select` and playbooks: `vault://`, `pass://`, `env://`, `kdbx://`, `agentmail://`
- `lib/vault.py` — local encrypted store (no third-party crypto package required)
- Tool schema: `wick_vault`; `wick_act` documents secret refs
- RPC cmd: `vault`
- Docs: [VAULT.md](VAULT.md), SECURITY.md vault section

## Security contract

- List/status/match never print secrets
- Fill resolves refs in-process; JSON returns `vault.ref` + `chars` only
- Audit log under `~/.wick/vault/audit.jsonl` (redacted refs)
- `WICK_HOME/vault` mode `0700`, keys `0600`

## Compatibility

- 0.7 observe/act/session/shields unchanged
- VERSION `0.8.0`
