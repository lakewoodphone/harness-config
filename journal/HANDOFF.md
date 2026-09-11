# HANDOFF — state of play, newest first

**Rule:** newest entry at the top. Every session that changed anything writes one before ending.
Format is fixed so a future self can skim it in seconds:

```
## YYYY-MM-DD HH:MM · <host> · <one-line title>
CHANGED     what is now different in the world
IN FLIGHT   what is unfinished, and where the thread is
BROKEN      what is known-broken right now
NEXT        the single most useful next action
EVIDENCE    files, commits, or commands that prove the above
```

---

## 2026-09-11 13:12 · ZABZ-YOGA · The thirteen-day silence, investigated and labelled

**CHANGED**
- The owner was asked whether the zero-tick window was deliberate. **He did not know and asked for an
  investigation.** Done, from evidence rather than inference.
  **The host was up and healthy every single day; the work loop was dead.**
  - Last tick `2026-07-22T00:21:02Z` → first tick back `2026-08-04T18:06:44Z` = **13 days 17 hours**.
  - The machine was demonstrably alive throughout: files written on **every** day of the window
    (1992/17/12/88/40/13/45/34/24/24/3/2 per day), `logrotate` ran 2026-07-23 06:02, hundreds of
    writes into `~/.local/lib/python3.14/site-packages`, 101 under `/var/lib/dpkg/info`, and git
    operations on the app repo on Jul 26, Jul 29 and Aug 3.
  - The database is silent in **every** table, not just `tick_telemetry`: no work sessions, no model
    usage, no errors, no delegations. Three `activity_log` rows in twelve days. A dead *loop*, not a
    failing one.
  - `secretary-api.log` records the mechanism that kept it down: `Stale autopilot thread detected
    (last_run_at=2026-07-21T06:00:51…) — exiting`, after **six restarts in twelve minutes** on the
    evening of Jul 21, the last of which logged **"Startup complete (autopilot disabled)"**.
- Written up as a postmortem: `personal-secretary-mvp/docs/postmortem/2026-07-22-thirteen-day-silence.md`
  (commit `f25d8d333`), including three things that remain **unknown** rather than glossed.
- The kernel now **names this gap instead of re-discovering it**: `KNOWN_GAPS` in `ck/sentinel.py`
  reports *"largest historical gap 12d (2026-07-22 -> 2026-08-04) — known: thirteen-day silence…"*
  (commit `3778bac`, deployed and verified live on `secratary`). An answered question stops being
  re-opened every five minutes, which is the failure mode that produced P6's dismissal schemes.

**IN FLIGHT**
- **The kernel is doing its job unattended**: cron fires every 5 minutes; runs at 16:55, 17:00, 17:05
  all landed with provenance (`authoritative:true`, 203 tables). Latest: 4 findings need attention.
- Three postmortem action items are **open and unfixed**: the autopilot's stale-guard **disables instead
  of re-arming** (`app/autopilot.py`); the cron watchdog asserts process liveness, not outcomes; and the
  monitor lives on the machine it monitors (PAIN P20 — the heartbeats must go off-host).
- `latest.json` still prints `age=?` (PAIN P12); `ck trend` still unbuilt; kernel Phases 2–7 unbuilt.

**NEXT**
Fix the two liveness-shaped holes the postmortem names — the autopilot stale-guard re-arming itself, and
an off-host heartbeat that alarms on **absence** — because those are the exact conditions that produced
this outage, and they are still in place today. Then `ck trend` over the accumulating `history.jsonl`.

**EVIDENCE**
- `ssh secretary-ts`: `find` histogram per day; `logrotate` mtimes; `sqlite3 -readonly` last/first tick
- `~/secretary-api.log`, `~/secretary-startup.log` (the six restarts and the autopilot refusal)
- postmortem `f25d8d333`; kernel `3778bac`; `ck status` on `secratary` showing the labelled gap

---

## 2026-09-11 13:05 · ZABZ-YOGA · Home Assistant: audited live, and the security system is blind

