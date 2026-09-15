# IN FLIGHT — work that is open right now

Updated: 2026-09-15 20:05Z (ZABZ-TECH, credential session — AWS key killed D164, Twilio token rotated D165, H275)

Sections below the marker are from the comms session (ZABZ-YOGA, 14:05Z); this session's open
work is at the end of the file.

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
| **Names for the unnamed people** | 1,226 people, ~922 named; 43 of 60 `waiting` rows still show a bare number. A read-only subagent is measuring which of the business's own records (repair jobs, invoices, orders, lpt-hub case files, contact exports) hold name↔phone mappings, and how many of the unnamed they would cover. Biggest single lever on every other view. |
| **`display_name` can be a source LABEL, not a person** | `7325036369` has 1,669 communications and reads as **"Microsoft Word"**, because `dialpad_sms_cache.customer_name` says so — the source says it, so this is not a merge error, but an agent will be misled. 38 of 1,226 names look non-human by a rough filter and most of the rest are legitimate businesses. Needs a deliberate design pass (prefer evidence-weighted names; fall back to the number), not a blocklist guessed in a hurry. |
| **The fleet still does not reach for it** | 34 calls, all mine. The tool can no longer dead-end; nothing yet puts recent comms in front of an agent at the moment a customer speaks (inbound message or task context). |
| **Kernel index-age metric** (**P131**) | `ck/sentinel.py` was being edited by another session, so a change there collides. `health` exposes it to agents and the cron fails on ingestion staleness. |
| **The softer re-transcripts** | Calls that already have Dialpad text and could be re-transcribed from better audio for ~$45. Now the only transcript work left, and it is a quality swap, not a gap. |
| **The authority's app checkout is a third lineage** (**P143**) | 57 commits reachable from no remote (now backed up as `backup/secratary-checkout-20260915`), 136 behind origin/master, 75 dirty files. Needs a dedicated reconciliation session; never scp a whole file into it — patch the single hunk (`/tmp/pt.py` pattern). |

## Credential session, 2026-09-15 20:05Z (ZABZ-TECH) — full record **H275**, decisions **D163–D165**

Closed tonight: the AWS AdministratorAccess key in `phone-and-tech-full/backend/.env.test` is deleted
and verified dead (**D164**); Lakewood's own Twilio auth token is rotated through Twilio's
secondary-token path, every consumer patched and restarted, the old token now 401 (**D165**).
Device Parts is out of favour by owner instruction (**D163**).

Still open, mine:

| Item | State |
|---|---|
| **ZABZ-YOGA's app stack** | DONE 19:58Z — patched, restarted, `/health` 200 with token fp `c4e6`. The earlier "unreachable" was Tailscale on ZABZ-TECH being stopped, not yoga. |
| **Tailscale on ZABZ-TECH** | Root cause found and fixed at the cause (**D172**): IP Helper crashed at 15:40 local and Windows stopped Tailscale as its dependent; iphlpsvc's own recovery never restarts it. `scripts/ensure-mesh-prereqs.ps1` + the 5-minute task 'DSH Mesh Prereqs (5m)' now repair iphlpsvc first, then Tailscale, then the LAN portproxy — verified by breaking it on purpose. **Still open: the other five nodes have no such watch.** |
| **Dead plaintext in the repos** | The leaked AWS key and Twilio token strings are still in `phone-and-tech-full` and `personal-secretary-mvp`. Both are inert now, so this is hygiene plus a pre-commit secret gate — not done inside another session's dirty tree. |
| **Outworq LLC's Twilio token** | Still live in `personal-secretary-mvp/deploy/twilio-studio-flow/.env.vogel`, verified active. Client account — queue **#17**, needs Shimon. |
| **IAM leftovers** | `github-actions-deployer` holds an unused AdministratorAccess key; root has MFA disabled and no root access keys; `~/.twilio-cli/config.json` holds two API-key secrets (not affected by an auth-token rotation). |
| **Local desktop API startup** | ~6 minutes to `Application startup complete` (Chroma telemetry warning last line before it). `scripts/restart-api.ps1` waits only 45s, so it always reports failure — **L1566**. |
