# Passkeys and AI agents

Wick can use passkeys the way Bitwarden / Proton Pass / 1Password do when the **password manager is the authenticator**. It cannot use platform biometrics or hardware keys.

## What an agent can do

1. Store a discoverable WebAuthn credential (rpId + P-256 PKCS#8) in the local vault.
2. On a matching HTTPS origin (or `localhost` / `127.0.0.1`), inject that credential into Chromium via CDP `WebAuthn.addVirtualAuthenticator` + `addCredential`.
3. Click the page's "Use passkey" control. Presence and user-verification are simulated (`UV=true`, `automaticPresenceSimulation`).

```bash
wick vault passkey-new demo --url https://example.com/login --username agent
wick vault match --url https://example.com/login
# → has_passkey, passkey_ref=vault://demo/passkey  (no private key)

wick act passkey https://example.com/login
# or: wick act login …  (tries passkey first, then password)

# After a real site's navigator.credentials.create:
wick act passkey_register https://example.com/login demo
```

The private key is written only into Chromium CDP. List / match / suggest / create JSON never include it. `vault://name/passkey` is **not** a fillable secret ref (`passkey_not_a_ref`).

## Origin bind

Same Chrome/Brave rules as passwords:

| Saved | Page | Allowed |
|-------|------|---------|
| `https://example.com/` | `https://example.com/login` | yes |
| `https://example.com/` | `https://evil.test/` | **no** |
| `https://example.com/` | `http://example.com/` | **no** (HTTPS-saved never on HTTP) |
| `http://127.0.0.1/…` | `http://127.0.0.1/…` | yes (localhost fixture) |

rpId must match the page host (`www` alias allowed). Grants (`wick vault grant --url`) apply to passkey export the same way they apply to password resolve.

## What an agent cannot do

- Press **Touch ID**, **Face ID**, or **Windows Hello**.
- Tap a **hardware security key** (YubiKey, Titan).
- Invent approval. If `WICK_REQUIRE_APPROVAL=1`, a human or outer harness must run `wick approve passkey` (or set `WICK_APPROVE`). Page text cannot mint that token.

## Honest limits

- This is a **virtual authenticator**, not a roaming hardware authenticator.
- Sites that require a specific device-bound attestation or a real platform authenticator will still fail.
- Independent crypto audit is **not** claimed.
