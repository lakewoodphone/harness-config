# What was actually changed on ZABZ-YOGA — 2026-09-15/16

Owner's brief: many parallel DSH sessions, each with subagents, must not freeze
the laptop. **Trim waste first; reduce capability only as a last resort, and as
little as possible.** Nothing below reduces what an agent can do at once.

Everything here has a measurement behind it. Where a number came from the host,
it says when.

---

## 1. Journal lock: file-unlink race → OS lock (the biggest pure-latency defect)

**Was.** `journal/.lock`, created `O_CREAT|O_EXCL`, "stale" decided by age > 600 s
or a dead holder PID, and broken by `unlink()` on the *path* — decided from a
content read taken earlier. Two writers that both read the same dead token both
judged it stale, both unlinked, both entered the critical section. `release_lock`'s
compare-and-swap protected release only, so the loss of mutual exclusion was
silent. That is the mechanism behind the 161-collided-id incident. Two further
holes: the `age > 600 s` branch broke a **live** slow writer with no liveness
check, and a kill between `os.open` and `write` left a zero-byte lock that was
neither dead nor stale, so every waiter burned the full 240 s.

**Measured before the fix** (subagent C, with 3-4 live sessions): real appends held
the lock **41 s, 41 s, ≥89 s, ≥98 s**; a `journal.py check` was killed at the
harness 120 s cap while an append held it; two journal processes outlived the
reported timeout; the stale-break path ran routinely (22:48:40: lock named
`append 42088@zabz-yoga`, pid 42088 already gone).

**Now.** `acquire_lock` takes a real OS lock — `msvcrt.locking(fd, LK_NBLCK, 1)`
on Windows, `fcntl.flock` elsewhere — so:

- the kernel releases it when the holder dies: **"stale" no longer exists**;
- after acquiring, the fd's inode must still be the path's inode, so a v1-style
  process that unlinks-and-recreates the file underneath us cannot hand the lock
  to two writers (back off and retry instead);
- release unlinks only its own inode;
- the wait is bounded and jittered, and `LOCK_WAIT_SEC` is **110 s** (below the
  120 s harness kill) — safe to keep long now that dying releases the lock;
- `JOURNAL_LOCK_WAIT` env override bounds a caller's own wait.

**Verified** (`_dsh-scale/lock_stress.py`, real child processes):
- 3 concurrent writers, hold 2 s each → **zero overlap** (acquire/release
  timestamps c0 → c1 → c2, serialised);
- a writer force-killed with `taskkill /T /F` mid-hold → the next process took the
  lock in **0.00 s**;
- after the fix, under live load, the lock was free (`acquire 0.00 s`) and the
  lock file did not exist between holders.

**Second defect fixed in the same file.** `status` — the always-read page —
called `_maybe_refresh_questions`, which spawned the **mutating** `questions`
command, which takes the global write lock and holds it across
`ssh secratary-ts` (45 s timeout). **Reads were creating writer contention for
every other session.** Now the refresh is skipped entirely when the lock is held
(reported honestly as "mirror age N min"), and when it does run it gets
`JOURNAL_LOCK_WAIT=15`.

---

## 2. MCP servers: four process layers and an npm registry hit per start

**Was** (measured on the live engine, 2026-09-15 21:5x): every MCP server ran
behind `python launcher → cmd.exe → npx-cli.js → cmd.exe → server`, and the
engine held **three complete generations of every server at once** (3 ×
{firecrawl, context7, jina, fetch, playwright}), i.e. 9 `npx` shims, 15 `cmd`
shims, ~1 GB, all alive. `npx -y <pkg>` also only reuses a cached install when
name **and exact version** match, so `@latest` forced a registry round trip on
every start (~3-4 s here; `npx --version` measured 4061 ms, `node -v` 964 ms).

**Now.** The five packages are installed once into a stable per-machine
location — `C:\Users\ezabz\.dsh\tools\mcp` (316 packages, verified entry points
for all five) — and every row invokes **`node <absolute entry point>` directly**:

| Row | Before | After |
|---|---|---|
| `mcp-fetch` | `npx.cmd -y mcp-fetch-server` | `node.exe …\mcp-fetch-server\dist\index.js` |
| `mcp-playwright` | `npx.cmd @playwright/mcp@latest …` | `node.exe …\@playwright\mcp\cli.js …` |
| firecrawl / jina / context7 (via `mcp_launcher.py`) | `python → cmd → npx → cmd → server` | `python → node → server` (npx kept only as fallback) |

The child DSH spawns is now the server itself, so killing it kills the server —
the leaked-generation problem came from the shim layers surviving the kill.

---

## 3. Node startup: compile cache on for every spawned process

