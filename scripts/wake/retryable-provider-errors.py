#!/usr/bin/env python3
"""wake.py: a transient provider refusal must not fail the subject or consume its attempt.

Ledger item 159. Measured 2026-09-30: five releases started inside twelve seconds and every one died in
about 21 seconds with the provider's own words, `dsh: QUOTA: Insufficient Balance`, while the account
answered is_available true with a balance of 48.94 and the next batch ran clean. The attempt is spent at
CLAIM time (`attempts=attempts+1` in the claim statement), so a flake is indistinguishable from a real
failure and costs one of max_attempts; subjects 133, 153 and 154 sat at 1 of 2, one flake from losing their
work for ever with nothing recorded.

AFTER: `finish --failed` whose outcome matches a transient signature puts the row back to `new`, refunds the
attempt, clears the claim and sets not_before ten minutes out, recording which signature matched. Everything
else still fails exactly as before. The signature list is deliberately narrow - it matches only what a
provider or a socket says about ITSELF, never a test failure or an agent error.

Verifies itself on a COPY of the store when the store path is env-overridable, so no live row is touched.
"""
import os
import re
import shutil
import subprocess
import sys
import time

WAKE = "/home/zabz/bin/wake.py"

HELPER = '''

# A TRANSIENT REFUSAL IS NOT A FAILED SUBJECT. The attempt is spent at CLAIM time, so without this a flake
# that kills a session consumes one of max_attempts and, on the second, ends the subject for good with its
# work silently lost. Measured 2026-09-30: five releases in one twelve-second burst died in about 21 seconds
# with "dsh: QUOTA: Insufficient Balance" while the account answered is_available true, balance 48.94.
_RETRY_AFTER_SEC = 600
_RETRYABLE_SIGNATURES = (
    "quota", "insufficient balance", "rate_limit", "rate limit", "too many requests",
    "429", "502", "503", "service unavailable", "overloaded",
    "timeout", "timed out", "transport", "connection reset", "broken pipe", "connection refused",
)


def _retryable_reason(outcome: str):
    """The matched transient signature, or None when this looks like a genuine failure."""
    low = (outcome or "").lower()
    for sig in _RETRYABLE_SIGNATURES:
        if sig in low:
            return sig
    return None


def cmd_finish(args) -> int:'''

OLD_BODY = '''        conn.execute(
            """UPDATE wake SET state=?, finished_at=?, outcome=?,
                   cost_usd=COALESCE(?, cost_usd), lease_until=NULL WHERE id=?""",
            (state, now(), args.outcome or "", cost, args.id),
        )
        if state == "failed" and row["state"] != "failed":
            _bump_budget(conn, failed=1)'''

NEW_BODY = '''        why = _retryable_reason(args.outcome or "") if state == "failed" else None
        if why:
            retry_at = (now_dt() + timedelta(seconds=_RETRY_AFTER_SEC)).isoformat(timespec="seconds")
            conn.execute(
                """UPDATE wake SET state='new', claimed_by=NULL, claimed_at=NULL, lease_until=NULL,
                       attempts=MAX(0, attempts-1), not_before=?, outcome=?
                   WHERE id=?""",
                (retry_at, "retryable: %s - attempt refunded, retrying after %ss" %
                 (why, _RETRY_AFTER_SEC), args.id),
            )
            state = "retry"
            sys.stderr.write("wake: #%s transient (%s) - back to new, attempt refunded, retry after %ss\\n"
                             % (args.id, why, _RETRY_AFTER_SEC))
        else:
            conn.execute(
                """UPDATE wake SET state=?, finished_at=?, outcome=?,
                       cost_usd=COALESCE(?, cost_usd), lease_until=NULL WHERE id=?""",
                (state, now(), args.outcome or "", cost, args.id),
            )
            if state == "failed" and row["state"] != "failed":
                _bump_budget(conn, failed=1)'''

src = open(WAKE, encoding="utf-8").read()
if "_RETRYABLE_SIGNATURES" in src:
    sys.exit("SKIP: already patched")
if src.count("\ndef cmd_finish(args) -> int:") != 1:
    sys.exit("FAIL: cmd_finish anchor not unique - nothing written")
if src.count(OLD_BODY) != 1:
    sys.exit("FAIL: the finish body anchor was not found exactly once - nothing written")
src = src.replace("\ndef cmd_finish(args) -> int:", HELPER, 1)
src = src.replace(OLD_BODY, NEW_BODY, 1)

stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
shutil.copy2(WAKE, "%s.bak-retryable-%s" % (WAKE, stamp))
tmp = WAKE + ".tmpnew"
open(tmp, "w", encoding="utf-8").write(src)
os.chmod(tmp, os.stat(WAKE).st_mode)
os.replace(tmp, WAKE)
print("patched %s (backup .bak-retryable-%s)" % (WAKE, stamp))

subprocess.run(["python3", "-c", "import ast;ast.parse(open('%s').read())" % WAKE], check=True)
print("syntax OK")

# Self-test on a COPY of the store, so no live row is touched. Only runs if the path is env-overridable.
env = re.search(r'os\.environ(?:\.get)?\(?\[?"(WAKE_[A-Z_]*DB[A-Z_]*)"', src) or \
      re.search(r'"(WAKE_[A-Z_]*DB[A-Z_]*)"', src)
var = env.group(1) if env else None
print("store env override:", var or "NOT FOUND")
if not var:
    sys.exit(0)

live = os.path.expanduser("~/.sms-inbox/inbox.db")
copy = "/tmp/wake-retryable-test.db"
shutil.copy2(live, copy)
E = dict(os.environ)
E[var] = copy
run = lambda *a: subprocess.run(["python3", WAKE] + list(a), env=E, capture_output=True, text=True)
run("flag", "--subject", "retryable-selftest-20260930", "--prompt", "selftest",
    "--kind", "selftest", "--priority", "low", "--json")
claim = run("claim", "--by", "selftest", "--json")
rid = None
try:
    import json as _j
    rid = _j.loads(claim.stdout)["row"]["id"]
except Exception:
    pass
if rid is None:
    sys.exit("selftest: could not claim a row (flag/claim output: %s)" % (claim.stdout or claim.stderr)[:200])
before = subprocess.run(["sqlite3", "-readonly", copy,
                         "select state,attempts,not_before from wake where id=%d" % rid],
                        capture_output=True, text=True).stdout.strip()
out = run("finish", str(rid), "--failed", "--outcome",
          "dsh: QUOTA: Insufficient Balance (request_id: selftest)", "--json")
after = subprocess.run(["sqlite3", "-readonly", copy,
                        "select state,attempts,substr(not_before,1,16),substr(outcome,1,40) from wake where id=%d" % rid],
                       capture_output=True, text=True).stdout.strip()
print("selftest row %d" % rid)
print("  before (claimed):", before)
print("  finish output   :", (out.stdout or out.stderr).strip()[:140])
print("  after           :", after)
print("  EXPECTED state=new attempts=0 with a not_before about 10 minutes out")
os.remove(copy)
