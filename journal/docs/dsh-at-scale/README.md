# DSH at scale — program index

Opened 2026-09-15 on `ZABZ-YOGA`. Applies to **both** workstations (`ZABZ-YOGA`,
`ZABZ-TECH`); durable changes live in `C:\Users\ezabz\code\harness-config` (git) and
reach the other machines through the normal sync.

**Objective.** Many windows and many agents in parallel, on both machines, with tool
calls — especially PowerShell — staying responsive, and with the DeepSeek API bill
minimised.

**The rule that governs every change** (owner, 2026-09-15): *"Focus on getting rid of
waste. If reducing power at the end of the day is needed … then we'll have to reduce
power, but that just isn't the first thing we're going to do."* So: remove waste first;
reduce capability only if measurement proves it is the only lever left, and as little as
possible. A queue is acceptable; a smaller cap on what an agent can do is not, unless
proven necessary.

## Documents, in the order they were produced
| File | What it is |
|---|---|
| `10-dsh-source-audit.md` | Process model from the installed source: one engine process; a session is not a process; a subagent is not a process; every shell tool call costs a Job-owner runner + the shell. The root cause of the blank/hanging `list_agents`. Every existing concurrency cap with its default. |
| `20-research.md` | 425 lines, 110 cited URLs: Node/Windows process and memory behaviour, spawn cost, admission-control patterns, keeping the desktop responsive, SQLite and lock-file protocols, prior art (including same-OS MCP-leak reports). Myths killed with citations. |
| `30-locks-audit.md` | Journal lock forensics (the exact race, measured 41-98 s critical sections) and the SQLite contention picture. |
| `50-implementation.md` | What was actually changed, with measurements, and what is deliberately next. |
| `60-cost-audit.md` | *(in flight)* Where the API money went; prompt-prefix/cache stability; compaction knobs; ranked savings that do not reduce capability. |
| `70-toolcall-latency.md` | *(in flight)* Per-call overhead measured cold and warm; the persistent-shell behavioural diff and spec. |
| `80-windows-and-parity.md` | *(in flight)* Browser window cost, the `Invoke-New` force-enable defect, and ZABZ-TECH counters over SSH. |
| `90-plugin-health-governor.md` | Host plugin (`packages/plugin-health`): a live health surface (`GET /healthz` + an `engine_health` tool — loop lag p50/p95/max, memory, commit charge, process/thread counts, tool-call runner processes, MCP servers per name, running agent loops); a deadline + short-TTL cache replacing `list_agents` (which declares no `timeoutMs`, so nothing could ever time it out, and re-scans every session on disk for every caller); and an admission governor that leases heavy work against measured memory headroom and queues rather than refusing. 58 unit tests plus a 15-check cross-process stress proof. Needs one engine restart to mount. |
| `tools/measure-tool-call.py` | Time any tool call from the authoritative session log (pairs `tool/call` and `tool/result` by `callId`). This is how `list_agents`'s 644–4285 ms range and its 21-minute outlier were measured without a wrapper distorting them. |
| `lock_stress.py` | The proof for the lock rewrite: 3 writers zero overlap; a force-killed holder released the lock in 0.00 s. |

## Landed and verified
- **Journal lock**: OS lock (`msvcrt`/`fcntl`) with an inode check. The unlink-based
  stale-break race is gone; "stale" no longer exists because the kernel releases on
  process death. Reads no longer trigger the mutating `questions` refresh.
  `LOCK_WAIT_SEC` 240 → 110 s; `JOURNAL_LOCK_WAIT` override.
- **MCP**: five packages installed once into `C:\Users\ezabz\.dsh\tools\mcp`; the two
  `npx.cmd` preset rows replaced with direct `node <absolute entry>`; the python launcher
  prefers the local install. Four process layers per server → one, with no registry
  resolve per start.
- **`scripts\dsh-reap.ps1`**: reaps parentless harness processes and stale MCP
  generations. Never touches the engine (which is parentless by design) or a browser.
  Registered as the user scheduled task **"DSH Process Reaper"** every 10 minutes.
- **`NODE_COMPILE_CACHE`**: cold 1608 ms → warm 446 ms per Node start.
- **Journal append path** (round 2): legacy absorption no longer runs on every write,
  `_rel_of` no longer calls `pathlib.relative_to` (15,303 calls), and the write path's
  cache key no longer walks `entries/`. Append **10.4 s → 2.2–2.8 s**; dry-run
  14.9 s → 2.7 s; `check` 0 errors.
- **`dshw.ps1`**: `new` respects `enabled:false` (the window ratchet is stopped).
- **`owner-queue.py`**: a read no longer takes the write lock, the DB path resolves per
  host, and it refuses rather than creating an empty queue (an empty queue reads as
  "nothing needs the owner").
- **Untouched capability knobs**: `maxParallelToolCalls` still 20; workflow fan-out still
  `min(16, cores-2)`; same model, same tools.
- **Cost (round 3)**: compaction trigger moved to `thresholdRatio: 0.7` (closes a 7,424-token
  band where the API rejected the request but DSH refused to compact — 10 recorded failures),
  and the tool-result pruner tightened to 5000/2500/700, measured **76.7 % → 66.6 %** of raw
  tool bytes kept on a 12.6 M-char corpus. Both are in `presets/cordis-bg/agent.cordis.yml`.
- **Generator is now the source of truth**: the preset's MCP + persona rows live in
  `scripts/make_zabz_preset.py`, and `--check` reports *"zabz: in sync with the generator"*.

## Next, ordered
1. Persistent-shell row (`dsh-tool-pwsh-persistent`) once the diff proves no capability loss.
2. The journal append critical section (two full-repo `git grep`s + a 6.4 MB index rebuild
   inside the lock) — needs the 6-way concurrency selftest before it lands.
3. Tool deadline + cache and the health surface (plugin workstream).
4. Cost changes, from measured token accounting rather than guesses.
5. SQLite: `BEGIN IMMEDIATE`, `owner-queue.py` schema gate + per-host DB path,
   `sqlite_version()` check.
6. Re-measure both machines against one fixed counter set and record before/after.
7. **Owner action pending**: Defender path exclusions need elevation on ZABZ-YOGA —
   the single biggest remaining measured win, and free in capability terms.

## Working rules for anyone continuing this program
Read `10-dsh-source-audit.md` before proposing a process-level change — the process model
is counter-intuitive. Never edit files inside the installed DSH package: an npm update
erases them; put host-side behaviour in a plugin under `harness-config`. Keep commands
small (the host is often loaded), never recurse `~/.dsh/profiles`, and never grep a repo
tree end to end. Every claim needs a source and a time.
