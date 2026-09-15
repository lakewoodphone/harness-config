# IN FLIGHT — work that is open right now

Updated: 2026-09-15 01:50Z (ZABZ-YOGA, comms/Dialpad session, goal round 4)

Rewritten, not appended. This session: **H202**, **H208**, **H213**, **H214**; record **W105**,
**D141**, **D146**, **L1081–L1086**, **L1467–L1469**, **L1474–L1476**, **L1479**, **L1481**,
**L1484**, **P131**. *(Correction: H208 cites "D142" for the digest decision — it is **D146**.)*

## The two numbers that say where this stands

* **`fetchable: 0`** — the fetch is done. Every call whose audio Dialpad will still serve is
  local. (The queue shows 4 because the live harvest keeps adding new calls; that is the system
  working, not a backlog.)
* **455 calls left to transcribe**, of 10,357 total: **3,753 already carry words (36%)**, 642 of
  those from our own re-transcription of the recording (~1,064 audio-minutes, **~$6.39** spent
  of the ~$36 cap). The remaining 455 are draining at **~16/min** with four shards plus cron.

## Running right now

| Job | How | What says it worked |
|---|---|---|
| **Sharded transcription** — `scripts/dialpad-transcript-gap.py --shard I/N`, four processes | launched by hand this round; **cron `*/10` continues when they finish** | Measured: **437 → 642 transcripts in 14 minutes** (~16/min, vs ~3/min serial). Disjoint slices by `rowid % N`, so nothing is transcribed or paid for twice. |
| **Dialpad media fetch** (`--limit 300`) | cron `*/5`, flock | Dry run selects ~0. Files on disk ~4,900. |
| **Comms index refresh** (`~/.fsearch/comms-refresh.py`) | cron `7,37` | **Now builds beside the live file and swaps it in atomically** — verified: the live index answered continuously through a build (166,903 → 166,905) and never went empty. Exit non-zero when the index is incomplete **or** the data has stopped flowing. |
| **Dialpad harvest** | cron `*/30` | Freshness on the health surface: newest SMS 0.4 h, newest call 0.4 h. |

**Read this before touching them.** Ten defects made these jobs look healthy while producing
nothing, all fixed today. The pattern: **a job's exit code and its output are different things.**
The families: a flag that never reached the layer doing the work; a selector that joined the
media **row** instead of testing the **file**; a multi-URL call judged from one joined row; a
scan window too small to see the work; and three writers where `database is locked` discarded
work already done — in one case work already **paid for** (**L1484**). A read-snapshot upgrade
cannot be waited out by `busy_timeout`, so all three retry on a fresh transaction.

## Settled, with evidence — do not re-open these

* **6,129 calls can never have words** (**L1481**): Dialpad neither recorded nor transcribed
  them, their media URLs 404, and no notification email exists for any of them — 248 Dialpad
  voicemail emails exist in Gmail and every one describes a voicemail that already has text.
  Of the 916 voicemail calls, 312 are readable and 604 are in this bucket.
* **"All time" is complete for calls**: 7-day windows probed in 2024-10, 2025-01, 2025-04,
  2025-07, 2025-09 and 2025-06 returned `read=0 stored=0 errors=0`, so 2025-10-20 is the
  account's first call, not the harvest's horizon.
* **A dynamic tool edited in place is deployed on the next call** — `run_tool` reloads when the
  file is newer than the loaded copy, proven by edit-and-revert without a restart.

## Mine, measured and waiting on a trigger

| Item | What would show it |
|---|---|
| **Kernel index-age metric** (**P131**) | `ck/sentinel.py` was being edited by another session, so a change there collides. `health` exposes it to agents and the cron fails on ingestion staleness. |
| **A "waiting" line in the owner's digest** (**D146**) | `ps_comms_waiting` returns it (17 waiting, 12 missed calls, verified through the live API). One deduplicated line, only when non-zero — that surface has an alert-fatigue history (P40). |
| **The softer re-transcripts** | Calls that already have Dialpad text and could be re-transcribed from better audio for ~$45. Deferred behind everything that has no words at all. |
| **Alias coverage is 49%** | 1,225 people, 921 named. The rest are one-off callers who never gave a name; a wrong merge is worse than a missing one (L1467). |
