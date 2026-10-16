#!/bin/bash
# 60-run.sh -- run the repair tooling on the MERGED CANDIDATE tree, unmodified, in the order the
# round-6 brief prescribes (dedupe, then repair-ids), but with BOTH the dry run and the apply of
# each, so the report can quote what each printed before it was allowed to write.
#
# NO LIVE TREE IS TOUCHED. --root is /root/work/r7/merged-journal everywhere.
# `dedupe` and `repair-ids` are DRY RUNS unless --apply is passed (they both expose --apply and
# neither writes without it); the brief's literal `dedupe` / `repair-ids` change nothing at all.
set -u
R7=/root/work/r7
M=$R7/merged-journal
TOOL="$M/tools/journal.py"
LOG=$R7/logs/run.log
: > "$LOG"

count(){ find "$M/entries" -name '*.md' -type f | wc -l; }
say(){ echo "" | tee -a "$LOG"; echo "################ $*" | tee -a "$LOG"; }
run(){ echo "---- \$ python3 journal.py --root \$MERGED $*" | tee -a "$LOG"; \
       python3 "$TOOL" --root "$M" --no-color "$@" >>"$LOG" 2>&1; \
       echo "---- exit=$?" | tee -a "$LOG"; }

echo "merged tree : $M" | tee -a "$LOG"
echo "tool        : $TOOL" | tee -a "$LOG"
sha256sum "$TOOL" | tee -a "$LOG"
echo "tool version: $(python3 -c 'import re,sys;print(re.search(r"CACHE_VERSION = (\d+)",open(sys.argv[1]).read()).group(1))' "$TOOL") (CACHE_VERSION)" | tee -a "$LOG"
echo "date -u     : $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG"
df -Pk / | tail -1 | tee -a "$LOG"
echo "entries BEFORE: $(count)" | tee -a "$LOG"

say "STEP 1  check  (BEFORE any repair; the 386 second-copy files are expected to be errors)"
run check

say "STEP 2  dedupe  -- the brief's literal command, NO --apply  (dry run)"
run dedupe

say "STEP 3  dedupe --apply"
echo "entries before dedupe --apply: $(count)" | tee -a "$LOG"
run dedupe --apply
echo "entries after  dedupe --apply: $(count)" | tee -a "$LOG"

say "STEP 4  repair-ids  -- the brief's literal command, NO --apply  (dry run)"
run repair-ids

say "STEP 5  repair-ids --apply"
echo "entries before repair-ids --apply: $(count)" | tee -a "$LOG"
run repair-ids --apply
echo "entries after  repair-ids --apply: $(count)" | tee -a "$LOG"

say "STEP 6  check  (AFTER)  -- must be 0 errors, exit 0"
run check

say "STEP 7  verify  -- the independent no-loss gate"
run verify

say "STEP 8  counts"
echo "entries FINAL: $(count)" | tee -a "$LOG"
python3 - "$M" <<'PY' | tee -a "$LOG"
import collections,hashlib,pathlib,re,sys
root=pathlib.Path(sys.argv[1])
K=("decisions","handoff","lessons","pain","wins")
MARK=re.compile(r"^<!--\s*e:(?P<k>[a-z]+)\|(?P<i>[^|]*)\|")
files=[]; ids=collections.Counter(); shas=collections.defaultdict(set)
for k in K:
    for p in sorted((root/"entries"/k).glob("*.md")):
        raw=p.read_bytes(); m=MARK.match(raw.decode("utf-8","replace").split("\n")[0])
        files.append(p); ids[m.group("i")]+=1; shas[m.group("i")].add(hashlib.sha256(raw).hexdigest())
print("entry files              %d"%len(files))
print("distinct ids             %d"%len(ids))
print("ids carried by >1 file   %d"%sum(1 for v in ids.values() if v>1))
print("distinct (id,file-sha)   %d"%sum(len(v) for v in shas.values()))
PY
df -Pk / | tail -1 | tee -a "$LOG"
du -sh "$M" | tee -a "$LOG"
echo "DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG"
