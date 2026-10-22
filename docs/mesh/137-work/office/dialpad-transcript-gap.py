#!/usr/bin/env python3
"""Backfill the calls that have a recording and NO transcript at all.

WHY THIS ONE AND NOT THE GENERAL RETRANSCRIBE. Measured on the authority,
2026-09-14: 4,298 downloaded recordings have never been re-transcribed, but 3,181 of
those calls already carry Dialpad's own transcript — replacing a readable transcript
with a cleaner one is a quality improvement. The other **1,117 carry no transcript at
all**: 35.4 hours of customer conversation that no search can reach, and the reason a
recent voicemail shows up in the index as nothing but a phone number. Those come
first, because for them the transcript is the difference between searchable and
invisible.

WHAT IT COSTS. OpenAI `whisper-1` is $0.006/audio-minute; the measured gap is 2,125
minutes, so about **$13**. The `--max-minutes` guard (default 2,400) stops the run
before it can spend more than ~$15 even if the selection query is wrong.

HOW IT SELECTS. Calls with a local media file, no `transcription_text`, and no
successful re-transcript; newest first, because a recent customer is more likely to
be live business than one from last November. It is idempotent — a re-run continues
where the last one stopped — so it can be run in batches from cron or by hand.

USAGE
  .venv/bin/python scripts/dialpad-transcript-gap.py --limit 50
  .venv/bin/python scripts/dialpad-transcript-gap.py --limit 1500 --max-minutes 2400
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dialpad_call_reconciliation import (  # noqa: E402
    _audio_file_problem,
    transcribe_downloaded_recordings,
)

# ── PORTER'S NOTE (2026-10-11, migration workstream 138) ─────────────────────
# The office default was `ROOT / "data" / "secretary.db"`. On the cloud box that
# resolves to /opt/company/data/secretary.db, a STALE 1,826,816-byte local copy
# that HAS NO `dialpad_call_full` TABLE at all (measured 2026-10-11 06:31Z) — the
# live authority is /root/authority.db (dialpad_call_full: 13,995 rows,
# dialpad_media_file: 7,069 rows). The app reads settings.database_url
# (DATABASE_URL in /opt/company/.env = sqlite:////root/authority.db); this script
# now does the same thing instead of keeping a second, wrong answer.
# SECRETARY_DB overrides it, for a run against a snapshot.
def _secretary_db() -> Path:
    override = os.environ.get("SECRETARY_DB")
    if override:
        return Path(override)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from app.config import settings  # noqa: WPS433
        url = str(getattr(settings, "database_url", "") or "")
        if url.startswith("sqlite:///"):
            return Path(url[len("sqlite:///"):])
    except Exception:
        pass
    return ROOT / "data" / "secretary.db"


DB = _secretary_db()


def _parse_shard(value: str) -> tuple[int, int] | None:
    """Parse 'I/N' into (I, N), refusing anything that would overlap or duplicate."""
    if not value:
        return None
    try:
        index_s, total_s = value.split("/", 1)
        index, total = int(index_s), int(total_s)
    except ValueError:
        raise SystemExit(f"--shard expects I/N, got {value!r}")
    if total < 1 or not (0 <= index < total):
        raise SystemExit(f"--shard out of range: {value!r}")
    return index, total


def select_gap(limit: int, retry_failed: bool = False,
               shard: tuple[int, int] | None = None) -> list[dict]:
    """Calls with local audio and no transcript, newest first.

    `retry_failed` re-includes calls whose re-transcript was recorded as terminal
    failure. That matters because 1,114 calls were marked failed on 2026-09-14 for a
    reason that was not the audio: `dialpad_media_file.local_path` held Windows paths,
    so the file was "missing" on Linux (see dialpad-media-path-repair.py). Rows the
    audio pipeline genuinely cannot read will simply fail again, cheaply.

    `shard=(i, n)` partitions the work by `rowid % n` so several processes can run at
    once without transcribing the same call twice. Per-call latency is ~22 s (Whisper
    plus a cleanup pass), so one process drains ~3 calls a minute and the last few
    hundred calls take hours; four shards make it minutes, at identical cost. Without a
    deterministic partition, concurrent runs would pick the same newest calls and pay for
    them twice.
    """
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    blocked = "('success')" if retry_failed else "('success','failed')"
    shard_sql, shard_args = "", []
    if shard:
        index, total = shard
        shard_sql = " AND (c.rowid % ?) = ?"
        shard_args = [max(1, int(total)), int(index)]
    try:
        rows = con.execute(
            f"""
            SELECT c.call_id,
                   COALESCE(c.duration_seconds, 0) AS duration_seconds,
                   datetime(c.date_started_ms/1000,'unixepoch') AS started,
                   COALESCE(m.local_path, '') AS local_path
            FROM dialpad_call_full c
            JOIN dialpad_media_file m ON m.call_id = c.call_id
                 AND (m.kind LIKE 'recording%' OR m.kind = 'voicemail')
            WHERE TRIM(COALESCE(c.transcription_text,'')) = ''
              AND NOT EXISTS (
                    SELECT 1 FROM dialpad_call_retranscript r
                    WHERE r.call_id = c.call_id AND r.status IN {blocked}
              ){shard_sql}
            ORDER BY c.date_started_ms DESC
            LIMIT ?
            """,
            (*shard_args, int(limit) * 3),
        ).fetchall()
    finally:
        con.close()

    # A media ROW is not a media FILE. The first version of this selector stopped at
    # the join, so all 1,054 rows it selected had a row in `dialpad_media_file` and no
    # file on disk: the batch failed instantly, every pass, and the supervisor logged
    # rc=0 forever. `os.path.exists` is the only thing that says whether there is audio
    # to transcribe. (This is the same class as L1086 -- a stored path is not evidence
    # that the content is there.)
    out: list[dict] = []
    skipped_not_audio = 0
    for r in rows:
        path = (r["local_path"] or "").strip()
        if not path or not os.path.exists(path) or os.path.getsize(path) == 0:
            continue
        # A file is not necessarily audio. Some fetched "recordings" are HTML or JSON
        # error pages saved with an .mp3 name (75 of them, all 13,732 bytes in June, plus
        # more alongside), and the transcriber refuses them every time. Re-offering those
        # forever kept the queue from ever reaching zero and made "how much is left" a
        # number that could not converge. The check is the transcriber's own, so the
        # selector and the worker agree on what is transcribable.
        if _audio_file_problem(path):
            skipped_not_audio += 1
            continue
        out.append(dict(r))
        if len(out) >= limit:
            break
    if skipped_not_audio:
        print(f"  ({skipped_not_audio} files skipped: not audio)", file=sys.stderr)
    return out


def trim_to_budget(todo: list[dict], max_minutes: float) -> tuple[list[dict], int]:
    """Take the newest calls that fit inside the cost guard, rather than refusing all.

    A guard that rejects the whole batch when the backlog is large would never make
    progress; this one spends the budget on the most recent conversations and leaves
    the rest for the next run.
    """
    kept: list[dict] = []
    spent = 0.0
    for row in todo:
        minutes = (row["duration_seconds"] or 0) / 60.0
        if kept and spent + minutes > max_minutes:
            break
        kept.append(row)
        spent += minutes
    return kept, len(todo) - len(kept)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--max-minutes", type=float, default=2400.0,
                    help="spend the budget on the newest calls, leave the rest")
    ap.add_argument("--retry-failed", action="store_true",
                    help="re-attempt calls whose earlier attempt failed (e.g. after "
                         "a media-path repair)")
    ap.add_argument("--cumulative-max-minutes", type=float, default=6000.0,
                    help="refuse to run once successful transcriptions already total this "
                         "much audio (~$0.006/min). The budget lives in the tool, not in "
                         "whatever happens to invoke it, so cron and a human are bounded "
                         "the same way.")
    ap.add_argument("--shard", default="",
                    help="I/N -- take only calls where rowid %% N == I, so N processes can "
                         "run at once without transcribing the same call twice")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    spent = 0.0
    con0 = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        row = con0.execute(
            "SELECT COALESCE(SUM(c.duration_seconds),0) FROM dialpad_call_retranscript r "
            "JOIN dialpad_call_full c ON c.call_id = r.call_id WHERE r.status='success'"
        ).fetchone()
        spent = (row[0] or 0) / 60.0
    finally:
        con0.close()
    if spent >= a.cumulative_max_minutes:
        print(json.dumps({"stopped": "cumulative budget reached",
                          "minutes_spent": round(spent, 1),
                          "cumulative_max_minutes": a.cumulative_max_minutes,
                          "estimated_spend_usd": round(spent * 0.006, 2)}, indent=1))
        return 0


    todo = select_gap(a.limit, retry_failed=a.retry_failed,
                      shard=_parse_shard(a.shard))
    todo, deferred = trim_to_budget(todo, a.max_minutes)
    minutes = sum(r["duration_seconds"] or 0 for r in todo) / 60.0
    plan = {
        "selected": len(todo),
        "deferred_over_budget": deferred,
        "audio_minutes": round(minutes, 1),
        "estimated_cost_usd": round(minutes * 0.006, 2),
        "oldest": todo[-1]["started"] if todo else None,
        "newest": todo[0]["started"] if todo else None,
    }
    if not todo:
        print(json.dumps(plan, indent=2))
        return 0
    if a.dry_run:
        print(json.dumps(plan, indent=2))
        return 0

    t0 = time.time()
    result = transcribe_downloaded_recordings(
        call_ids=[r["call_id"] for r in todo],
        limit=len(todo) or 1,
        # `--retry-failed` must reach the pipeline, not just this selector. The
        # pipeline skips any row with a terminal failure recorded against it, so the
        # first version of this flag widened the selection and then had every row
        # skipped inside the call: the supervisor logged "attempt N rc=0" every 90
        # seconds for twenty minutes while transcribing nothing at all.
        force=bool(a.retry_failed),
        only_needs_retranscribe=False,  # the selection already decided this
    )
    out = dict(plan, **result, seconds=round(time.time() - t0, 1))
    print(json.dumps(out, indent=2) if a.json else
          f"transcript gap backfill: {result.get('transcribed', 0)}/{len(todo)} "
          f"transcribed, {result.get('failed', 0)} failed, "
          f"{out['audio_minutes']} min (~${out['estimated_cost_usd']}), "
          f"{out['seconds']}s")
    return 0 if not result.get("failed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
