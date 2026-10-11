#!/usr/bin/env bash
# =============================================================================
# test_guard_service_state.sh — the regression test for AGENTS.md §5.
#
# The rule: before changing ANY machine's service state, find out what that machine
# is FOR and who decided its current state. The guard is
# `scripts/mesh/guard-service-state.sh`; the designation is
# `settings/machines/host-posture.tsv`.
#
# The behaviour asserted here is the behaviour whose absence cost 5,129 rows on
# 2026-10-11: a frozen host must REFUSE, an ordinary host must ALLOW, and a host
# nobody has designated must REFUSE rather than default to permission.
#
# Run:  bash tests/test_guard_service_state.sh
# Exit: 0 all passed · 1 a failure · 2 the harness itself is broken
# =============================================================================
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
GUARD="$REPO/scripts/mesh/guard-service-state.sh"
POSTURE="$REPO/settings/machines/host-posture.tsv"

PASS=0; FAIL=0; LAST_OUT=""
ok()   { PASS=$((PASS+1)); printf '  [PASS] %s\n' "$*"; }
bad()  { FAIL=$((FAIL+1)); printf '  [FAIL] %s\n' "$*"; }
hdr()  { printf '\n=== %s ===\n' "$*"; }
note() { printf '  [info] %s\n' "$*"; }

[ -x "$GUARD" ] || [ -f "$GUARD" ] || { echo "harness broken: $GUARD missing" >&2; exit 2; }
[ -f "$POSTURE" ] || { echo "harness broken: $POSTURE missing — the guard has nothing to read" >&2; exit 2; }

# expect <label> <wanted-exit> <args...>
expect() {
  local label="$1" want="$2"; shift 2
  local out rc
  out="$(bash "$GUARD" "$@" 2>&1)"; rc=$?
  LAST_OUT="$out"
  if [ "$rc" -eq "$want" ]; then ok "$label (exit $rc)"
  else bad "$label — wanted exit $want, got $rc"; printf '%s\n' "$out" | sed 's/^/         /'; fi
}

hdr "1. A frozen host REFUSES. This is the incident, replayed."
# The 2026-10-11 commands were `systemctl unmask cron.service`, `systemctl enable --now cron`
# and `systemctl start secretary-api` — all three on the office box.
for op in unmask enable start restart stop mask disable; do
  expect "secratary + $op is refused (exit 2)" 2 --host secratary --op "$op"
done
note "the refusal text names what the host is for, who decided, and since when:"
printf '%s\n' "$LAST_OUT" | grep -q 'WHAT IT IS FOR' && ok "refusal explains WHAT IT IS FOR" || bad "refusal does not say what the host is for"
printf '%s\n' "$LAST_OUT" | grep -q 'WHO DECIDED'    && ok "refusal names WHO DECIDED"        || bad "refusal does not name the decider"
printf '%s\n' "$LAST_OUT" | grep -q 'MASKED OR STOPPED UNIT ON THIS HOST IS DELIBERATE' \
  && ok "refusal says a masked unit is deliberate" || bad "refusal does not address the masked unit"

hdr "2. Every alias of the frozen box refuses, not just the pretty name."
expect "secratary-ts refuses"      2 --host secratary-ts   --op unmask
expect "secratary-lan refuses"     2 --host secratary-lan  --op unmask
expect "192.168.50.77 refuses"     2 --host 192.168.50.77  --op unmask

hdr "3. The authority ALLOWS. The same rule must not block the box that is in charge."
expect "secratary-cloud + restart is allowed (exit 0)" 0 --host secratary-cloud --op restart
printf '%s\n' "$LAST_OUT" | grep -q 'ALLOW' && ok "the allow is spoken, not silent" || bad "an allow said nothing"
expect "178.156.194.1 + restart is allowed"            0 --host 178.156.194.1 --op restart
expect "zabz-tech + restart is allowed"                0 --host zabz-tech --op restart

hdr "4. Prefix safety: 'secratary' must never match 'secratary-cloud'."
# The lookup is exact and case-insensitive on purpose. A substring match here would
# let the authority's name authorise a change on the anchor, which is the whole hazard.
expect "secratary-cloud is NOT treated as secratary (allowed)" 0 --host secratary-cloud --op start
expect "secratary is NOT treated as secratary-cloud (refused)" 2 --host secratary --op start

