# IN FLIGHT — work that is open right now

Updated: 2026-09-15 02:55Z (ZABZ-YOGA, comms/Dialpad session, **goal complete — H219**)

Rewritten, not appended. This session: **H202**, **H208**, **H213**, **H214**, **H219**; record
**W105**, **D141**, **D146**, **L1081–L1086**, **L1467–L1469**, **L1474–L1476**, **L1479**,
**L1481**, **L1484**, **P131**. *(Correction: H208 cites "D142" for the digest decision — it is
**D146**.)*

## Done — the comms objective is met

Texts **127,678** (2025-04-18 → live) · calls **12,552** (2025-10-20 → live; the far end probed
in 2024-10, 2025-01, 2025-04, 2025-06, 2025-07 and 2025-09, `read=0 stored=0 errors=0` each time,
so the oldest call is the account's first and not the harvest's horizon) · voicemails **916**
records with audio fetched for every one Dialpad will still serve · **transcripts: 6,497 calls
carry Dialpad's own text and 1,101 carry a transcript we made from the audio, and the queue is
0** · index **166,874 with 0 missing**, base = fts = trigram, rebuilt on `:07`/`:37` and swapped
in atomically · five read modes through the live API, the CLI and MCP, registered so agents find
them · staleness visible on both halves, with the cron failing on either. Spend **~$10.90 of the
~$36 cap**.

**Do not re-open the ceiling.** **6,055 calls can never have words**: 74 hold a file that is not
audio, 1,258 hold media URLs Dialpad refuses with HTTP 404, and 4,797 have no audio URL at all —
Dialpad neither recorded nor transcribed them, because its AI transcription only appears in this
account's data from around April 2026. Of the 916 voicemail calls, 312 are readable and 604 are in
that bucket (**L1481**, **L1479**).

## Running — four cron entries, nothing session-dependent

| Job | Schedule | What says it worked |
|---|---|---|
| **Dialpad harvest** (calls, sessions, transcripts) | `*/30` | Freshness in `health`: newest SMS 0.4 h, newest call 0.8 h |
| **Media fetch** (`dialpad-recording-gap.py --limit 300`) | `*/5` | Dry run selects ~0 (only calls the harvest added minutes ago) |
| **Transcript gap** (`dialpad-transcript-gap.py --limit 400 --retry-failed --max-minutes 600`) | `*/10` | Dry run selects **0**. Cumulative budget inside the tool (6,000 min ≈ $36) |
| **Index refresh** (`~/.fsearch/comms-refresh.py`) | `7,37` | Exit 0; `comms_state.json`; **builds beside the live file and swaps it in atomically**, so no reader sees a half-built table |

**Read this before touching them.** Ten defects, all one family: **a job that runs, exits 0 and
produces nothing.** A flag that never reached the layer doing the work; selectors that joined the
media **row** and never tested the **file**; a multi-URL call judged from one joined row; a scan
window too small to see the work; three writers where `database is locked` discarded completed
work — in one case work already **paid for** (**L1484**); a selector re-offering URLs Dialpad had
already refused; and a selector re-offering files that are not audio. Every one was found by
measuring the job's *subject* rather than watching its exit code.

## Also settled, with evidence

* **A dynamic tool edited in place is deployed on the next call** — `run_tool` reloads when the
  file is newer than the loaded copy; proven by editing the installed file (the next API call
  returned the change) and reverting it.
* **`--shard I/N` partitions the work** by `rowid % N`, so several transcription processes can run
  at once without paying twice for the same call. It took the rate from ~3/min to ~24/min.

## Mine, measured and waiting on a trigger

| Item | What would show it |
|---|---|
| **A "waiting" line in the owner's digest** (**D146**) | `ps_comms_waiting` returns it (18 waiting, 13 missed calls, verified through the live API). One deduplicated line, only when non-zero — that surface has an alert-fatigue history (P40). |
| **Kernel index-age metric** (**P131**) | `ck/sentinel.py` was being edited by another session, so a change there collides. `health` exposes it to agents and the cron fails on ingestion staleness. |
| **The softer re-transcripts** | Calls that already have Dialpad text and could be re-transcribed from better audio for ~$45. Now the only transcript work left, and it is a quality swap, not a gap. |
| **Alias coverage is 49%** | 1,226 people, 921 named. The rest are one-off callers who never gave a name; a wrong merge is worse than a missing one (**L1467**). |
