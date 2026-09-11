# WINS — what measurably worked

**Rule:** record changes that demonstrably helped, with the measurement that shows it. This exists
for a specific failure mode: a working thing gets "optimised" away by a later self who does not know
it was load-bearing. It also gives the evolution loop a baseline of known-good.

Only entries with evidence belong here. An improvement that felt good is a hypothesis, not a win.

---

**W1 · 2026-09-11 · Provenance layer prevents a repeated false report.**
Run on the Yoga against a structurally-old replica, the kernel **refused to report** rather than
producing numbers: *"no usable database found … only 173 tables (< 190); structurally old"*. Run on
`secratary` against the authority, it reported normally and labelled the source `AUTHORITATIVE`.
*Measurement:* the same query that previously produced a fabricated 45-day outage now either reports
with provenance or refuses. **A refusal is the correct output.**

**W2 · 2026-09-11 · The sentinel found things manual analysis missed.**
Against the live database it surfaced two findings that had never been noticed:
`engineering_indexer` with **172 ticks and zero completions**, and an owner question **131 days old**.
*Measurement:* 4 attention findings on first run, 2 of them new information.

**W3 · 2026-09-11 · The sentinel detects the historical failure retrospectively.**
`find_failure_windows()` generalises the 8–13 August incident into "any run of consecutive days whose
completion rate fell below 60% with real volume". It flagged `2026-08-23..08-24` (890 ticks, 28%
complete) on live data.
*Measurement:* the acceptance test for Phase 1 — detect a failure that already happened — passes.

**W4 · 2026-09-11 · The harness now converges instead of drifting.**
Two machines, one git source of truth, sync verified byte-identical (`sha256 65FCB7E4…` both sides),
and a second sync run reporting **fully clean** — no phantom differences.
*Measurement:* previously the two `settings.yaml` files differed in both directions and an authored
preset was invisible to the other machine and switched off on its own.

**W5 · 2026-09-11 · The CRLF trap is solved for every machine, including future ones.**
`.gitattributes` (`* text=auto eol=lf`) plus content-normalised comparison. *Measurement:* verified
with a **fresh clone using the machine's default git config** — no per-machine setup required. Before
the fix, every machine reported perpetual phantom diffs that would never converge.

**W6 · 2026-09-11 · The `zabz` preset composes.**
`standingKeyFor('zabz')` → **`mounted OK: zabz`**, alongside 20 rows including the full toolbelt and
the secretary MCP bridge. *Measurement:* mount-validation is the harness's own real composition check,
not a shape check.

**W7 · 2026-09-11 (later) · The secretary bridge registers and works in a live session — the last unproven item, now proven.**
The previous session's open question was whether `mcp__secretary__ps_*` actually appears in a session
running `zabz`. It does.
*Measurement:* the harness's own session record reads `"agentPreset":"zabz"`; the live tool catalog
contains all 14 `mcp__secretary__ps_*` tools; and `ps_company_status` **returned real company data** —
6 active goals, today's model usage across 8 models. A tool that appears but cannot be called would
have been the next failure; it was called.

**W8 · 2026-09-11 (later) · The kernel now watches without being asked.**
The sentinel existed and worked, but only when invoked — which is the exact shape of failure it was
built to catch (its own PAIN entry left "run it on a schedule" for later).
*Measurement:* cron on `secratary` runs `scripts/run-sentinel.sh` every 5 minutes; the state
directory holds `latest.json` (13.8 KB, full provenance) and a `history.jsonl` line recording
`exit:1, authoritative:true, tables:203, attention:4`, naming the four failing checks. The reading is
self-describing: source path, host, authority flag and table count travel with the numbers.
**Observed, not assumed:** `run.log` holds `16:51:24` (run by hand) and **`16:55:02` — the cron
tick, at a time nobody chose.** That second line is the actual proof; the first one proved nothing
about the schedule.

