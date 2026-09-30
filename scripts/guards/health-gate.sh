#!/usr/bin/env bash
# health-gate.sh -- tell THREE states apart: healthy, DEGRADED-BUT-SERVING, and not answering.
#
# WHY THIS EXISTS (journal P170 and P66, both verified live on 2026-09-30)
# ----------------------------------------------------------------------
# Every gate that decides whether production is up uses `curl -fsS <url>`. `-f` fails on an HTTP
# error status -- and this API answers **HTTP 200 with `ok:false`** when it is degraded (lock
# contention, a dead subsystem). So:
#
#   * a gate that trusts `-fsS` reads a degraded API as HEALTHY;
#   * a gate that treats any non-2xx as "did not start" cannot see degraded at all;
#   * and the measured overlap is not theoretical: 4,795 `database is locked` lines in seven days in
#     the API journal, with `/health` answering 200/`ok:true` in five consecutive probes when the
#     disk was quiet -- the same endpoint, two different states, one indistinguishable reading.
#
# That is the failure class the whole estate keeps re-learning (journal P3, P12, P58): a reading that
# cannot distinguish two states is not a reading. This file is the one place that decides, so nine
# gates cannot each decide differently.
#
# CONTRACT
#     health-gate.sh show    <url>            -> prints HEALTHY|DEGRADED|DOWN, exit 0|2|1
#     health-gate.sh require <url> [label]    -> prints "<label>: HEALTHY|DEGRADED|DOWN"; exit 0|2|1
#     health-gate.sh wait    <url> <seconds>  -> polls until HEALTHY, prints the last state, exit 0|2|1
#
# RULES, deliberately strict:
#   * an unreadable or unparseable body is DEGRADED, never HEALTHY -- an unknown health is not health;
#   * a missing `ok` field is DEGRADED for the same reason;
#   * a 2xx with `ok:true` is the ONLY thing that prints HEALTHY;
#   * exit codes are distinct (0 healthy, 2 degraded, 1 down) so a caller can choose.
#
# Read-only: it makes one HTTP GET per call, writes nothing, and never reads a credential.
set -uo pipefail

MAX_TIME="${HEALTH_GATE_MAX_TIME:-8}"

_state() {
  local url="$1" body code
  body="$(mktemp "${TMPDIR:-/tmp}/health-gate-XXXXXX")"
  code="$(curl -s -o "$body" -w '%{http_code}' --max-time "$MAX_TIME" "$url" 2>/dev/null || echo 000)"
  local ok
  ok="$(python3 - "$body" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8", errors="replace"))
except Exception:
    print("unparseable"); raise SystemExit
if not isinstance(d, dict):
    print("unparseable"); raise SystemExit
v = d.get("ok")
print("true" if v is True else ("false" if v is False else "missing"))
PY
)"
  rm -f "$body"
  case "$code" in
    000|"") echo "DOWN"; return 1 ;;
  esac
  case "$code" in
    2*) : ;;
    *) echo "DOWN"; return 1 ;;
  esac
  case "${ok:-unparseable}" in
    true)  echo "HEALTHY";  return 0 ;;
    false) echo "DEGRADED"; return 2 ;;
    *)     echo "DEGRADED"; return 2 ;;
  esac
}

cmd="${1:-show}"; shift || true

case "$cmd" in
  show)
    url="${1:-}"; [ -n "$url" ] || { echo "usage: health-gate.sh show <url>" >&2; exit 1; }
    _state "$url"
    ;;
  require)
    url="${1:-}"; label="${2:-$url}"
    [ -n "$url" ] || { echo "usage: health-gate.sh require <url> [label]" >&2; exit 1; }
    st="$(_state "$url")"; rc=$?
    printf '%s: %s\n' "$label" "$st"
    [ "$rc" = "0" ] || echo "  (this is not the same as 'did not start' -- read the body before deciding)" >&2
    exit "$rc"
    ;;
  wait)
    url="${1:-}"; secs="${2:-60}"
    [ -n "$url" ] || { echo "usage: health-gate.sh wait <url> <seconds>" >&2; exit 1; }
    waited=0
    while :; do
      st="$(_state "$url")"; rc=$?
      [ "$rc" = "0" ] && { echo "$st"; exit 0; }
      waited=$((waited + 2))
      [ "$waited" -ge "$secs" ] && { echo "$st"; exit "$rc"; }
      sleep 2
    done
    ;;
  *)
    echo "unknown command: $cmd" >&2; exit 1 ;;
esac
