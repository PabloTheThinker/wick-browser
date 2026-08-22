#!/usr/bin/env bash
# Fail if tree still contains private identifiers.
# Allows the public clone URL in README (owner + repo name).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Split tokens so this script does not match the search.
pat1='pab''lo|vek''tra|yo''mu|dev''on'
pat2='/ho''me/ilo|par''allax|ilo-head''less|pro''ton'
owner="$(printf '%s%s' Pab loTheThinker)"
allow="github.com/${owner}/wick-browser"

hits="$(rg -ni "${pat1}|${pat2}" \
  --glob '!.venv/**' \
  --glob '!**/__pycache__/**' \
  --glob '!bin/lightpanda' \
  --glob '!scripts/scrub-check.sh' \
  -n . || true)"

bad="$(printf '%s\n' "$hits" | grep -viF "$allow" | grep -v '^$' || true)"
if [[ -n "$bad" ]]; then
  printf '%s\n' "$bad"
  exit 1
fi
echo CLEAN
