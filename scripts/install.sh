#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$HOME/.local/bin" "$HOME/.wick"/{engines,shots,logs,state,shields,sessions,downloads,vault}


chmod +x "$ROOT/bin/wick"
ln -sfn "$ROOT/bin/wick" "$HOME/.local/bin/wick"

# Python venv + Playwright (Chromium path for shots/forms)
if [[ ! -x "$ROOT/.venv/bin/python3" ]]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" -q install -U pip
  "$ROOT/.venv/bin/pip" -q install playwright
  "$ROOT/.venv/bin/playwright" install chromium || \
    "$ROOT/.venv/bin/playwright" install --only-shell chromium || true
fi

# Optional Lightpanda engine
if [[ ! -x "$ROOT/bin/lightpanda" && ! -x "$HOME/.wick/engines/lightpanda" ]]; then
  echo "Optional: install Lightpanda engine with:  wick install-engine"
fi

echo "installed: $(command -v wick || echo "$HOME/.local/bin/wick")"
"$HOME/.local/bin/wick" doctor || true
echo "try: wick open https://example.com/"