`NODE_COMPILE_CACHE` is set as a **user** environment variable
(`%LOCALAPPDATA%\node-compile-cache`). Measured on this host: a cold
`node -e "require('fs')"` took **1608 ms**, the same command after the cache
warmed took **446 ms** — and this cost is paid once per tool call, per subagent,
per MCP start, hundreds of times an hour.

---

## 4. Process reaper for the waste the platform guarantees

Node's own `child_process` docs state that `ChildProcess.kill()` does **not** kill
a process tree on Windows, so a cancelled or timed-out tool call leaks its shell
by default. `harness-config/scripts/dsh-reap.ps1` implements two provable rules:

1. **Orphans** — a harness process (node/cmd/conhost/pwsh matching the npx cache,
   `dsh-subprocess-local`, or an MCP path) whose parent PID no longer exists.
   Nothing can ever reap it; it can only leak.
2. **Stale MCP generations** — for each MCP server package, keep the **newest**
   generation of its whole chain (walked up to the highest harness ancestor) and
   reap older ones.

It never touches the engine (`dsh\lib\bin.js web` — which is *parentless* in
practice because its launching terminal closed, and would otherwise be the first
thing eaten), never touches a browser, never touches anything without a harness
command line, and never touches anything younger than `-MinAgeMinutes`.
Report-only by default; `-Apply` to act.

Run just now in report mode: **4 stale MCP generations found** (2 fetch, 2
playwright, the two older chains), engine correctly protected, zero false
positives among 30 candidates.

---

## What is NOT done yet, in the order I would do it

1. **The append critical section is still 41-98 s.** After taking the lock, an
   append runs **two full-repo `git grep`s** to find the id ceiling and a **6.4 MB
   `journal.db` rebuild**. That, not the lock, is why appends queue for minutes
   under a fleet. Fixing it means caching the id ceiling and making the index
   rebuild incremental — it touches the id allocator, which is the exact path
   that produced the 161 collided ids, so it needs its own test (the 6-way
   concurrency selftest) before it lands. **This is the biggest remaining
   latency win.**
2. **Playwright's headless Chrome** stays alive per MCP server holding ~11
   browser processes (~333 MB) even when unused. Options: keep it (capability)
   or make the row opt-in on the laptop. Owner-facing choice, capability cost
   real — noted, not applied.
3. **Defender path exclusions** (needs admin): the single biggest measured win
   left, and free in capability terms.
4. **`owner-queue.py`** runs `executescript(SCHEMA)` DDL on *every* call — so
   reading the owner queue takes the **write lock on the 500 MB DB** — and its
   `DEFAULT_DB` is the Linux authority path, so on Windows it would silently
   create `C:\home\zabz\...` and report an empty queue. Gate the schema behind
   `PRAGMA user_version`; fail loudly instead of creating a phantom DB.
5. **SQLite**: check `sqlite_version()` (a WAL-reset corruption bug affected
   3.7.0–3.51.2, fixed 3.51.3, and it needs two connections writing/checkpointing
   on one file — exactly this workload); every read-then-write must be
   `BEGIN IMMEDIATE` (documented: after a successful `BEGIN IMMEDIATE`, SQLite
   guarantees no `SQLITE_BUSY` until COMMIT — `busy_timeout` cannot fix an
   upgrade race).
6. **EcoQoS / BELOW_NORMAL** on fleet process trees so the desktop compositor
   wins under contention (Microsoft measured 14-76 % foreground-responsiveness
   gain; no capability cost).
7. **Capability budget, only if still needed after all of the above** — and then
   the shape is a *queue*, not an amputation: DSH has **no cap on concurrent
   sessions** and workflow subagent fan-out defaults to
   `min(16, cores-2) = 16` per run, with `maxParallelToolCalls` at **20** here.
   10 sessions × 20 in-flight tool calls is 200 concurrent shells (~160 MB each
   in flight) with no machine-wide budget behind it. Measured today: commit
   **36-39 GB against 31.6 GB physical**, 600-2400 hard page faults/s.

## Evidence for the "waste, not power" claim

Nothing in this change removes a tool, a provider, a model, an agent, or a
parallelism setting. The knobs that would cap capability —
`agent-loop.maxParallelToolCalls` (20) and `workflow-worker-thread
.maxConcurrentAgents` (default 16) — were **deliberately left untouched**.

---

# Round 2 — 2026-09-16

## 5. The journal append was slow for a reason nobody had profiled

The lock was innocent. `cProfile -s cumtime` of `append --dry-run --no-fetch` split a
14.9 s append into:

| Where | Cost |
|---|---|
| `absorb_all` — legacy absorption, run before **every** write | **12.6 s** |
| → 7 calls to `max_number`, inside it | 11.7 s |
| → 15,303 `pathlib.relative_to()` calls | **7.2 s** |
| → `tree_signature` walking every file in `entries/` | 8.2 s |
| the append itself | ~0.3 s |

