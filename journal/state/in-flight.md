# IN FLIGHT — work that is open right now

Updated: 2026-09-15 00:45Z (ZABZ-YOGA, comms/Dialpad session, goal round 2)

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

## Running right now — CRON, not supervisors

Hand-launched supervisors die with the SSH session that started them, which is why the fetch
kept stopping. Everything below is a cron entry on the authority, flock-guarded and
idempotent, so nothing depends on a session staying open.

| Job | Schedule | What says it worked |
|---|---|---|
| **Dialpad media fetch** (`scripts/dialpad-recording-gap.py --limit 300`) | `*/5` | A cron-equivalent run measured **276 files in 345 s** (`requested 426, errors 150` — the 404s the attempt log records). Queue 3,237 calls; files on disk 3,945 and rising. Watch `~/dialpad-recording-gap.log`; the dry run must fall to 0. **Free.** |
| **Transcript gap** (`scripts/dialpad-transcript-gap.py --limit 400 --retry-failed --max-minutes 600`) | `*/10` | Its dry run selects the calls with **no text at all** and real audio. **It is 0 right now** — every such call is transcribed; the queue refills as the fetch lands audio. **The cumulative cap (6,000 min ≈ $36) is inside the tool**, so cron and a human are bounded identically. Spent: 277 calls / 381 min (~$2.3). |
| **Comms index refresh** (`~/.fsearch/comms-refresh.py`) | `7,37 * * * *` | Exit 0; `~/.fsearch/comms-state.json`; `comms_search health`. Fails when the **data** stops flowing, not only when the index is incomplete (verified: injected staleness → exit 1). |
| **Dialpad harvest** (calls, sessions, transcripts) | `*/30` | Unchanged; `~/dialpad-harvest.log`. |

**Read this before touching the fetch or the transcription.** Six defects made these look
healthy while doing nothing, all fixed and all worth knowing: `--retry-failed` did not reach
the pipeline's terminal-failure guard; selectors joined `dialpad_media_file` (a media **row**
is not a media **file** — `os.path.exists` and the audio check are what count); a multi-URL
call was judged from one joined row; the scan window was `limit*3`, so a small limit saw only
already-resolved rows and reported `selected 0` on a 3,237-call queue; both row-writes died
with SQLITE_BUSY (a read-snapshot upgrade the 10-second busy timeout cannot wait out); and the
selector kept re-offering URLs Dialpad had already refused (2,105 of them). **L1475**,
**L1476**, **L1479**.

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
