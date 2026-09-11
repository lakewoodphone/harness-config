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

**D30 · 2026-09-11 · The phone signs itself in; the owner never handles a token URL again.**
A one-time `?token=` link dies at every engine restart, and a bookmark that dies is a support call in his hand.
So the entry point is `scripts/phone-gate.py` on 127.0.0.1:3086 — the port Tailscale Serve publishes — and a
document request to `/` with no harness cookie and no token is answered with a 302 to `/?token=<live>`, read
from the engine's own log at request time. Everything else (the exchange, assets, the REST API, the WebSocket)
is relayed byte-for-byte, which is why upgrades survive. The engine now sits behind it on 3089. Superseded
within the hour: the token is read from `engine-<engine-port>.log`, not by newest mtime (L133).

**D31 · 2026-09-11 · "Does the phone work" has exactly one source of truth: `~/.dsh-phone/probe.json`.**
`probe-phone.py` walks the human path and writes its verdict atomically every five minutes from cron; the kernel
reads that verdict rather than re-deriving health from a socket. A missing or stale file is reported as absent
evidence (medium), never as green. *Rejected:* teaching the kernel the probe's logic (two implementations of one
truth), and mailing on failure (no inbox exists yet, and mail-per-run is the alert fatigue this system already
paid for — see P40).

**D32 · 2026-09-11 · A broken public link is medium; a broken tailnet link is high.**
The phone reaches the harness over the tailnet, so a Cloudflare-path failure is a degraded second route, not a
phone outage. Severity that cries wolf is severity that gets ignored, and this file already contains the cost of
that lesson.

**D33 · 2026-09-11 · `ai.abletelsolutions.com/` is left alone.**
Its root is a Next.js app on :3000 with its own sign-in — a different product, not the harness. The owner's
reported error was the harness 401, which means the icon he taps already points at the harness, so nothing needs
moving for him. Re-pointing that root without evidence of what else uses it would be an irreversible-ish change
to someone else's surface for no gain.

**D34 · 2026-09-11 · The gate completes the login in flight and returns the document. (Supersedes D30.)**
D30 handed the visitor a 302 to `/?token=<live>`. That cannot be made safe: a client that keeps a cookie the engine refuses
refollows for ever (measured: 50 hops), and no query marker survives the engine's own 303 back to `/`. So the gate now does
the login itself — exchange the token, keep the session cookie the engine returns, fetch the document with it, return it with
`Set-Cookie` injected. Cost: the doc is buffered (27 KB, once per unauthenticated request). Benefit: one client request, one
200, no loop constructible, and the launch token never appears in a URL, a Location header, or browser history.

**D35 · 2026-09-11 · The public redirector hands out a bare URL.**
With the gate signing visitors in, the launch token does not need to exist in any link the owner can save. One fewer secret
in a header, one fewer thing that can go stale on a home screen.

**D36 · 2026-09-11 · One request per connection: `Connection: close` on everything but upgrades.**
The gate must decide on every request, and it can only do that if every request arrives on its own connection. Serve pools;
forcing close upstream makes the engine end each response, which forces Serve to reconnect. The websocket upgrade is
exempt — it carries every streamed reply and must stay open.

**D37 · 2026-09-11 · HA's `zone.home` is the shop; Home Assistant is never allowed to name "home".**
Measured: `zone.home` = 40.108374,-74.232428 (1001 W Kennedy Blvd), `radius` 100 m, with `person.montrose` — a *worker* —
GPS-verified 69 m from the centre, and the shop's own `doorbell_cam` and Shelly plug reading `home`. HA therefore answers
only *at-the-shop / not-at-the-shop*, and its `person.eliyahu_zabrowsky = not_home` is fed by a LAN-MAC tracker that is
blind off the office Wi-Fi. So presence is resolved by fusing HA's office ground truth with a **network** signal (which
LAN/WAN the phone is dialable on), and `not_office` is a distinct verdict that is **never** upgraded to `home`.
*Also decided:* an empty reading is never reported as `away` — iOS suspends Tailscale routinely, so absence of an endpoint
is `unknown`.
*Rejected:* adding a home geofence by hardcoding a coordinate. See D38.

**D38 · 2026-09-11 · The home zone is learned from a GPS fix, never typed in.**
Rather than asking the owner for his address, the resolver records the first real fix that lands while the observer is on
the home LAN as the home zone (haversine + 150 m). Consequences: the harness never has to ask him where he lives, the zone
cannot drift from reality the way a hand-entered constant can, and if the permission is never granted the resolver keeps
answering `not_office` honestly instead of guessing.
*Depends on:* the owner granting the iOS HA app location permission — currently `Not determined`, which is the root cause
of the dead `device_tracker.iphone_15_2`.

**D39 · 2026-09-12 · A verdict is cached against the thing it is about, and an unverified allow is a defect, not a bug.**
Found and fixed in the kosher filter's browser lane: per-image ML verdicts were stored in the **domain**-keyed broker cache
and returned `safe` early on a hit, so on an image CDN the first SAFE picture flipped the whole host to ALLOW for five
minutes and every later picture was revealed unclassified. A cached domain ALLOW is no longer sufficient to reveal an
image, and an unjudgeable picture no longer writes a domain DENY that reached the DNS router.
*Why it is a decision and not a fix:* it names the standing rule for the whole visual path — **the cache key must be at
least as specific as the claim**; pixels by content hash, hosts by hostname, pages by URL. Any future cache in this
product is measured against that sentence.

