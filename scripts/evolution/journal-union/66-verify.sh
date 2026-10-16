#!/bin/bash
# 66-verify.sh -- re-run the gates on the merged candidate AFTER the stem normalisation, and get
# `verify` to run at all.
#
# `verify.py` computes SRC = Path(__file__).resolve().parent.parent.parent and loads the frozen v1
# parser from SRC/"journal"/"tools"/"archive"/"journal-v1.py". For a candidate root at
# /root/work/r7/merged-journal that resolves to /root/work/r7/journal/tools/archive/journal-v1.py,
# which does not exist, and `verify` dies with FileNotFoundError before reading a single entry.
# This is a defect in verify.py, not in the merged tree: the brief's own command
# `journal.py --root /root/work/r7/merged-journal verify` has never been runnable away from a
# checkout named `journal/`.
#
# The workaround is a SYMLINK in this job's own work directory -- /root/work/r7/journal ->
# merged-journal -- so SRC/"journal" resolves to the tree under test. Nothing live is touched.
set -u
R7=/root/work/r7
M=$R7/merged-journal
LOG=$R7/logs/verify.log
: > "$LOG"
say(){ echo "" | tee -a "$LOG"; echo "################ $*" | tee -a "$LOG"; }
run(){ echo "---- \$ python3 journal.py --root \$MERGED $*" | tee -a "$LOG"; \
       python3 "$M/tools/journal.py" --root "$M" --no-color "$@" >>"$LOG" 2>&1; \
       echo "---- exit=$?" | tee -a "$LOG"; }

echo "date -u : $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG"

say "AFTER NORMALISATION: check  -- this is the line the brief asks to be 0 errors"
run check

say "VERIFY WITHOUT THE WORKAROUND (proves the crash, not the tree)"
python3 "$M/tools/journal.py" --root "$M" --no-color verify >>"$LOG" 2>&1
echo "---- exit=$?  (above: the raw failure)" | tee -a "$LOG"

say "SET UP THE WORKAROUND: /root/work/r7/journal -> merged-journal"
if [ ! -e "$R7/journal" ]; then ln -s "$M" "$R7/journal"; fi
ls -la "$R7/journal" | tee -a "$LOG"
echo "frozen v1 parser now resolves to: $(readlink -f $R7/journal/tools/archive/journal-v1.py)" | tee -a "$LOG"

say "VERIFY THROUGH THE WORKAROUND"
run verify

say "RE-RUN 60-run STEP 8 COUNTS"
echo "entry files: $(find $M/entries -name '*.md' | wc -l)" | tee -a "$LOG"
python3 - "$M" <<'PY' | tee -a "$LOG"
import collections,hashlib,pathlib,re,sys
root=pathlib.Path(sys.argv[1]); K=("decisions","handoff","lessons","pain","wins")
MARK=re.compile(r"^<!--\s*e:(?P<k>[a-z]+)\|(?P<i>[^|]*)\|")
files=[]; ids=collections.Counter(); shas=collections.defaultdict(set); bodies=collections.Counter()
for k in K:
    for p in sorted((root/"entries"/k).glob("*.md")):
        raw=p.read_bytes(); m=MARK.match(raw.decode("utf-8","replace").split("\n")[0])
        files.append(p); ids[m.group("i")]+=1; shas[m.group("i")].add(hashlib.sha256(raw).hexdigest())
print("entry files              %d"%len(files))
print("distinct ids             %d"%len(ids))
print("ids carried by >1 file   %d"%sum(1 for v in ids.values() if v>1))
print("distinct (id,file-sha)   %d"%sum(len(v) for v in shas.values()))
PY
du -sh "$M" | tee -a "$LOG"
df -Pk / | tail -1 | tee -a "$LOG"
echo "DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG"
