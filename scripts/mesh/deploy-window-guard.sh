#!/usr/bin/env bash
# Refuse to deploy into a measurement window.
#
# WHY THIS EXISTS
#   On 2026-10-20 a session spent four hours building a controlled comparison of DeepSeek's
#   01:00-04:00Z peak block, then restarted company-api FIVE times inside that block
#   (03:15:25, 03:17:27, 03:20:58, 03:27:37, 03:37:04). Its own verifier printed
#   "CONTAMINATED ... Do NOT read the deltas above as a result" and the result was void.
#   The agent had refused to change the *policy* inside the window and did not think a code deploy
#   counted. It does: a restart stops ticks, resets cadence and changes what is cached.
#
#   Lesson L10626. This is that lesson as a mechanism, because a rule that lives only in a document
#   is a rule with no reader.
#
# USAGE
#   deploy-window-guard.sh                 # check; exit 0 allow, 2 in a window, 3 usage
#   deploy-window-guard.sh --json
#   deploy-window-guard.sh --override "reason"   # proceed anyway, reason is printed and required
#
# WINDOW SOURCES
#   1. The DeepSeek peak bands themselves (Mon-Fri 01:00-04:00 and 06:00-10:00 UTC) - a peak block is
#      a measurement window unless somebody says otherwise.
#   2. A declared measurement window file, $GUARD_WINDOW_FILE (default
#      /var/lib/measurement-window), two UTC ISO timestamps on one line: "<start> <end>".
#   3. Deferral to the weekly proof: if a file $GUARD_PROOF_FILE exists it is printed, because a
#      deploy during the proof week voids the proof.
set -uo pipefail

WINDOW_FILE="${GUARD_WINDOW_FILE:-/var/lib/measurement-window}"
PROOF_FILE="${GUARD_PROOF_FILE:-/var/lib/savings-proof-week}"
JSON=0
OVERRIDE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --json) JSON=1; shift ;;
    --override) OVERRIDE="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "usage: $(basename "$0") [--json] [--override \"reason\"]" >&2; exit 3 ;;
  esac
done

now_epoch=$(date -u +%s)
now_iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
dow=$(date -u +%u)     # 1=Mon .. 7=Sun
hour=$(date -u +%H); hour=$((10#$hour))

# DeepSeek peak: Mon-Fri 01:00-04:00 and 06:00-10:00 UTC (35 of 168 hours).
in_peak=0
peak_band=""
if [ "$dow" -ge 1 ] && [ "$dow" -le 5 ]; then
  if [ "$hour" -ge 1 ] && [ "$hour" -lt 4 ]; then in_peak=1; peak_band="01:00-04:00"; fi
  if [ "$hour" -ge 6 ] && [ "$hour" -lt 10 ]; then in_peak=1; peak_band="06:00-10:00"; fi
fi

# Declared window.
in_declared=0; declared=""
if [ -f "$WINDOW_FILE" ]; then
  read -r ws we _ < "$WINDOW_FILE" || true
  if [ -n "${ws:-}" ] && [ -n "${we:-}" ]; then
    s=$(date -u -d "$ws" +%s 2>/dev/null || echo 0)
    e=$(date -u -d "$we" +%s 2>/dev/null || echo 0)
    if [ "$s" -gt 0 ] && [ "$e" -gt 0 ] && [ "$now_epoch" -ge "$s" ] && [ "$now_epoch" -le "$e" ]; then
      in_declared=1; declared="$ws .. $we"
    fi
  fi
fi

proof=""
[ -f "$PROOF_FILE" ] && proof=$(head -1 "$PROOF_FILE")

refuse=0
[ "$in_peak" -eq 1 ] && refuse=1
[ "$in_declared" -eq 1 ] && refuse=1

if [ "$JSON" -eq 1 ]; then
  printf '{"now":"%s","in_peak":%s,"peak_band":"%s","in_declared":%s,"declared":"%s","proof":"%s","refused":%s}\n' \
    "$now_iso" "$in_peak" "$peak_band" "$in_declared" "$declared" "$proof" "$refuse"
  [ "$refuse" -eq 1 ] && exit 2
  exit 0
fi

echo "DEPLOY WINDOW GUARD — $now_iso (UTC, day-of-week $dow)"
if [ "$in_peak" -eq 1 ]; then
  echo "  IN PEAK BAND: $peak_band UTC — DeepSeek peak is 2x price and is the comparison window."
fi
if [ "$in_declared" -eq 1 ]; then
  echo "  IN DECLARED MEASUREMENT WINDOW: $declared"
fi
[ -n "$proof" ] && echo "  NOTE: a proof week is recorded ($proof) — a deploy voids the proof."

if [ "$refuse" -eq 1 ]; then
  if [ -n "$OVERRIDE" ]; then
    echo "OVERRIDING, reason: $OVERRIDE"
    echo "  This deploy will be recorded as having landed inside a measurement window."
    exit 0
  fi
  cat >&2 <<'EOF'
REFUSED — a measurement window is open.

  A deploy is not inert. A restart stops ticks, resets cadence and changes what is cached, so a
  cost or throughput comparison spanning it measures two systems. On 2026-10-20 exactly this made
  a whole night's result void (lesson L10626).

  If you must proceed, say why in the same breath:
      deploy-window-guard.sh --override "reason"

  If the window is wrong, correct it: /var/lib/measurement-window holds "<start> <end>" in UTC.
EOF
  exit 2
fi

echo "ALLOW — outside every known measurement window."
exit 0
