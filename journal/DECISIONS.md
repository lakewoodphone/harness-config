# DECISIONS — what was decided, and why

**Append-only.** A decision that is later reversed is not deleted; it is superseded by a new entry
citing it. The record of having changed course is itself useful.

The full working log, with evidence and the owner's own words, is
`~/code/personal-secretary-mvp/docs/secretary-replacement-audit/06-decision-log.md`. This file is the
short form, so a future self does not have to read seven documents to avoid relitigating something.

---

**D1 · 2026-09-11 · The CEO replaces the console, and owns the systems.**
DSH takes the seat Copilot held, as CEO. It commands `secratary` and evolves it. It does **not**
rebuild the secretary — 216k lines, 618 routes and working integrations are the asset.
*Owner's words:* "you take on the ceo instead of copilot and you take charge of all teh systems."

**D2 · 2026-09-11 · The secretary's orchestrator is the Chief of Staff.**
DSH decides; the company executes continuously on its own tick loop. Putting orchestration in DSH
would idle the company whenever the owner closed a window — the failure being migrated away from.

**D3 · 2026-09-11 · Visibility before capability.**
Build order: outcome monitor → digest → bridge → then evolve. An owner who cannot see his own systems
repeats the six silent days.

**D4 · 2026-09-11 · Keep GitHub and chat sync; make the secretary the only authoritative chat store.**
Transport was never the problem — 1,585 sessions were indexed correctly. Provenance was.

**D5 · 2026-09-11 · One authoritative database.**
Three copies of `secretary.db` exist (203 / 194 / 173 tables, three different last-tick dates). The
one on `secratary` is the truth; everything else is a replica and must say so.

**D6 · 2026-09-11 · Authority on `secratary`, compute on the desktop.**
The durable monitor lives on the always-on Linux host (8-day uptime, same LAN as the database); the
primary console is the office desktop (i9, 63 GB). *The thing watching must outlive the thing being
watched.*

**D7 · 2026-09-11 · `harness-config` is the single source of truth for the harness.**
Presets, settings and skills are git-tracked with a remote on `secratary`, synced by
`scripts/sync.py`. Never edit `~/.dsh` directly.

**D8 · 2026-09-11 · Do not stop for permission already granted.**
A turn ends only for completion with evidence, a genuine blocker, an owner-only decision, or an
irreversible action.

**D9 · 2026-09-11 · Build the conversational interface first.**
*Owner's words:* "what affects me most right now and day to day is the you i talk to, the
conversational interface." The CEO and the secretary evolution are long-term; the face is now.
→ the `zabz` preset, set as default after mount validation.

**D10 · 2026-09-11 · The journal is the memory.**
Because every session starts blank, growth is only possible if lessons, handoffs, pain and decisions
are written down. `journal/` is the organ, not documentation. The persona requires writing for the
self that wakes up without memory.

**D11 · 2026-09-11 · The kernel is version-controlled the same way the harness is.**
`ceo-kernel` is a git repo with remote `secretary-ts:/home/zabz/ceo-kernel.git`. `secratary` holds a
**checkout**. The server copy is never edited in place — that is the same rule as D7 and the same
failure as L13. Rationale: the kernel is code that runs on the always-on host, so it must be
deployable, reviewable and revertible from one source, or the server silently becomes a second,
divergent truth. Runtime output is explicitly excluded: the sentinel writes to
`/home/zabz/ceo-kernel-var/`, outside the working tree, because observations of a moment are not
source and a scheduled job must never dirty the repo it lives in.

**D12 · 2026-09-11 · The sentinel runs on cron as the interim Phase 6, and deliberately sends nothing.**
Every 5 minutes on `secratary`, via a script **in the repo** (`scripts/run-sentinel.sh`) rather than an
inline crontab command, so the behaviour is versioned instead of living in someone's crontab.
It records `latest.json` + `history.jsonl` and routes nothing.
*Why not alert:* the inbox (Phase 2) owns escalation and the interrupt quota (design §3.3). Mailing on
every run before that exists would recreate the alert fatigue that buried 7 critical and 46 urgent
messages (PAIN P6) — a monitor that trains its reader to ignore it is worse than a silent one.
*Superseded when:* Phase 6 lands a systemd daemon; this entry is then **replaced, not duplicated**.

**D13 · 2026-09-11 · Home Assistant's live truth is collected over HA's own APIs, read-only, not by SSH.**
`scripts/ha_truth.py` + `scripts/ha-truth.ps1` read `/api/config`, `/api/states`, `/api/services`,
`/api/error_log` and the WebSocket admin surfaces (`config_entries/get`, `entity`/`device` registry
lists), and emit a payload in which every reading carries source, read time, the data's own age, its
assertions, or an explicit refusal.
*Why:* (1) it cannot mutate anything, so it is safe to run unattended; (2) it works from a host that
can only reach the office LAN through `secratary`; (3) it kept working while the SSH add-on was off,
which is exactly the condition the system was found in. The SSH-based `scripts/inventory.ps1` path
stays for what only SSH can see (`/config` contents, add-ons via `ha` CLI) — the two are complements,
and the audit states which claims come from which.
*Explicitly rejected:* installing a Python package (`websockets`) on the company server to read from
it. The protocol is ~120 lines of standard library instead.

