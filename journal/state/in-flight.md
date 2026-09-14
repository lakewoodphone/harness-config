# IN FLIGHT — work that is open right now

Updated: 2026-09-15 00:15Z (ZABZ-YOGA, comms/Dialpad session, round 2)

Rewritten, not appended. This session: **H202**, **H208**, **H213**; record **W105**, **D141**,
**D146**, **L1081–L1086**, **L1467–L1469**, **L1474**, **L1475**, **P131**.
*(Correction: H208 cites "D142" for the digest decision — the decision is **D146**.)*

## Running right now, unattended

Both are idempotent and both now stop with a reason when they stall (three passes with no
movement in the remaining count). If one is not running and work remains, re-run its command.

| Job | Where it lives | What says it worked |
|---|---|---|
| **Recording download** — 4,000+ calls with a media URL and no *usable* local audio (no row, file missing, **or the file is not audio**) | `~/supervised-download.sh` → `scripts/dialpad-recording-gap.py --limit 700`; logs `~/dialpad-recording-gap.log` + `.supervisor.log` | `ls data/dialpad/recording \| wc -l` rising (3,478 at 00:14Z); re-run the dry run until it selects 0. **Free.** Measured backlog 5,434 audio-minutes. |
| **Transcript backfill** | `~/supervised-retry.sh` → `scripts/dialpad-transcript-gap.py --limit 5000 --retry-failed`; logs `~/dialpad-transcript-gap.log` + `.supervisor.log` | Its dry run must select a number that falls. **Transcript queue is 2 calls / 6.8 min right now** — i.e. every call with real audio and no transcript is already transcribed; the queue refills as the downloader lands audio. Cumulative cap 6,000 min (~$36), 352 spent. |
| **Comms index refresh** | authority cron `7,37 * * * *` → `~/.fsearch/comms-refresh.py` | `~/.fsearch/comms-state.json`, `comms-refresh.py --check` (exit 0), and `comms_search health` (index age **and** ingestion age per channel). |

**Read this before touching the transcript job.** Two defects made it look healthy while doing
nothing for twenty minutes, and both are fixed but worth knowing: `--retry-failed` now reaches
the pipeline (`force=True`), because the pipeline silently skipped every terminal-failure row;
and the selector now checks `os.path.exists` (and audio-ness), because joining
`dialpad_media_file` selected 1,054 calls that had a media **row** and no **file** — instant
failure, every pass, rc=0. See **L1475**.

## Mine, measured and waiting on a trigger

| Item | What would show it |
|---|---|
| **Kernel index-age metric** (**P131**) | `ck/sentinel.py` was being edited by another session (` M ck/sentinel.py` on the authority at 23:45Z), so a change there collides. The information is available to agents through `health` meanwhile. |
| **A "waiting" line in the owner's digest** (**D146**) | `ps_comms_waiting` returns it (20 customers in 7 days, verified). Putting it on *his* surface is its own change: one deduplicated line, only when non-zero, because that surface has an alert-fatigue history (P40). |
| **The softer re-transcripts** | 4,415 calls with local audio and no successful re-transcript, 7,537 minutes — but most already have Dialpad's own readable text. ~$45 for a quality swap. Deferred behind the no-text gap, which is what the current cap covers. |
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
