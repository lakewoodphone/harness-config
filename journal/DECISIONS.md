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
**D19 · 2026-09-11 · Cost is a plugin, the rate card lives in git, and unpriced is an allowed answer.**
The Web GUI shows tokens and no money. *Decided:* add cost as a **local DSH plugin package**
(`harness-config/packages/plugin-cost`, installed into the web profile by `file:` path) rather than by
patching the shipped `dsh-client-ui-chat` bundle.
*Why:* the footer's stats row is already an additive list Slot (`conversation.composer.dock`,
`replaceRisk: "none"`), so a fresh `id` lands beside the shipped pill and replaces nothing; a patch to
`node_modules` would be reverted by the next install, could not be reviewed, and would make the system
describe itself wrongly. Two surfaces, because they answer different questions: `/cost` prices the
durable log per attempt with the real provider/model and the real call timestamp, and the composer pill
prices the session-level `tokenUsage` projection — which carries **no** route and no time, so the pill
prices at the deployment default and says so in its popover.
*Rate source:* `pricing.json` in the package, in git, every rate carrying its URL and read date. It is
the **only** authoritative card; `dsh-cost` keeps a copy so the standalone analyzer runs without this
checkout, and `lib/pricing-drift.mjs` exits non-zero when the two diverge.
*Why unpriced is allowed:* the DeepSeek card has three line items and no cache-write row. Charging
`cacheWriteTokens` at the miss rate would invent a charge the provider does not make and can double-count
tokens the harness also reports as uncached input. A route with no published price returns "unpriced",
and a model call that settled with no usage sample is named and the total is labelled a lower bound.
*Time-of-day matters:* `deepseek-official` bills 01:00-04:00 and 06:00-10:00 UTC Mon-Fri at exactly 2x
off-peak, so a cost is a function of the attempt's own clock and the report also prints a peak upper
bound. A single constant would be wrong about half the time.
*Open, and the owner's to decide:* whether the pill ships on all machines and whether the profile is
restarted to mount it. `~/.dsh/profiles/web/package.json` on this machine now lists the package and the
bundle; the running session still has the old bundle list, so nothing is mounted until restart. The
`/cost` command is host-only and needs no approval; the pill is a client half and a first run asks for
one.
**D20 · 2026-09-11 · "Verified" means observed on the real target, and a free blocker gets cleared instead of recorded.**
Two rules adopted together, both from one day on the Kosher filter.
*First:* a claim of verification requires an observation from the real target — a booted device, a live
server, an actual call — and **an exit code is not an observation when the command it wrapped did not
run**. `verify_on_device_ml.ps1` had been recorded as "verified: exits 1 with a clear message" while
every one of its 16 adb calls was malformed, so `adb` never ran and the "clear message" was adb's help
text (LESSONS L47). Concretely: no claim that a script works without a run against its real target, and
when a script has only ever been exercised on its failure path, say exactly that.
*Second:* when a task's only blocker is a free, scriptable dependency, **install the dependency rather
than recording the blocker**. A-BACK-011 sat blocked for five days on "no device or emulator"; the
emulator package and system image were a 15-minute install on a machine with 110 GB free, and clearing
it immediately produced a crash fix plus the discovery that the waiting harness had never worked.
*Scope note for this repo:* an emulator is accepted as the device for A-BACK-011 evidence, with the
limitation (no GpuDelegate, no NNAPI, so the GPU/NNAPI paths are unverified on silicon) recorded in the
backlog and the handoff rather than left implicit.

**D17 · 2026-09-11 · One DSH engine, many windows — not one process per window.**
A DSH window is only a browser client; one `dsh web` process already hosts many independent agent
sessions. An engine costs ~196 MB idle but **~1.4 GB once its five stdio MCP bridges are mounted**, and
those bridges are declared per process (`agent.cordis.yml`, `transport: stdio`) — measured three engines
at 26 descendants and ~1.4 GB each. One engine with 8–12 windows costs ~2.7–3.1 GB; 12 engines cost
~17 GB, which does not fit this laptop (31.6 GB total, 7.7 GB free, a qemu VM holding 5.3 GB).
`mode: "multi"` in `windows.json` keeps the per-window-engine option for the desktop.
*See:* `docs/multi-window/ANALYSIS-AND-DECISION.md`, `docs/multi-window/research-resource-cost.md`.

**D18 · 2026-09-11 · Window independence comes from the browser profile, not from a separate port.**
A session is not addressable by URL (zero `pushState`/`location.hash`/`sessionId` across all 65 client
bundles; the SPA is served only at `/`), and the chosen session lives in
`localStorage["dsh.sessions.current"]`, keyed by origin. One `--user-data-dir` per window gives each
window its own cookie jar and its own last-session record, so windows do not fight over one key — proven
by reading `dsh.sessions.current` out of the LevelDB of two separate window profiles. Restoring a window
to a *specific* session still needs a UI change; asked as question 3.

