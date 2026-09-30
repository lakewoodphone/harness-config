set -u
cp -a /home/zabz/bin/autonomy-status.sh /home/zabz/bin/autonomy-status.sh.bak-value-line-$(date -u +%Y%m%dT%H%M%SZ)
python3 - <<'PY'
import re, sys
p = "/home/zabz/bin/autonomy-status.sh"
src = open(p, encoding="utf-8").read()
if "wake-value.py" in src:
    print("SKIP: already patched"); raise SystemExit(0)
anchor = "\nPY\nexit 0"
if src.count(anchor) != 1:
    raise SystemExit("FAIL: the closing PY/exit anchor is not unique (%d) - nothing written" % src.count(anchor))
add = ("\nPY\n"
       "# VALUE AND BUDGET, in one read. Items closed today, dollars per closed item, and the spend against\n"
       "# the ceiling the queue itself enforces - so a reader can never be shown a cap no process honours.\n"
       "python3 \"${WAKE_VALUE:-/home/zabz/bin/wake-value.py}\" 2>/dev/null || true\n"
       "exit 0")
src = src.replace(anchor, add, 1)
open(p, "w", encoding="utf-8").write(src)
print("patched autonomy-status.sh")
PY
bash -n /home/zabz/bin/autonomy-status.sh && echo "status syntax OK"
echo "--- the two new lines, live ---"
bash /home/zabz/bin/autonomy-status.sh 2>&1 | tail -4
echo "--- standalone, and against a copy of the ledger to prove it never invents a zero ---"
python3 /home/zabz/bin/wake-value.py
WORK_DB=/tmp/does-not-exist.db python3 /home/zabz/bin/wake-value.py
