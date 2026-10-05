# DSH at scale — the program, end to end

**Opened** 2026-09-15 on `ZABZ-YOGA`, at the owner's request: *"make many-parallel DSH work well
on both machines — many windows, many agents, responsive tool calls and PowerShell, no freeze —
and cut the DeepSeek API cost."*

**The rule that governs every change in it** (his words, 2026-09-15): *"Focus on getting rid of
waste. If reducing power at the end of the day is needed … then we'll have to reduce power, but
that just isn't the first thing we're going to do."* So: **remove waste first; reduce capability
only if measurement proves it is the only lever left, and as little as possible.** Where a limit
was genuinely needed, the shape chosen is a *queue*, never a smaller cap on what an agent may do.

**Nothing in this program reduced a capability knob.** `agent-loop.maxParallelToolCalls` is still
20, workflow subagent fan-out still defaults to `min(16, cores-2)`, and no tool, provider or model
was removed.

## The measured result

| | before | after | how |
|---|---|---|---|
| memory commit | 36–39 GB of 31.6 GB physical | **21.8 GB** | MCP generations reaped, direct-node rows, orphan cleanup |
| hard page faults | 600–2,400/s | **18/s** | same |
| processes / node | 502–572 / 43–70 | 422 / 15 | same |
| MCP server processes (npx shims) | 31 (9) | 11 (4) | direct-node + reaper |
| journal append | 10.4 s dry-run, 31.7 s+ real, **41–98 s** lock sections | **2.2–2.8 s** | profiling + three write-path fixes |
| Node start | 1608 ms cold | **446 ms** warm | `NODE_COMPILE_CACHE` |
| tool-result bytes carried | 76.7 % of raw | **66.6 %** | pruner 5000/2500/700 |

Run `scripts/harness-verify.ps1` to check the invariants behind all of it (10 checks, exits
non-zero on a false one, `-Quiet` for a timer). It asserts the **deployed** copy under `~/.dsh`,
not just the repo — committed is not the same as deployed, and only one of those is what the
harness actually reads.

## What changed, and what each one bought