**W10 · 2026-09-11 (later) · The kernel learned to see absence — and immediately found a 12-day outage.**
Every check grouped rows that exist, which made the sentinel structurally blind to a day the company
never ran. That is the failure mode the whole kernel was built for (L12), sitting inside the kernel.
Added `check_telemetry_gaps` (calendar days in the trailing window with zero telemetry, silence still
open = critical) and made every span count calendar days instead of rows.
*Measurement:* the new check reports *"a tick row exists for every day in the last 30; largest
historical gap **12d (2026-07-22 -> 2026-08-04)**"* — a **12-day total outage, 2026-07-23..08-03,
zero tick rows**, that no monitor, no digest and no human had flagged. It was previously invisible
because the sentinel described it as part of "120 days".
*Second measurement, for honesty:* off-authority the same code produces **no numbers at all** — on
ZABZ-YOGA, with only a 173-table replica present, all eight checks refuse with their reason. A refusal
is the correct output, and it was verified rather than assumed.

**W9 · 2026-09-11 (later) · A false entry in my own record was caught by re-measuring, not by review.**
PAIN P10 claimed duplicate MCP servers. Nobody reviewed it away — re-measuring did, in one command,
by counting processes by exact script name instead of by directory.
*Measurement:* the claimed four `ps_mcp_server.py` processes are **one**; the other three matches were
different scripts in the same directory. P10 is retracted in place (kept, not deleted, because the
error is the useful part) and LESSONS L28/L29 record the method.
*Honest caveat:* the discipline worked on the second look, not the first. The entry was written
confidently and sat in the file. The lesson is that a surprising count needs a second filter before it
becomes a finding, not that the correction mechanism is reliable on its own.

**W11 · 2026-09-11 (later) · Home Assistant got a live truth surface, and it found the failures a manual look missed.**
Before: the newest live Home Assistant facts in the repo were dated 2026-04-17, and the whole inventory
path needed SSH, which is closed. Now: `scripts/ha_truth.py` reads HA's own APIs (REST + WebSocket
admin) read-only and emits provenance packets plus deterministic findings; `scripts/ha-truth.ps1` runs
it locally or through `secratary`.
*Measurement (three verification runs, 16:55→17:01 UTC):* the tool reproduced every number this session
had gathered by hand — 1068 live entities, 45 config entries (40 loaded, 2 not loaded, 3 setup_retry),
1895 registry entities with 834 disabled, 82/150 automations unavailable, 41 Keymaster entities — and
added three findings the manual pass had not surfaced: `EVIDENCE_CAPTURE_FAILING` (365 camera snapshot
errors), `LOG_LOUDEST_ERROR` (683 identical OAuth lines) and `OAUTH_RETRY_STORM`.
*Second measurement:* the first end-to-end run **refused** on `/api/error_log` because the endpoint
returns text, not JSON, with the reason and the raw bytes in the payload. The fix took one edit, and
the second run's log section is real. A tool that had silently returned an empty log would have hidden
the camera failure entirely.
*Honest caveat:* the tool cannot see add-on versions, the HAOS version, or `/config` contents — it says
so in `not_verifiable` rather than leaving a blank. It is a complement to the SSH inventory path, not a
replacement for it.
**CORRECTED later the same day:** "SSH, which is closed" was wrong — SSH is on port 2222, and the
toolchain scripts all defaulted to 22 (LESSONS L46). Also, `EVIDENCE_CAPTURE_FAILING` overstated the
camera situation; see W15.

**W12 · 2026-09-11 (later) · The absence check paid for itself the same day: it found a 13-day outage nobody knew about.**
`telemetry_gaps` was written because the kernel could not see a day on which nothing ran. Within the
hour it surfaced a **13-day 17-hour total silence** (last tick `2026-07-22T00:21:02Z`, first tick back
`2026-08-04T18:06:44Z`) that no monitor, no digest, no postmortem and no human had ever flagged.
*Measurement:* the investigation then established, from evidence rather than inference, that **the host
was up and healthy every single day** (files written on all twelve days, `logrotate` ran Jul 23, apt and
pip activity throughout) while **the work loop was dead** — so every liveness monitor in the system was
green during the longest outage in its history. Written up in
`personal-secretary-mvp/docs/postmortem/2026-07-22-thirteen-day-silence.md`.
*Second measurement:* the fix generalised rather than special-casing. The kernel still reports the gap
and now attaches its explanation (`KNOWN_GAPS`), so an answered question stops being re-opened every
five minutes — the failure mode that produced the three competing dismissal schemes of P6.
*Cost of the discovery:* ~20 minutes of tooling. Cost of not having it: the outage was already three
weeks old and would have stayed unknown indefinitely.

