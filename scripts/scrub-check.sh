#!/usr/bin/env bash
# Fail if tree still contains private identifiers.
# Allows the public clone URL in README (owner + repo name).
# Allows public product names: Proton Pass / pass-cli / AgentMail (not house mail paths).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Split tokens so this script does not match the search.
pat1='pab''lo|vek''tra|yo''mu|dev''on'
# House paths + personal Proton Mail product surface (not "Proton Pass" the password manager)
pat2='/ho''me/ilo|par''allax|ilo-head''less|proton''mail|bridge\.p''roton'
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