**CHANGED**
- `ha-config` has a **live truth surface** now: `scripts/ha_truth.py` (read-only collector over
  HA's own REST **and** WebSocket-admin surfaces, with provenance packets and deterministic severity
  findings) plus `scripts/ha-truth.ps1` (runs locally or on an always-on host over SSH). Verified
  end-to-end three times from the Yoga against the live system via `secratary`; JSON + Markdown land
  in `.runtime/` (git-ignored by design).
- `docs/AUDIT-2026-09-11-live-systems.md` — the first live-grounded audit since 2026-04-17. Committed
  as `7be821d`; `ha-config` is now **7 commits ahead of `origin/main`**, still unpushed.
- `docs/DISPOSAL-PLAN-2026-09-11-dead-generations.md` (`6e89501`) — removal plan for the four piles of
  dead logic, deliberately *not* the removal: manifest → repo-wide reference grep → backup → batches of
  ten with exact-count verification → regression assertion using the collector's own finding codes.
  Key numbers: **42 orphaned Keymaster entities with no config entry and no device**, **390 registry
  entities with a collision suffix (only 18 live, and 12 of those are legitimate Dahua sub-streams that
  must not be touched)**, **82 unloaded automations** (`disabled_by=null`, so the question is whether
  their YAML still exists), **834 entities disabled by their own integration — no registry surgery**.
- Raw evidence persisted on the always-on host (not just in a session's `/tmp`):
  `/home/zabz/ceo-kernel-var/ha/truth-20260911T1701Z.json` and
  `…/disposal-evidence-20260911T1705Z.json`.
- The collector's first run found a bug in itself and refused correctly (`/api/error_log` is text, not
  JSON) — fixed, re-run, verified. That refusal is why the log section is real instead of empty.
- Journal IDs collided with a concurrent session's (both wrote P15/P16). Mine are now **P17/P18**,
  append-only with the collision recorded in P17. See P13 — same cause.

**FOUND** (reads dated 2026-09-11 16:55–17:00 UTC; HA Core 2025.10.3)
- **CRITICAL — the intrusion system's primary trigger is blind.** `binary_sensor.phoenix_outside_door_contact`,
  its interior sibling, and the raw contacts went `unavailable` at **01:48 local** and have not
  recovered. Three Zigbee devices failed to rejoin at boot; the mesh is otherwise healthy
  (`zigbee2mqtt_bridge_connection_state = on`, v2.6.2, other nodes reporting live), so this is
  device-level, not a dead coordinator.
- **CRITICAL — evidence capture fails on every trigger.** The Dahua integration is config-entry
  `loaded` while `192.168.50.170:80` is unreachable: **365 snapshot errors** in one log span
  (`snapshot_latest_with_retries` 276, `snapshot_control_room_cameras` 48, `snapshot_entry_cameras` 41).
  The intrusion chain's "critical evidence" step cannot succeed.
- **HIGH — 41 Keymaster entities still loaded** beside the documented Phoenix path (April: 37; it grew).
  82 of 150 automations `unavailable`. 114 entities carry registry collision suffixes (`_2`…`_10`).
- **HIGH — Core is 11 months behind**; the `spotify` entry loops on a revoked refresh token
  (**683 log lines**), ~4 errors/minute of pure noise.
- **MEDIUM** — dead `zha` config entry (0 devices in the registry), `ipp` printer not loaded,
  `tplink` device unreachable, NUT flapping; 834 integration-disabled registry entities; **all 1895
  registry entities have no area**.
- **Verified healthy, for balance:** intrusion scripts and automations all present,
  `rest_command.phoenix_security_page` and `secretary_ptt` registered, phone notify targets present,
  apartment deadbolt `locked`, and the repo's newest five commits **are** live (every snapshot script
  exists on the host).

**IN FLIGHT**
- **`ha-config` Part 1 is code-complete but has never actually run**: `.runtime/`,
  `docs/PART1_RUNTIME_SUMMARY.md` and the inventory documents do not exist anywhere, because every one
  of those scripts needs SSH.
