#!/usr/bin/env python3
"""Download the recordings that were never fetched, so they can be transcribed.

WHY. Two data gaps sit behind each other, and the second is invisible until the first is
closed. Measured on the authority 2026-09-14:

  * 1,375 calls hold a `recording_url` and have **no local media row at all** — the
    download leg stopped mid-June, so nothing was fetched for July, August or September;
  * 1,948 calls from 2026-07..09 have no transcript **and no audio**, so the transcript
    backfill cannot reach them no matter how long it runs: there is nothing to transcribe.

That is why this is a separate script from `dialpad-transcript-gap.py`: one fetches, the
other transcribes, and the second picks up whatever the first brings in (both select from
`dialpad_media_file`).

WHAT IT COSTS. Nothing — the download is authenticated with the existing Dialpad token and
writes files locally. The cost appears later, at ~$0.006/audio-minute, when these calls
reach the transcriber; `dialpad-transcript-gap.py --max-minutes` bounds that.

CAVEAT ON THE COST ESTIMATE: `dialpad_call_full.duration_seconds` is 0 for voicemail
calls, so the printed `future_transcription_cost_usd` is a FLOOR, not a total, whenever
voicemails are in the batch. A voicemail is 30-60 seconds of audio; 800 of them is roughly
$3.75 that the estimate cannot see. Said out loud so nobody reads a small number as a
small job.

USAGE
  .venv/bin/python scripts/dialpad-recording-gap.py --limit 1600 --dry-run
  .venv/bin/python scripts/dialpad-recording-gap.py --limit 1600
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
    download_recordings_for_call_ids,
)

# ── PORTER'S NOTE (2026-10-11, migration workstream 138) ─────────────────────
# The office default was `ROOT / "data" / "secretary.db"`. On the cloud box that
# resolves to /opt/company/data/secretary.db, a STALE 1,826,816-byte local copy
# that HAS NO `dialpad_call_full` TABLE at all (measured 2026-10-11 06:31Z) — the
# live authority is /root/authority.db (dialpad_call_full: 13,995 rows). The app
# itself reads settings.database_url (DATABASE_URL in /opt/company/.env =
# sqlite:////root/authority.db); this script now does the same thing instead of
# keeping a second, wrong answer. SECRETARY_DB overrides it for a snapshot run.
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


def _terminal_urls(con: sqlite3.Connection) -> set[tuple[str, str]]:
    """(call_id, source_url) pairs that Dialpad will not serve, already tried and logged.

    Without this the selector asks for the same dead URLs forever: 604 voicemails return
    HTTP 404 from their voicemail link, so they stay at the front of a queue that can never
    shrink — measured 2026-09-15, a batch reported `requested 561, downloaded 0, errors 561`
    and the file count stood still. `dialpad_media_download_attempt` already records the
    answer; this reads it.
    """
    out = set()
    try:
        for call_id, url in con.execute(
                "SELECT call_id, source_url FROM dialpad_media_download_attempt "
                "WHERE status IN ('unavailable', 'invalid_payload', 'failed')"):
            out.add((str(call_id), str(url)))
    except sqlite3.Error:
        return set()
    return out


def _urls_for_call(row: sqlite3.Row) -> list[str]:
    """The URLs a call carries, the same way the downloader collects them."""
    urls: list[str] = []
    for value in (row["recording_url"], row["admin_recording_urls"],
                  row["call_recording_ids"], row["recording_details"],
                  row["voicemail_link"]):
        text = str(value or "")
        if text.startswith("http") and text not in urls:
            urls.append(text)
        elif text.startswith("["):
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = []
            if isinstance(parsed, list):
                for item in parsed:
                    item = str(item or "")
                    if item.startswith("http") and item not in urls:
                        urls.append(item)
    return urls


def select_gap(limit: int, voicemail_first: bool = True) -> list[dict]:
    """Calls with a media URL and no *usable* local audio.

    Ordering is deliberate, in three tiers:

      0. a voicemail with **no transcript** — a customer speaking into the business's
         ear that nobody can read at all. Audio is the only way those words exist.
      1. any other voicemail — readable already, but short and worth having.
      2. everything else — the 4,000-call recording backlog.

    Newest-first alone left the unreadable voicemails behind hours of recordings, so the
    one thing a person most needs was the last thing the system would fetch. Measured
    before this: 916 voicemail calls, 312 readable, 604 with nothing to read.
    """
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    order = ("(CASE WHEN COALESCE(c.voicemail_link,'') <> ''"
             "           AND TRIM(COALESCE(c.transcription_text,'')) = '' THEN 0"
             "      WHEN TRIM(COALESCE(c.transcription_text,'')) = '' THEN 1"
             "      WHEN COALESCE(c.voicemail_link,'') <> '' THEN 2"
             "      ELSE 3 END), c.date_started_ms DESC"
             ) if voicemail_first else "c.date_started_ms DESC"
    try:
        rows = con.execute(
            f"""
            SELECT c.call_id,
                   COALESCE(c.duration_seconds, 0) AS duration_seconds,
                   datetime(c.date_started_ms/1000,'unixepoch') AS started,
                   COALESCE(c.recording_url,'') AS recording_url,
                   COALESCE(c.admin_recording_urls,'') AS admin_recording_urls,
                   COALESCE(c.call_recording_ids,'') AS call_recording_ids,
                   COALESCE(c.recording_details,'') AS recording_details,
                   COALESCE(c.voicemail_link,'') AS voicemail_link,
                   COALESCE(m.local_path,'') AS local_path
            FROM dialpad_call_full c
            LEFT JOIN dialpad_media_file m
                   ON m.call_id = c.call_id
                  AND (m.kind LIKE 'recording%' OR m.kind = 'voicemail')
            WHERE (COALESCE(c.recording_url,'') <> ''
                   OR COALESCE(c.admin_recording_urls,'') <> ''
                   OR COALESCE(c.voicemail_link,'') <> '')
            ORDER BY {order}
            LIMIT ?
            """,
            # The scan window must cover the whole call table, not a multiple of the
            # output cap: the ordering puts voicemails and the newest calls first, and
            # after a few runs every one of those is already resolved -- so a small
            # window returns nothing while real work sits deeper in the table. Measured
            # 2026-09-15: `--limit 300` reported `selected: 0` on a queue that a full
            # scan showed to be 3,237 calls.
            (20000,),
        ).fetchall()
    finally:
        con.close()

    dead = _terminal_urls(sqlite3.connect(f"file:{DB}?mode=ro", uri=True))

    # A call can have several media rows (a recording plus an admin URL plus a voicemail
    # link), so the join yields several rows per call and **the decision has to be made over
    # all of them**. Judging from one row made the selector re-offer calls the downloader
    # then skipped as already-present: measured 2026-09-15, `selected 167, requested 0,
    # downloaded 0, skipped_existing 167` -- a whole batch spent re-deciding 167 calls it had
    # nothing to do for, and the queue number never moved.
    by_call: dict[str, dict] = {}
    for r in rows:
        call_id = str(r["call_id"])
        entry = by_call.setdefault(call_id, {"row": r, "paths": [], "n_urls": 0})
        path = (r["local_path"] or "").strip()
        if path:
            entry["paths"].append(path)
        entry["n_urls"] = max(entry["n_urls"], len(_urls_for_call(r)))

    out: list[dict] = []
    for call_id, entry in by_call.items():
        # Usable if ANY of the call's media rows holds real audio -- the same test the
        # downloader's "already present" check applies to the URL it is about to fetch.
        if any(not _audio_file_problem(p) for p in entry["paths"]):
            continue
        r = entry["row"]
        urls = _urls_for_call(r)
        if urls and all((call_id, u) in dead for u in urls):
            continue                      # every URL for this call has been refused
        out.append({"call_id": call_id, "duration_seconds": r["duration_seconds"],
                    "started": r["started"]})
        if len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--voicemail-only", action="store_true",
                    help="fetch only voicemail audio (short, high value, few)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    todo = select_gap(a.limit)
    if a.voicemail_only:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            vm_ids = {str(r[0]) for r in con.execute(
                "SELECT call_id FROM dialpad_call_full "
                "WHERE COALESCE(voicemail_link,'') <> ''")}
        finally:
            con.close()
        todo = [r for r in todo if r["call_id"] in vm_ids]
    minutes = sum(r["duration_seconds"] or 0 for r in todo) / 60.0
    plan = {
        "selected": len(todo),
        "audio_minutes": round(minutes, 1),
        "future_transcription_cost_usd": round(minutes * 0.006, 2),
        "oldest": todo[-1]["started"] if todo else None,
        "newest": todo[0]["started"] if todo else None,
    }
    if a.dry_run:
        print(json.dumps(plan, indent=2))
        return 0
    if not todo:
        print(json.dumps(plan, indent=2))
        return 0

    t0 = time.time()
    result = download_recordings_for_call_ids(
        [r["call_id"] for r in todo], limit=len(todo), force=False)
    out = dict(plan, **result, seconds=round(time.time() - t0, 1))
    print(json.dumps(out, indent=2) if a.json else
          f"recording gap: {result.get('downloaded', 0)} downloaded, "
          f"{result.get('errors', 0)} errors, {result.get('skipped_existing', 0)} already "
          f"present, {out['seconds']}s — future transcription ~"
          f"${out['future_transcription_cost_usd']}")
    return 0 if not result.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