**W13 · 2026-09-11 (later) · The harness shows money now, and the numbers are cross-checked against the harness itself.**
Before this, nothing in the installed harness priced anything in currency: the footer showed tokens, the
`tokenUsage` projection carried four integers with no route and no cost, and the only USD rates in the
tree were in upstream `pi-ai` catalogs that `dsh-llm-pi-ai` deliberately zeroes. Now `pricing.json`
carries a cited rate card, `/cost` prices a session from its own durable log, and a cost pill sits in
the composer dock.
*Measurement, in three parts.* (1) **The totals reconcile.** `lib/validate.mjs` replays the harness's own
`tokenUsage` projection — the function behind the footer's figure — over every session log on this
machine, and this tool's total equals it **on all 15 logs**, with zero differences. (2) **The arithmetic
is exact.** Costs are integer micro-dollars, so a session total equals the sum of its per-turn costs
exactly, asserted on every log; and the peak-rate upper bound is never below the actual cost. (3) **The
plugin resolves and renders.** `test/verify.mjs` passes four independent checks: generated files current,
rates and tier arithmetic correct against real logs, the browser half registering and rendering under a
reproduction of the module-loader contract, and the package resolving by name from the profile.
*What this exposed:* on the 22-turn session of 2026-09-11, **$1.36** at off-peak rates ($2.19 if every
call had landed in a peak window) for 135.7M billed tokens at a 97% cache-hit rate — and 98% of the
cost is the uncached input, which is what a cache hit rate actually buys. The single most expensive turn
was **$0.33**: one turn, one third of the session.
*Honest caveat:* the footer pill is verified to register and render, **not** to look right on screen;
only a browser session proves that. And the session-level projection has no route, so the pill prices at
the deployment default and says so, while `/cost` prices each attempt from the log with its real route
and timestamp.
**W14 · 2026-09-11 · The Kosher filter's on-device ML verification finally ran — and it found a crash every JVM test had missed.**
`A-BACK-011` had been "PARTIAL — needs a device or emulator" since 2026-09-06. The blocker cost one
command: `sdkmanager 'emulator' 'system-images;android-34;google_apis;x86_64'` plus an
`avdmanager create avd`, on a machine with 110 GB free and WHPX available. With the AVD booted, the
harness reported **pass=16 warn=0 fail=0**, and the device logcat proved the whole claim:
`GantManNsfw: Model loaded successfully` and `NudeNet: Model loaded from .../files/models/nudenet_320n.onnx`
with a real decision, then — with every model file hidden — `ShareIntercept: Blocked uncertain image
share: No local classifiers available`.
*What it bought:* three genuine findings that no test on this box could have produced. (1) A
**main-thread crash**: the first image a user ever shared killed the app, because an `Error` from a
`compileOnly` GPU dependency escaped `catch (Exception)` through the whole ML stack (L48) — the R8
`-dontwarn` added to make the *build* pass is what hid it. (2) The verification harness **had never
once run** (L47). (3) The fail-closed probe could never have observed anything, because nothing ever
asked the cascade to classify — the section is now driven by a real `ACTION_SEND` share, and `-DriveShare`
exists for the same reason.
*Measured:* Android unit suite **362 tests / 0 failures** after the fix (was 360; +2 new), the new
contract test verified to fail on the pre-fix script, and the probe's restore verified to put all three
model files back in place.
*Honest caveats:* an emulator has no GpuDelegate and no NNAPI, so the GPU/NNAPI runtime paths and the
GPU delegate now being optional are unverified on silicon. The two new Kotlin tests pass with or without
the fix, so the on-device run — not the unit test — is the evidence.