- Parts 2–7 of the overhaul (access control, presence, cameras/evidence, notifications, climate,
  security response, data hygiene) have **no roadmap documents** — the master plan names them, nothing
  specifies them.

**BROKEN**
- **SSH to the HA host is closed** (tcp/22 refused on `192.168.50.34` while 8123 answers; verified from
  `secratary`, office LAN, 2026-09-11 16:52 UTC). Consequence: `check.ps1`, `deploy.ps1`, `backup.ps1`,
  `prune-backups.ps1`, `inventory.ps1` and `refresh-runtime-truth.ps1` **cannot run at all**, and
  repo-vs-host `/config` drift cannot be proven. Worked around, not solved — the audit says so.
- Add-on versions/states, HAOS version and the update backlog are **unverified**: they live on the
  Supervisor API, which the Core token does not reach.

**NEXT**
- The owner's decision on the security blind spot: attempt a remote recovery of the three unjoined
  Zigbee devices (reload the integration / re-pair), or leave it until someone is physically at the
  office on Sunday. Everything else on the list is mine and proceeds read-only regardless.
- Independently: ask for the HA SSH add-on to be restarted so Part 1 can actually run once.

**EVIDENCE**
- `~/code/ha-config/docs/AUDIT-2026-09-11-live-systems.md` (§8 lists every read with its time)
- `~/code/ha-config/scripts/ha_truth.py`, `scripts/ha-truth.ps1` (commit `7be821d`)
- `~/code/ha-config/.runtime/ha-truth.json` + `.runtime/ha-truth.md` (git-ignored; regenerate with
  `scripts/ha-truth.ps1 -ViaSshHost 100.84.72.88 -SshAcceptNewHostKey`)
- Live reads: `/api/config`, `/api/states`, `/api/services`, `/api/error_log`, WS `config_entries/get`,
  WS `config/entity_registry/list`, WS `config/device_registry/list`

---

## 2026-09-11 13:02 · ZABZ-YOGA · Inventoried the WAZE/MDM/DRN/LPT stack and fixed a silent billing data loss

**CHANGED**
- **Fixed a real, ongoing data loss.** The daily `telnyx_billing.py --snapshot` cron wrote to an
  orphaned SQLite file (`/data/fleet.db`) while `fleet_api` reads PostgreSQL, so **both**
  `fleet_telnyx_*` tables in Postgres were permanently at 0 rows while every log line said success.
  Two defects: `_connect_db()` preferred SQLite unconditionally, and the per-SIM insert named a
  `customer` column Postgres never got, with the failure swallowed by a bare `log.warning`.
- `_connect_db()` now **prefers Postgres when `PG_DSN` is set**, via a small sqlite3-compatible shim
  (`?` → `%s`, dict rows) so the two dialects cannot drift. `persist_snapshot()` returns success/
  failure, rolls back on error, and the CLI **exits 2** instead of printing success when nothing landed.
- **Recovered the stranded history into Postgres:** 12 usage + 18 ledger rows, 2026-09-06 → 09-11.
  Proved idempotent (re-run inserted 0, skipped 30).
- **Installed a regression guard:** `operator-tools/telnyx_usage_freshness.py` refuses (exit 2) when it
  cannot see the data and fails (exit 1) if the newest usage row is >26 h old. In cron at **05:00
  daily**, after the 04:30 snapshot. Currently: `OK: 2 usage rows, newest 0.0h old`.
- `deploy/waze-mdm/docs/holdings-2026-09-11.md` — a verified inventory of the whole WAZE/MDM/DRN/LPT
  stack and exactly where it is holding. Commit `6f2a5195b`.
- Crontab backed up to `/root/crontab.bak-20260911` before editing.

**VERIFIED STATE (read live, not assumed)**
- Hetzner fleet-api: `{"status":"ok","nanomdm":{"version":"v0.9.0"},"mode":"direct"}`; container
  `healthy` after rebuild. 11 containers up.
