#!/usr/bin/env bash
set -euo pipefail

ANKI_APP="${ANKI_APP:-/Applications/Anki.app}"
ANKI_LAUNCHER="$ANKI_APP/Contents/MacOS/launcher"
ANKI_TEST_BASE="${ANKI_TEST_BASE:-$HOME/src/anki-dev}"

if [[ ! -x "$ANKI_LAUNCHER" ]]; then
  echo "Could not find Anki launcher at: $ANKI_LAUNCHER" >&2
  echo "Set ANKI_APP if Anki is installed elsewhere." >&2
  exit 1
fi

mkdir -p "$ANKI_TEST_BASE"
echo "Launching Anki with isolated base folder:"
echo "  $ANKI_TEST_BASE"

exec "$ANKI_LAUNCHER" -b "$ANKI_TEST_BASE"
