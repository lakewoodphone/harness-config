# 153 — THE LOST-JOB WORK LIST

**Author:** the coordinator session (ZABZ-TECH), 2026-10-11 ~21:20Z. **Companion to** `132-CRON-INVENTORY.md`
(which classifies) and `151-VERIFY-CLOUD-AUTHORITY.md` (which verifies). This file does the arithmetic that
neither does: what was running a week before the cutover, what is running now, and what the difference
actually is.

## The arithmetic

| reading | value | how |
|---|---|---|
| jobs that ran on the office box 2026-10-04 .. 2026-10-11T05:00 | **88** | `awk` over `secratary-ts:/home/zabz/.cron-status/runs.tsv`, read-only |
| distinct jobs that have ever run on `secratary-cloud` | **21** | `cut -f2 /root/.cron-status/runs.tsv` |
| office-active, never seen on the cloud | **67** | set difference |
| excused by `132`'s classes: DEAD 16 + OFFICE-ONLY 11 | **27** | quoted from `132` §3 and §4 |
| **genuinely lost** | **~40** | 67 − 27, ±2 on the judgement calls below |

**Treat ~40 as the working number, not a precise count.** Two judgement calls move it to about 38:
`capture-test` appears in `132`'s not-scheduled group, and `push-db-offsite` is the retired original the
systems register says must NOT be run because it would publish the FROZEN office database over the live
object.

## The ~40 to port, and they are not a tail

auto-categorize, cfo-ask, cfo-scoreboard, cfo-shift, chip-resume, comms-refresh, comms-refresh-2,
company-offsite-push, daily-finance-sync-cron, db-integrity-check, deadman, dialpad-call-fresh,
family_chat_watchdog, git-health-check, lpt-daily-track, lpt-hub-refresh, lpt-report-freshness,
lpt-retranscribe, model-failover-watch, nightly-plaid-sync, node-agent-cron, owner-ask,
owner-attention-digest, promote-owner-texts, prune-backups, push-dsh-sessions, reconcile-sms-status,
run-sentinel, run-wake-sources, store-write-check, supplier-order-ingest, transcript-archive,
tree-integrity-check, wake-balance, wake-cost, wake-fanout, website-comms-push-cron, work-integrator.

Order the work by `132` §2's tiers, which already rank by risk-if-absent: **Tier 1** backups and the
offsite copy, **Tier 2** the external dead-man switch, **Tier 3** freshness monitors, **Tier 4**
company-data ingestion, **Tier 5** owner channel/spend/asks, **Tier 6** guards and self-checks.

## FIVE OF THE "EXCUSED" MUST STILL BE REBUILT — this is the part that gets lost

`132` says of each of these that the **cron line** is dead but the **purpose** is not. Counting them as
"not lost" would quietly drop real work:

| job | why the schedule is dead | what must happen |
|---|---|---|
| `audit` | **500 runs, 500 non-zero (100%).** Never once exited 0 | port **and fix**. Its finding is 12 real ERRORs including revoked pickup promises — the finding is the value, the schedule is what broke |
| `order-feed-refresh` | rc=127 "command not found" — the script MOVED | find the script, re-point, schedule |
| `pain-check` | 9 runs, 9 non-zero. `cron-wrap.sh`'s own comment: "the pain check suite had not run for 37 h" | rebuild; it is the loop that closes fixed defects |
| `hours-drift` | works, and is *correctly* failing — the Google listing genuinely disagrees | keep the finding, do NOT port the failing line unchanged |
| `cron-target-guard` | kept as PORT-ADAPT, but as evidence it is dead: it never decodes the base64, so it reports `ok / 0 missing` while ~60 targets are one wrapper | same green-while-blind shape as `cron-script-guard`. Fix the decoder |

## Six more already-red on the cloud, from `151` and confirmed live in the coordinator's round 5

`ai-gateway-health` rc=1 (95 s), `dialpad-recording-gap` rc=1 (traceback, line 199),
`dialpad-transcript-gap` rc=1 (SQL join on `dialpad_call_retranscript`), `guard-registry` rc=2
(`/root/bin/guards.yaml` missing), `lpt-freshness-watchdog` rc=1, `production-comms-freshness` rc=1
("website 5.25 h behind local store"). `dialpad-harvest-cron` is rc=0 but takes **227 s**.
And `cron-script-guard` still ran rc=0 four times in thirty minutes — green while blind.

## How this file was produced, and its one weakness

Every number is read-only: two ledger files and `132` itself. **The DEAD and OFFICE-ONLY classes were read
BY EYE from `132` §3 and §4, not extracted by code** — two automated attempts failed, first on a multibyte
sort error and then on a `§` encoding mismatch under `LC_ALL=C`. The classifications are quoted from `132`
so they are the inventory's; the subtraction arithmetic is the coordinator's and is checkable by rerunning
the two ledger commands above.

---

## RECONCILIATION WITH `152` — and a correction to this file's headline, 2026-10-11 ~21:25Z

`152-OWNERSHIP-MAP-AND-PORT.md` landed after this file was written, and it changes how the number above
should be read. It is the ownership map, built by requiring a **chain of three artefacts each naming the
job** (132 §1 job→family, 141 lines 30-37 family→workstream, then the workstream's own artifact naming
the job), applying the rule strictly: *a family allocation with no artifact naming the job is not
ownership.*

**Its finding: of 151's 27 "no home" jobs, 25 are OWNED by a named workstream and merely not done. Only
two were genuinely UNOWNED — `monitor-hetzner-backups` and `stripe-key-watch` — and it PORTED both,
proven by real cron ticks: `runs.tsv` rows at 21:06:01Z and 21:08:01Z (monitor), 21:07:01Z (stripe), all
rc 0.** It also reports `trunk-check` and `fa-index` are owned by workstream 137, **which retired both**,
so they need no port.

It further records that **my earlier guess of the unowned residue was 7 of 8 wrong.** I guessed
`lpt-daily-track`, `lpt-business-report`, `lpt-report-freshness`, `node-agent-cron`, `lpt-retranscribe`,
`dialpad-call-fresh` and `lpt-hub-refresh`; each of those IS named by its owning workstream's artifact.
Only `stripe-key-watch` was right, and the other unowned job, `monitor-hetzner-backups`, was not in my
guess at all.

**SO READ THIS FILE'S "~40 GENUINELY LOST" CORRECTLY.** The two files measure different things and both
are true:
- **`152` measures OWNERSHIP.** Its answer is about who is responsible.
- **this file measures EVIDENCE.** Its answer is about what has actually run on the cloud box, by ledger.

A job can be owned and still never have run — that is exactly the state of most of the ~40. So
**"never run on the cloud" must NOT be read as "unowned", and it must not be read as "nobody is doing
it".** Of the ~40, the large majority are owned-and-pending per `152`'s stricter test; two were unowned
and are now ported.

**The correction to make before acting on the ~40: cross this list against `152`'s ownership column
first, and count a job as needing a NEW owner only where no artifact names it.** Otherwise this file
will cause the very thing it was written to prevent — a second agent porting something another
workstream already owns and is mid-way through.
