# IN FLIGHT — work that is open right now

Updated: 2026-09-14 23:05Z (ZABZ-YOGA, comms/Dialpad session)

Rewritten, not appended. An item leaves this file by being finished (a `log/handoff/` entry) or by
becoming a `state/open-pain.md` row. This session's full handoff: **H202**; its record: **W105**,
**D141**, **L1081–L1083**, **P131**.

## Running right now, unattended

| Job | Where it lives | What says it worked |
|---|---|---|
| **Transcript-gap backfill, supervised** — 1,107 calls that hold local audio and no transcript | authority: `~/supervised-retry.sh` (40 attempts, 90 s apart) driving `scripts/dialpad-transcript-gap.py --limit 5000 --retry-failed --max-minutes 2400`. Logs `~/dialpad-transcript-gap.log`, supervisor `~/dialpad-transcript-gap.supervisor.log` | `SELECT status, COUNT(*) FROM dialpad_call_retranscript GROUP BY status` — 189 success at 23:12Z rising; `failed` should also fall as rows are re-attempted under repaired paths. Cap ~$13. **If it is not running and gap rows remain, re-run the same command — it is idempotent.** |

**Read this before touching that job.** The first attempt marked 1,107 calls `failed` in four minutes
and it was **not** the audio: `dialpad_media_file.local_path` held Windows paths
(`data\dialpad\recording\…`) while the files were on the authority all along. 1,933 rows were
repaired by `scripts/dialpad-media-path-repair.py` (reversal in `data/media-path-backup-*.json`), and
the retry passes `--retry-failed` to re-open the terminal rows. The pipeline also dies with
`database is locked` under the app's continuous writes, which is why it runs under a supervisor
rather than once.
| **Comms index refresh** | authority cron `7,37 * * * *` → `~/.fsearch/comms-refresh.py` | `~/.fsearch/comms-state.json` (`ok`, `at`, `missing`) and `comms-refresh.py --check` (exit 0). Rebuild is 29 s; if `at` is more than ~40 min old the cron line has gone. |

## Mine, measured and waiting on a trigger

| Item | What would show it |
|---|---|
| **The whole July–September transcript gap needs the recording DOWNLOAD leg restarted** (**P131**) | 1,948 calls from 2026-07..09 have **no transcript and no media row at all** (`has_media_row = 0` for every month from July on) — the download step stopped mid-June, so there is nothing local to transcribe. Measured: 1,375 calls hold a `recording_url` with no local file, 34.7 audio-hours (~$12.5). This is the remaining piece of "all the calls"; the supervised backfill cannot reach it. |
| **Index-age sensing for the kernel** (**P131**) | Today the index sat 6.7 h stale and nothing anywhere said so; the fix is to read `~/.fsearch/comms-state.json` from `ck/sentinel.py:check_comms_freshness`, or call `comms-refresh.py --check` from the attention digest. Not shipped because it cannot be verified from this laptop (the sentinel reads the authority's database) and an unverified change to the sensing organ is worse than a recorded gap. |
| **The 3,181 softer re-transcripts** (**P131**) | Those calls already have Dialpad text; a re-transcript is a quality swap, ~$44. Deferred deliberately — decide once the $13 run has reported. |
| **The harvest re-requests the same 200 transcript-less calls every 30 min** (**L1085**) | `harvest_transcripts_for_recent_calls` has no negative cache: ~9,600 API calls a day that always answer "none". Harmless, but it makes a healthy no-op read as a fault. Fix is a small "asked and empty" marker. |

## Broken, as last measured

- **The authority's checkout is ~104 commits behind and 69 files dirty** (measured 23:00Z); the app
  runs from it and is healthy (`/health` 200). Nothing pulls it automatically; `git-health-check.sh`
  only alerts. Do not "fix" it from another machine — a second session was live on it during this
  session (HEAD moved twice under me).
- **`~/bin/owner-queue.py` is tracked in no repository** (**P47**).
- **The journal still has two writers** (**P57**).
- **MagicDNS failed transiently** at 23:01Z (`secratary.tail93e6e6.ts.net` → NXDOMAIN) while the
  tailnet was up and `100.84.72.88` worked immediately. If `ssh secratary-ts` stops resolving, use
  the IP — the alias is not broken, the resolver is.

## His, waiting

Unchanged from the previous revision of this file: the Amazon/eBay interactive logins, the BoA
password rotation. **Nothing in this session added an owner question** — the index work produced no
decision that is his.
