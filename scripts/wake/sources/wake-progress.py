#!/usr/bin/env python3
"""FLAG SOURCE: the fleet stopped producing, and no surface said so.

THE SIGNAL
----------
`~/.sms-inbox/wake-dispatch.log`, one line per release written by `wake-dispatch.sh`:
`<ISO-8601 Z> released <day> wake #<n> (<subject>) ... exit=<code> ...`.

WHY THIS EXISTS, measured 2026-10-18 on the authority
-----------------------------------------------------
The wake fleet's own history, read out of that log:

    2026-10-13  ok=144  failed=2
    2026-10-14  ok=146  failed=1
    2026-10-15  ok=139  failed=10
    2026-10-16  ok=139  failed=6      <- last release 2026-10-16T16:4xZ
    2026-10-17  ok=0    failed=0      <- NOTHING. No line was written at all.
    2026-10-18  ok=124  failed=4      <- first release 2026-10-18T00:0xZ

A **32-hour hole** in which the fleet built nothing. The cause was found in a shift's own
outcome line: the office desktop `zabz-tech-ts`, which every release is dispatched to
(`DESKTOP=${WAKE_DESKTOP:-zabz-tech-ts}`, one host, no fallback), was asleep — "its OpenSSH log
has no connection from the authority accepted between 2026-10-16 10:00 local and 2026-10-17
23:45". For most of that hole the dispatcher was in fact still trying and being refused rc=1
on the SSH hop; on the 17th it wrote no release line at all.

Not one guard fired. The authority's own deadman (`authority-deadman.service`) pings
healthchecks.io to prove the AUTHORITY is alive — it was, the whole time. `wake-tuner.py` emits
one cost digest a day and said "already emitted". `wake-lock-watch` watches the SQLite write
lock, which was never held. So the only record of a 32-hour production stop was 133 consecutive
`rc=1` rows in a log nobody reads, and the owner found out by asking "is it building daily?".

A fleet whose silence is indistinguishable from its health is not autonomous; it is a machine
that has to be asked.

A CAP IS NOT A STALL — measured 2026-10-19, and this is the false alarm this file used to file.
On 2026-10-18 the fleet reached its DELIBERATE release-count ceiling (`daily_cap: 150/150
releases today`) at 16:05Z. Every fan-out tick after that refused with `daily-cap` and wrote no
release line; the last success had been 16:09Z (a session claimed before the cap). At 22:37Z
this source read the silence as a stall and filed a p2 item — item 641 — whose `why` asserted the
single-desktop theory as fact even though the log held NO failed release in the window (0/0).
The gate reset at 00:00Z and seven releases started within ten seconds. A ceiling that is
supposed to stop the fleet is not evidence that the fleet is broken, and an alarm that fires
every evening for eight hours is not an alarm.

So before filing, ask the RELEASE PATH itself (`wake.py stats --json`, the same `caps_in_force`
list `wake-fanout.sh` and `wake-nextclaim.py` read) whether a whole-queue gate is in force. For
the automatic budget ceilings (`daily_cap`, `cost_cap`), if the fleet has not even ATTEMPTED a
release since its last success, the silence is the gate, not a fault: print `capped` and file
nothing. `paused` is deliberately different: a kill switch may be a deliberate stop OR a pause
someone forgot (the 2026-10-14 one-way door), so a paused fleet still files an item that NAMES
the pause. If a release was attempted and failed after the last success, the gate does not
explain that failure and the item is still filed. An unreadable gate never suppresses: the stall
item still files, and its `why` says the gate state could not be read.

THRESHOLDS (all env-overridable)
    WAKE_STALL_HOURS     6     no SUCCESSFUL release for this long = stalled
    WAKE_STALL_MIN_BAD   3     and/or at least this many consecutive failures inside the window
    WAKE_DISPATCH_LOG    ~/.sms-inbox/wake-dispatch.log
    WAKE_CLI             ~/bin/wake.py   the release path whose caps_in_force is authoritative

EXIT CODES — the distinction matters more than the alarm
    0  healthy   a successful release inside the window, OR the silence is a whole-queue
                 gate (paused / daily cap / cost cap) that the release path is enforcing
    1  STALLED   an item was filed naming the episode
    4  REFUSED   the log is missing or holds no release line at all, so this source cannot
                 answer. A refusal is NOT a negative: it must never be reported as "quiet".

MUST NEVER
    - write, truncate or rotate the dispatch log (this is a reader);
    - file the same episode twice (`work.py add` dedupes an open title, and the title carries the
      episode's own start time so a NEW stall is a NEW item);
    - restart, retry or re-dispatch anything itself. The session that claims the item does that,
      with the evidence in front of it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG = Path(os.environ.get("WAKE_DISPATCH_LOG") or (Path.home() / ".sms-inbox" / "wake-dispatch.log"))
STALL_HOURS = float(os.environ.get("WAKE_STALL_HOURS") or 6)
MIN_BAD = int(os.environ.get("WAKE_STALL_MIN_BAD") or 3)
WORK_CLI = os.environ.get("WORK_CLI") or str(Path.home() / "bin" / "work.py")
WAKE_CLI = os.environ.get("WAKE_CLI") or str(Path.home() / "bin" / "wake.py")
PROJECT = os.environ.get("WAKE_STALL_PROJECT") or "housekeeping"

# The same tokens `wake-nextclaim.py` treats as BLOCKING, because these are the only entries
# `wake.py`'s release_block() refuses the whole queue on. source_cap / night_quiet are per-row
# gates and do not stop the fleet, so they must not silence this alarm.
BLOCKING = {"paused": "paused", "daily_cap": "daily-cap", "cost_cap": "cost-cap"}
# Only the automatic budget ceilings explain a silence without anyone acting. `paused` is a
# kill switch: it may be a deliberate stop, but it may also be a pause someone forgot (the
# 2026-10-14 one-way door), so a paused fleet still files an item — one that NAMES the pause.
AUTO_GATES = {"daily-cap", "cost-cap"}

RELEASE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)Z\s+released\s+.*?\bexit=(\d+)\b")


def release_gate():
    """(name, detail) of the whole-queue gate the release path is refusing on, or (None, why-not).

    Read-only, and it does not re-implement the predicate: it asks `wake.py stats --json` for
    the `caps_in_force` list that the dispatcher itself gates on. Never raises. The second
    element says why no gate was returned when the read failed, so the caller can report it
    instead of silently treating an unreadable gate as "no gate".
    """
    try:
        proc = subprocess.run(["python3", WAKE_CLI, "stats", "--json"],
                              capture_output=True, text=True, timeout=90)
        if proc.returncode != 0 or not (proc.stdout or "").strip():
            return None, "wake.py stats rc=%d with no JSON on stdout" % proc.returncode
        doc = json.loads(proc.stdout or "{}")
        if not doc.get("ok", True):
            return None, "wake.py answered not-ok"
        for entry in doc.get("caps_in_force") or []:
            head = str(entry).split(":", 1)[0].strip()
            if head in BLOCKING:
                return BLOCKING[head], str(entry)
    except Exception as exc:  # noqa: BLE001 - a reader must say it could not read, never crash
        return None, "%s: %s" % (type(exc).__name__, exc)
    return None, None


def parse(path: Path):
    """[(datetime, rc)] oldest first, plus the count of unparsable 'released' lines."""
    rows, unparsed = [], 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if " released " not in line:
                continue
            m = RELEASE.match(line)
            if not m:
                unparsed += 1
                continue
            try:
                ts = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                unparsed += 1
                continue
            rows.append((ts, int(m.group(2))))
    return rows, unparsed


def file_item(title: str, why: str, dod: str) -> int:
    payload = {"project": PROJECT, "title": title, "why": why, "dod": dod,
               "priority": 2, "source": "wake-progress"}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(payload, fh)
        path = fh.name
    try:
        proc = subprocess.run([sys.executable, WORK_CLI, "add", "--from-json", path],
                              capture_output=True, text=True, timeout=120)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    blob = (out + err).lower()
    # `work.py add` REFUSES an identical open title on purpose and says so with
    # {"already-filed": ...} on stdout and exit 2. That is the dedupe working, not a fault.
    if "already-filed" in blob or "duplicate" in blob or "exists" in blob:
        print("wake-progress: %s (already filed)" % title)
        return 0
    if proc.returncode != 0:
        print("wake-progress: work.py add failed rc=%d: %s" % (proc.returncode, (err or out)[:200]))
        return 4
    print("wake-progress: filed %s" % (out.splitlines()[0] if out else title))
    return 0


def main() -> int:
    if not LOG.is_file():
        print("wake-progress: REFUSED - no dispatch log at %s, so this source cannot answer" % LOG)
        return 4
    rows, unparsed = parse(LOG)
    if not rows:
        print("wake-progress: REFUSED - %s holds no parsable 'released ... exit=' line (%d unparsable), "
              "so this source cannot answer" % (LOG, unparsed))
        return 4

    now = datetime.now(timezone.utc)
    ok_rows = [r for r in rows if r[1] == 0]
    if not ok_rows:
        print("wake-progress: REFUSED - %d releases in the log and NOT ONE succeeded; that is a "
              "different fault from a stall and needs a human, not a filed item" % len(rows))
        return 4

    last_ok = ok_rows[-1][0]
    age_h = (now - last_ok).total_seconds() / 3600.0
    window = [r for r in rows if (now - r[0]) <= timedelta(hours=STALL_HOURS)]
    ok_in_window = [r for r in window if r[1] == 0]
    bad_in_window = [r for r in window if r[1] != 0]

    if age_h > STALL_HOURS:
        gate, gate_detail = release_gate()
        last_attempt = rows[-1][0]
        # A CAP IS NOT A STALL. An automatic budget gate explains the silence ONLY when the
        # fleet has not even attempted a release since its last success; then there is no
        # failure to diagnose, only a deliberate ceiling doing its job (measured 2026-10-18/19:
        # the daily cap held from 16:05Z to 00:00Z and this source filed item 641 against it).
        # `paused` is deliberately NOT in AUTO_GATES: a stuck pause must still reach the ledger.
        if gate in AUTO_GATES and last_attempt <= last_ok:
            print("wake-progress: capped - last success %sZ, %.1f h ago, but the release path is "
                  "refusing under %s (%s) and has attempted nothing since; this is the gate, not a "
                  "stall" % (last_ok.strftime("%Y-%m-%dT%H:%M"), age_h, gate, gate_detail))
            return 0
        if gate == "paused" and last_attempt <= last_ok:
            cap_note = ("The release path is PAUSED (%s) and has attempted nothing since the last "
                        "success. A pause is a kill switch, not proof of a fault and not proof of "
                        "health: confirm whether it should still be in force before resuming."
                        % gate_detail)
        elif gate:
            cap_note = ("The release path reports whole-queue gate %s (%s), but a release was "
                        "attempted after the last success, so the gate does not explain the failure."
                        % (gate, gate_detail))
        elif gate_detail:
            cap_note = ("The release path's own gate could not be read (%s), so this item cannot say "
                        "whether a deliberate cap explains the silence." % gate_detail)
        else:
            cap_note = ("The release path reports NO whole-queue gate in force (wake.py caps_in_force "
                        "carries no daily_cap/paused/cost_cap), so a deliberate cap does not explain "
                        "this silence.")
        title = "Wake fleet stalled: no successful release since %sZ" % last_ok.strftime("%Y-%m-%dT%H:%M")
        why = ("Measured this run from %s: newest successful release is %sZ, %.1f h ago (threshold %.0f h). "
               "In the last %.0f h there were %d releases, %d of them non-zero. %s The 2026-10-16/17 "
               "hole was 32 h and no guard fired, which is why this source files an item at all."
               % (LOG, last_ok.strftime("%Y-%m-%dT%H:%M"), age_h, STALL_HOURS, STALL_HOURS,
                  len(window), len(bad_in_window), cap_note))
        dod = ("A successful release is present in %s with a timestamp newer than %sZ, quoted from the log, "
               "AND the reason the fleet stopped is named with its fix, not merely restarted (host asleep / "
               "ssh refused / no fallback / a whole-queue gate that should not have been in force). If a "
               "second dispatch target or a wake-on-demand is added, quote the config line and one real "
               "release that used it." % (LOG, last_ok.strftime("%Y-%m-%dT%H:%M")))
        print("wake-progress: STALLED - last success %sZ, %.1f h ago, %d/%d failed in window"
              % (last_ok.strftime("%Y-%m-%dT%H:%M"), age_h, len(bad_in_window), len(window)))
        # 1 = the stall is real; 5 = the stall is real AND the item could not be filed, which is a
        # different thing to fix and must not read as the same line in the sources log.
        return 1 if file_item(title, why, dod) == 0 else 5

    if not ok_in_window and len(bad_in_window) >= MIN_BAD:
        title = "Wake fleet is releasing and every release is failing (since %sZ)" % last_ok.strftime("%Y-%m-%dT%H:%M")
        why = ("%d releases in the last %.0f h and none succeeded; last success %sZ. Read the release lines, "
               "not the unit state: rc=1 on the SSH hop and a model that refuses to boot both look like this."
               % (len(bad_in_window), STALL_HOURS, last_ok.strftime("%Y-%m-%dT%H:%M")))
        dod = ("A release after this item that exits 0 with its line quoted from %s, and the failing line's "
               "own diagnostic quoted to show it is the same fault." % LOG)
        print("wake-progress: ALL FAILING - %d releases in %.0f h, 0 ok" % (len(bad_in_window), STALL_HOURS))
        file_item(title, why, dod)
        return 1

    print("quiet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
