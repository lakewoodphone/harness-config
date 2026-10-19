#!/usr/bin/env bash
# test_wake_progress_cap.sh -- prove a deliberate whole-queue gate is not filed as a stall.
#
# WHY THIS TEST EXISTS. On 2026-10-18 the fleet reached its release-count ceiling
# (daily_cap: 150/150) at 16:05Z. wake-progress.py read the resulting silence as a stall and
# filed ledger item 641 at 22:37Z, whose `why` asserted a single-desktop fault even though the
# window held 0 releases (so 0 failures). The gate reset at 00:00Z and seven releases started.
#
# This test is hermetic: every log, CLI and marker is a temp file. It calls the real detector
# with stub `wake.py stats` / `work.py add`, never the live store, and files nothing.
#
#   ./test_wake_progress_cap.sh [path/to/wake-progress.py]     exit 0 = all pass
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC="${1:-$HERE/../sources/wake-progress.py}"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

cat > "$T/wake_cap.py" <<'PY'
import json
print(json.dumps({"ok": True, "caps_in_force": ["daily_cap: 150/150 releases today"]}))
PY
cat > "$T/wake_open.py" <<'PY'
import json
print(json.dumps({"ok": True, "caps_in_force": []}))
PY
cat > "$T/wake_paused.py" <<'PY'
import json
print(json.dumps({"ok": True, "caps_in_force": ["paused: kill switch present"]}))
PY
cat > "$T/wake_broken.py" <<'PY'
import sys
sys.stderr.write("stub: wake store unreadable\n")
sys.exit(3)
PY
cat > "$T/work_stub.py" <<'PY'
import os, shutil, sys
marker = os.environ["STUB_WORK_MARKER"]
with open(marker, "a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\n")
if len(sys.argv) >= 4 and sys.argv[1] == "add" and sys.argv[2] == "--from-json":
    shutil.copyfile(sys.argv[3], marker + ".payload.json")
print('{"id": 999, "ok": true}')
PY

ts() { date -u -d "$1" +%Y-%m-%dT%H:%M:%SZ; }
printf '%s released 2026-10-18 wake #1 done exit=0 runner_code=0 dur=60s subject="x"\n' \
  "$(ts '-7 hours')" > "$T/ok.log"
{ cat "$T/ok.log"; printf '%s released 2026-10-18 wake #2 done exit=1 runner_code=1 dur=60s subject="y"\n' "$(ts '-2 hours')"; } > "$T/fail.log"

pass=0; fail=0
check() {
  local name="$1" want_rc="$2" want_out="$3" got_rc="$4" got_out="$5"
  if [ "$got_rc" = "$want_rc" ] && printf '%s' "$got_out" | grep -q "$want_out"; then
    echo "PASS  $name"; pass=$((pass + 1))
  else
    echo "FAIL  $name  (want rc=$want_rc matching '$want_out'; got rc=$got_rc)"
    printf '%s\n' "$got_out" | sed 's/^/        /'
    fail=$((fail + 1))
  fi
}

# 1. Cap in force, no attempt since the last success -> capped, NO item.
M="$T/m1"; rm -f "$M"
out=$(WAKE_DISPATCH_LOG="$T/ok.log" WAKE_CLI="$T/wake_cap.py" WORK_CLI="$T/work_stub.py" \
      STUB_WORK_MARKER="$M" python3 "$SRC" 2>&1); rc=$?
check "daily cap with no attempt since success is capped, not a stall" 0 "capped" "$rc" "$out"
[ -e "$M" ] && { echo "FAIL  capped case filed an item"; fail=$((fail + 1)); } \
            || { echo "PASS  capped case filed nothing"; pass=$((pass + 1)); }

# 2. No gate in force, silence -> the stall IS filed (the deadman still works).
M="$T/m2"; rm -f "$M"
out=$(WAKE_DISPATCH_LOG="$T/ok.log" WAKE_CLI="$T/wake_open.py" WORK_CLI="$T/work_stub.py" \
      STUB_WORK_MARKER="$M" python3 "$SRC" 2>&1); rc=$?
check "no gate + silence still files the stall" 1 "STALLED" "$rc" "$out"
[ -s "$M" ] && { echo "PASS  no-gate case called work.py add"; pass=$((pass + 1)); } \
            || { echo "FAIL  no-gate case did not file"; fail=$((fail + 1)); }

# 3. Cap in force, but a release FAILED after the last success -> still files.
M="$T/m3"; rm -f "$M"
out=$(WAKE_DISPATCH_LOG="$T/fail.log" WAKE_CLI="$T/wake_cap.py" WORK_CLI="$T/work_stub.py" \
      STUB_WORK_MARKER="$M" python3 "$SRC" 2>&1); rc=$?
check "a failed attempt after the last success is not excused by the cap" 1 "STALLED" "$rc" "$out"
grep -q "does not explain the failure" "$M.payload.json" 2>/dev/null \
  && { echo "PASS  payload says the gate does not explain the failure"; pass=$((pass + 1)); } \
  || { echo "FAIL  payload missing the gate-vs-failure sentence"; fail=$((fail + 1)); }

# 4. Unreadable gate -> never suppresses; the payload says it could not read the gate.
M="$T/m4"; rm -f "$M"
out=$(WAKE_DISPATCH_LOG="$T/ok.log" WAKE_CLI="$T/wake_broken.py" WORK_CLI="$T/work_stub.py" \
      STUB_WORK_MARKER="$M" python3 "$SRC" 2>&1); rc=$?
check "unreadable gate still files the stall" 1 "STALLED" "$rc" "$out"
grep -q "could not be read" "$M.payload.json" 2>/dev/null \
  && { echo "PASS  payload says the gate state could not be read"; pass=$((pass + 1)); } \
  || { echo "FAIL  payload did not admit the unreadable gate"; fail=$((fail + 1)); }

# 5. A PAUSE is a kill switch, not a budget ceiling: it must still reach the ledger, and the
#    item must name the pause so nobody reads it as a host fault.
M="$T/m5"; rm -f "$M"
out=$(WAKE_DISPATCH_LOG="$T/ok.log" WAKE_CLI="$T/wake_paused.py" WORK_CLI="$T/work_stub.py" \
      STUB_WORK_MARKER="$M" python3 "$SRC" 2>&1); rc=$?
check "a paused fleet still files an item" 1 "STALLED" "$rc" "$out"
grep -q "PAUSED" "$M.payload.json" 2>/dev/null \
  && { echo "PASS  paused payload names the pause"; pass=$((pass + 1)); } \
  || { echo "FAIL  paused payload did not name the pause"; fail=$((fail + 1)); }

echo "----"
echo "pass=$pass fail=$fail"
[ "$fail" = 0 ]