**W15 · 2026-09-11 (later) · The Home Assistant estate now reads itself every 30 minutes — and the first scheduled tick was observed, not assumed.**
The instrument from W11 found everything but nothing ran it: `ha_truth.py` was invoked by hand, so a
door contact going dark at 01:48 was a discovery rather than a message.
*Measurement:* `ceo-kernel/scripts/run-ha-truth.sh` added (`0ec7104`), deployed to `secratary`, cron
`*/30 * * * *` installed. The first line in `ha/run.log` is **18:21:43** — run by hand, which proves
nothing. The second is **`18:30:01`** — the cron tick, at a time nobody chose. Same proof pattern as
`run-sentinel.sh`, same rejection of the assumption that a cron line means a job runs.
*What it records:* `ha/latest.json` + `ha/latest.md` per run, and one line in `ha/history.jsonl`
carrying the trend rather than a sample — `{"at":"2026-09-11T18:21:43Z","entities":1068,"unavailable":400,
"security_critical_unavailable":5,"severity":{"critical":3,"high":3,"medium":7,"low":1},
"codes":["SECURITY_SENSORS_UNAVAILABLE","SECURITY_INTEGRATION_DEGRADED","EVIDENCE_CAPTURE_FAILING", …]}`.
*Design decision worth keeping:* it keeps the **last good reading** when a run produces nothing, because
an empty file is not evidence of health; and it exits 0 while routing nothing, because alerting belongs
to the inbox (design §3.3) and mailing on every run is what buried the 7 critical messages.
*It regenerates the collector from the ha-config mirror on every run*, so a fix in that repo lands
without a second deployment step.

