#!/usr/bin/env bash
# check-phone-ui.sh — run the phone layer's own checks and write evidence a watchdog can read.
#
# WHY THIS EXISTS
# Two phone UI defects reached the owner's phone on 2026-09-14 and neither was noticed by anything
# automatic: the composer doubled into two rows of controls whenever a session had usage, and an
# agent's question card could not be answered at all (Submit sat under the composer and a tap at its
# centre hit the composer instead). Both were found because the owner photographed them and said so.
# Both now have a check that fails on the old layer and passes on the fixed one:
#
#   scripts/phone-layout-check.py    the composer: one control band, no overflow, no clipping
#   scripts/question-card-check.py   the question card: fits the viewport, every control tappable
#
# This runs them and writes one JSON file whose `ok` is the conjunction. A watchdog only has to ask
# whether that file is fresh and whether `ok` is true — the same "absence is not health" rule the
# rest of this tree follows (L1, L2): a missing or stale evidence file is a refusal, not a pass.
#
# USAGE
#   scripts/check-phone-ui.sh                 # both checks, evidence to $PHONE_STATE/phone-ui.json
#   scripts/check-phone-ui.sh --quiet         # write evidence, print nothing
# The exit status is 0 only when both checks pass.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="${PHONE_STATE:-$HOME/.dsh-phone}"
mkdir -p "$STATE"
EVIDENCE="$STATE/phone-ui.json"
LOG="$STATE/phone-ui.log"
URL="${PHONE_URL:-http://127.0.0.1:3086/}"
QUIET=0
[ "${1:-}" = "--quiet" ] && QUIET=1

say() { [ "$QUIET" -eq 1 ] || echo "$@"; }

started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
note() { echo "$started $*" >>"$LOG"; }

if ! command -v google-chrome >/dev/null 2>&1 && ! command -v chromium >/dev/null 2>&1; then
  note "SKIP no chrome/chromium on this host (the checks drive a real browser)"
  python3 - "$EVIDENCE" "$started" <<'PY'
import json, sys
json.dump({"ok": None, "skipped": "no browser on this host", "at": sys.argv[2]}, open(sys.argv[1], "w"), indent=1)
PY
  exit 0
fi

composer_out="$(python3 "$HERE/phone-layout-check.py" --url "$URL" 2>&1)"
composer_rc=$?
card_out="$(python3 "$HERE/question-card-check.py" --app-url "$URL" 2>&1)"
card_rc=$?

composer_tail="$(printf '%s' "$composer_out" | tail -3 | tr '\n' ' ')"
card_tail="$(printf '%s' "$card_out" | tail -3 | tr '\n' ' ')"

python3 - "$EVIDENCE" "$started" "$composer_rc" "$card_rc" "$composer_tail" "$card_tail" <<'PY'
import json, sys
evidence, started, crc, krc, ctail, ktail = sys.argv[1:7]
ok = (int(crc) == 0 and int(krc) == 0)
json.dump({
    "ok": ok,
    # `at`, not `checked_at`: the consumers of this tree (plugin-attention's ageMinutes, and the
    # kernel's own readers) look for at/iso/ts. An evidence file whose stamp nothing recognises
    # reads as "age unknown" forever.
    "at": started,
    "composer": {"ok": int(crc) == 0, "summary": ctail.strip()},
    "question_card": {"ok": int(krc) == 0, "summary": ktail.strip()},
}, open(evidence, "w"), indent=1)
PY

if [ "$composer_rc" -ne 0 ] || [ "$card_rc" -ne 0 ]; then
  note "FAIL composer=$composer_rc card=$card_rc"
  say "phone UI checks FAILED"
  say "--- composer ---"; printf '%s\n' "$composer_out" | tail -8
  say "--- question card ---"; printf '%s\n' "$card_out" | tail -8
  exit 1
fi
note "PASS"
say "phone UI checks passed ($(date -u +%H:%MZ))"
exit 0