- Fleet: **65 devices** (63 `lakewood` + 2 `lpt`), 55 deployed / 9 retired / 1 deploying,
  55 healthy / 1 warning / 0 critical / 0 offline / 0 stale.
- **The ~19,300-command backlog from the previous handoff is GONE** — `avg_queue_depth=0`, per-device
  `pending=0 notnow=0`. The queue reads 114/91 residual rows on the two LPT devices, not pending work.
- LPT devices DRN **2001**/`FFYGNQ8AN72J` and **2002**/`FFXGT23HN72J` both `deployed`, wallpapers
  rendered, last MDM check-in **2026-09-11 01:27 UTC** (~15 h before this read).
- Live portal endpoint works: 2001 = 5.6 MB / 2.0 GB (0.3%), 2002 = 183.1 MB / 2.0 GB (9.2%), both
  `state=active`. The customer-facing usage number is correct — **it calls Telnyx live**.
- `lpt-flip-phone` working tree **clean**, last commit `84e42d53` **2026-07-20**.

**IN FLIGHT**
- **Kosher Waze customer integration is gated on owner decisions, not engineering.** Q1–Q7 answered,
  **Q8–Q28 unanswered**, and the plan doc frames all 21 as owner questions. **They are not.** Only
  **four** are genuinely his: (1) billing shape — is `$9/mo · 250MB · 800MB cap · $18/GB` final, and does
  the portal *collect* money or only *show* it? (2) self-serve line — do customers get pause/resume, and
  is customer-triggered lost mode allowed? (3) cap behaviour — pause, throttle, or throttle+upsell at cap?
  (4) location/compliance — do we store any trip data, and any constraint before payments? The rest are
  factual or engineering calls that are mine. **This is the next thing to do.**
- Only the daily cron snapshot path is asserted. A manual `--report` also persists and is unguarded.

**BROKEN / KNOWN**
- **`docs/drn/generated/` holds 8,182 files and grows ~2,800/day** — a 463-byte JSON+CSV pair written
  every ~30 s by `scripts/drn-export-live-phone-source.py`, **always empty** (`rows_total: 0`). The
  invoker is not on this host (no process, no scheduled task) — **driven from elsewhere in the mesh,
  unidentified**. Pure waste; safe to clean since every file is empty.
- **87 `fleet_alerts` rows are all stale noise**, every one a `warning` timestamped **2026-07-12**
  reading "last seen: never". They inflate `fleet-health` and mask real alerts.
- `installed_profiles()` is structurally useless — `device_profiles` is always empty, so it reports
  "none" regardless of reality. **It lies to an operator.** Reimplement via `ProfileList` or delete it.
- `fleet.ps1 sql` is broken (`Unknown command: Invoke-SqlOnHetzner`). Use
  `scripts/Invoke-SqlOnHetzner.ps1` directly, or pipe SQL over ssh on stdin.
- `data_limit_gb` reads **2.0** on both LPT devices; intended default is **0.8**.
- Unchanged: three divergent `secretary.db` copies (P3), evolution loop not closing (P4),
  `engineering_indexer` dead weight (P5), 7 critical + 46 urgent messages held (P6).

**NEXT**
Answer the **four** owner questions above — one at a time, with a recommendation — and record each in
the plan doc's ANSWER LOG. Do not route the other 17 to him; answer them from the live config and the
findings in `holdings-2026-09-11.md`.

