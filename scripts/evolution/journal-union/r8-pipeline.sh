#!/bin/bash
# r8-pipeline.sh -- build ONE journal tree out of every source on the estate, and prove nothing left.
#
# WHY A SECOND RUN. Round 6 built the union at 15:08Z from trees captured at 14:37Z. Both ZABZ-YOGA
# and the authority appended since. A union built from a stale capture drops the newest entries.
#
# THE SOURCE SET IS THE PART THAT GOES WRONG, and this run is the proof. The first attempt used six
# sources and reported `BODIES MISSING 0`. Widening it to ten -- the same gate, the same merged tree
# -- reported **62 bodies missing**. Nothing about the merge had changed; the source set had. That
# is the whole lesson of this directory in one measurement.
#
# WHAT IS IN THE SET, and why each one is here rather than assumed:
#   cloud            /root/code/harness-config on the authority -- the CANONICAL checkout
#   yoga             ZABZ-YOGA's checkout (the merge BASE: widest coverage, and what round 6 verified)
#   tech             ZABZ-TECH's checkout
#   linux-r6capture  zabz-tech-linux is OFFLINE (tailscale: active; relay "nyc"; offline, last seen
#                    1h ago). Round 6's capture is reused and LABELLED, never passed off as fresh.
#   mac              lakewooechsmini
#   item221          /root/work/wt-item221 -- the worktree of branch hk/221-live-wake-reconcile,
#                    with 234 ids absent from the canonical checkout
#   mfx              ZABZ-YOGA harness-config-mfx -- 37 ids yoga's main tree lacks
#   p1evidence       one of NINE _worktrees/harness-config/p1*|p2* worktrees. Measured: all nine
#                    carry the SAME eight ids (H2915,L3047,L3048,L3058,L3059,L3060,P2667,P2668),
#                    so one representative is enough -- and that was verified, not assumed.
#   hcd              ZABZ-YOGA _scratch/hc-master-deliver -- 4 ids (H229,H3290,H3291,L221a)
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
# THE BASE DECIDES WHICH BODY KEEPS THE ORIGINAL ID in every collision. Round 6 based on `yoga`
# (the widest coverage). For a tree that is going to LAND ON THE AUTHORITY that is backwards: it
# would renumber the canonical checkout's own ids in ~500 collisions in order to preserve yoga's,
# which is the opposite of "the authority is the source of truth". So the base is `cloud` -- the
# canonical checkout -- and yoga is overlaid like every other source. Coverage no longer decides
# anything: every source is in the union either way.
ORDER='["cloud", "yoga", "tech", "linux-r6capture", "mac", "item221", "mfx", "p1evidence", "hcd"]'

# The tools travel WITH this script, so the run depends on neither a scratch directory nor a
# checkout another session may be mid-edit in. Run this file from the repo copy.
HERE="$(cd "$(dirname "$0")" && pwd)"
for t in 30-merge.py 65-normalise-stems.py r7-restore-archived.py r7-verify-body-loss.py; do
  for src in "$HERE/$t" "$HERE/../$t" "$R6/$t"; do
    [ -s "$src" ] && { cp -f "$src" "$R8/$t"; break; }
  done
  [ -s "$R8/$t" ] || say "WARN: could not stage $t from $HERE, $HERE/.. or $R6"
done

say "HOST $(hostname)"; df -Pk / | tail -1 | tee -a "$LOG"

# ── 1. COLLECT ───────────────────────────────────────────────────────────────────────────────────
grab(){ # grab <name> LOCAL <dir>   |   grab <name> <ssh-target...>   (dir comes from TAR_C)
  local name=$1; shift
  say "collect $name : $*  (dir=$TAR_C)"
  if [ "$1" = "LOCAL" ]; then
    tar -cf "$R8/trees/$name.tar" -C "$TAR_C" journal || { say "$name tar FAILED"; return 1; }
  else
    $SSH "$@" "tar -cf - -C $TAR_C journal" > "$R8/trees/$name.tar" 2>"$R8/logs/$name.err"
    [ -s "$R8/trees/$name.tar" ] || { say "$name tar EMPTY err=[$(head -c 200 "$R8/logs/$name.err" | tr '\n' ' ')]"; return 1; }
  fi
  rm -rf "$R8/trees/$name"; mkdir -p "$R8/trees/$name"
  tar -xf "$R8/trees/$name.tar" -C "$R8/trees/$name" || { say "$name EXTRACT FAILED"; return 1; }
  say "$name: $(find "$R8/trees/$name/journal/entries" -type f -name '*.md' | wc -l) entry files"
}

