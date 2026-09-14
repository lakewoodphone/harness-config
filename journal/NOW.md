# NOW — the one page every session reads

Updated: 2026-09-14 (late session, ZABZ-YOGA)

This file is **state**, not history: it is rewritten, never appended. History lives in `entries/`,
one file per entry, and every claim here traces to an entry there. `journal.py status` prints a
capped slice of this file plus live counts, open pain, the owner-question count and the cache/drift
state.

## The journal, as it works now (v2)

```
J=~/code/harness-config/journal/tools/journal.py
python $J status                     # this page, hard-capped at 6 KB, exit 0 even when cut
python $J newest handoff 2           # the last two sessions' state of play
python $J list --kind pain --status open
python $J show P46                   # an exact id opens exactly one file
python $J search "the area I am about to touch" --kind lessons --since 2026-09-01
python $J costs                      # what each read actually costs; doctor = health
```

Everything takes `--budget N`, `--limit N`, `--json`, `--since/--until`, `--tag`, `--host`. The log
is `entries/<kind>/<id>.md`; `index/` is a cache that rebuilds itself; `log/**` and the six flat
files are frozen inputs read only by `import-legacy` and `check`'s drift test. Never read the tree
end to end. Why it changed, measured: `AUDIT.md`. What it had to be: `SPEC-v2.md`.

Measured tonight, same tree: `status` **5,986 B / 97 ms / exit 0** (was 12,347 B / 8.9 s / exit 1);
`show` 9 ms on one file (was 0.41 s on a 249 KB shard); `search` 105 ms; `newest` 100 ms. **707 entries** (23:38 UTC), 0 redundant copies, `check` **0 errors**, legacy drift **0**, `import-legacy` reports
**new 0** (idempotent).

## Last session on the record

**H205** — journal v2 shipped and verified; the record was rebuilt from the frozen sources after a
concurrent session's migration wrote a tree whose file names, marker ids and heading ids disagreed
in 563 files. Decisions **D144** (one file per entry + self-healing cache), **D142** (identity-based
absorption, aliases instead of copies), **D145** (rebuild-and-carry, never nuke). Wins **W108-W110**:
the before/after read table, the no-loss proof, and the two silent failures that stopped (a mirror
that could not refresh on Windows, a drift count that cried wolf at 322). Lessons **L1087-L1093**.
Pain **P132** (two sessions can rewrite this journal at once; the lock does not cross machines) and
**P133** (`log/**` and the flats are still writable by a stale checkout).

## Where the owner's work stands

- **Kosher filter** — tiers and privacy posture are settled (on-device escalation → our server →
  third-party API) and the website can take money; the last mile is three values only he can supply
  (owner question #33). **D50**, **D54**, **H201**.
- **Owner's phone path** — fixed and verified 15/15; two named items stay open: a first run lands
  with no session (**P46**) and the gate died once with no cause on the record (**P59**).
- **Frontend** — off Netlify onto Cloudflare Pages, live on `lakewoodphoneandtech.com`, `www` and
  `test.`; deploy with `node scripts/deploy-frontend-cloudflare.mjs --env test|production` (**D83**,
  **H87**). Cloudflare silently ignores a `404` rule in `_redirects`; MX/TXT on that zone are live
  email — touch only the frontend CNAMEs.
- **DRN fleet** — manageable from the LPT portal (state, liveness, applied profiles, lockdown,
  lost-device lock). **The fleet is healthy and the "53 silent devices" alarm was our own monitoring**
  (H200 → H206, L565). A device only answers when something is SENT to it, and the only regular traffic
  was one hourly sweep at a SINGLE device, so everyone else's `last_seen` was frozen at enrolment.
  Measured: a read-only query got an answer from DRN 2 in seconds, then `POST /fleet/heartbeat` asked all
  54 quiet devices and **27 answered within seconds** — **28 of 65 heard from in the last hour, up from 0**.
  The heartbeat is deployed and runs every 6 h (`stale_hours=24`), so "silent" now means the phone did not
  answer. Two traps: the MDM's reply history **before 2026-08-14 is gone** from every surviving store, so a
  gap in the record is NOT evidence about hardware (our July batch records prove the fleet was provisioned:
  install-waze 57, lockdown 47, activation-lock 45, renumber 39, all completed); and a count that only moves
  when WE act measures us, not the fleet. Profile truth is still read-only-cached: 1 device had a
  ProfileList on file before the heartbeat, so "unknown" is the correct reading, never "empty".
- **Comms and transcripts** — a transcript-gap backfill (~1,117 calls, idempotent re-run) and the
  comms index refresh are in flight; their measurements live in `state/in-flight.md`, which the
  other session owns this hour.

## State of the systems, as last measured

- **Tailscale on ZABZ-YOGA is UP** (23:0x UTC: `100.72.162.5 zabz-yoga-1`, and `git ls-remote origin`
  answers). H96 says the daemon was wedged, P127 says it has been dead since boot, L326 is a
  correction saying the tailnet was never down — three records, none re-measured until tonight
  (**L1093**). Trust the measurement, and date it.
- **Two sessions wrote this repo at once tonight**, and one migrated the journal while the other
  audited it. The repair held; the guard that would prevent it does not exist (**P132**).
- **Any machine not yet pulled** still writes v1 shards into `log/**`; that is recoverable
  (`import-legacy`) but it is a second copy of the record until it is absorbed (**P133**).
- **`~/.dsh` is never the source of truth.** `harness-config` is (**D7**).

## Owner questions

12 open, mirror refreshed 2026-09-14 23:10 UTC by `journal.py questions` over ssh to the authority
(the table `owner_decision_queue` is the only source of truth). The two that are one plain question
each, and the most expensive to leave open: **#17** a live Twilio account SID and auth token are
committed to a repository, and **#31** the two provider API keys that leaked into a transcript are
still unrotated (**P13b**).

## The rule that keeps this honest

Every reading carries its source and its age. If a file here cannot say when it was written and from
where, it is not evidence (**L1**). An empty result is a refusal, not a health check (**L2**).
