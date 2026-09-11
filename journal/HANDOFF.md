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

## 2026-09-11 · ZABZ-YOGA · Built the conversational CEO and its memory

**CHANGED**
- Authored the `zabz` preset — the CEO that replaces Copilot. Persona written from the measured
  analysis of 23,035 owner turns, plus the full toolbelt and the secretary MCP bridge.
  Mount-validated: `mounted OK: zabz`.
- Built `ceo-kernel` Phase 1: provenance layer, sourced readers, and a sentinel that detects
  outcome collapses. Verified against the live authoritative database.
- Established `harness-config` as the single source of truth for presets and settings, with a git
  remote on `secratary` and a sync tool. Applied on both workstations; converged.
- Turned on the background-first shell preset `cordis-bg`, which the desktop had authored and never
  switched on.
- Created this journal.

**CHANGED, THEN REVERTED — read this before touching model settings**
The default model was briefly switched to `deepseek-v4-pro` on the assumption that "pro" meant more
capable. **The owner corrected it: 4.1 Flash is better and cheaper.** Verified afterwards: the API
advertises only `deepseek-flash` and `deepseek-v4-pro`, `deepseek-v4.1-flash` is rejected by name,
and Flash and Pro returned byte-identical usage on an identical probe. Reverted to `deepseek-flash`
within the hour. See LESSONS L25–L27 — do not change a cost-bearing default on a hunch.

**ALSO FOUND — the running process does not hot-reload the preset default**
`self_audit` reported this session's live agent on preset `cordis`, not `zabz`, because the DSH
process started at 12:32:28 and `settings.yaml` was written at 12:32:29 — one second later. The
model namespace *does* re-read per request (a model change applied live), but the **preset** is
chosen at session start. **`zabz` therefore requires a profile restart**, and it has still never
been run in a real session.

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
