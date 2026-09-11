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
