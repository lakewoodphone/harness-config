# IN FLIGHT — work that is open right now

Updated: 2026-09-15 00:35Z (ZABZ-YOGA, comms/Dialpad session, round 3 of the goal)

Rewritten, not appended. This session: **H202**, **H208**, **H213**; record **W105**, **D141**,
**D146**, **L1081–L1086**, **L1467–L1469**, **L1474–L1476**, **L1479**, **P131**.
*(Correction: H208 cites "D142" for the digest decision — the decision is **D146**.)*

## Settled this round, with evidence — do not re-open these

* **604 voicemails are unrecoverable from every source we can reach.** 916 calls carry a
  voicemail link; 312 are readable, 604 are not. Each of the 604 returns **HTTP 404** from
  `https://dialpad.com/v/<call_id>`, has no `voicemail_recording_id`, and `was_recorded=0`
  (true of all 916). `transcripts/<id>` returns only `{call_id}`; `calls/<id>` is 404. Dialpad
  *does* email a notification containing the transcript — 248 exist and 191 matched a call —
  but every one describes a voicemail that already has text, and **searching for any of the
  604 by its own number at both ends of the range returns nothing**. Their call lengths are
  30–40 s, consistent with a caller who listened to the greeting and hung up. This is a source
  limitation (**L1479**), not a pipeline gap. The email reader
  (`scripts/dialpad-voicemail-email-backfill.py`) stays as the fallback path.
* **"All time" is complete for calls.** Probed 7-day windows in 2024-10, 2025-01, 2025-04,
  2025-07 and 2025-09 through the real harvest path: `read=0 stored=0 errors=0` each time.
  2025-10-20 is the account's first call, not the harvest's horizon.
* **A downloaded file is not ingested until its row exists** (**L1479**), and **bookkeeping
  must not fail the work it records** — both cost real progress today.

## Running right now, unattended

| Job | Where it lives | What says it worked |
|---|---|---|
| **Recording download** — 3,404 calls with a URL Dialpad has not refused | `~/supervised-download.sh` → `scripts/dialpad-recording-gap.py --limit 700`; logs `~/dialpad-recording-gap.log` + `.supervisor.log` | It is converging: **files +180 and rows +180 in four minutes, `errors: 0`**, queue 5,097 → 3,404 (00:31Z). Files on disk 3,945. Re-run the dry run until it selects 0. |
| **Transcript backfill** | `~/supervised-retry.sh` → `scripts/dialpad-transcript-gap.py --limit 5000 --retry-failed` | Its dry run must fall to 0 (**it is 0 now** — every call with real local audio and no transcript is transcribed); the queue refills as the downloader lands audio. Cumulative cap 6,000 min (~$36); **381 min / 277 calls spent (~$2.3)**. |
| **Comms index refresh** | authority cron `7,37 * * * *` → `~/.fsearch/comms-refresh.py` | Exit 0, `~/.fsearch/comms-state.json`, and `comms_search health`. It now **fails when the data stops flowing**, not only when the index is incomplete (verified: injected staleness → exit 1). |

**Read this before touching either job.** Three defects made them look healthy while doing
nothing, all fixed and all worth knowing: `--retry-failed` did not reach the pipeline's
terminal-failure guard; the selectors joined `dialpad_media_file` (a media **row** is not a
media **file** — `os.path.exists` and the audio check are what count); and both row-writes
(`dialpad_media_file`, `dialpad_media_download_attempt`) died with SQLITE_BUSY, which the
10-second busy timeout cannot fix because it is a read-snapshot upgrade. The supervisors now
stop with a reason when the queue stops moving, which is how the third one was found.

## Mine, measured and waiting on a trigger

| Item | What would show it |
|---|---|
| **Kernel index-age metric** (**P131**) | `ck/sentinel.py` was being edited by another session, so a change there collides. `health` already exposes it to agents, and the cron now fails on ingestion staleness. |
| **A "waiting" line in the owner's digest** (**D146**) | `ps_comms_waiting` returns it (20 customers in 7 days, verified). One deduplicated line, only when non-zero — that surface has an alert-fatigue history (P40). |
| **The softer re-transcripts** | ~4,400 calls with local audio and no successful re-transcript, most already carrying Dialpad's readable text: ~$45 for a quality swap. Deferred behind the no-text gap, which is what the cap covers. |
| **Alias coverage is 49%** | 1,225 people, 921 named. The rest are one-off callers who never gave a name; a wrong merge is worse than a missing one (L1467). |
| **The harvest re-requests the same 200 transcript-less calls every 30 min** (**L1085**) | `harvest_transcripts_for_recent_calls` has no negative cache: ~9,600 API calls a day that always answer "none". Harmless, but it makes a healthy no-op read as a fault. Fix is a small "asked and empty" marker. |

## Broken, as last measured

- **The authority's checkout is ~104 commits behind and 69 files dirty** (measured 23:00Z); the app
  runs from it and is healthy (`/health` 200). Nothing pulls it automatically; `git-health-check.sh`
  only alerts. Do not "fix" it from another machine — a second session was live on it during this
  session (HEAD moved twice under me).
- **`harness-config` has two live writers on ZABZ-YOGA** (**P57**): at 23:35Z a commit of mine failed
  with `cannot do a partial commit during a merge` while another session merged the journal v2
  rebuild in the same working tree. The other session's merge commit `e383047` swept my working-tree
  edits in, so nothing was lost — but the only reason it survived is that it happened to be swept in.
  Prefer `git show <commit>:<file>` to check what actually landed over trusting the working tree.
- **`~/bin/owner-queue.py` is tracked in no repository** (**P47**).
- **MagicDNS failed transiently** at 23:01Z (`secratary.tail93e6e6.ts.net` → NXDOMAIN) while the
  tailnet was up and `100.84.72.88` worked immediately. If `ssh secratary-ts` stops resolving, use
  the IP — the alias is not broken, the resolver is.

## His, waiting

Unchanged: the Amazon/eBay interactive logins, the BoA password rotation. **Neither round of this
session added an owner question** — the comms work produced no decision that is his, and the two
spends (~$13 then ~$20 more, both bounded by a cumulative cap) are inside the instruction he gave:
"make sure you have all the texts, all the calls, all the voice mails, all the transcripts properly
set up".