**W16 · 2026-09-11 (later) · A one-space indentation bug had silently disabled the intrusion siren, and it is fixed and verified.**
`packages/secretary.yaml` had `phoenix_alarm_mac_on`/`_off` indented one space, making them siblings of
`rest_command:` rather than entries inside it. Home Assistant parsed the file, found no such commands,
and carried on. **Measured before the fix:** `rest_command.phoenix_alarm_mac_on` and `_off` were ABSENT
from the live service list while `script.phoenix_intrusion_reset` called one of them — an earlier commit
message claimed the siren had been restored, and nothing had ever called it.
Same class, same day: `configuration.yaml`'s entire `http:` block was mis-indented, so `ip_ban_enabled`
and `login_attempts_threshold` added 2026-09-05 had **never been active**; `packages/phoenix_security.yaml`
did not parse at all.
*Measured after:* `rest_command.reload` restored both commands **with no downtime** (verified by re-reading
the service list, not by the reload's return value), then an `ha core restart` loaded the `http:` settings.
Post-change: all four `rest_command`s LIVE · 1068 entities · 150 automations / 64 on / 82 unavailable —
**every count unchanged** · `grep -icE 'invalid config|failed to parse|setup failed'` → **0**.
*The endpoint was checked before it was wired in:* `POST /alarm/on` → `200 {"ok": true, "alarm": "on"}`,
so the step the sequence now makes actually answers.
*Preventive artefact:* `scripts/validate_ha_yaml.py` parses with Home Assistant's tags registered and
fails on a parse error, a `rest_command` ownership mistake, or an intrusion sequence whose first step is
not the evidence-snapshot block. This defect class cannot ship again without the validator failing.
*Honest caveat:* the siren being reachable is not the same as the siren being audible in the office. What
is proven is that the call exists, resolves, and gets a 200 from the Mac mini listener. Loudness at the
speaker is unverified from here.

**W5 · 2026-09-11 · Twelve DSH windows became an operational reality, and the numbers say which design.**
Built `multi-window/dshw.ps1` + `windows.json`: start/stop/restart/status/new/open/logs/autostart/doctor
over one engine and N isolated browser windows. *Measurement:* engine up on port 3099 and **8 app windows
open simultaneously**, each with its own browser profile and its own auth cookie (verified per profile:
`Cookies`, `Local Storage\leveldb`, `Preferences` present in all 8); status reports `1 engine(s) live,
8 window(s) open, 196 MB engine RSS, 206 MB whole engine tree`. The cost model that decided the design is
measured, not estimated: three engines on three ports each held ~1.4 GB of tree (26 descendants), so the
"one process per window" plan would have needed ~17 GB on a laptop with 7.7 GB free.
*Why it matters:* the previous answer to "many sessions" was eight sessions sharing one ad-hoc process
started by hand, which died with its terminal and could not be restored.
**W20 · 2026-09-11 · The phone path is proven end to end, by the steps a human actually walks.**
Before: the owner's phone showed *"dsh web authentication required"* and iOS offered that text as a download.
After, 7/7 on `scripts/probe-phone.py`: cold visitor gets a token link (302) → the link redeems to a signed
cookie (303, HttpOnly, SameSite=Strict) → the document loads (200, 27,724 bytes, `<title>DeepSeek Harness</title>`)
→ **101 Switching Protocols** on `/api/remote.mux` → a foreign Host is still refused (401) → the identical chain
over real HTTPS through Tailscale Serve → the public `/phone` link 302s into the tailnet. Judged at 393×852 CSS
px, the harness collapses to an icon rail and stays readable, and a session created *from that viewport* answered
("phone link works.") and then landed in the authoritative database: 19 verbatim events, preset `zabz`,
`torn_tail 0`, full-text searchable. Measured, not asserted.

**W21 · 2026-09-11 · One negative test found two defects that every green check had hidden.**
Stopping the engine on purpose cost about ninety seconds and exposed two faults: the probe died instead of
reporting its failure, and the kernel then read the stale green file it left behind. Both are fixed, and both
fixes are covered by the same test run again (broken → `severity=high`, `needs_attention=True`, probe exit 1;
healthy → 7/7, `severity=info`, probe exit 0). *Why it matters:* it is cheap, repeatable proof that "all checks
pass" is worth exactly as much as the last time something was broken on purpose.

**W22 · 2026-09-11 · The phone signs in in one request, from every state, and the proof is the owner's own paths.**
Before: a stale cookie or a saved link with a dead token produced `dsh web authentication required`, which iOS offered as a
text download. After (probe 10/10, plus a real browser at 393×852 with default caching): a cold visitor, a returning visitor
with an unusable cookie, a saved link whose token died at the last restart, and the public home-screen link **all** return
200 / 27,724 bytes / `<title>DeepSeek Harness</title>` **with zero redirects** and a session cookie, and the app's
authenticated calls come back 200 (`session/list`, `agentPresets/list`, `credentials/describe`). The gate does the whole
login internally, so there is no redirect chain for a broken client to loop on and no bearer token in any URL.
*Why it matters:* this is the first version of this link that is correct for the client he actually holds, rather than for
the client I kept testing with.

**W23 · 2026-09-11 · The harness can name "home" for the first time — from the home LAN, with no owner input and no new hardware.**
The owner's iPhone on the tailnet reports the address it is dialable at, and an RFC1918 endpoint names the network it sits on.
From the Yoga, on the same LAN as the phone: `pong from iphone-15-pro (100.85.105.93) via 192.168.12.249:41641`,
**3/3 attempts**, resolving to `HOME [high]`. This is the first signal in the company's history that could distinguish his
house from his shop, and it required no new device, no new credential and no hardware purchase.
*Why it matters:* HA's `zone.home` is the shop, so the company's best presence system was structurally incapable of naming
home; a tailnet endpoint was already sitting there unused.

**W24 · 2026-09-11 · Skipping an unreachable probe by topology cut a reading from 19.3 s to 2.2 s.**
HA is reachable only from the office LAN (P18), and `homeassistant.local` is an mDNS name, so probing it from the home LAN
did not fail fast — it **stalled for ~19 seconds** every single time. The resolver now derives which LAN it is standing on
(connected-UDP-socket trick, no dependency, no packets) and skips the HA probe when it cannot possibly succeed.
*Measurement:* 19,342 ms → 2,249 ms on the same host and the same verdict.
*Why it matters:* a slow probe is how a reading gets abandoned by the next caller; the fix cost three lines.

**W25 · 2026-09-12 · A concurrency test found the optimisation was dead on arrival, before it shipped.**
`ProxyImageStore` exists to stop the classifier re-downloading every image the browser already fetched. Its waiter test
failed on the first run: `put()` swept "expired" slots on every store, and a waiter's placeholder has no bytes yet
(`storedAtMs == 0`), so it looked ancient and was deleted mid-wait — the waiter timed out **after the bytes arrived**.
That is the *normal* case (a page announces an element as soon as `src` is set, before the download completes), so the
feature would have silently fallen back to a second download on exactly the path it targets, and would have looked like
it worked.
*Measurement:* the diagnostic assertion carried the state that proved it — `writerRan=true size=1 peek=32` with
`await() == null`. Fixed with a distinct pending clock; `ProxyImageStoreTest` is now **13 tests**, including the
deterministic reproduction of that interleaving. Full Android suite: **395 tests, 0 failures** (94 suites), up from 362.
*Why it matters:* this is the second entry in this journal of a *test* being worth more than the code it covers (W21).
A green suite over a feature nobody proved was exercised is how a product ships blind.

**W23 · 2026-09-11 · The phone UI is now usable on a phone, and every claim is measured.**
`assets/mobile.css`, injected by `scripts/phone-gate.py` into every document request. Before → after, at 393x852 on the
live app: controls under the 44px touch minimum **9 → 0** (hero state); composer field font **13.33px → 16px**, which
removes the iOS auto-zoom that fired on every focus; `safe-area-inset` rules **0 → present**, so the composer clears the
home indicator; the open sidebar **squeezed the content column to 113px → overlays at `position: fixed` with a scrim**;
the Chat/Trajectory tabs **27x25 → 64x44**; icon glyphs **unchanged** (max 24px, median 15px) after the regression that
inflated them was caught and fixed. `scripts/probe-phone.py` carries it as check 10 (11/11) so it cannot silently stop
being served. Desktop is untouched by construction: everything is scoped to `max-width: 768px`.

**W24 · 2026-09-11 · The phone's drawer now closes itself when a conversation is picked, and desktop is untouched.**
`packages/plugin-mobile` — a client plugin whose only behaviour is that one, because it is the one the stylesheet could not
reach. Measured at 393x852 on the live app: pick a conversation with the drawer open → **drawer 339px open → 56px closed**,
conversation visible behind it; before the plugin, the same tap left the drawer covering the screen. A tap on the scrim
closes it too, as does Escape. At 1440px the sidebar **stays open at 280px** before and after the same tap, so desktop
regression is excluded by measurement, not by intent — the plugin tests `matchMedia('(max-width: 768px)')` per click.
`probe-phone.py` check 11 fails if the roster stops carrying it (12/12), and `serve-phone.sh` reinstalls the symlink and the
bundle-list entry when either is missing, so the behaviour cannot vanish without a red check.

**W25 · 2026-09-11 · Proved a physical automation would fire tonight without waiting for it to fire.**
Erev Rosh Hashana 5787 needed the office interior maglock released and HA + all cameras powered down at 18:46:53
EDT, with the household locked out for three days if the software step silently failed. Four independent readings
established it in advance, none of them by reading code: the live app's own `/shabbat/status` returned
`enabled=true, plug_connected=true, switch_on=true, next_action off @ 18:46:53`; `/proc/<pid>/task/*/comm` showed
the **`apscheduler-boot`** thread alive in the live process (the thread that registers the 1-minute executor job);
`curl 192.168.50.103/rpc/Schedule.List` showed the on-device cron holding OFF 18:46 and ON 20:23 **Sunday** — the
device's own fallback, correct for a three-day block and not a Saturday-night lie; and a `.venv` dry-run with live
settings showed the executor returning `nothing_due` at 18:43:53 and the action due at 18:44:30. The publish path
was then exercised idempotently by re-sending the LOCKED payload (HTTP 200, `switch.smart_switch_l4` unchanged at
`on`) — a real end-to-end test of the exact service the unlock uses, with zero physical effect. 14/14 unit tests
pass. Nothing was assumed and nothing was left to hope.

**W26 · 2026-09-11 · Three independent paths to the yoga machine were verified by using them, not by assuming
them.**
The question was whether the other machine's conversations are reachable from ZABZ-TECH. All three answers were
exercised in the same hour: (1) `ssh zabz-yoga-1` over Tailscale returns `zabz-yoga` — a live, key-based shell on
the other laptop (port 22 open; the DSH engine's ports are not exposed); (2) the authoritative archive answers on
secratary — `secretary.db` holds 99 sessions / 31,031 rows across three machines, with yoga current to
`21:06:32Z`, searchable by full text (`--search kosher` returned yoga rows with ordinals and snippets); (3) the
journal itself, which is how yoga's HANDOFF entries already reach this machine through `harness-config` → `git`.
The useful consequence: a session that happened on yoga can be read, searched and continued from here, and the
safety net that makes that possible — the hourly shipper — was found to be failing and was repaired in the same
turn rather than being reported as a risk.


**W27 · 2026-09-11 · Live-only code was rescued without disturbing it, and the alarm that was named-and-not-built
is now built, wired and proven.**
Two results, both verified rather than asserted. (1) The Shabbat fix running tonight lived only as uncommitted
working-tree edits on the authority; it is now a pushed commit (`6784354c`, branch `deployed-truth-20260911`,
verified with `git ls-remote`) with blob hashes equal to the live files, achieved via `read-tree`/`commit-tree`/
`update-ref` so the working tree, the index and HEAD were never touched — dirty count identical before and after
(30). (2) `check-dsh-freshness.py` closes the gap L160 named: exit 0 fresh / 1 stale / 2 could-not-read, wired as
section 0 of the digest that already runs every 30 minutes, with a 6-case self-test that includes the real
2.5-hour outage and a refusal path that must not read as health. Live run: all three machines shipping. No new
cron, no second alert surface, no guessing.



**W28 · 2026-09-11 · The false-success defect was measured, fixed, guarded and surfaced — and the surface the
owner already reads now shows the truth.**
Half a day of the company's work was being counted as finished when it had merely run out of budget, and the
count had never been checked against the evidence. Fix in one pass: one shared close-unfinished helper replacing
four dishonest writes; an honest completion section in the digest that splits completed sessions by whether
`[WORK_DONE]` is actually present; and an AST guard that fails if a future edit reintroduces an ungated
`status="completed"`. Proven, not asserted: 3/3 new tests; the surrounding autopilot suite's single failure
proven pre-existing by A/B against the unpatched file; the diff shown to be exactly 5 hunks, with the only
surviving completed-writes being the docstring and the two `[WORK_DONE]`-gated sites. Honest first reading:
**182 of 329 "completions" in 24 hours were hollow**. The complement of this win is W26's shape — the same
defect class (`failures recorded as success`, `alarms routed nowhere`) appeared twice in one sitting.



**W29 · 2026-09-11 · The 54-day owner silence was found, explained, and routed instead of escalated.**
The question was "why is nothing reaching the owner". Answer, from primary evidence rather than inference: a
kill switch file created to stop a 28-text spam loop, still honoured in four modules 54 days later, plus a
second threshold that can never pass `normal` messages, against a healthy Twilio transport. With that in hand
the response was not a risk report: 595 undelivered messages were **routed** (383 mine as engineering faults,
45 superseded briefings, 167 owner items, nothing deleted), the six still-live owner items were promoted into a
new decision queue, two `critical` items (Google breach alerts) were investigated to the point of being
**closed as non-incidents** rather than forwarded, and the queue the owner asked for was built and working.
The 28-text loop is what made the switch look reasonable; the correct replacement — a rate limit plus dedup —
is the next piece of work, and it is safe to build before he answers.

