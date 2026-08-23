# Wick Vault (0.8)

Open-source password manager **for agents**, wired into Brave-inspired shields and optional Proton Pass + AgentMail.

## Why this exists

Agent browsers that paste real passwords into tool JSON leak credentials into model context, logs, and session transcripts. Wick Vault keeps **refs** in the agent loop and injects secrets only on the Chromium fill path.

## Secret refs

| Ref | Backend | Example |
|-----|---------|---------|
| `vault://name/field` | Local encrypted store under `WICK_HOME/vault` | `vault://github/password` |
| `pass://Vault/Item/field` | Proton Pass CLI (`pass-cli`) agent tokens | `pass://Work/GitHub/password` |
| `env://VAR` | Process environment | `env://CI_BOT_PASSWORD` |
| `kdbx://Entry/field` | KeePassXC-CLI + `WICK_KDBX` | `kdbx://Web/GitHub/password` |
| `agentmail://token` | Alias → `vault://agentmail/token` | Bearer for proton-agent-mail |

Default field is `password` when omitted: `vault://github` → `vault://github/password`.

## CLI

```bash
wick vault init                          # create master.key (0600) + empty store
wick vault status                        # backends + Brave stack honesty
wick vault list                          # metadata only — never secrets
wick vault set github --username me --password '…' --url https://github.com/login
# safer set:
WICK_VAULT_SET_PASSWORD='…' wick vault set github --username me --url https://github.com/login

wick vault match --url https://github.com/login
wick vault get github                    # fields present, no values
wick vault gen --length 28               # generate (prints once)

# Agent login (secret never in agent JSON response)
wick act fill 'css=input[name=login]' 'vault://github/username'
wick act fill 'css=input[name=password]' 'vault://github/password'
wick act click 'css=button[type=submit]'
```

## Proton Pass + AgentMail

**Proton Pass** (official): create an AI agent token with scoped vault access and audit logging, install `pass-cli`, then fill with `pass://…` refs. See [Proton Pass developer features](https://proton.me/pass/developer-features).

**AgentMail / proton-agent-mail**: store the loopback bearer token once:

```bash
WICK_VAULT_SET_PASSWORD="$TOKEN" wick vault set agentmail/token --field token="$TOKEN"
# or:
wick vault set agentmail --field token="$TOKEN"
```

Agents request mail via the token-gated local API; Wick only holds the token as a ref (`agentmail://token`). Same compartment story as Bridge on `127.0.0.1`.

## Brave-inspired security stack

| Layer | Wick |
|-------|------|
| Tracker / ad lists | `wick shields` (EasyList / EasyPrivacy / Fanboy) |
| SSRF / private net | Lightpanda path block (default on) |
| Privacy headers | DNT / Sec-GPC |
| Session isolation | `WICK_SESSION` cookie jars + Chromium profiles |
| Credentials | **Vault refs** — not page cookies alone |
| Fingerprint farbling | **Not claimed** (needs Brave/Camoufox-class engine) |

Together: observe with shields, act in an isolated session, fill only via vault refs.

## Storage layout

```
~/.wick/vault/          # mode 0700
  master.key            # 0600 (or WICK_VAULT_KEY env)
  store.enc             # scrypt + stream + HMAC (wickvault1)
  audit.jsonl           # actions + redacted refs — never secret values
  config.json           # backend paths
  meta.json
```

## Agent rules

1. Prefer `wick vault list` / `match` — never `--reveal` in harnesses.
2. `wick act fill SELECTOR 'vault://…'` — response includes `vault.ref` + `chars`, not the password.
3. Playbooks: `"secret_ref": "vault://name/password"` or put the ref in `text` / `value`.
4. RPC: `{"cmd":"vault","args":{"action":"list"}}` for metadata; fill via `act`.

## Honest limits

- Local crypto is intentional and open (`lib/vault.py`) — not a drop-in for enterprise HSM.
- Proton Pass and KeePassXC require their CLIs on `PATH`.
- Does not replace 2FA / passkeys UX; TOTP can be stored as a field but Wick does not auto-submit WebAuthn.
- Page content remains untrusted (`observe_security` annotations).
