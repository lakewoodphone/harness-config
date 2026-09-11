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