TAR_C=/root/code/harness-config;                            grab cloud      LOCAL
TAR_C=/root/work/wt-item221;                                grab item221    LOCAL
TAR_C=C:/Users/ezabz/code/harness-config;                   grab yoga       zabz-yoga-ts
TAR_C=C:/Users/ezabz/code/harness-config;                   grab tech       zabz-tech
TAR_C=/Users/lpt/code/harness-config;                       grab mac        -l lpt mac-mini-ts
TAR_C=C:/Users/ezabz/code/harness-config-mfx;               grab mfx        zabz-yoga-ts
TAR_C=C:/Users/ezabz/code/_worktrees/harness-config/p1evidence; grab p1evidence zabz-yoga-ts
TAR_C=C:/Users/ezabz/code/_scratch/hc-master-deliver;        grab hcd        zabz-yoga-ts

if [ -d "$R6/trees/linux/journal/entries" ]; then
  rm -rf "$R8/trees/linux-r6capture"
  cp -a "$R6/trees/linux" "$R8/trees/linux-r6capture"
  say "linux: OFFLINE - reused the round-6 capture as linux-r6capture: $(find "$R8/trees/linux-r6capture/journal/entries" -type f -name '*.md' | wc -l) entry files"
else
  say "linux: OFFLINE and no round-6 capture on disk - SOURCE MISSING"
fi

# ── 2. MERGE ─────────────────────────────────────────────────────────────────────────────────────
say "patch 30-merge.py for r8"
# A MISSING INPUT HERE DOES NOT FAIL -- IT SILENTLY BECOMES A NO-OP, measured 2026-10-16. `sed`
# with an unreadable input writes nothing and exits non-zero only on stderr; the redirect creates an
# EMPTY file; `python3 empty.py` is a valid program that does nothing and exits 0; the pipeline then
# runs `check`, `dedupe` and `repair-ids` against the PREVIOUS candidate and reports a clean tree.
# That is how this run first "passed" with 0 errors over a 6-source tree while claiming 9 sources.
# So: assert the input, assert the output, assert the patch actually landed.
[ -s "$HERE/30-merge.py" ] || { say "ABORT: $HERE/30-merge.py is missing or empty"; exit 1; }
sed -e 's|/root/work/r7|/root/work/r8|' \
    -e 's|^BASE = "yoga"|BASE = "cloud"|' \
    -e "s|^ORDER = .*|ORDER = $ORDER|" \
    "$HERE/30-merge.py" > "$R8/30-merge.py"
[ -s "$R8/30-merge.py" ] || { say "ABORT: the patched merge script is EMPTY -- refusing to continue"; exit 1; }
grep -q 'item221' "$R8/30-merge.py" || { say "ABORT: ORDER was not patched -- refusing to continue"; exit 1; }
grep -q '^BASE = "cloud"' "$R8/30-merge.py" || { say "ABORT: BASE was not patched to cloud -- refusing to continue"; exit 1; }
grep -n -e '^R7 =' -e '^BASE =' -e '^ORDER =' "$R8/30-merge.py" | tee -a "$LOG"
python3 "$R8/30-merge.py" 2>&1 | tee -a "$LOG"
grep -q 'base files:' "$LOG" || { say "ABORT: the merge produced no summary -- it did not run"; exit 1; }

# ── 3. REPAIR + CHECK + VERIFY inside the candidate only ─────────────────────────────────────────
M=$R8/merged-journal
TOOL="$M/tools/journal.py"
[ -f "$TOOL" ] || { say "ABORT: candidate has no tools/journal.py"; exit 1; }
run(){ echo "---- journal.py --root \$M $*" | tee -a "$LOG"; python3 "$TOOL" --root "$M" --no-color "$@" >>"$LOG" 2>&1; echo "---- exit=$?" | tee -a "$LOG"; }
count(){ find "$M/entries" -type f -name '*.md' | wc -l; }