**EVIDENCE**
- `deploy/waze-mdm/docs/holdings-2026-09-11.md` (this session's inventory, every reading sourced+aged)
- `deploy/waze-mdm/fleet-api/telnyx_billing.py` (dual-dialect `_connect_db`, honest `persist_snapshot`)
- `deploy/waze-mdm/operator-tools/telnyx_usage_freshness.py`, `telnyx_migrate_sqlite_history.py`
- Commit `6f2a5195b`; crontab backup `/root/crontab.bak-20260911` on Hetzner
- Postgres now: `usage|14| 2026-09-07 02:05 → 2026-09-11 16:57`, `ledger|19| 2026-09-06 23:18 → 2026-09-11 16:57`
- LESSONS **L34** (a job can succeed and write nowhere anyone reads)

---

## 2026-09-11 12:55 · ZABZ-YOGA · The open verification is closed, and the kernel now runs by itself


**CHANGED**
- **The one unproven thing is proven.** This session runs preset `zabz` — read from the harness's own
  session record, not asserted — and the secretary bridge is live: the 14 `mcp__secretary__ps_*` tools
  are registered, and `ps_company_status` returned real company data (6 active goals, today's model
  usage). Previous HANDOFF's NEXT is done.
- `ceo-kernel` is now a **git repo with a remote on `secratary`**
  (`secretary-ts:/home/zabz/ceo-kernel.git`), mirroring `harness-config`: LF policy, `.gitignore` for
  runtime state, and the server is a **checkout, never edited in place**.
- Deployed to `/home/zabz/ceo-kernel` from git (pre-git copy moved aside, not deleted), and **the
  sentinel now runs on cron every 5 minutes**. `scripts/run-sentinel.sh` writes `latest.json` and
  `history.jsonl` to `/home/zabz/ceo-kernel-var/` — outside the working tree, because a scheduled job
  must never dirty the repo it lives in. **PAIN P2's remaining item is closed.**
- First authoritative reading, `secratary`, 2026-09-11T16:50Z: **4 findings need attention**
  - `tick_completion` — 4 collapse windows in 120 days with data; worst `2026-06-14..2026-08-04`,
    10,355 ticks, 32% complete
  - `attention_debt` — 7 critical + 46 urgent held; oldest question 131d
  - `agent_dead_weight` — **5 agents** completing ~nothing, worst `engineering_indexer` 172 ticks / 0
  - `evolution` — 56 unapplied; 30 duplicate offers on `app/services/activity_sync.py`
- **The kernel can now see absence, which it could not before.** Every check grouped rows that
  exist, so a day on which nothing ran was invisible by construction — the exact failure the kernel
  exists to catch. Added `check_telemetry_gaps`, and fixed every span to count calendar days rather
  than rows (see the correction below).
- **NEW FINDING, from that check: a 12-day total outage nobody had flagged.**
  `2026-07-23 .. 2026-08-03` — **zero tick rows for twelve consecutive days.** Cause unknown, not
  investigated. It is now permanently visible in every report (`telemetry_gaps`). The last 30 days
  are fully covered, so this is historical, not live.

**CORRECTED (this session, before it could mislead anyone)**
The first reading said "4 collapse windows in **120 days**" and labelled the worst "**30d**" while it
spanned `2026-06-14..08-04`, 52 calendar days. Both were counting **days that have rows**, not elapsed
time — so the 12-day hole above sat inside the quoted window and was reported as if it had not
happened. Spans now read `120 days with data across 148 calendar days` and `30d of data over 52d`.
Found by reading live data, not by review.

**FOUND BY ACCIDENT, AND IT MATTERS: seven other sessions were running in this same directory**
At 12:58 there were **eight live DSH sessions** on one DSH server process, all preset `zabz` — cost
estimates, Home Assistant audit, Waze MDM status, extension mapping, three read-only recon sessions,
and this one. One of them wrote `journal/reference/deepseek-token-pricing-2026-09-11.md` into
`harness-config` while this session was editing the journal, and this session's `git add -A` committed
it (in `4becfa4`) under a message that does not mention it.
**That file is not mine, and I have not verified its numbers.** It appears legitimate and well-sourced,
and its headline claim — every `deepseek-official` id is served by V4.1-Flash at Flash price — is
consistent with the owner's own statement recorded in L26. Treat it as a claim from another session
until checked.
Consequences recorded: PAIN P13 (shared tree + `git add -A`), LESSONS L33 (stage explicit paths).
Also measured and worth knowing: the MCP bridges compose **once per process, not once per session** —
seven extra sessions added no bridges — and the real memory cost per concurrent session is its shell
runner at ~58 MB, not the tools (PAIN P14).

**CORRECTED — PAIN P10 was wrong, and it was wrong in the exact way this journal exists to catch**
P10 claimed repeated mount-validation spawns duplicate MCP servers ("four `ps_mcp_server.py`"). **It
does not.** The number came from filtering process command lines for `personal-secretary-mvp` — a
*directory* — which matches every script in it: 1× `ps_mcp_server.py` plus 3× `mcp_launcher.py`
(firecrawl, jina, context7). Counted by script name: **one bridge per server, exactly.** Separately,
every venv-python launch appears as two processes (a ~4 MB parent and the real 14–63 MB child),
reproduced with a `time.sleep` payload containing no spawn code — so a naive process count
double-counts every python bridge. LESSONS L28/L29.

**IN FLIGHT**
- **The cron job is verified firing unattended:** runs at 16:51:24 (by hand) and **16:55:02 (by cron,
  nobody asked)**. Two history lines, both authoritative, `total:8` checks.
- `latest.json` packets print **`age=?`** — the freshness assertion exists but is unmeasured for most
  checks. Recorded as PAIN P12. This is the largest remaining honesty gap in Phase 1.
- ceo-kernel **Phases 2–7 unbuilt** (inbox, ledger, gate, preset tools, daemon, evolution). The cron
  job is the **interim** form of Phase 6 and must be replaced, not duplicated, when the daemon lands.

**BROKEN / KNOWN** (unchanged unless noted)
- **12-day total outage `2026-07-23..2026-08-03`, cause unknown** (new, above) — historical.
- **Seven other sessions share this project directory** and may write into any repo under it (P13).
- Three divergent `secretary.db` copies (P3); evolution loop not closing (P4); 7+46 held messages
  (P6); `harness-config` sync still manual (P8); 5 dead-weight agents (P5, up from 1).

**NEXT**
`history.jsonl` now accumulates a line every 5 minutes and **nothing reads it**. The smallest useful
step is `ck trend` — read those lines, say what changed since yesterday. Then Phase 5: expose
`ck status` to the face as a tool, so the CEO reads its own kernel in one call instead of an SSH round
trip. Third: close P12 (`age=?`) so a reading can prove it is current.

**EVIDENCE**
- preset: `~/.dsh/storages/session_projcache/sessions/session-3ca4f3f2-….json` → `"agentPreset":"zabz"`
- bridge: live `ps_company_status` returned 6 active goals + 8 models of today's usage
- kernel: `/home/zabz/ceo-kernel` @ `496899f`; `ck doctor` → `AUTHORITATIVE`, 203 tables, 2.4 GB
- schedule: `crontab -l` on secratary ends with the `*/5` entry; backup `~/crontab.bak-20260911-165133`
- state: `/home/zabz/ceo-kernel-var/run.log` → `16:51:24 exit=1` (by hand) and **`16:55:02 exit=1`
  (by cron)**; `history.jsonl` holds both lines, `authoritative:true, tables:203`
- absence: `telemetry_gaps` → *"a tick row exists for every day in the last 30; largest historical gap
  12d (2026-07-22 -> 2026-08-04)"*

---

## 2026-09-11 · ZABZ-YOGA · Built the conversational CEO and its memory

**VERIFIED STATE (both workstations, checked not assumed)**
- `zabz` is the default preset on **ZABZ-YOGA and ZABZ-TECH**; second sync run on each is fully clean.
- Model is **`deepseek-flash`** on both (reverted; see the correction below).
- `zabz` is **25 rows**: full toolbelt + background-first shell policy + **6 MCP bridges**
  (secretary, firecrawl, jina, context7, fetch, playwright).
- Mount validation: **`mounted OK: zabz`**.
- **The MCP servers genuinely spawn** — proven by process tree, not assumption. DSH pid 11744 had
  children running `ps_mcp_server.py`, `mcp_launcher.py`, `mcp-fetch-server` and the Playwright MCP.
- `ceo-kernel` Phase 1 runs on `secratary` and its sentinel found two things manual analysis missed.

**CHANGED, THEN REVERTED — read before touching model settings**
The default model was briefly switched to `deepseek-v4-pro` on the assumption that "pro" meant more
capable. **The owner corrected it: 4.1 Flash is better and cheaper.** Verified afterwards: the API
advertises only `deepseek-flash` and `deepseek-v4-pro`, `deepseek-v4.1-flash` is rejected by name,
and Flash and Pro returned byte-identical usage on an identical probe. Reverted. LESSONS L25–L27:
do not change a cost-bearing default on a hunch.

**THE ONE THING STILL UNPROVEN**
The preset default is chosen **at session start**, so `settings.yaml` saying `zabz` does not mean any
running session uses it. `self_audit` showed the live session on `cordis` because the DSH process
started one second before the settings were written. **A profile restart is required**, and a real
session on `zabz` has still never been observed. First check after restarting: `self_audit` should
report the agent's preset as `zabz`, and the tool catalog should include `mcp__secretary__ps_*`.

**ALSO FOUND — the running process does not hot-reload the preset default**
The model namespace *does* re-read per request (a model change applied live), but the **preset** is
fixed at session start. Recorded as PAIN P11: a change can be reported as done while having no
effect. Rule adopted: no claim about a preset without a live agent reporting that preset.

**IN FLIGHT**
- `zabz` is installed and defaulted on **both** workstations (Yoga and desktop), each verified with a
  clean second sync run. A **profile restart** is required for the default to take effect.
- **The one unproven thing: the secretary MCP row's 14 tools have not been observed registering in a
  live session.** What *is* proven: the preset mounts (`mounted OK: zabz`); the row resolves
  **enabled** on win32 (`disabled: !!js process.platform !== 'win32'` evaluates false); both paths
  exist; the venv python imports the `mcp` SDK; the `dsh-mcp-client` package is present (0.1.5-rc.2);
  and an independent handshake against `ps_mcp_server.py` returned all 14 tools. What is *not* proven
  is that the client completes that handshake at preset mount time and registers them. **First session
  on `zabz` should list its tools** — if `mcp__secretary__ps_*` is absent, this is the thread to pull.
- `ceo-kernel` is staged on `secratary` at `/home/zabz/ceo-kernel` and runs, but **not scheduled** —
  it only runs when invoked. Phase 1 is complete; Phases 2–7 (inbox, ledger, gate, preset tools,
  daemon, evolution loop) are designed in `ceo-kernel/docs/DESIGN.md` and not built.

**BROKEN / KNOWN**
- Three divergent `secretary.db` copies; nothing yet prevents writes to a stale replica (PAIN P3).
- Evolution loop still not closing: 56 unapplied, 30 duplicates, 13 node_modules targets (PAIN P4).
- `engineering_indexer`: 172 ticks, 0 completions (PAIN P5).
- 7 critical + 46 urgent messages held undelivered (PAIN P6).
- `harness-config` sync is **manual**. Nothing schedules it, so drift resumes the moment someone
  forgets to run it. A scheduled pull is a small, high-value fix.

**NEXT**
Open a session on `zabz` and confirm the tool list — specifically whether `mcp__secretary__ps_*`
appears. That closes the only open verification, and it is the difference between a CEO that can talk
and one that can act on the company.

**EVIDENCE**
- `~/code/harness-config/presets/zabz/agent.cordis.yml` (20 rows)
- `~/code/ceo-kernel/ck/{provenance,sources,sentinel,cli}.py`
- `~/code/personal-secretary-mvp/docs/secretary-replacement-audit/` (7 documents)
- Sentinel run on `secratary`: 4 findings, including `engineering_indexer` dead weight and a
  131-day-old question — both new discoveries
