# IN FLIGHT — work that is open right now

Updated: 2026-09-15 01:25Z (ZABZ-YOGA, comms/Dialpad session, goal round 3)

Rewritten, not appended. This session: **H202**, **H208**, **H213**; record **W105**, **D141**,
**D146**, **L1081–L1086**, **L1467–L1469**, **L1474–L1476**, **L1479**, **L1481**, **L1484**,
**P131**. *(Correction: H208 cites "D142" for the digest decision — the decision is **D146**.)*

## The one number that says where this stands

`fetchable: 0` — **every call whose audio Dialpad will still serve now has it locally.** What
remains is transcription of audio already in hand, plus a permanently unrecoverable remainder
that is measured rather than assumed:

| bucket (calls with no transcript) | count | meaning |
|---|---|---|
| audio in hand, awaiting transcription | **554** | cron fills these at ~37 per 10-minute tick (~2.5 h) |
| media URL refused by Dialpad (404 / non-audio payload) | 1,266 | **unrecoverable** |
| no audio URL at all | 4,863 | **unrecoverable** |
| **permanent ceiling** | **6,129** | Dialpad neither recorded nor transcribed these |

## Running right now — CRON, not supervisors

Hand-launched supervisors die with the SSH session that started them, which is why the fetch
kept stopping. All four are cron entries on the authority, flock-guarded and idempotent:

| Job | Schedule | What says it worked |
|---|---|---|
| **Dialpad media fetch** (`scripts/dialpad-recording-gap.py --limit 300`) | `*/5` | Its dry run now selects **0** — the fetch is done. Files on disk ~4,900. |
| **Transcript gap** (`scripts/dialpad-transcript-gap.py --limit 400 --retry-failed --max-minutes 600`) | `*/10` | Verified: **313 → 350 transcripts in one tick (+37)**. **The cumulative cap (6,000 min ≈ $36) is inside the tool**, so cron and a human are bounded identically. Spent: 350 calls / 479 min / **~$2.9**. |
| **Comms index refresh** (`~/.fsearch/comms-refresh.py`) | `7,37 * * * *` | Exit 0; `~/.fsearch/comms-state.json`; `comms_search health`. Fails when the **data** stops flowing, not only when the index is incomplete (verified: injected staleness → exit 1). |
| **Dialpad harvest** (calls, sessions, transcripts) | `*/30` | Freshness visible in `health`: newest SMS 1.9 h, newest call 0.6 h. |

**Read this before touching them.** Nine defects made these jobs look healthy while producing
nothing, all fixed today, and the pattern is always the same: **a job's exit code and its output
are different things.** The last three were one bug in three writers — `dialpad_media_file`,
`dialpad_media_download_attempt`, `dialpad_call_retranscript` — where a `database is locked`
failure discarded work already done, and in the third case work already **paid for** by Whisper
and DeepSeek. A read-snapshot upgrade cannot be waited out by `busy_timeout`
(`app/services/dsh_session_ingest.py:247`), so each now retries on a fresh transaction.
**L1475**, **L1476**, **L1479**, **L1484**.

**Also fixed and worth knowing:** a dynamic tool edited in place was NOT deployed — the app kept
the cached module, so `comms_search` returned old fields over HTTP while the CLI returned new
ones for the same database. `run_tool` now reloads when the file is newer than the loaded copy;
proven by editing the installed file (the next API call returned the change) and reverting it.

## Settled, with evidence — do not re-open these

* **6,129 calls can never have words** (**L1481**): Dialpad neither recorded nor transcribed
  them, their media URLs 404, and no notification email exists for any of them — 248 Dialpad
  voicemail emails exist in Gmail and every one describes a voicemail that already has text.
  Of the 916 voicemail calls, 312 are readable and 604 are in this bucket.
* **"All time" is complete for calls**: 7-day windows probed in 2024-10, 2025-01, 2025-04,
  2025-07 and 2025-09 through the real harvest path returned `read=0 stored=0 errors=0`, so
  2025-10-20 is the account's first call, not the harvest's horizon.

## Mine, measured and waiting on a trigger

| Item | What would show it |
|---|---|
| **Kernel index-age metric** (**P131**) | `ck/sentinel.py` was being edited by another session, so a change there collides. `health` exposes it to agents and the cron fails on ingestion staleness. |
| **A "waiting" line in the owner's digest** (**D146**) | `ps_comms_waiting` returns it (17 customers in 7 days, 12 missed calls, verified). One deduplicated line, only when non-zero — that surface has an alert-fatigue history (P40). |
| **The softer re-transcripts** | Calls that already have Dialpad text and could be re-transcribed from better audio for ~$45. Deferred behind everything that has no words at all. |
| **Alias coverage is 49%** | 1,225 people, 921 named. The rest are one-off callers who never gave a name; a wrong merge is worse than a missing one (L1467). |
