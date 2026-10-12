#!/usr/bin/env python3
"""The absence monitor for the CEO kernel sentinel.

WHY THIS EXISTS -- measured 2026-10-12, six hours of it
------------------------------------------------------
The company's authority moved from the office box to the cloud box at 2026-10-11T05:43:36Z. The
database, the API, the dashboard and the phone gate moved. The `ceo-kernel` sentinel did not -- it only
ever ran on the office box, which was then frozen as the rollback anchor. For six hours every attention
badge in the fleet rendered `6 needing attention · stale 6h ago` from a `latest.json` whose newest
sample was 2026-10-11T20:20:06Z, and the owner asked the only question that mattered: *"why does it say
stale? why is everything stable?"* Stable meant stopped.

Nothing detected it, and nothing could have:
  * the sentinel's own wrapper, `run-sentinel.sh`, **always exits 0 on purpose** -- a finding is the
    signal, not a scheduler failure -- so `cron-wrap.sh`'s ledger reads `0` for a run that senses
    nothing wrong AND for a sentinel that never ran at all;
  * the badge is honest (`stale <age>`) but it is a *reading*, not an alarm: it needs a human to look,
    understand what stale means, and care;
  * a producer cannot report its own death. The check for "the sentinel stopped" must live outside the
    sentinel.

That is the estate's own standard for this migration, in the owner's words (`docs/mesh/131-MIGRATION-
BRIEF.md` §"The standard of success"): *"a monitor that reports absence instead of silence."* This is
that monitor, and the formulation is the one `140-PORT-CORE-AND-GAPS.md` §A1 named: *"no new
history.jsonl row in 15 minutes"*.

WHAT IT DOES, AND WHAT IT DELIBERATELY DOES NOT
-----------------------------------------------
  * reads the newest row of `$CEO_KERNEL_STATE/history.jsonl` (the wrapper appends exactly one row per
    run, with `at`, `exit` and the checks that needed attention) and measures its AGE against wall
    clock. Nothing else -- no exit-code inference, no "is the process running", because the process is
    a 15-second cron job and a missing row is the only thing that distinguishes "quiet" from "dead";
  * writes a machine-readable `status.json` every run, so a human or another job can read the state
    without re-deriving it (one status file per question, in this estate's convention);
  * when the row is too old, OR the file is missing/unreadable (which is the same finding -- a refusal
    is not health), it files **one** journal `pain` entry naming the sentinel, rate-limited to one per
    `--alarm-every` seconds (default 6h) so a long outage does not bury the journal it is trying to
    reach, and exits **2** ("cannot see"), so the ledger row itself is a signal;
  * exits **0** when the sentinel is writing.

Exit codes: 0 healthy · 2 stale or unreadable. Never 1: this monitor measures absence, and conflating
"the sentinel has a finding" with "the sentinel has stopped" would recreate the exact defect above.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_STALE_SECONDS = 1200.0   # 4 missed writes of a 5-minute cron, the badge's own staleness rule
DEFAULT_ALARM_EVERY = 6 * 3600.0
DEFAULT_JOURNAL_REPO = "/root/code/harness-config"


def newest_row(hist: Path, count_limit: int = 8 << 20) -> tuple[str | None, str | None, int | None, int]:
    """The `at` of the newest row, a parse problem if there is one, the row count, and the file size.

    The count is deliberately **bounded**: this file grows by one ~590-byte line every five minutes,
    forever (about 62 MB a year), and a monitor that re-reads the whole of it every five minutes for a
    diagnostic number has quietly become a disk load that grows without limit. Past `count_limit` the
    count is `None` -- "not counted" is honest, and the size is always exact and always cheap.
    """
    if not hist.is_file():
        return None, None, None, 0
    try:
        size = hist.stat().st_size
    except OSError as exc:
        return None, f"unreadable: {exc}", None, 0
    rows: int | None = 0
    last = ""
    try:
        with hist.open("rb") as fh:
            if size <= count_limit:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    rows += chunk.count(b"\n")
            else:
                rows = None
            if size:
                back = min(65536, size)
                fh.seek(size - back)
                tail = fh.read().decode("utf-8", "replace").strip().splitlines()
                last = tail[-1] if tail else ""
    except OSError as exc:
        return None, f"unreadable: {exc}", None, size
    if not last:
        return None, None, rows, size
    try:
        row = json.loads(last)
    except ValueError:
        return None, "the newest row is not JSON", rows, size
    return row.get("at"), None, rows, size


def age_seconds(stamp: str | None, now: dt.datetime) -> float | None:
    if not stamp:
        return None
    text = stamp.strip().replace("Z", "+00:00")
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return (now - when).total_seconds()


def alarm_is_due(mark: Path, now_epoch: float, every: float) -> bool:
    try:
        last = float(mark.read_text().strip())
    except (OSError, ValueError):
        last = 0.0
    return (now_epoch - last) >= every


def file_alarm(journal_repo: str, verdict: str, detail: str, rows: int | None, age: float | None,
               size: int, state: str) -> str:
    """One journal `pain` entry. Returns what happened, for the status file.

    Uses the journal's own tool so the id is allocated the same way every other entry's is -- never by
    writing a file into `entries/` directly, which is how two entries get one id.
    """
    tool = Path(journal_repo) / "journal" / "tools" / "journal.py"
    if not tool.is_file():
        return f"not filed: {tool} does not exist"
    body = (
        "## The CEO kernel sentinel has stopped writing\n\n"
        f"**Verdict:** {verdict}\n\n"
        f"**Detail:** {detail}\n\n"
        f"- state dir: `{state}`\n"
        f"- `history.jsonl`: {size} bytes, "
        f"{'row count not taken (file is over the bounded count limit)' if rows is None else str(rows) + ' row(s)'}\n"
        f"- age of the newest row: {'unknown' if age is None else f'{age / 60:.1f} min'}\n"
        "- threshold: 20 min (four missed writes of a 5-minute cron)\n\n"
        "**Why this matters:** every \"Company findings\" item in the attention badge is computed by "
        "that sentinel. When it stops, the badge keeps rendering its last reading and labels it "
        "`stale` -- honestly, and uselessly, because nobody is watching a badge for a missing number. "
        "Measured 2026-10-12: it was left behind on a frozen host and read a six-hour-old report while "
        "the owner asked whether the company had gone quiet.\n\n"
        "**What to check, in order:** (1) is `run-sentinel` still in the root crontab "
        "(`crontab -l | grep run-sentinel`); (2) is `cron` active on this host "
        "(`systemctl is-active cron`); (3) does `run-sentinel.sh` still run by hand "
        "(`CEO_KERNEL_STATE=... CEO_KERNEL_DB=... CEO_KERNEL_AUTHORITY_HOST=... "
        "/root/ceo-kernel/scripts/run-sentinel.sh`); (4) read the tail of `run.log` and `run.err`.\n\n"
        "**Full incident and the port this protects:** `harness-config/docs/mesh/168-ATTENTION-AUTHORITY.md`.\n"
    )
    try:
        done = subprocess.run(
            [sys.executable, str(tool), "append", "pain", "--no-fetch",
             "--title", "The CEO kernel sentinel has stopped writing",
             "--tags", "monitoring,kernel,sentinel,deadman",
             "--body", body],
            capture_output=True, text=True, timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"not filed: {exc}"
    line = (done.stdout or "").strip().splitlines()
    if done.returncode != 0:
        return f"not filed: rc={done.returncode} {(done.stderr or '').strip()[:200]}"
    return line[-1] if line else f"filed (rc={done.returncode})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", default=os.environ.get("CEO_KERNEL_STATE", "/root/ceo-kernel-var"),
                    help="the kernel's state directory (holds history.jsonl)")
    ap.add_argument("--status-dir", default=os.environ.get("SENTINEL_STATUS_DIR",
                                                          "/root/.sentinel-freshness"))
    ap.add_argument("--stale-seconds", type=float,
                    default=float(os.environ.get("SENTINEL_STALE_SECONDS", DEFAULT_STALE_SECONDS)))
    ap.add_argument("--alarm-every", type=float,
                    default=float(os.environ.get("SENTINEL_ALARM_EVERY", DEFAULT_ALARM_EVERY)))
    ap.add_argument("--journal-repo", default=os.environ.get("JOURNAL_REPO", DEFAULT_JOURNAL_REPO))
    ap.add_argument("--no-alarm", action="store_true", help="measure and write status only")
    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    state = Path(args.state)
    hist = state / "history.jsonl"
    status_dir = Path(args.status_dir)
    status_dir.mkdir(parents=True, exist_ok=True)
    status_file = status_dir / "status.json"
    mark = status_dir / "last-alarm"

    stamp, parse_error, rows, size = newest_row(hist)
    age = age_seconds(stamp, now)

    if parse_error:
        state_name, verdict, detail = "unreadable", "cannot see", parse_error
    elif not hist.is_file():
        state_name, verdict = "missing", "cannot see"
        detail = f"no history file at {hist} — the sentinel has never run here, or its state dir moved"
    elif stamp is None:
        state_name, verdict = "unreadable", "cannot see"
        detail = f"{hist} has {rows} row(s) but none of them is a readable timestamp"
    elif age is None:
        state_name, verdict = "unreadable", "cannot see"
        detail = f"the newest row's `at` is not a timestamp: {stamp!r}"
    elif age > args.stale_seconds:
        state_name, verdict = "stale", "stopped"
        detail = (f"the newest row is {age / 60:.1f} min old "
                  f"(threshold {args.stale_seconds / 60:.0f} min) — the sentinel has stopped writing")
    else:
        state_name, verdict, detail = "ok", "writing", f"newest row {age:.0f}s old"

    alarm = "not needed"
    if state_name != "ok" and not args.no_alarm:
        if alarm_is_due(mark, now.timestamp(), args.alarm_every):
            alarm = file_alarm(args.journal_repo, verdict, detail, rows, age, size, str(state))
            # The marker is written on ANY attempt, successful or not, and deliberately not keyed on
            # the wording of the message it returned: a journal tool that is missing or that fails must
            # be rate-limited too, or a broken alarm path retries every five minutes forever and the
            # alarm becomes the outage. (Measured: the first version of this file keyed the marker on
            # the message prefix, the stub in the test returned a different prefix, and the alarm fired
            # on every run -- the test caught a bug that would have buried the journal it writes to.)
            try:
                mark.write_text(f"{now.timestamp():.0f}\n")
            except OSError as exc:
                alarm += f" | marker not written: {exc}"
        else:
            alarm = "rate-limited (already alarmed recently)"

    payload = {
        "checked_at": now.isoformat(),
        "state": state_name,
        "verdict": verdict,
        "detail": detail,
        "newest_row_at": stamp,
        "age_seconds": None if age is None else round(age, 1),
        "rows": rows,
        "bytes": size,
        "stale_seconds": args.stale_seconds,
        "history": str(hist),
        "alarm": alarm,
    }
    tmp = status_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(status_file)

    print(f"sentinel-freshness: {state_name} — {detail} "
          f"(bytes={size}, rows={rows if rows is not None else 'not counted'}, alarm={alarm})")
    return 0 if state_name == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
