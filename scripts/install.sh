#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$HOME/.local/bin" "$HOME/.wick"/{engines,shots,logs,state,shields,sessions,downloads,vault}


chmod +x "$ROOT/bin/wick"
ln -sfn "$ROOT/bin/wick" "$HOME/.local/bin/wick"

# Python venv + Playwright (Chromium path for shots/forms)
# cryptography is required by the vault (wickvault2 = AES-256-GCM + HKDF);
# argon2-cffi is optional and only used for WICK_VAULT_PASSPHRASE (else scrypt).
if [[ ! -x "$ROOT/.venv/bin/python3" ]]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" -q install -U pip
  "$ROOT/.venv/bin/pip" -q install playwright cryptography
  "$ROOT/.venv/bin/pip" -q install argon2-cffi || true
  "$ROOT/.venv/bin/playwright" install chromium || \
    "$ROOT/.venv/bin/playwright" install --only-shell chromium || true
else
  "$ROOT/.venv/bin/pip" -q install cryptography || true
fi

# The CLI and tests also run under the system interpreter.
python3 -c 'import cryptography' 2>/dev/null || \
  python3 -m pip install --user cryptography || \
  echo "warn: install 'cryptography' for the vault (wick vault doctor reports aead_aes_256_gcm)"

# Optional Lightpanda engine
if [[ ! -x "$ROOT/bin/lightpanda" && ! -x "$HOME/.wick/engines/lightpanda" ]]; then
  echo "Optional: install Lightpanda engine with:  wick install-engine"
fi

echo "installed: $(command -v wick || echo "$HOME/.local/bin/wick")"
"$HOME/.local/bin/wick" doctor || true
echo "try: wick open https://example.com/"
