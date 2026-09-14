# IN FLIGHT — work that is open right now

Updated: 2026-09-14 23:50Z (ZABZ-YOGA, comms/Dialpad session, round 2)

Rewritten, not appended. An item leaves this file by being finished (a `log/handoff/` entry) or by
becoming a `state/open-pain.md` row. This session: **H202** and **H208** (round 2); its record:
**W105**, **D141**, **D146**, **L1081–L1086**, **L1467–L1469**, **P131**.
*(Correction: H208 cites "D142" for the digest decision — the decision is **D146**.)*

## Running right now, unattended

Both jobs are idempotent. If one is not running and work remains, re-run its command.

| Job | Where it lives | What says it worked |
|---|---|---|
| **Recording download** — 2,500 calls with a recording URL and no usable local audio (selector: no media row **or** the file is not on disk) | `~/dialpad-recording-gap.log`; `scripts/dialpad-recording-gap.py --limit 2500` | `ls data/dialpad/recording/ \| wc -l` rising (3,022 at 23:47Z); `SELECT kind, COUNT(*) FROM dialpad_media_file GROUP BY kind`. **Free** — the cost is the transcription it enables. |
| **Transcript backfill, supervised** | `~/supervised-retry.sh` → `scripts/dialpad-transcript-gap.py --limit 5000 --retry-failed --max-minutes 2400`; logs `~/dialpad-transcript-gap.log` + `.supervisor.log` | `SELECT status, COUNT(*) FROM dialpad_call_retranscript GROUP BY status` — 249 successes / 349 audio-minutes at 23:47Z (~$2.1). **Cumulative cap 6,000 min (~$36)**, measured backlog ~5,486 min (~$33). |
| **Comms index refresh** | authority cron `7,37 * * * *` → `~/.fsearch/comms-refresh.py` | `~/.fsearch/comms-state.json` and `comms-refresh.py --check` (exit 0). Rebuild is 60 s with the person layer; if `at` is more than ~40 min old the cron line has gone. |

**Read this before touching the transcript job.** The first attempt marked 1,107 calls `failed` in four
minutes and it was **not** the audio: `dialpad_media_file.local_path` held Windows paths
(`data\dialpad\recording\…`) while the files were on the authority all along (375 MB of them). 1,933
rows were repaired by `scripts/dialpad-media-path-repair.py` (exact reversal in
`data/media-path-backup-*.json`) and the retry passes `--retry-failed` to re-open the terminal rows.
The pipeline also dies with `database is locked` under the app's continuous writes, which is why it
runs under a supervisor. Newly downloaded recordings are picked up automatically by the next attempt,
because the selector joins on `dialpad_media_file`.

## Mine, measured and waiting on a trigger

| Item | What would show it |
|---|---|
| **Index-age sensing for the kernel** (**P131**) | Today the index sat 6.7 h stale and nothing anywhere said so; the fix is to read `~/.fsearch/comms-state.json` from `ck/sentinel.py:check_comms_freshness`, or call `comms-refresh.py --check` from the attention digest. Not shipped because it cannot be verified from this laptop (the sentinel reads the authority's database) and an unverified change to the sensing organ is worse than a recorded gap. |
| **A "waiting" line in the owner's digest** (**D146**) | `ps_comms_waiting` returns it now (20 customers, 7 days, verified); putting it on *his* surface is its own small change because that surface has a documented alert-fatigue history (P40). One deduplicated line, only when the count is non-zero. |
| **The 3,181 softer re-transcripts** (**P131**) | Those calls already have Dialpad text; a re-transcript is a quality swap, ~$44. Deferred deliberately — decide once this round's spend has reported. |
| **Alias coverage is 49%** | 1,225 people, 921 named, 49% of communications attributed. The rest are one-off callers who never gave a name. Raising it means work on name inference, and a wrong merge is worse than a missing one (L1467). |
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
