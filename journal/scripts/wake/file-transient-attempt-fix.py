#!/usr/bin/env python3
"""File one ledger item: a transient provider error must not consume an attempt.

MEASURED 2026-09-30 on ZABZ-TECH. Five releases started inside 12 seconds at 15:30:05-15:30:12Z and every
one died in about 21 seconds with the provider's own words in the runner output:

    dsh: QUOTA: Insufficient Balance (request_id: 50aa8493-e9db-4755-9963-c0b7039c4909)
    === exit code: 1 ===   elapsed: 21s

The account was NOT out of money: both the authority's key and the desktop's key answered
`is_available: true, balance 49.10` within the same hour, and the next batch at 15:45 ran clean. So the
error is transient - a burst the provider refused - and the system has no way to tell that apart from a real
failure. The consequence is permanent: subject 133, 153 and 154 are `failed` at 1 of 2 attempts, so one more
transient refusal kills those subjects for good, and the work behind them is silently lost.
"""
import re
import subprocess
import sys

WORK = "/home/zabz/bin/work.py"
TITLE = ("Wake: a transient provider error must not consume an attempt or fail the subject")
DOD = ("Kill a run mid-flight with a simulated provider refusal and show all three: the row returns to "
       "state new (not failed), its attempts counter is UNCHANGED, and not_before is set about 10 minutes "
       "out with the reason recorded. Then show a genuine failure (a nonzero exit with no transient "
       "signature) still increments attempts and still fails. Quote both runs and the row before and after.")
WHY = ("Measured 2026-09-30: five releases in one 12-second burst died with 'dsh: QUOTA: Insufficient "
       "Balance' in about 21 seconds each, while the same account answered is_available true with a balance "
       "of 49.10 and the next batch ran clean. Subjects 133, 153 and 154 are now failed at 1 of 2 attempts, "
       "so one more transient refusal loses that work permanently and silently. Transient signatures to "
       "treat as retryable rather than failed: QUOTA, Insufficient Balance, RATE_LIMIT, 429, TIMEOUT, "
       "TRANSPORT, connection reset, broken pipe, and a nonzero exit whose output contains none of the "
       "agent's own answer. This is the same class as the 16 all-time rows whose outcome is the ssh banner: "
       "the system cannot distinguish 'the provider refused' from 'the work failed'.")

args = ["python3", WORK, "add", "--project", "housekeeping", "--title", TITLE, "--dod", DOD,
        "--why", WHY, "--priority", "1", "--source", "audit-20260930-round3"]
p = subprocess.run(args, capture_output=True, text=True, timeout=120)
out = ((p.stdout or "") + (p.stderr or "")).strip()
print(out[:400] or "no output at all")
sys.exit(0 if ("item-filed" in out or "already-filed" in out) else 1)