**D19 · 2026-09-11 · No browser extension; act through the DSH launch API.**
Where the GUI lacks something, the answer is the REST/CLI surface of the DSH launch, not a content script
in Edge. The harness's own README and factory workflow say so directly.
**D21 · 2026-09-11 · The modesty model does not need a training programme, and the Levels need a wording fix.**
Owner asked for a full re-analysis of the AI landscape because six months had passed since the Feb-2026 research
(directives 005/008/009, all dated 2026-02-25…27). Verdict, recorded in
`kosher-filter-ai/docs/research/015-ai-capability-reanalysis-2026-09-11.md` with four verbatim evidence reports:
1. **The $850–1,600 / 5–6-week training programme no longer prices anything real** — fine-tuning is $1–10 of
   rented GPU and hours, labelling $10–100 for 20k images. Cash is not the obstacle.
2. **But "no training needed at all" is also wrong.** Best zero-shot VLMs reach 64.0% macro-F1 on garment
   attributes yet only 24.7% at deciding whether an attribute is *visible*; model confidence is unusable for
   fail-closed gating (L54).
3. **Three of the five attributes are better solved by measurement than classification** — a verified ~22MB
   Apache-2.0 MediaPipe stack (pose 5.51MB + selfie-multiclass 15.61MB + hair 0.75MB) with no training, which
   fails visibly on out-of-frame parts. Direction validated by LaGPS (NeurIPS 2025, +19.4% mIoU over CLIPSeg).
4. **No VLM can run on the target device** — the floor is ~200MB on disk / 350–420MB resident against a ~512MB
   Android per-app ceiling, the SD835 has no INT8 tensor unit, NNAPI is deprecated, and the driver froze at
   Android 11 (which voids 009's Hexagon-for-INT8 decision on this hardware).
5. **"Married women's hair" is not a visual attribute**; hair *covered* is a solved binary (99.1% acc / 5.7%
   EER supervised). Tight/clingy fit has no benchmark above ~55% and is the one attribute that needs a probe.
*Decided:* do not fund a training programme. Replacement plan — one-day physical-device measurement, then a
**one-week three-arm bake-off on ~1,000 hand-labelled screenshots** (zero-shot VLM vs geometric rules vs a ~5MB
classifier trained on those same labels) using the existing Phase 13 calibration harness: under $500, 3–10 days,
with human labels as the only irreplaceable input. 008's *business* trigger (50–200+ devices) stands; its
*technical* assumptions are superseded.

**D22 · 2026-09-11 · The modesty ladder is now: Level 3 hides women, everything is a configurable knob, and the cascade covers before it decides.**
Owner decisions taken in conversation this session, all recorded in `kosher-filter-ai/docs/modesty-baseline-owner-decisions-2026-09-09.md` §6 (appended, nothing in §1–§5 superseded) — and recorded *here* because the journal is what I read first, and a decision that lives only in a repo I have to remember to open is a decision I will re-ask.
1. **The strictest Level means "no women visible"** — a *mechanism* difference, not a threshold. His reasoning, which I had not seen: the population that wants women hidden does not care about a hair judgement (the person is hidden anyway), and the population comfortable seeing women is rarely moved by hair covering either. So hair covering **stops being a level rule** and survives only as an optional knob — the most sensitive and finest-grained judgement in the original ladder became optional.
2. **Who counts as a woman: any female figure, including girls** (my recommendation, accepted). "Adults only" is a knob. Reason it matters: age estimation from a screenshot is the least reliable component available, and it would bolt the weakest link onto the weakest part of the pipeline; and the direction of error is right — someone choosing this level wants fewer females on screen, so when the model is unsure, hiding is what they asked for.
3. **Everything is a configurable knob; a Level is a default bundle, never a lock.** His words: *"just because something is the default doesn't mean you can't configure it… Everything is configurable at setup time by the user if they want. And even later, based on their time delays and how they set up, they could change that up. You always have to remember that."* A Level 3 household may switch hiding off; a Level 1 household may switch it on. **Nothing I design may hard-code a policy.** I flagged one inference for correction rather than asserting it: that loosening is gated by the meta-rules/time-delay machinery while tightening is immediate.
4. **Cover on uncertainty; reveal only on verification** — for the *spatial* problem (per-region pixel hiding) as well as the temporal one. He agreed, with the reasoning that whole-image hiding is unacceptable for home/family photos: **per-region hiding, not whole-picture hiding.**
*Consequence for everything downstream:* the Level→policy mapping must be a preset over individual knobs, and the policy-adaptive guard model makes a policy a *prompt*, so a household's configuration is data rather than a release.