Three fixes, all measured:

1. **`_rel_of` fast path** — a precomputed prefix + `str.startswith` instead of
   `pathlib.relative_to`. Verified identical on 120 sampled paths, 0 mismatches.
2. **`legacy_signature()`** — the write path's cache key used `tree_signature()`, which
   hashes 15,303 files to build an `entries_sig` the write path never reads. The new
   function hashes only `log/**` and the v1 flat files; `tree_signature()` is unchanged
   for callers that need the entries signature.
3. **`absorb_if_due()`** — absorption is a migration task, not per-write work. It runs
   when the stamp is missing, older than 6 h, or a legacy **source** changed, or when
   forced (`--absorb`, `JOURNAL_ABSORB=always`).

The third fix taught its own lesson: the first version of the change-check globbed
*every top-level journal file*, which includes the tool's own outputs (`aliases.tsv`,
`entries.tsv`) — so every append looked like drift and re-ran the scan (2.5 s of a 2.7 s
dry-run). Narrowing it to the real legacy sources fixed that.

**Result:** dry-run 14.9 s → **2.7 s**; steady-state real append 10.4 s (dry-run) / 31.7 s+
(real, under load) / 41–98 s (lock sections) → **2.2–2.8 s** across three samples.
`journal.py check`: 0 errors, 51 warnings (all pre-existing).

## 6. The window count was a one-way ratchet

`dshw.ps1`'s `new` pick considered all twelve slots and then ran
`foreach ($slot in $slots) { $slot.enabled = $true }`, so it opened slots `windows.json`
says must never open — and never wrote the file back, so `doctor` kept reporting "8
enabled" while 12 were on screen. Fixed: the pick requires `$_.enabled`, and the
force-enable is deleted. Verified: parses clean, `doctor` = "8 enabled, 4 disabled", one
engine, auth probe 303. The 4 currently-open disabled windows (~1.7 GB private) remain
until someone closes them — I did not close windows that may hold the owner's work.

## 7. Counter discipline (a correction to my own earlier number)

"12 Edge windows cost 8.18 GB" was the **sum of `WorkingSet`** across 113 processes, which
double-counts shared pages. Private bytes for the same fleet: **3.6–3.9 GB**. Per window:
**324.8 MB private, 9–10 processes**. Windows are therefore *not* the binding constraint
(~46 windows of headroom); running agent turns are (~0.81 GB/turn, 10 running = 2.9 GB
headroom, ~13–14 turns pages). Also settled: **tabs cannot replace windows** — all tabs of
one origin share one `localStorage["dsh.sessions.current"]` and no URL carries session
identity, so N tabs are one session slot written by N pages. Separate windows (separate
profiles) are required for independent sessions; 8 is the right count for *correctness*.

## 8. Defender exclusions are only reachable with elevation

`get-mppreference`/exclusion writes need admin, which this session does not have. Defender
was measured at ~30 % of a core continuously while the fleet churns files, and `node -v`
measured 964 ms under load against 289 ms for a warm start. Prepared for the owner as a
single elevated command — the biggest remaining win that costs no capability.

## 9. Blocked on the network, not on the work

