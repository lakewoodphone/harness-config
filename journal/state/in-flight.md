# IN FLIGHT — work that is open right now

Updated: 2026-09-15 14:05Z (ZABZ-YOGA, comms session — objective complete H219, reader hardening H224/H225)

Rewritten, not appended. Earlier session: **H202**, **H208**, **H213**, **H214**, **H219**; record
**W105**, **D141**, **D146**, **D151**, **L1081–L1086**, **L1467–L1469**, **L1474–L1476**, **L1479**,
**L1481**, **L1484**, **L1503**, **L1504**, **P131**, **P143**, **H224**, **H225**.
*(Correction: H208 cites "D142" for the digest decision — it is **D146**.)*

## Done — the comms objective is met

Texts **127,678** (2025-04-18 → live) · calls **12,552** (2025-10-20 → live; the far end probed
in 2024-10, 2025-01, 2025-04, 2025-06, 2025-07 and 2025-09, `read=0 stored=0 errors=0` each time,
so the oldest call is the account's first and not the harvest's horizon) · voicemails **916**
records with audio fetched for every one Dialpad will still serve · **transcripts: 6,497 calls
carry Dialpad's own text and 1,101 carry a transcript we made from the audio, and the queue is
0** · index **166,939 with 0 missing** (2026-09-15 14:00Z), base = fts = trigram, rebuilt on
`:07`/`:37` and swapped in atomically · five read modes through the live API, the CLI and MCP,
registered so agents find them · staleness visible on both halves, with the cron failing on
either. Spend **~$10.90 of the ~$36 cap**.

**Do not re-open the ceiling.** **6,055 calls can never have words**: 74 hold a file that is not
audio, 1,258 hold media URLs Dialpad refuses with HTTP 404, and 4,797 have no audio URL at all —
Dialpad neither recorded nor transcribed them, because its AI transcription only appears in this
account's data from around April 2026. Of the 916 voicemail calls, 312 are readable and 604 are in
that bucket (**L1481**, **L1479**).

## Done — the reader layer, 2026-09-15 (H224, H225)

The index was built and kept fresh; the *reader* was not usable by an agent. Measured: 34
calls to `comms_search` through the live API, every one of them mine — the fleet had been
told to use it and could not. Fixed: parameter aliases and `**extra` (an agent guesses
`query=`, and a guessed key used to be dropped, leaving FTS5 to answer
`syntax error near ""`); every query tokenised and quoted (`screen replacement?` was a
syntax error); the loose fallback drops stopwords, orders by bm25 and reports
`match_mode` + the terms used (a sentence used to return `It's a iPhone 16 pro max`);
`_party_filter` is shared by search and thread (they disagreed about who "Dovid" is, so
`thread Dovid` returned 0 while `search --party Dovid` returned his messages); opt-outs
have their own bucket (a `Stop` sat at the top of `waiting`); `search --party X` with no
keywords works; `--line` gives a digest one age-carrying summary line.