**D14 · 2026-09-11 · Severity on the HA truth surface is assigned by deterministic code, not by a model.**
The collector maps measured conditions to fixed finding codes and severities
(`SECURITY_SENSORS_UNAVAILABLE`, `EVIDENCE_CAPTURE_FAILING`, `KEYMASTER_ENTITIES_LOADED`, …). A model
may summarise but may not decide whether something is a problem.
*Why:* a monitor whose judgement varies between runs cannot be trended, diffed, or trusted; and the
single most expensive failure in this system's history was a confident reading nobody could check.

**D15 · 2026-09-11 · Security-relevant integration degradation is judged narrowly on purpose.**
Only integrations with direct security or access-control consequences (`zha`, `mqtt`/`zigbee2mqtt`,
`esphome`, `dahua`, `reolink`, `keymaster`, `phoenix_access_manager`, `hassio`, `bluetooth`/`bermuda`)
raise the security flag. A dead printer and a flapping UPS are reported at their true severity.
*Why:* the first run of the collector called the UPS and the printer "security-relevant" because their
titles contained no security words but their domains were guessed into the list. Inflating severity is
how an alert surface gets ignored — the same failure mode as the 144 sync-breaker alerts that led to
three competing dismissal schemes (PAIN P6).

**D16 · 2026-09-11 · The thirteen-day silence is investigated, explained and labelled — not silenced.**
The owner was asked whether the zero-tick window `2026-07-22 → 2026-08-04` was deliberate. He did not
know and asked for an investigation. Established: **the host was up and healthy every day** (files
written daily, `logrotate` ran, apt/pip/git activity) while the **work loop was dead** for
**13 days 17 hours** — a company built to work unattended, unattended by accident. Written up in
`personal-secretary-mvp/docs/postmortem/2026-07-22-thirteen-day-silence.md` (commit `f25d8d333`).
*How it is recorded:* the kernel **keeps reporting the gap and attaches its explanation**
(`KNOWN_GAPS` in `ck/sentinel.py`). Hiding it would defeat the check; reporting it bare would re-open an
answered question on every single run — and a monitor that keeps asking what has already been answered
is how a real alarm gets trained away.
*Open, deliberately not closed here:* the autopilot's stale-guard **disables instead of re-arming**
(`app/autopilot.py`); the cron watchdog asserts process liveness, not outcomes; and the monitor still
lives on the machine it monitors (PAIN P20). Three things were not established and are listed
individually in the postmortem rather than glossed.

**D17 · 2026-09-11 · A write crossing a storage boundary is verified by reading the row back from the consumer's store.**
The Waze MDM Telnyx snapshot had been running daily, exiting 0, and logging `Persisted 2 per-SIM usage
rows` while writing to an orphaned SQLite file — the `fleet_api` it feeds reads PostgreSQL, where both
`fleet_telnyx_*` tables were at zero rows and always had been. Two mechanisms: a leftover SQLite default in
`_connect_db()`, and a per-SIM insert naming a `customer` column Postgres never received (its
`CREATE TABLE IF NOT EXISTS` cannot alter an existing table), with the failure swallowed by a bare
`log.warning`. *Decided:* `_connect_db()` prefers PostgreSQL when `PG_DSN` is set; a `try/except` around a
write may not both log-and-continue, so `persist_snapshot()` now returns success/failure, rolls back, and
the CLI exits 2 rather than printing success; and `telnyx_usage_freshness.py` runs in cron at 05:00 to fail
loudly if the data goes stale. *Reasoning:* "the job ran" and "the job exited 0" are not evidence, and this
is LESSONS **L1** and **L2** arriving through a cron job. The stranded history was migrated into Postgres
(12 usage + 18 ledger rows, 2026-09-06 -> 09-11, proved idempotent). See PAIN **P15**.

**D18 · 2026-09-11 · The Kosher Waze gate is four owner decisions, not twenty-one questions.**
The integration plan lists Q8-Q28 unanswered and treats all of them as the owner's. They are not: most are
factual (answerable from the live system) or engineering calls already inside the mandate, and Q2-Q5 are
already locked in the answer log. *Decided:* collapse the gate to the **four** that are genuinely his —
(1) billing shape: is `$9/mo - 250MB - 800MB cap - $18/GB` final, and does the portal *collect* money or
only *show* it; (2) self-serve line: do customers get pause/resume, and is customer-triggered lost mode
allowed; (3) cap behaviour at the limit — pause, throttle, or throttle-and-upsell; (4) location/compliance:
is any trip data stored, and what constraint applies before payments. Ask them **one at a time with a
recommendation**, and answer the remaining seventeen myself from live config. *Reasoning:* he does not do
dev questions (LESSONS **L7**), and 21 questions in one batch is exactly the shape of request that cost
this system its workflow before. See `deploy/waze-mdm/docs/holdings-2026-09-11.md` section 5.