Tailscale on ZABZ-YOGA reports `BackendState=NoState`, the laptop is on **192.168.12.x**
(neither documented network), its tailnet interface is APIPA/`NoTraffic`, and both
`secratary` (100.84.72.88) and ZABZ-TECH (100.85.153.96) refuse connections;
`secratary.tail93e6e6.ts.net` does not resolve. Consequences: `git push` fails (all of
today's commits are **local only**), the authority owner-queue cannot be read, and
**ZABZ-TECH has no measurements at all** — its parity work must not be guessed.

---

# Round 3 — 2026-09-16 — cost

The cost audit measured the money rather than guessing it: DSH records real provider usage
locally, **99.1 % of prompt tokens are cache hits** (the caching works), and the bill is
dominated by re-billing history — **82 % of spend is re-reading context**, and tool output is
82.5–95.8 % of prompt tokens in the long sessions that were half of the $54 day.

**Landed (both waste recovery; nothing removed from the toolbelt):**

1. **Compaction trigger** — `thresholdRatio: 0.7` on `compaction-basic`
   (`presets/cordis-bg/agent.cordis.yml`). The trigger ignored the 256,000-token completion
   reservation, leaving a **7,424-token band** where DSH refuses to compact and the API rejects
   the request; 10 `CONTEXT_WINDOW_EXCEEDED` failures were recorded, each forcing an emergency
   whole-history compaction. 0.7 puts the trigger at 700k, under the credential's 792,576
   ceiling, so the band cannot be entered.
2. **Tool-result pruner** — 8192/4096/1024 → **5000/2500/700**. Measured on the same
   12,597,690-char corpus: kept **76.7 % → 66.6 %** (suppressed 2.94 M → 4.21 M chars, ≈317 k
   more tokens in that corpus). Deliberately not the audit's 2000/800/400 (**42.6 %** measured):
   over-tightening forces an extra read call, and each extra call re-sends the whole context,
   which can cost more than the bytes it saved. Head+tail kept; the full output still spills.

**A hole in my own earlier work, found and fixed:** the preset is *generated* by
`scripts/make_zabz_preset.py`, which rewrites it wholesale — so the direct-node MCP rows I had
edited into the YAML would have been reverted by the next regeneration. They now live in the
generator. Regenerating also deleted two hand-added owner rules from the live system prompt (the
orchestration rule and the AI-models rule) because `--check`'s drift warning was treated as a
formality. Both were restored byte-for-byte from a backup; `--check` now reports **"zabz: in
sync with the generator"** and a line diff against the backup shows **0 lines lost**.

**Sized but not applied — the owner's call, not mine:**
- Un-mounting the overlapping web-retrieval MCP servers (firecrawl 27 tools + jina 22 + fetch 6
  ≈ 28–29 k tokens of schema on *every* request): ≈$2–3 over six days at measured cache-hit
  rates. The audit calls the capability risk "small, **not none**", so it is one question for
  him rather than a unilateral tool removal.
- "More sessions, shorter" as the default (potentially the largest item: the three most
  expensive sessions were 52.5 % of the day, and cost scales as steps × mean context). No
  capability cost — it replaces conversational memory with the written handoff this system
  already uses — but it changes how every session behaves, so it lands with the instruction
  block.
- Lowering compaction to 400 k: the audit's arithmetic says it fires 2.5× as often with an
  ambiguous, possibly negative, net. Re-measure items 1–2 first.

---

# Round 4 — 2026-09-16 — tool-call latency

**What a tool call actually costs** (n=30 interleaved, ms, min/p50): kernel spawn floor 32.8/35.9;
`runner.js` (the Job owner) 120.3/136.3; `node -e` warm 69.8/76.6; trivial `pwsh` call
**~540/~700**. Split: **pwsh start-up 78 %, the Job-owner runner 19 %, everything else <3 %.**
Reproduced independently on the bench harness (pwsh exit p50 292 ms, runner idle 110 ms). The
overhead is the shell, not the machinery around it — and there is no kernel-level spawn problem.

**The persistent shell was rejected, and that is the audit's main value.** It is not a safe
drop-in: it registers `pwsh` with only a `command` parameter, so it loses `run_in_background`
(every long build returns to the 120 s cap — the L1566 outage), `sandbox_permissions` (a denial
becomes final), the **spill file** (output cut at 16,000 chars **keeping the head and dropping the
tail**, no path to the rest, where today there is a 64 KB tail plus a 64 MB named spill), per-call
`workdir` and `timeoutMs`, `description`, separate stdout/stderr, and — load-bearing — **Windows
Job containment**, because ConPTY is explicitly outside it and cleanup reverts to descendant
enumeration that the code itself documents as not guaranteeing termination. It also cannot mount:
nothing in this profile provides `ctx.terminals`. The runner's ~135 ms and its
`TerminateJobObject` cleanup guarantee are **the same purchase**.

**What was adopted instead, and verified:** a standing rule in the preset's Technical-discipline
block — `pwsh` is for what only a shell can do (running a program, git, a package manager,
inspecting processes); `read`/`grep`/`glob`/`edit` are for bytes. Measured: `read` p50 **0.76 ms**,
`stat` **0.11 ms** vs **~700 ms** for the same bytes through `pwsh` — a ~700× difference available
today with no capability change. It compounds because every shipped tool is declared *exclusive*
(no tool declares `isConcurrencySafe`), so N shell calls in one step run in series at N × 700 ms.
Source of truth is `scripts/make_zabz_preset.py`, so it survives regeneration; `--check` reports
in-sync and a line diff against the previous preset shows **0 lines removed**.

**Not reachable from config:** `POWERSHELL_TELEMETRY_OPTOUT` / `POWERSHELL_UPDATECHECK`.
`ENV_OVERRIDES` (`dsh-pwsh-local\lib\index.js:145-149`) is a hardcoded constant and the Config
schema exposes only timeouts and output caps — nothing that touches start-up. The durable fixes
are upstreaming the missing tool parameters, or a **pipe-based** persistent shell (which OpenHands
ships on Windows in production) instead of ConPTY; the gate test before any of it is "kill the
owner, confirm no surviving `pwsh`".

**Not done, deliberately:** mounting `pty` + `terminal-pwsh` into `~/.dsh/profiles/web/cordis.patch.yml`.
It is additive and latency-neutral, but that file lives outside `harness-config`, so the change
would exist on one machine only — worse than no change. It needs the sync extended to carry it,
which is its own task.