**The owner can now see it**: digest section **1c** prints
`🔔 N customer(s) waiting on a reply (last 3 days)` and nothing when N is 0. Verified by
running the digest as cron does — 6.1 s end to end. (`D146`'s line, delivered.)

`scripts/comms-verify.py` (harness-config) is the regression battery: **13 assertions**
through the live HTTP dispatcher and the CLI. Run it after any change here.

**Two measurement rules earned in this batch:** HTTP 200 is not success — `{"ok": false}`
rides inside a 200, so a log full of "200 OK" is not evidence a tool worked (**L1503**);
and any search that loosens must be relevance-ordered, name the terms it used, and say it
loosened (**L1504**).

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
| **Done 2026-09-15: names, and a wrong name removed** | 1,226 -> **1,479** people, 922 -> **1,204** with a real name, from the shop's own case records (368 files) and the repair-order SMS templates inside the corpus (9,782 messages). `name_trust` (0 case record / 1 order template / 2 observed label) now chooses the display name, and a case record saying the name is UNKNOWN suppresses an untrusted label -- so the busiest correspondent (1,669 comms) shows its number instead of "Microsoft Word", which was a job description. **267 of the 295 stay unnamed and ~90% of `waiting` will keep showing a number: that is the data, not a bug.** |
| **The name source that is unreachable** | The Prisma Postgres `phonetech_dev` behind `repos/phone-and-tech-full` is what renders the named templates, and it is **not installed on the authority** (`postgresql.service` does not exist as a unit, no `postgres` user, nothing on 5432 -- measured, not assumed). Six heavy unnamed numbers (7326642417/448, 7326146974/404, 3472154686/315, 8483897895/292, 8454282434/174, 5163302373/162) are the ones it would name. |
| **The fleet still does not reach for it** | 34 calls, all mine. The tool can no longer dead-end; nothing yet puts recent comms in front of an agent at the moment a customer speaks (inbound message or task context). |
| **This checkout needs a merge before master can take the naming work** | `~/code/harness-config` is **6 commits ahead of origin/master and 2 behind**, and two files another live session is editing (`presets/yocheved/agent.cordis.yml`, `scripts/ps-mesh.mjs`) block `git pull --rebase` and `git merge`. The naming work is pushed to the remote as **`refs/heads/comms-naming-20260915`** (`eb1b9ab3`). To land it: when those two files are clean, `git pull origin master` then `git push origin HEAD:master`. Never stash or discard another session's uncommitted files to get a merge through. |
| **Kernel index-age metric** (**P131**) | `ck/sentinel.py` was being edited by another session, so a change there collides. `health` exposes it to agents and the cron fails on ingestion staleness. |
| **The softer re-transcripts** | Calls that already have Dialpad text and could be re-transcribed from better audio for ~$45. Now the only transcript work left, and it is a quality swap, not a gap. |
| **Voicemail self-identification** | "my name is X" in a transcript -- measured ~10-12 usable names after review, ASR-noisy. Deliberately NOT applied: the owner's own "... from Lakewood" line sits on 40+ customer numbers and must be screened first. |
| **The authority's app checkout is a third lineage** (**P143**) | 57 commits reachable from no remote (now backed up as `backup/secratary-checkout-20260915`), 136 behind origin/master, 75 dirty files. Needs a dedicated reconciliation session; never scp a whole file into it -- patch the single hunk (`/tmp/pt.py` pattern). |

---

## In flight — added 2026-09-15 17:2xZ (ZABZ-YOGA, self-audit round 59; H255)

*(Appended, not a rewrite, because another session holds in-flight state in this file and
clobbering a live session's notes is a real loss. The rewrite convention resumes when one
session owns the file.)*

- **Shipped:** `check_owner_queue` in `~/ceo-kernel` (`9962993`) — the next owner decision,
  one at a time, with true age/severity/blocking/recommendation, in the badge payload.
  15 checks; payload verified 17:14Z.
- **Owner queue 14 → 11 pending** with recorded reasons (#39, #15, #31, #10 split; one
  owner-only medical row re-filed). Mirror refreshed: 11 open, 30 closed.
- **Evolution proposals 12 → 1 → 0.** Ten generic refactor templates + one duplicate
  dismissed with per-class reasons; #222 closed as applied (capability above).
- **Mine, not his, still open:** enable cheap-first routing as a *measured* change; repair
  Google Voice monitoring over CDP; find why a medical task routed to `finance_bookkeeper`;
  fix the generic-refactor proposer template once `app/evolution.py` is free (another
  session holds ~79–80 modified files, including it).
- **Blocked on another session, not on the owner:** anything touching `app/evolution.py`
  or `app/workforce.py`.
- **Loose end to remember:** row #39's note carries a `CORRECTION:` clause — I wrote "the
  row is gone" before the delete had run, and the delete had failed on a lock. See L1537.

