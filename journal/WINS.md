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