**D40 · 2026-09-12 · The cover is recoverable; the placeholder is not — so bytes are never replaced on uncertainty.**
Continuing the same review: the proxy still forwards image bodies unchanged, and the injected CSS blur is what covers
them until a verdict arrives. Byte-level placeholder substitution is deliberately **deferred**, and the guard-rail is
recorded so it is not silently re-decided later: a placeholder may follow only a **positive DENY**, never "unknown" or
"over budget", because the page has already received those bytes and no later verdict can give the real image back.
*Impact:* the tempting quick win would convert a recoverable cover into an unrecoverable one on every image the cascade
cannot reach in time, turning a single false positive into a permanently broken page.

**D41 · 2026-09-12 · The kosher filter's calibration question goes to the owner as one money question, with the free path first.**
The 2026-09-11 re-analysis removed the need to train a model, which changed the funding question that had been sitting open
as `A-BACK-014` ("fund a modesty model, ~$1,200"). What remains is ground truth: no labelled frames exist, so every
threshold is unverified (P45). The honest sequence is in-house first — build the harness, label ~200 frames in about an
hour of a person's time, learn whether the cascade can hold a usable risk level — and only then consider a paid
1,000-frame round ($4–8k). Asked as a single question with a recommendation; the `A-BACK-014` row is marked superseded
rather than deleted.

**D37 · 2026-09-11 · Mobile fixes live in a stylesheet the gate injects, not in the harness package.**
`assets/mobile.css` is served by `scripts/phone-gate.py` into every document request. Rejected alternatives: editing the
installed `@deepseek-ai/dsh-client-ui-*` packages (npm overwrites them on update, and the change would be invisible in
git), and forking the client (a rebuild per harness release for a stylesheet). Scoped to `max-width: 768px`, matched on
CSS-module local-name substrings and ARIA semantics rather than hashes so a client rebuild does not silently disable it,
and reversible with `PHONE_MOBILE_CSS=0` without a code change. Supersede this with a real client plugin once a session
has the `cordis_*` tooling: state behaviour (closing the drawer on navigation) is out of a stylesheet's reach.

**D38 · 2026-09-11 · Phone behaviour is split by what it needs: CSS where any browser must get it, a client plugin where state is involved.**
`assets/mobile.css`, injected by the gate, carries what a stylesheet can express and what must work even in a browser without
the plugin: touch targets, the 16px field font that stops iOS auto-zoom, safe-area insets, and the open drawer overlaying
rather than squeezing the content. `packages/plugin-mobile` carries state — closing the drawer once a conversation has been
picked — because a stylesheet cannot see a selection. Both use the same 768px breakpoint, so there is one definition of
"narrow" rather than two that drift. The plugin is installed through a symlink plus a bundle-list entry (neither in git) and
`serve-phone.sh` reinstall checks them, on the same reasoning as the gate: a component that can silently disappear needs a
keeper, not a procedure.

**D39 · 2026-09-11 · Untracked production code is archived onto a side branch built with plumbing, not by touching the working tree.**
The Shabbat/Yom Tov automation (`shabbat_orchestrator.py`, `shalom_zmanim.py`, `shelly_plug.py` and their two test
files) was **untracked in git on the host that runs the business**, with nine other files modified by another
author and 71 commits of it behind origin. Archiving it was required — tonight it has to work and a disk death
would take it forever — but committing it normally would have moved HEAD on production or swept someone else's
in-flight work into my commit. Instead: a temporary `GIT_INDEX_FILE`, `git read-tree HEAD`, add only the five
paths, `git write-tree`, `git commit-tree`, then `git branch -f shabbat-automation-20260911` and push. Result:
commit `8490d137` on the remote, `git status --porcelain | wc -l` unchanged at 26, HEAD still `master`. This is
the general pattern for preserving someone else's live work without negotiating with them.

**D40 · 2026-09-11 · The erev-day block merge is not changed unilaterally an hour before Yom Tov; it is asked.**
`is_power_down_day` counts *erev* days, so the maximal run Fri Sep 18 → Mon Sep 21 is programmed as ONE block:
HA and every camera stay dark from Fri 18:35 until Mon 20:10, spanning Sunday Sep 20 (erev Yom Kippur, a
working-day-shaped day, shop closed per the owner's own stated hours). The owner's human practice was off Friday →
on Saturday night, up all Sunday, off again for Yom Kippur — so this is a divergence introduced by the automation,
not a continuation of it. The change is small (run blocks over *holy* days only, and take the OFF time from the
first holy day's erev) and would not affect tonight's Fri–Sun block. It was still not applied: it alters a security
system's behaviour, it needs his judgement about the Sunday, and there is no urgency — the next program run that
could apply it is Tue Sep 15 at 10:00. Escalated as one question with a recommendation instead. Recorded so a
future self does not "helpfully" apply it in the meantime.

**D41 · 2026-09-11 · Two holy periods separated by an ordinary weekday are two power-down runs (owner: "For sure, split it").**
Asked with options and a recommendation, the owner chose to split. Power-down runs are now built from **holy days
only** (`shalom_zmanim.is_holy_day` = Shabbat or chag); an erev day supplies the OFF *time* of the run that starts
the next day (`block_off_time`) instead of extending a run already open. Concretely, from the device:
`OFF 18/09 18:35 → ON 19/09 20:13` (Shabbat) and `OFF 20/09 18:31 → ON 21/09 20:10` (Yom Kippur) replace one
`OFF 18/09 18:35 → ON 21/09 20:10` run. HA and every camera are therefore up for the whole of Sunday 20 Sep, and
the interior maglock is re-latched Saturday night rather than left released for 73½ hours. Rosh Hashana (Sat+Sun,
both holy) remains a single run, so tonight is unchanged. Supersedes the "left alone, escalated" position in D40 —
the owner has now answered. `is_power_down_day()` is retained but is **no longer** the block predicate; do not
rebuild runs from it.
