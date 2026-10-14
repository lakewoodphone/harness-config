#!/usr/bin/env python3
"""Apply the exit-code fix to liveness_probe.main, and prove it with a test that discriminates.

THE DEFECT, measured on the authority 2026-10-14 22:38Z. `main()` ended with

    return 0 if result["ok"] else 1

so a probe that RAN CORRECTLY and DETECTED A FAILURE exited 1. Under `Type=oneshot` that marks
`r4-liveness-probe.service` **failed** — `systemctl is-failed` → `failed` — on every real outage.
Two consequences, both bad:

  1. The unit's failure state stops meaning "the probe broke". When the API wedges, systemd shouts
     about the probe instead, and a genuine probe crash becomes indistinguishable from a genuine
     outage.
  2. `systemctl --failed` becomes a place where an expected condition sits permanently, which is how
     people learn to ignore it. The whole point of this probe is the opposite: it exists because a
     wedge was invisible for 50 minutes (`H3660`).

WHAT IT SHOULD BE. The probe's `ok` belongs in `state.json`, which is where the consecutive-failure
count and the escalation threshold already live. The exit code should answer a different question:
*did the probe complete its check?* It exits 0 when it checked, and non-zero only when the check
could not be performed at all (a bug, a bad state path, no JSON).

VERIFICATION, in this script:
  * the new test FAILS on the unpatched file and PASSES after (both result lines printed);
  * the pre-existing tests in the same file are unchanged in their verdicts.
"""
from __future__ import annotations

import os
import subprocess
import sys

TARGET = "/root/work/r4-transport/app/services/liveness_probe.py"
TEST = "/root/work/r4-transport/tests/test_r4_probe_exit_code.py"
PY = "/opt/company/.venv/bin/python3"

OLD = '''    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1
'''

NEW = '''    print(json.dumps(result, sort_keys=True))
    # THE EXIT CODE ANSWERS "DID THE PROBE COMPLETE A CHECK?", NOT "WAS THE VERDICT POSITIVE?".
    #
    # Measured 2026-10-14 on the authority: returning 1 on a negative verdict marked
    # `r4-liveness-probe.service` FAILED on every real outage, so the unit's failure state stopped
    # meaning "the probe is broken" and started meaning "the thing exists that the probe is for".
    # `systemctl --failed` then carries an expected condition permanently, which is how an alarm is
    # taught to be ignored -- the opposite of this probe's purpose, which is that a silent wedge was
    # invisible for over 50 minutes (`H3660`).
    #
    # The verdict already lives where a consumer reads it: `state.json`, with the consecutive-failure
    # count and the escalation outcome. So this returns success whenever the check RAN, and a small
    # non-zero only when it genuinely could not run.
    if result.get("checked_at") is None:
        return 2
    return 0
'''

TEST_SRC = '''"""A negative liveness verdict is not a failed unit."""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "/root/work/r4-transport")

from app.services import liveness_probe as lp  # noqa: E402


def test_a_detected_failure_still_exits_zero(tmp_path):
    """The probe ran and found the API wedged: the run SUCCEEDED, the verdict did not.

    Under Type=oneshot, exit 1 here marks the unit failed, which buries a real probe crash under
    the expected condition this probe exists to report.
    """
    state = tmp_path / "state.json"
    rc = lp.main([
        "--state-path", str(state),
        "--base-url", "http://127.0.0.1:9",   # nothing listens on port 9: connection refused
        "--no-escalate",
    ])
    assert rc == 0, f"a detected failure must not fail the unit; got rc={rc}"
    written = json.loads(state.read_text())
    assert written["consecutive_failures"] == 1
    assert written["last_result"]["ok"] is False


def test_the_verdict_is_in_the_state_file_not_the_exit_code(tmp_path):
    """What a consumer needs is readable after the fact, whichever way the exit code went."""
    state = tmp_path / "state.json"
    lp.main(["--state-path", str(state), "--base-url", "http://127.0.0.1:9", "--no-escalate"])
    last = json.loads(state.read_text())["last_result"]
    assert last["url"].endswith("/health")
    assert "detail" in last and last["detail"]
    assert "checked_at" in last and "elapsed_ms" in last
'''


def run(cmd: list[str], cwd: str | None = None) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    src = open(TARGET).read()
    open(TEST, "w").write(TEST_SRC)

    print("=== 1. the new test against the UNPATCHED file (must FAIL)")
    rc_before, out_before = run(
        [PY, "-m", "pytest", TEST, "-q", "--basetemp=/root/work/r4-transport/_pt_exit_before"])
    print(out_before.strip().splitlines()[-1] if out_before.strip() else "(no output)")

    if OLD not in src:
        print("REFUSING: the expected unpatched text is not present in the file.")
        print("  (has it already been patched, or did the builder write it differently?)")
        return 3
    open(TARGET, "w").write(src.replace(OLD, NEW, 1))
    print("=== patched", TARGET)

    print("=== 2. the new test against the PATCHED file (must PASS)")
    rc_after, out_after = run(
        [PY, "-m", "pytest", TEST, "-q", "--basetemp=/root/work/r4-transport/_pt_exit_after"])
    print(out_after.strip().splitlines()[-1] if out_after.strip() else "(no output)")

    print("=== 3. the pre-existing suite, unchanged by this edit")
    rc_old, out_old = run([PY, "-m", "pytest", "/root/work/r4-transport/tests/test_r4_liveness_and_ceiling.py",
                           "-q", "--basetemp=/root/work/r4-transport/_pt_exit_old"])
    print(out_old.strip().splitlines()[-1] if out_old.strip() else "(no output)")

    ok = rc_before != 0 and rc_after == 0
    print(f"=== VERDICT: discriminating={ok} (before rc={rc_before}, after rc={rc_after})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
