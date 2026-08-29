#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$ROOT/bin:$PATH"

wick doctor
wick open https://example.com/ --max 500
wick tree https://example.com/ --max 400
wick links https://example.com/
SMOKE_HOME="${WICK_HOME:-/tmp/wick-smoke-home}"
mkdir -p "$SMOKE_HOME/downloads"
export WICK_HOME="$SMOKE_HOME"
wick get https://example.com/ -o "$SMOKE_HOME/downloads/wick-smoke.html"
test -s "$SMOKE_HOME/downloads/wick-smoke.html"
echo SMOKE_OK