hdr "5. A read-only host REFUSES without the owner, and allows with them."
expect "lpt-apps + enable is refused (exit 3)"                3 --host lpt-apps --op enable
expect "lpt-apps + enable + --owner-confirmed is allowed"     0 --host lpt-apps --op enable --owner-confirmed
expect "survivor + stop is refused"                           3 --host survivor --op stop

hdr "6. An UNDESIGNATED host REFUSES. Silence is not permission."
expect "an unknown host refuses (exit 4)"                     4 --host some-new-box --op restart
expect "a tailnet name is not assumed to be its host"         4 --host secratary-cloud.tail93e6e6.ts.net --op restart
printf '%s\n' "$LAST_OUT" | grep -qi 'not permission' && ok "the refusal says an unknown host is not permission" || bad "refusal does not state that silence is not permission"
note "the refusal, verbatim:"; printf '%s\n' "$LAST_OUT" | sed 's/^/         /'

hdr "7. The guard reads a FILE, not a hardcoded list."
# If a hostname were hardcoded in the script, flipping the file would change nothing.
TMPD="$(mktemp -d)"; trap 'rm -rf "$TMPD"' EXIT
cp "$POSTURE" "$TMPD/posture.tsv"
expect "the real file refuses secratary"                      2 --host secratary --op unmask
printf 'secratary|writable|2026-10-11T00:00:00Z|this test|flipped for the test\n' > "$TMPD/posture.tsv"
expect "--posture with secratary flipped to writable ALLOWS"  0 --posture "$TMPD/posture.tsv" --host secratary --op unmask
expect "--posture with an unknown host still REFUSES"         4 --posture "$TMPD/posture.tsv" --host secratary-cloud --op unmask
printf 'secratary|banana|2026-10-11T00:00:00Z|this test|bad posture value\n' > "$TMPD/posture.tsv"
expect "a nonsense posture REFUSES rather than allowing"      1 --posture "$TMPD/posture.tsv" --host secratary --op unmask
expect "a MISSING posture file REFUSES"                       1 --posture "$TMPD/nope.tsv" --host secratary-cloud --op unmask

hdr "8. No stage of the guard reaches the network or runs systemctl."
# The guard protects a box that is meant to be untouched, so it must never have to
# reach it. A guard that ssh'd to the target could not protect a powered-off anchor.
# Lines whose sole job is to PRINT a command (the `you were about to: systemctl …`
# message, the usage text, the `warn` lines that name the forbidden verbs) are not
# executions, so they are excluded — by requiring the command to appear at the start
# of a statement or after a shell operator, not inside a quoted string.
exec_lines() {
  grep -vE '^[[:space:]]*#' "$GUARD" \
    | grep -E '(^|[;&|(]|&&|\|\|)[[:space:]]*(ssh|scp|sftp|systemctl|service|curl|wget|nc|reboot|shutdown)[[:space:]]' || true
}
if [ -n "$(exec_lines)" ]; then
  bad "the guard EXECUTES a network or systemctl command"
  exec_lines | sed 's/^/         /'
else
  ok "the guard is offline and non-mutating by construction"
fi
note "for the record, the only two matches are printed, never run:"
grep -nE '\bssh\b|\bsystemctl\b' "$GUARD" | sed 's/^/         /'

hdr "9. AGENTS.md carries the rule, and the guard is where the rule says it is."
AG="$REPO/AGENTS.md"
if [ -f "$AG" ]; then
  grep -q 'find out what that machine is FOR' "$AG" && ok "AGENTS.md states the general rule" || bad "AGENTS.md is missing the general rule"
  grep -q '5,129' "$AG" && ok "AGENTS.md carries the measured evidence (5,129 rows)" || bad "AGENTS.md does not carry the evidence"
  grep -q '131-MIGRATION-BRIEF' "$AG" && ok "AGENTS.md names the governing brief" || bad "AGENTS.md does not name the brief"
  grep -q 'host-posture.tsv' "$AG" && ok "AGENTS.md points at the designation file" || bad "AGENTS.md does not point at the designation file"
else
  bad "AGENTS.md is absent — the rule reaches no agent"
fi

hdr "RESULT"
printf '  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
