#!/bin/bash
# r8-pipeline.sh -- carry the journal union forward from round 6's candidate.
#
# WHY A SECOND RUN. Round 6 built the union at 15:08Z from trees captured at 14:37Z. Both
# ZABZ-YOGA and the authority have appended since (measured: 36 entries with foreign host tags
# landed in the authority's tree after 15:00, and the authority's own entries to P4569/L5729).
# A union built from a stale capture is a union that will drop the newest entries.
#
# WHAT IS DIFFERENT FROM ROUND 6, and each difference is a measurement, not a preference:
#   1. `/root/work/wt-item221` is a NEW SOURCE. It is the worktree of branch
#      `hk/221-live-wake-reconcile`, and it holds 234 entry ids the authority's own checkout does
#      not contain (D3111.. among them). The five-tree union never saw them.
#   2. `zabz-tech-linux` is OFFLINE (tailscale: active; relay "nyc"; offline, last seen 1h ago),
#      so its tree is the round-6 capture, copied in and LABELLED `linux-r6capture`. A source that
#      could not be re-read is named as such rather than silently presented as current.
#   3. The base is still `yoga` -- the widest-coverage tree, and the base round 6 verified.
#
# READ-ONLY ON EVERY SOURCE. Nothing under any live `journal/` is created, moved or deleted.
# Every write is under /root/work/r8.
set -u
R8=/root/work/r8
R6=/root/work/r7
LOG=$R8/logs/pipeline.log
mkdir -p "$R8/trees" "$R8/logs"
: > "$LOG"
say(){ echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"; }
SSH="ssh -n -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15"

say "HOST $(hostname)"; df -Pk / | tail -1 | tee -a "$LOG"

# ── 1. COLLECT ───────────────────────────────────────────────────────────────────────────────────
grab(){ # grab <name> <ssh-target...> -- writes trees/<name>.tar then extracts
  local name=$1; shift
  say "collect $name : $*"
  if [ "$1" = "LOCAL" ]; then
    tar -cf "$R8/trees/$name.tar" -C "$2" journal || { say "$name tar FAILED"; return 1; }
  else
    $SSH "$@" "tar -cf - -C $TAR_C journal" > "$R8/trees/$name.tar" 2>"$R8/logs/$name.err"
    local rc=$?
    [ -s "$R8/trees/$name.tar" ] || { say "$name tar EMPTY (rc=$rc) err=[$(head -c 200 "$R8/logs/$name.err" | tr '\n' ' ')]"; return 1; }
  fi
  mkdir -p "$R8/trees/$name"
  tar -xf "$R8/trees/$name.tar" -C "$R8/trees/$name" || { say "$name EXTRACT FAILED"; return 1; }
  say "$name: $(find "$R8/trees/$name/journal/entries" -name '*.md' | wc -l) entry files, tar $(stat -c %s "$R8/trees/$name.tar") B"
}

TAR_C=/root/code/harness-config;  grab cloud LOCAL "$TAR_C"
TAR_C=/root/work/wt-item221;      grab item221 LOCAL "$TAR_C"
TAR_C=C:/Users/ezabz/code/harness-config; grab yoga  zabz-yoga-ts
TAR_C=C:/Users/ezabz/code/harness-config; grab tech  zabz-tech
TAR_C=/Users/lpt/code/harness-config;     grab mac   -l lpt mac-mini-ts

# linux is offline: reuse round 6's capture, labelled so nothing can mistake it for a fresh read
if [ -d "$R6/trees/linux/journal/entries" ]; then
  rm -rf "$R8/trees/linux-r6capture"
  cp -a "$R6/trees/linux" "$R8/trees/linux-r6capture"
  say "linux: OFFLINE - reused the round-6 capture as linux-r6capture: $(find "$R8/trees/linux-r6capture/journal/entries" -name '*.md' | wc -l) entry files"
else
  say "linux: OFFLINE and no round-6 capture on disk - SOURCE MISSING"
fi

# ── 2. MERGE (30-merge.py, patched only for the directory and the source list) ────────────────────
say "patch 30-merge.py for r8"
sed -e 's|/root/work/r7|/root/work/r8|' \
    -e 's|ORDER = \["yoga", "cloud", "tech", "linux", "mac"\]|ORDER = ["yoga", "cloud", "tech", "linux-r6capture", "mac", "item221"]|' \
    "$R6/30-merge.py" > "$R8/30-merge.py"
grep -n -e 'R7 =' -e 'ORDER =' "$R8/30-merge.py" | tee -a "$LOG"
python3 "$R8/30-merge.py" 2>&1 | tee -a "$LOG"

# ── 3. REPAIR + CHECK + VERIFY inside the candidate only ─────────────────────────────────────────
M=$R8/merged-journal
TOOL="$M/tools/journal.py"
[ -f "$TOOL" ] || { say "ABORT: candidate has no tools/journal.py"; exit 1; }
run(){ echo "---- journal.py --root \$M $*" | tee -a "$LOG"; python3 "$TOOL" --root "$M" --no-color "$@" >>"$LOG" 2>&1; echo "---- exit=$?" | tee -a "$LOG"; }
count(){ find "$M/entries" -name '*.md' -type f | wc -l; }

say "check BEFORE repair (expect errors: the suffixed second copies)"; run check
say "dedupe (dry)"; run dedupe
say "dedupe --apply   before=$(count)"; run dedupe --apply; say "after=$(count)"
say "repair-ids (dry)"; run repair-ids
say "repair-ids --apply before=$(count)"; run repair-ids --apply; say "after=$(count)"
say "check AFTER repair (must be 0 errors)"; run check
say "verify"; run verify
say "entries FINAL: $(count)"

# ── 4. ACCEPTANCE: no body lost, nothing invented ────────────────────────────────────────────────
say "body-loss gate"
python3 "$M/../r8-body-loss.py" --trees "$R8/trees" --merged "$M" --normalise-ids 2>&1 | tee -a "$LOG"
df -Pk / | tail -1 | tee -a "$LOG"
say "DONE"
