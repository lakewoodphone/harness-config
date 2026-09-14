# IN FLIGHT — work that is open right now

Updated: 2026-09-14 23:05Z (ZABZ-YOGA, comms/Dialpad session)

Rewritten, not appended. An item leaves this file by being finished (a `log/handoff/` entry) or by
becoming a `state/open-pain.md` row. This session's full handoff: **H202**; its record: **W105**,
**D141**, **L1081–L1083**, **P131**.

## Running right now, unattended

| Job | Where it lives | What says it worked |
|---|---|---|
| **Transcript-gap backfill** — 1,117 calls that hold a recording and no transcript at all | authority, pid in `~/dialpad-transcript-gap.log` (`scripts/dialpad-transcript-gap.py --limit 1200 --max-minutes 2400`) | `SELECT status, COUNT(*) FROM dialpad_call_retranscript GROUP BY status` — 186 success at 23:01Z, rising ~2.4/min; the no-transcript count falls from 1,117 toward 0. ~7.7 h, ~$12.75, capped. **If it is not done and not running, re-run the same command — it is idempotent.** |
| **Comms index refresh** | authority cron `7,37 * * * *` → `~/.fsearch/comms-refresh.py` | `~/.fsearch/comms-state.json` (`ok`, `at`, `missing`) and `comms-refresh.py --check` (exit 0). Rebuild is 29 s; if `at` is more than ~40 min old the cron line has gone. |

## Mine, measured and waiting on a trigger

| Item | What would show it |
|---|---|
| **Index-age sensing for the kernel** (**P131**) | Today the index sat 6.7 h stale and nothing anywhere said so; the fix is to read `~/.fsearch/comms-state.json` from `ck/sentinel.py:check_comms_freshness`, or call `comms-refresh.py --check` from the attention digest. Not shipped because it cannot be verified from this laptop (the sentinel reads the authority's database) and an unverified change to the sensing organ is worse than a recorded gap. |
| **The 3,181 softer re-transcripts** (**P131**) | Those calls already have Dialpad text; a re-transcript is a quality swap, ~$44. Deferred deliberately — decide once the $12.75 run has reported. |
| **Recent voicemail audio is not downloaded** (**P131**) | 4 voicemails from 09-13/14 index as a phone number and nothing else; 223 voicemail recordings exist on disk but the newest is 2026-07-21. `dialpad_call_full.voicemail_link` already holds the URL to fetch. |
| **Kernel index metrics** | `ck`'s `comms_freshness` check numbers, re-read after this session's changes, to confirm nothing it reported moved in the wrong direction. |

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