say "check BEFORE repair (expect errors: the suffixed second copies)"; run check
say "dedupe (dry)"; run dedupe
say "dedupe --apply   before=$(count)"; run dedupe --apply; say "after=$(count)"
say "repair-ids (dry)"; run repair-ids
say "repair-ids --apply before=$(count)"; run repair-ids --apply; say "after=$(count)"

# 65 IS REQUIRED, AND IT IS A STEP ROUND 6 DID BY HAND. `repair-ids` renumbers the surplus copy of
# an id; it does not care what FILE NAME the survivor has, so when the earliest copy was one of the
# suffixed ones the survivor of X is left in `<X>b.md` and check reports
#   ERROR entries/<kind>/<X>b.md: id in the file name (<X>b) disagrees with the marker (X)
# for every one -- measured 94 on the six-source tree, with check exiting 1. This is a PURE RENAME,
# and it refuses if any id is still carried by two files (that would mean the repair did not finish).
say "65-normalise-stems (dry)"; python3 "$R8/65-normalise-stems.py" "$M" 2>&1 | tail -8 | tee -a "$LOG"
say "65-normalise-stems --apply"; python3 "$R8/65-normalise-stems.py" "$M" --apply 2>&1 | tail -6 | tee -a "$LOG"

say "check AFTER repair"; run check
say "verify"; run verify
say "entries FINAL: $(count)"

# ── 4. THE SEVEN `dedupe` RETIRED MUST COME BACK LIVE (P4251) ─────────────────────────────────────
# `dedupe` retires a colliding body to archive/duplicates/<id>.md rather than renumbering it, so a
# body that was LIVE in a source tree silently leaves the live view -- list/search/status stop
# returning it -- while its bytes stay on disk. Round 6 found seven. This restores each under a
# fresh LIVE id, guarding on whether the BODY is already live so a re-run writes nothing.
say "restore archived-but-was-live (measure, BY CRITERION)"; python3 "$R8/r7-restore-archived.py" --root "$M" --from-sources "$R8/trees" 2>&1 | tail -12 | tee -a "$LOG"
say "restore --apply"; python3 "$R8/r7-restore-archived.py" --root "$M" --from-sources "$R8/trees" --apply 2>&1 | tail -8 | tee -a "$LOG"
say "restore --apply again (idempotence: must write 0)"; python3 "$R8/r7-restore-archived.py" --root "$M" --from-sources "$R8/trees" --apply 2>&1 | tail -3 | tee -a "$LOG"

# 4b. THE SECOND HALF OF THE SAME TRAP, AND THE TOOL ALREADY OWNS IT. Restored entries that carry
# their own id in their BODY have had that body rewritten, so the `sha=` metadata recorded at write
# time no longer matches and check reports "metadata sha=... does not match the body (...)".
# `check --fix` is the tool's own repair: it re-emits through the writer a normal write uses, so the
# sha, the meta line and the line endings are recomputed together. Its comment records why a bare
# text replace is wrong -- "fixed the CRLF and left the sha stale, which turned one ERROR into
# another" -- which is why this calls it instead of adding a second tool that does it worse.
say "check --fix (re-emit entries whose sha= metadata went stale)"; run check --fix

# ── 5. ACCEPTANCE: no body lost, nothing invented, over EVERY source ─────────────────────────────
say "body-loss gate (the cross-tree acceptance test, all sources)"
python3 "$R8/r7-verify-body-loss.py" --trees "$R8/trees" --merged "$M" --normalise-ids --show 30 2>&1 | tail -45 | tee -a "$LOG"
say "final check (must be 0 errors)"; run check
say "index"; python3 "$TOOL" --root "$M" --no-color index 2>&1 | tail -3 | tee -a "$LOG"
df -Pk / | tail -1 | tee -a "$LOG"
say "DONE"