| Change | File | Bought |
|---|---|---|
| Journal lock is a real OS lock (`msvcrt`/`fcntl`) with an **inode check** | `journal/tools/journal.py` | The unlink-based stale-break was a real race (two writers could both judge a lock stale, both unlink, both enter) — the mechanism behind the 161-collided-id incident. Verified: 3 writers, zero overlap; a force-killed holder released in 0.00 s. |
| Legacy absorption gated; `_rel_of` string fast-path; legacy-only signature | `journal/tools/journal.py` | Append 10.4 s → 2.5 s. The profile showed 12.6 s of a 14.9 s append was a migration scan run before **every** write, plus 15,303 `pathlib.relative_to` calls at 7.2 s. |
| `status` no longer triggers the mutating `questions` refresh | `journal/tools/journal.py` | Reads were creating writer contention for every other session (the refresh held the global lock across a 45 s ssh). |
| MCP rows launch `node <absolute entry>` from a stable install | `scripts/make_zabz_preset.py` + `~/.dsh/tools/mcp` | Four process layers per server → one; no npm registry resolve per start; the child DSH spawns *is* the server, so killing it works. |
| `dsh-reap.ps1` + a 10-minute scheduled task | `scripts/dsh-reap.ps1` | Reaps parentless harness processes and stale MCP generations (~2–3 GB measured). Never touches the engine — which is parentless by design, and would otherwise be the first thing eaten. |
| `NODE_COMPILE_CACHE` | user environment | 1608 ms → 446 ms per Node start, paid on every tool call. |
| `dshw.ps1` `new` respects `enabled:false` | `multi-window/dshw.ps1` | `foreach ($slot in $slots) { $slot.enabled = $true }` opened the 4 slots config says never to open, and never wrote the file back — a one-way ratchet worth 1.7 GB. |
| `owner-queue.py` refuses instead of inventing an empty queue | `scripts/owner-queue.py` | An empty queue reads as "nothing needs the owner". Also stops a *read* taking the write lock on the 500 MB database. |
| Compaction `thresholdRatio: 0.7` | `presets/cordis-bg/agent.cordis.yml` | Closes a **7,424-token band** where DSH refuses to compact and the API rejects the request — all 10 recorded `CONTEXT_WINDOW_EXCEEDED` failures. |
| Tool-result pruner 8192/4096/1024 → 5000/2500/700 | `presets/cordis-bg/agent.cordis.yml` | 76.7 % → 66.6 % of raw tool bytes kept (≈317 k more tokens suppressed in one corpus), head+tail preserved, full output still spills to a file. |
| Instruction: prefer `read`/`grep` to a shell; keep sessions short and hand off | `scripts/make_zabz_preset.py` | A trivial `pwsh` call costs ~540–700 ms (78 % of it PowerShell's own start-up) against 0.76 ms for `read`; and cost scales as *steps × mean context* — the three priciest sessions were 52.5 % of the $54.92 day. |
| `sync.py` runs `install-client-plugins.ps1 -RequireAll` | `scripts/sync.py` | The keeper for the bundle list existed and nothing called it; a plugin package could silently miss a machine (as it did on 2026-09-11, refusing to boot). |
| `harness-verify.ps1` | `scripts/harness-verify.ps1` | The invariants above as an executable check, because each of them is silent when undone. |

## What was refused, and why that matters as much

**`dsh-tool-pwsh-persistent` was seriously considered and rejected.** It would save ~660 ms per
call, but it registers `pwsh` with only a `command` parameter, so it loses `run_in_background`
(every long build returns to the 120 s cap — the L1566 outage), `sandbox_permissions` (a denial
becomes final), the **spill file** (output cut at 16,000 chars, keeping the head and dropping the
tail, with no path to the rest), per-call `workdir`/`timeoutMs`, separate stdout/stderr, and
**Windows Job containment** — ConPTY is explicitly outside it, so cleanup reverts to descendant
enumeration that the code itself documents as not guaranteeing termination. The runner's ~135 ms
and its `TerminateJobObject` guarantee are *the same purchase*. It also cannot mount today: nothing
in this profile provides `ctx.terminals`. Re-open only if the missing parameters get upstreamed, or
with a **pipe-based** shell instead of ConPTY — and the gate test is: kill the owner, confirm no
surviving `pwsh`.

**Not applied because it is the owner's judgement, not mine:** un-mounting the overlapping
web-retrieval MCP servers (firecrawl 27 tools + jina 22 + fetch 6 ≈ 28–29 k tokens of schema on
*every* request). The saving is real (~$2–3 over six days at measured cache-hit rates) but the
audit calls the capability risk "small, **not none**", so it goes to him as one question.

## What each host can take (measured)

| Host | Measured | Rule |
|---|---|---|
| `ZABZ-YOGA` | 22 logical cores, 31.61 GB physical; **0.81 GB per running turn**; ~13–14 turns to paging; ~325 MB private per browser window; ~46 windows of headroom | fan heavy fleets out, not in |
| `ZABZ-TECH` | **measured 2026-09-16**: 32 cores, 63.6 GB physical, commit **44.5 GB**, 38.1 GB free, 28 page-ins/s, 518 processes, one engine on :3099 | ~19.1 GB headroom, i.e. ~23 running turns at the laptop's slope — **but it is not yet fixed there**: 46 MCP server processes with 15 npx shims, no `NODE_COMPILE_CACHE`, no reaper, `maxParallelToolCalls` unset (code default 10). Deploying the fixes requires integrating the two histories first (see "Open items") |
| `secratary` | — | prefer it for anything that must not depend on a laptop being awake |

Windows are *not* the binding resource. Sessions and subagents are **not processes** (subagents run
in-process); the process cost is per *tool call* (~160 MB in flight). Counter discipline: count
browser memory by **private bytes**, never `WorkingSet` — the "8.18 GB of Edge windows" figure this
program inherited was a summed working set and was 2.2× inflated.

## Open items, and who owns each

1. **The health/governor plugin** — in flight when this was written: a host-plane health surface,
   a deadline + short-TTL cache for the hanging `list_agents`, and an admission governor. Owned by
   a subagent; verified on an isolated engine before it goes near the live preset.
2. **ZABZ-TECH parity** — measured for the first time on 2026-09-16 (see the table above): it has
   ~19.1 GB of headroom but carries the same waste the laptop had, and **none of this program's
   fixes are deployed there yet**. Deploying them needs the two histories integrated first: the
   laptop was `ahead 17, behind 12`, and the 12 remote commits collide with the laptop's journal
   entries as **add/add conflicts on the same ids** (D201, D202, H367–H375, L1686–L1690, W174,
   W175) — two machines assigning one number to different records, which is exactly the class their
   `git_max` fix prevents from now on. Both records must survive under distinct ids with alias rows
   (`journal.py repair-ids` / `index/aliases.tsv`), never by dropping a side. The laptop's work is
   safe on the remote as branch `perf/dsh-at-scale-2026-09-16` in the meantime.
3. **Defender path exclusions** — needs one elevated command (`Add-MpPreference -ExclusionPath
   'C:\Users\ezabz\code','C:\Users\ezabz\.dsh'`). Defender was measured at ~30 % of a core while
   the fleet churns files, and `node -v` takes 964 ms loaded against 289 ms warm.
4. **Cost verification** — the pruner and compaction changes need a fresh usage export to measure
   their effect in dollars; no usage API exists, and the $54.92 figure only became knowable because
   the owner downloaded the console CSV.
5. **Revisit compaction at 400 k** — only with numbers, after 1–4: the audit's arithmetic says it
   fires 2.5× as often and the net is genuinely ambiguous, possibly negative.

## Where the evidence lives

This document is the spine. The audits, their raw measurements, the reproduction tools and the
research are in **`docs/dsh-at-scale/`**, brought into the repo on 2026-09-16 because they had been
written to a directory that was not under version control — 4.8 MB of evidence that could not
survive this laptop or reach the other machine.

| File | What it is |
|---|---|
| `10-dsh-source-audit.md` | The process model read from the installed source: one engine; a session is not a process; a subagent is not a process; a shell tool call costs a Job-owner runner plus the shell; the root cause of the blank/hanging `list_agents`; every concurrency cap with its default. |
| `20-research.md` | 425 lines, 110 cited URLs — Node/Windows process and memory behaviour, admission control, keeping a desktop responsive, SQLite and lock-file protocols, prior art. Includes the myths it killed, with citations. |
| `30-locks-audit.md` | Journal-lock forensics (the exact race, the 41–98 s measurements) and the SQLite contention picture. |
| `60-cost-audit.md` | The money, from the provider's own console export: $54.92 on 09-15 split across two machines, 99.1 % cache hit, 82 % of spend re-reading context. |
| `70-toolcall-latency.md` | Per-call cost decomposed; the persistent-shell diff table and why it was refused; the measurement method and the bench scripts. |
| `80-windows-and-parity.md` | Browser-window cost and the `Invoke-New` ratchet; the counter-discipline correction. |
| `95-session-list-pool.md` | The session-store walk: three sequential await chains, 219-641 s measured against 6.8 s of raw disk work, the pooling patch and its 16.1x interleaved A/B (identical artifact id set). |
| `96-engine-per-event-cost.md` | What the engine does **synchronously per session event**, measured: 407 ms of un-yieldable main-thread work per MB of events (`snapshotJsonValue` 60 %, redundant `structuredClone` 19 %, `deepFreeze` 12 %), a ~38 ms projection checkpoint on every `turn/end`, one extra JSON serialisation per attached window, and the ranked capability-preserving fixes F1-F8. |
| `tools/loop-lag-probe.ps1` | 10 s engine-loop sampler: lag bucketed by concurrent agent loops and by heap direction. Produced the "+8-15 ms per concurrent loop, not GC" result. |
| `50-implementation.md` | The dated log of what was changed, round by round. |
| `tools/`, `bench/`, `research/`, `notes/` | The measurement and reproduction tooling. |

Excluded from the repo deliberately: `data/` (3.5 MB of raw provider usage exports, including
account key names) and `src/` (656 KB of downloaded Node documentation that anyone can re-fetch).
Both remain on `ZABZ-YOGA` under `C:\Users\ezabz\code\_dsh-scale\`.

## How to verify any of this

```
pwsh -NoProfile -File C:\Users\ezabz\code\harness-config\scripts\harness-verify.ps1
python C:\Users\ezabz\code\harness-config\scripts\make_zabz_preset.py --check
python C:\Users\ezabz\code\harness-config\journal\tools\journal.py check
powershell -NoProfile -File C:\Users\ezabz\code\harness-config\scripts\dsh-reap.ps1   # report only
```

**Read `10-dsh-source-audit.md` before proposing a process-level change** — the process model is
counter-intuitive and most "obvious" optimisations here are aimed at the wrong 1 %.
