#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$ROOT/bin:$PATH"

wick doctor
wick open https://example.com/ --max 500
wick tree https://example.com/ --max 400
wick links https://example.com/
wick get https://example.com/ -o /tmp/wick-smoke.html
test -s /tmp/wick-smoke.html
echo SMOKE_OK
