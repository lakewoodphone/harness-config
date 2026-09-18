# 84 — O3 calibration: what one concurrent agent turn actually costs

**Stream:** O3 of the overnight program (`81-overnight-program.md` §0.7, §1, §2).
**Written:** 2026-09-17 03:30Z–04:05Z, on **ZABZ-YOGA**, measuring **ZABZ-TECH** over the tailnet.
**Owns:** this file and nothing else. Every other artefact named below is scratch under
`%TEMP%` (on the laptop) or `C:\Users\ezabz\AppData\Local\Temp` (on the target); no repository
file other than this one was created, edited, moved or deleted.
**Job:** replace `CORE_SLOT_FRACTION = 0.75` and `SWAP_PENALTY_PCT = 90`
(`packages/mesh-broker/lib/scoring.js:67`, `:69`) with measurements, or show they are wrong.

> **The headline.** One extra concurrent agent turn costs **403 MiB of commit**
> (95% CI 328–478 MiB, level-mean estimate 402 MiB CI 272–533 MiB). The inherited constant was
> **0.81 GB — 2.1× too high**; the replacement 60-verification proposed, **0.58 GB per node
> process**, is also too high by 1.5× when a *turn* (1.74 node processes) is what you are counting
> on this node. And the two questions the fraction and the threshold were invented to answer —
> "how many turns before the machine degrades" and "is a swapping node worse" — turn out to be
> answers about **CPU and about commit headroom**, not about the resources those two constants
> name.

---

## 0. The four answers, in one screen

**(1) How many concurrent turns does a node sustain before commit, paging or loop lag degrade?**
Measured on ZABZ-TECH (24 physical / 32 logical cores, 64 GiB) at N = 0, 2, 4, 6, 8 resident turns
and N = 8 tool-heavy turns: **nothing degrades in the reachable range.** The curve is flat and
benign through 8 concurrent turns:

* **commit** rises linearly at ~400 MiB/turn and never approaches anything. Physical (65,173 MiB)
  would be crossed at ≈ **111 turns** (95 % CI 93-136); the commit limit (69,269 MiB) at ≈ **121 turns** (101-149).
* **pagefile % usage** is **14.1 % in every single one of the 83 samples** — it does not move.
* **disk queue** peaks at **1** — from 0 idle. Nothing.
* **pages input/sec** rises from ~0–100/s idle to ~1,000–2,300/s under load, but its single largest
  reading of the night (**233,604/s**) is a *process-start transient* in the first two seconds of a
  fleet, and it is not accompanied by any pagefile growth. See §4.1 — this is not memory pressure.
* **event-loop lag** is the only counter that moves at all, and it moves in the **tail**: p50 stayed
  at 2–3 ms and p95 at 15–16 ms throughout, but **max went 18 ms → 54 ms** under 8 *tool-heavy*
  turns. The engine's worst-case stall tripled while its median did not move.

Above 8 turns is **outside the cap the brief set** (8 children maximum). The `N=8` point sits at
**44 % of the core term's 18** (8 of 18) and 33 % of the node's 24 physical cores, and **6.6 % of the measured memory ceiling**, so the crossing is not
nearby and could not have been reached even without the cap.

**(2) What does one additional concurrent turn cost in MiB of commit?**
**≈ 403 MiB**, 95 % CI **328–478 MiB**, from the steady-state row-level fit (n = 63, r = 0.806);
independently **402 MiB, CI 272–533 MiB** from a one-point-per-level fit (n = 6, r² = 0.948, which
removes within-level autocorrelation); cross-checked at **−410 MiB/turn** by the OS's own *Available
MBytes* (r = −0.862). Full fit in §3.

**(3) Is `0.75 × physical cores` the right fraction?** **It lands inside the measured band, but for
the wrong reason, and the band runs from 14 to 52 turns depending on the kind of turn and whether you count logical or physical processors.** A turn is not ~1 core: measured per level,
**a model-bound ("resident") turn occupies 0.62 logical CPUs** and **a tool-heavy ("working") turn
occupies 1.68**. On this 32-logical / 24-physical node that fills all logical CPUs at **≈52 turns
(resident)** or **≈19 turns (working)** — and in physical-core terms, ≈37 or ≈14. `0.75 × 24 = 18`
is inside 14…37 and is **about right for a tool-heavy fleet and ~2× conservative for a model-bound
one**. The constant is not refuted; it is *unfalsifiable as written*, because it converts a
**paging** observation into a **core** budget. The right form is a measured per-turn CPU cost, which
is what §4.3 gives.

**(4) Does swap at 90 % actually predict anything?** **No — and on these nodes it cannot, because the
field is not measuring swap.** `mem.swapUsedPct` is `max(0, committed − physical) / (commitLimit −
physical) × 100` (`scripts/phone-gate.py:1110–1149`). It reads **exactly 0.0** across a 10 GiB spread
of commit on both nodes — including ZABZ-YOGA right now, at **28,532 MiB committed of a 44,145 MiB
limit, only 10,692 MiB of RAM free, 1,469 MB resident in the pagefile and the pagefile 12 % used**.
It leaves 0.0 only in the last ~1 GiB before the hard commit limit: on ZABZ-TECH 90 % means commit is
within **410 MiB (0.6 %)** of the limit, on ZABZ-YOGA within **1,174 MiB (2.7 %)**. The threshold is
therefore not a graded warning about swap; it is a near-OOM alarm wearing a percentage. §4.4 has the
arithmetic and what to replace it with.

---

## 1. What was measured, on what, and how

### 1.1 The node, and why not the other one

The brief prefers `zabz-tech` and allows `zabz-yoga-1` only lightly (≤ 4 children) with a hard stop
if commit rises above 26 GB. **ZABZ-YOGA was above that stop line before any fleet was dispatched,
so it was loaded with no fleet at all.** The sequence, all read from
`\Memory\Committed Bytes` on the laptop:

| time (UTC) | yoga commit | note |
|---|---|---|
| 03:40:10 | 24.88 GiB | at the start of this stream's own session |
| 03:42:10 | 25.01 GiB | |
| 03:42:40 | 25.51 GiB | |
| 03:45:40 | **27.11 GiB** | crossed the 26 GB stop line — no fleet on yoga from here |
| 03:54:25 | **29.92 GiB** | commit limit 44,145 MiB, 10,692 MiB of RAM free, **6 agent loops executing** |
| 04:00Z | **34.72 GiB** | **3,408 MiB** of physical RAM free; the admission governor's own budget is at its floor of 4 slots. The laptop ended the stream ~10 GiB further into pressure than it started it, with the program's own seven streams running |

The 26 GB stop line is crossed on this laptop **by the overnight program's own sessions**, before any
calibration fleet runs. The premise in the brief ("you may load it LIGHTLY") assumes headroom that
does not exist at 03:45Z, and the measurement session itself is a large part of what consumes it.
**This is a measurement gap, not a workaround** (§6).

`zabz-tech` is the node measured. At 03:37Z it read: 32 logical / **24 physical** cores, 63.65 GiB
physical (65,173 MiB), commit limit 69,269 MiB, **4,096 MiB** pagefile, `agents.loopsRunning 0`,
`governor.inUse 0`, 10 `node.exe` processes, engine pid 23188 up 11 h, `workRoot C:/Users/ezabz/code`
with 221 GiB free — idle, and answering the capacity contract:

```json
{"schema":1,"node":"zabz-tech","cpu":{"logical":32,"physical":24,"load1":null},
 "mem":{"totalMiB":65173,"freeMiB":48057,"swapUsedPct":0.0},
 "agents":{"loopsRunning":0,"sessionsLive":1},
 "governor":{"budgetSlots":24,"inUse":0,"queued":0},
 "accepts":{"oneShot":true,"fleet":true,"maxChildren":12,"reason":null}}
```

`secratary` and `zabz-tech-linux` were not measured — they have no `/healthz` and mounting
plugin-health there needs the engine restart P210 forbids. **That is a measurement gap, recorded in
§6, not worked around.** Neither node was loaded.

### 1.2 The load is real agent turns

The load generator spawns, per lane,

```
"C:/Program Files/nodejs/node.exe" "<dsh>/lib/bin.js" --profile headless "<prompt>"
```

which is **the exact command `packages/plugin-remote-fanout` issues for one mesh child**
(`lib/remote-script.js:74`, `buildPwshScript`; `lib/index.js` / `cordis.patch.yml:79`
`remoteProfile: headless`). The only difference from production is the *parent*: a node process
instead of the ssh-spawned PowerShell wrapper, which is **less** overhead, not more. Each lane
re-spawns as soon as its turn exits, so N lanes hold ~N turns in flight for the whole window
instead of N short turns that finish and leave.

Two prompts, because the constants are about two different things:

* **resident** — *"Run the shell command `Start-Sleep -Seconds 8 ; hostname` and then reply with
  exactly one line: CAL-OK \<the hostname it printed\>. Nothing else."* A real turn, a real tool
  call, ~12.1 s wall, dominated by waiting — which is what most concurrent turns in a fleet are.
* **working** — *"Run the shell command `Get-ChildItem -Path C:\Windows\System32 -Recurse -File … |
  Measure-Object -Property Length -Sum` …"* — the tool-heavy upper bound of what one turn can cost
  in CPU and disk.

Every child printed `CAL-OK zabz-tech`, so **the turns provably executed on the measured node**, not
on the laptop.

### 1.3 The counter set, and which counter backs which claim

One sampler process on the target, one consistent set, one consistent window, sampled at a ~4.1 s
period (the brief allows 2–5 s; the period is set by `Get-Counter -SampleInterval 2 -MaxSamples 2`,
which needs two samples to cook a rate):

| counter | backs which claim |
|---|---|
| `\Memory\Committed Bytes` | **every memory claim and the slope** — this is the quantity the broker reasons about |
| `\Memory\Available MBytes` | the independent cross-check on the slope |
| `\Memory\Pages Input/sec` | the paging leg of Q1 |
| `\Paging File(_Total)\% Usage` | whether the pagefile is actually filling |
| `\PhysicalDisk(_Total)\Current Disk Queue Length` | disk saturation, in the form 60-verification §6.3 asked for |
| `\Processor(_Total)\% Processor Time` | the CPU leg of Q1/Q3 |
| `Get-Process node` → count, working set | the process-side cross-check |
| `GET /healthz` on the target's own engine | **loop lag p50/p95/max** and `agentLoopsRunning` |

`Load` average, `Pages free` and `% Disk Time` — the three counters this program has already been
misled by — are **not used for any claim in this document.** The engine's `/healthz` was reached the
way `scripts/phone-gate.py:mint_engine_cookie` reaches it (read `token=` from
`~/.dsh/multi-window/logs/3099.log`, `GET /?token=…` for a 303 and a cookie, then `GET /healthz`);
before writing this I confirmed the capacity route and a direct `Get-Counter`/`Win32_OperatingSystem`
read agree on the target's total memory and free memory to within 2 MiB.

### 1.4 Two sampling defects found and corrected in my own rig

Both are worth recording because they are the same class of error the program keeps making.

1. **A row's timestamp is not the moment it measured.** `ts` was stamped at the top of the loop and
   the counters were read over the following ~2.1 s, with `Get-Process` and `/healthz` after that.
   That misaligned concurrency against memory by 2–3 s and **attenuated the first slope I computed
   to 301 MiB/turn.** The offset is now **fitted per level** — the value that maximises the
   correlation between the concurrency series and node working set, the one column read at the same
   instant as the process table — and came out at **+1.2 to +3.4 s** (r = 0.64–0.91) across the six
   levels. With it, the same fit gives 363–403 MiB/turn. *A sampler that labels a row with the start
   of a window and fills it from the end of the window will mislead every reader of it.*
2. **The driver's `finished` counter was never incremented**, so it reported `finished: 0` for runs
   that completed 48 turns. The analysis counts `end` events instead. A counter that reads 0 is not
   evidence that nothing happened.

### 1.5 Cost

**~131 agent turns** were spent: 2 probe turns, 4 smoke, 8 (N=2) + 16 (N=4) + 18 (N=6) + 32 (N=8) +
48 (working N=8) = 122 in the sweep, and 3 for the real-dispatcher validation (1 parent + 2
children). Zero on ZABZ-YOGA.

**Estimated spend ≈ $0.9, range $0.5–1.5** — against the $3 cap. This is an *estimate*, not a billing
read, and §6 says why and what would settle it. The basis: a decoded turn session
(`session.v3.jsonl.zstd`, multi-frame zstd) contains a **26,181-byte `request/header`** (model config
plus the full tool schema list) and a 4,979-byte system message, and **2–3 steps** per turn
(`step/start` 2–3, `tool/call` 1–2) — so ~8 k tokens per model call, ~24 k per turn, ~3.1 M input
tokens for the night at `deepseek-flash` (`settings.yaml:7–9`).

---

## 2. The raw tables

### 2.1 Per level

`live` is the **instantaneous** number of turns in flight, from the driver's own spawn/exit event
log — not the nominal N. `ss` = steady state (rows with live ≥ 1); the baseline level has no such
rows and shows its full-window mean.

| level | prompt | N | live mean (ss) | max live | samples | turns completed | window s | turns/s | commit MiB mean (ss) | avail MB mean (ss) | node WS MiB | node procs | CPU % mean (ss) | CPU % max | pages-in mean / max | pagefile % | diskQ max | loop lag p50/p95/max (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `tech-b0` | — (baseline) | 0 | 0 | 0 | 9 | 0 | — | — | 20,491 | 48,335 | 593 | 10.0 | 2.56 | 11.5 | 11.3 / 100.9 | 14.1 | 0 | 2 / 16 / 18 |
| `tech-l2` | resident | 2 | 2.00 | 2 | 15 | 8 | 48.9 | 0.164 | 21,113 | 47,833 | 1,172 | 14.4 | 4.47 | 11.5 | 12.9 / 78.2 | 14.1 | 0 | 2 / 16 / 18 |
| `tech-l4` | resident | 4 | 3.77 | 4 | 15 | 16 | 52.7 | 0.304 | 22,096 | 47,037 | 1,828 | 18.3 | 9.33 | 21.8 | 1,143.5 / 3,878 | 14.1 | 1 | 2 / 16 / 19 |
| `tech-l6` | resident | 6 | 5.69 | 6 | 15 | 18 | 52.8 | 0.341 | 22,252 | 46,189 | 1,873 | 19.4 | 14.20 | 23.4 | 17,696.7 / 233,603.8 | 14.1 | 1 | 3 / 15 / 19 |
| `tech-l8` | resident | 8 | 8.00 | 8 | 15 | 32 | 53.2 | 0.602 | 23,499 | 45,451 | 2,639 | 23.9 | 18.35 | 41.0 | 2,098.3 / 5,286.9 | 14.1 | 1 | 3 / 15 / 19 |
| `tech-c8` | working | 8 | 7.42 | 8 | 14 | 48 | 46.8 | 1.026 | 23,813 | 45,105 | 2,733 | 20.3 | 41.50 | 62.9 | 1,574.2 / 4,382.6 | 14.1 | 1 | 3 / 15 / **54** |

**CPU per turn, derived per level** (Δ mean CPU % against the baseline, × 32 logical CPUs, ÷ measured
live): `l2` 0.306, `l4` 0.575, `l6` 0.655, `l8` 0.632, `c8` **1.679** logical CPUs per turn.

**The raw per-sample table** — all 83 rows - 74 in the five loaded levels and 9 baseline, the baseline rows carrying no concurrency by construction - with the fitted concurrency, the counters and the health reading, are generated from the CSVs into [§2.2](#22-the-raw-per-sample-table) by
`mcal-analyze.mjs`, so no number in it passed through a human.

### 2.2 The raw per-sample table

| level | sample (UTC) | live turns | commit MiB | avail MB | pages-in /s | pagefile % | disk queue | CPU % of 32 logical | node procs | node WS MiB | loop p50 | loop p95 | loop max | agent loops |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `tech-b0` | 2026-09-17T03:44:56.139Z | 0 | 20490 | 48339 | 1 | 14.1 | 0 | 0.7 | 10 | 594 | 2 | 15 | 18 | 0 |
| `tech-b0` | 2026-09-17T03:45:00.449Z | 0 | 20495 | 48334 | 0 | 14.1 | 0 | 11.5 | 10 | 594 | 2 | 15 | 18 | 0 |
| `tech-b0` | 2026-09-17T03:45:04.529Z | 0 | 20488 | 48344 | 0 | 14.1 | 0 | 4.5 | 10 | 594 | 2 | 15 | 18 | 0 |
| `tech-b0` | 2026-09-17T03:45:08.582Z | 0 | 20491 | 48336 | 0 | 14.1 | 0 | 0.1 | 10 | 594 | 2 | 15 | 18 | 0 |
| `tech-b0` | 2026-09-17T03:45:12.654Z | 0 | 20502 | 48317 | 0 | 14.1 | 0 | 0 | 10 | 593 | 2 | 16 | 18 | 0 |
| `tech-b0` | 2026-09-17T03:45:16.701Z | 0 | 20489 | 48335 | 0 | 14.1 | 0 | 2.3 | 10 | 593 | 2 | 16 | 18 | 0 |
| `tech-b0` | 2026-09-17T03:45:20.764Z | 0 | 20487 | 48338 | 0 | 14.1 | 0 | 3.9 | 10 | 593 | 2 | 16 | 18 | 0 |
| `tech-b0` | 2026-09-17T03:45:24.819Z | 0 | 20489 | 48338 | 0 | 14.1 | 0 | 0 | 10 | 593 | 2 | 16 | 18 | 0 |
| `tech-b0` | 2026-09-17T03:45:28.873Z | 0 | 20489 | 48332 | 100.9 | 14.1 | 0 | 0 | 10 | 593 | 2 | 16 | 18 | 0 |
| `tech-l2` | 2026-09-17T03:45:39.676Z | 0 | 20466 | 48356 | 0 | 14.1 | 0 | 4 | 10 | 593 | 2 | 16 | 18 | 0 |
| `tech-l2` | 2026-09-17T03:45:44.040Z | 2 | 21096 | 47833 | 1.5 | 14.1 | 0 | 3.2 | 14 | 1250 | 2 | 16 | 18 | 0 |
| `tech-l2` | 2026-09-17T03:45:48.104Z | 2 | 21248 | 47704 | 12.4 | 14.1 | 0 | 6.9 | 15 | 1308 | 2 | 16 | 18 | 0 |
| `tech-l2` | 2026-09-17T03:45:52.194Z | 2 | 21077 | 47883 | 78.2 | 14.1 | 0 | 6.5 | 15 | 1024 | 2 | 16 | 18 | 0 |
| `tech-l2` | 2026-09-17T03:45:56.249Z | 2 | 21076 | 47847 | 30.5 | 14.1 | 0 | 5.8 | 13 | 1174 | 2 | 16 | 18 | 0 |
| `tech-l2` | 2026-09-17T03:46:00.290Z | 2 | 21243 | 47717 | 0 | 14.1 | 0 | 0 | 15 | 1287 | 2 | 16 | 18 | 0 |
| `tech-l2` | 2026-09-17T03:46:04.362Z | 2 | 20972 | 47983 | 0 | 14.1 | 0 | 2.9 | 15 | 1025 | 2 | 16 | 18 | 0 |
| `tech-l2` | 2026-09-17T03:46:08.412Z | 2 | 21087 | 47829 | 15.4 | 14.1 | 0 | 0 | 13 | 1176 | 2 | 16 | 18 | 0 |
| `tech-l2` | 2026-09-17T03:46:12.475Z | 2 | 21269 | 47679 | 9 | 14.1 | 0 | 0 | 15 | 1290 | 2 | 16 | 18 | 0 |
| `tech-l2` | 2026-09-17T03:46:16.532Z | 2 | 20994 | 47966 | 0.5 | 14.1 | 0 | 9.5 | 15 | 1028 | 2 | 16 | 18 | 0 |
| `tech-l2` | 2026-09-17T03:46:20.582Z | 2 | 21165 | 47781 | 1.5 | 14.1 | 0 | 11.5 | 14 | 1234 | 2 | 16 | 18 | 0 |
| `tech-l2` | 2026-09-17T03:46:24.642Z | 2 | 21236 | 47730 | 0 | 14.1 | 0 | 2.8 | 15 | 1291 | 2 | 16 | 18 | 0 |
| `tech-l2` | 2026-09-17T03:46:28.694Z | 2 | 20897 | 48039 | 44.8 | 14.1 | 0 | 4.5 | 14 | 977 | 2 | 16 | 18 | 0 |
| `tech-l2` | 2026-09-17T03:46:32.767Z | 0 | 20500 | 48318 | 0 | 14.1 | 0 | 0 | 10 | 593 | 2 | 16 | 18 | 0 |
| `tech-l2` | 2026-09-17T03:46:36.803Z | 0 | 20497 | 48322 | 0 | 14.1 | 0 | 4.9 | 10 | 593 | 2 | 16 | 18 | 0 |
| `tech-l4` | 2026-09-17T03:46:47.883Z | 0 | 20498 | 48324 | 0.5 | 14.1 | 0 | 2.9 | 10 | 593 | 2 | 16 | 18 | 0 |
| `tech-l4` | 2026-09-17T03:46:52.178Z | 4 | 21749 | 47253 | 3.5 | 14.1 | 0 | 17.3 | 15 | 1726 | 2 | 16 | 17 | 0 |
| `tech-l4` | 2026-09-17T03:46:56.219Z | 4 | 22100 | 46999 | 3878 | 14.1 | 0 | 5 | 19 | 1955 | 2 | 16 | 17 | 0 |
| `tech-l4` | 2026-09-17T03:47:00.268Z | 4 | 21548 | 47522 | 1868.7 | 14.1 | 0 | 11.8 | 19 | 1414 | 2 | 16 | 17 | 0 |
| `tech-l4` | 2026-09-17T03:47:04.333Z | 4 | 21756 | 47239 | 2 | 14.1 | 0 | 6.9 | 15 | 1732 | 2 | 16 | 17 | 0 |
| `tech-l4` | 2026-09-17T03:47:08.411Z | 4 | 22121 | 46964 | 986.7 | 14.1 | 0 | 5.3 | 19 | 1960 | 2 | 16 | 17 | 0 |
| `tech-l4` | 2026-09-17T03:47:12.520Z | 4 | 21594 | 47471 | 9.4 | 14.1 | 0 | 1.3 | 19 | 1432 | 2 | 16 | 17 | 0 |
| `tech-l4` | 2026-09-17T03:47:16.585Z | 4 | 21807 | 47180 | 1.5 | 14.1 | 0 | 18.7 | 15 | 1769 | 2 | 16 | 17 | 0 |
| `tech-l4` | 2026-09-17T03:47:20.626Z | 4 | 23211 | 46313 | 24.9 | 14.1 | 0 | 10 | 24 | 2373 | 2 | 15 | 17 | 0 |
| `tech-l4` | 2026-09-17T03:47:24.680Z | 4 | 23668 | 45840 | 3268.6 | 14.1 | 0 | 9.4 | 24 | 2851 | 2 | 15 | 17 | 0 |
| `tech-l4` | 2026-09-17T03:47:28.728Z | 4 | 22338 | 46892 | 3777.8 | 14.1 | 0 | 21.8 | 17 | 1793 | 2 | 15 | 17 | 0 |
| `tech-l4` | 2026-09-17T03:47:32.779Z | 4 | 22095 | 46982 | 427.5 | 14.1 | 0 | 1.2 | 19 | 1941 | 2 | 15 | 16 | 0 |
| `tech-l4` | 2026-09-17T03:47:36.842Z | 4 | 22023 | 47130 | 146.9 | 14.1 | 0 | 4.9 | 20 | 1761 | 2 | 15 | 16 | 0 |
| `tech-l4` | 2026-09-17T03:47:40.879Z | 1 | 21242 | 47692 | 2282.8 | 14.1 | 1 | 7.7 | 13 | 1051 | 2 | 15 | 16 | 0 |
| `tech-l4` | 2026-09-17T03:47:44.944Z | 0 | 21122 | 47762 | 473.9 | 14.1 | 0 | 5.8 | 11 | 860 | 2 | 15 | 19 | 0 |
| `tech-l6` | 2026-09-17T03:47:55.529Z | 0 | 20468 | 48325 | 5466.1 | 14.1 | 0 | 4.6 | 10 | 593 | 3 | 15 | 19 | 0 |
| `tech-l6` | 2026-09-17T03:47:59.911Z | 0 | 20838 | 46471 | 233603.8 | 14.1 | 0 | 16.2 | 17 | 1008 | 3 | 15 | 19 | 0 |
| `tech-l6` | 2026-09-17T03:48:03.962Z | 6 | 21277 | 46444 | 5979.3 | 14.1 | 0 | 2.3 | 17 | 1114 | 3 | 15 | 19 | 0 |
| `tech-l6` | 2026-09-17T03:48:08.002Z | 6 | 21443 | 46390 | 2222.5 | 14.1 | 0 | 13.6 | 17 | 1365 | 3 | 15 | 19 | 0 |
| `tech-l6` | 2026-09-17T03:48:12.060Z | 6 | 21751 | 46443 | 1659.9 | 14.1 | 0 | 20.6 | 17 | 1419 | 3 | 15 | 19 | 0 |
| `tech-l6` | 2026-09-17T03:48:16.113Z | 6 | 23031 | 45249 | 2773.2 | 14.1 | 1 | 12.1 | 23 | 2629 | 3 | 15 | 19 | 0 |
| `tech-l6` | 2026-09-17T03:48:20.198Z | 6 | 23036 | 45516 | 4630.8 | 14.1 | 0 | 11.9 | 23 | 2632 | 3 | 15 | 19 | 0 |
| `tech-l6` | 2026-09-17T03:48:24.250Z | 6 | 21317 | 47090 | 1347.3 | 14.1 | 0 | 12.1 | 17 | 1180 | 3 | 15 | 19 | 0 |
| `tech-l6` | 2026-09-17T03:48:28.293Z | 6 | 23002 | 45678 | 1198.4 | 14.1 | 0 | 23.4 | 23 | 2580 | 3 | 15 | 19 | 0 |
| `tech-l6` | 2026-09-17T03:48:32.338Z | 6 | 23135 | 45594 | 1076.4 | 14.1 | 0 | 17.5 | 23 | 2583 | 3 | 15 | 19 | 0 |
| `tech-l6` | 2026-09-17T03:48:36.378Z | 6 | 21803 | 46822 | 1131.5 | 14.1 | 0 | 21.7 | 17 | 1479 | 3 | 15 | 19 | 0 |
| `tech-l6` | 2026-09-17T03:48:40.431Z | 6 | 22996 | 45753 | 1177.9 | 14.1 | 0 | 23.1 | 22 | 2532 | 3 | 15 | 19 | 0 |
| `tech-l6` | 2026-09-17T03:48:44.474Z | 6 | 23197 | 45598 | 987.1 | 14.1 | 0 | 7.7 | 23 | 2596 | 3 | 15 | 19 | 0 |
| `tech-l6` | 2026-09-17T03:48:48.522Z | 6 | 22163 | 46576 | 1184.8 | 14.1 | 0 | 17.2 | 20 | 1642 | 3 | 15 | 19 | 0 |
| `tech-l6` | 2026-09-17T03:48:52.574Z | 2 | 21118 | 47306 | 1011.1 | 14.1 | 0 | 1.4 | 10 | 593 | 3 | 15 | 19 | 0 |
| `tech-l8` | 2026-09-17T03:49:25.278Z | 0 | 21332 | 47093 | 981 | 14.1 | 0 | 5.7 | 10 | 593 | 3 | 15 | 19 | 0 |
| `tech-l8` | 2026-09-17T03:49:29.972Z | 8 | 23682 | 45141 | 1140.2 | 14.1 | 0 | 41 | 19 | 2813 | 3 | 15 | 19 | 0 |
| `tech-l8` | 2026-09-17T03:49:34.014Z | 8 | 24145 | 44877 | 5286.9 | 14.1 | 0 | 10 | 27 | 3269 | 3 | 15 | 19 | 0 |
| `tech-l8` | 2026-09-17T03:49:38.047Z | 8 | 23019 | 45979 | 3843.6 | 14.1 | 1 | 3.7 | 27 | 2172 | 3 | 15 | 19 | 0 |
| `tech-l8` | 2026-09-17T03:49:42.087Z | 8 | 22566 | 46368 | 1158.8 | 14.1 | 1 | 34.3 | 19 | 1823 | 3 | 15 | 19 | 0 |
| `tech-l8` | 2026-09-17T03:49:46.131Z | 8 | 24193 | 44836 | 1218 | 14.1 | 1 | 15.8 | 27 | 3269 | 3 | 15 | 19 | 0 |
| `tech-l8` | 2026-09-17T03:49:50.199Z | 8 | 24201 | 44838 | 1518.1 | 14.1 | 0 | 11 | 27 | 3272 | 3 | 15 | 19 | 0 |
| `tech-l8` | 2026-09-17T03:49:54.235Z | 8 | 22103 | 46708 | 3818.8 | 14.1 | 0 | 16.9 | 19 | 1324 | 3 | 15 | 16 | 0 |
| `tech-l8` | 2026-09-17T03:49:58.275Z | 8 | 24353 | 44722 | 3146.7 | 14.1 | 0 | 29.3 | 27 | 3303 | 3 | 15 | 16 | 0 |
| `tech-l8` | 2026-09-17T03:50:02.319Z | 8 | 24251 | 44777 | 1125 | 14.1 | 1 | 15.2 | 27 | 3307 | 3 | 15 | 16 | 0 |
| `tech-l8` | 2026-09-17T03:50:06.356Z | 8 | 22145 | 46618 | 1180 | 14.1 | 0 | 5.5 | 19 | 1559 | 3 | 15 | 16 | 0 |
| `tech-l8` | 2026-09-17T03:50:10.392Z | 8 | 23767 | 45148 | 954.4 | 14.1 | 0 | 29.8 | 22 | 2984 | 3 | 15 | 16 | 0 |
| `tech-l8` | 2026-09-17T03:50:14.437Z | 8 | 24230 | 44789 | 2002.6 | 14.1 | 0 | 14 | 27 | 3269 | 3 | 15 | 16 | 0 |
| `tech-l8` | 2026-09-17T03:50:18.477Z | 8 | 22833 | 46056 | 3033.7 | 14.1 | 1 | 12.1 | 24 | 1938 | 3 | 15 | 16 | 0 |
| `tech-l8` | 2026-09-17T03:50:22.508Z | 0 | 21383 | 47085 | 1067.4 | 14.1 | 1 | 23 | 10 | 593 | 3 | 15 | 16 | 0 |
| `tech-c8` | 2026-09-17T03:50:34.077Z | 0 | 21373 | 47035 | 1123.3 | 14.1 | 0 | 6.6 | 10 | 593 | 3 | 15 | 16 | 0 |
| `tech-c8` | 2026-09-17T03:50:38.362Z | 8 | 23597 | 45156 | 1117.9 | 14.1 | 0 | 37.7 | 19 | 2742 | 3 | 15 | 16 | 0 |
| `tech-c8` | 2026-09-17T03:50:42.424Z | 8 | 23775 | 45067 | 927.7 | 14.1 | 0 | 52.7 | 20 | 2878 | 3 | 15 | 16 | 0 |
| `tech-c8` | 2026-09-17T03:50:46.496Z | 8 | 23556 | 45233 | 878.3 | 14.1 | 0 | 42.1 | 19 | 2788 | 3 | 15 | 16 | 0 |
| `tech-c8` | 2026-09-17T03:50:50.534Z | 8 | 23557 | 45243 | 879.7 | 14.1 | 0 | 39 | 19 | 2702 | 3 | 15 | 16 | 0 |
| `tech-c8` | 2026-09-17T03:50:54.583Z | 8 | 23874 | 44937 | 993.8 | 14.1 | 1 | 39.1 | 19 | 2843 | 3 | 15 | 16 | 0 |
| `tech-c8` | 2026-09-17T03:50:58.638Z | 8 | 23298 | 45510 | 4348.9 | 14.1 | 0 | 34.3 | 19 | 2436 | 3 | 15 | 16 | 0 |
| `tech-c8` | 2026-09-17T03:51:02.687Z | 8 | 23912 | 44922 | 947.9 | 14.1 | 0 | 32.7 | 21 | 2923 | 3 | 15 | 16 | 0 |
| `tech-c8` | 2026-09-17T03:51:06.735Z | 8 | 23309 | 45897 | 1112 | 14.1 | 0 | 52.6 | 25 | 1787 | 3 | 15 | 16 | 0 |
| `tech-c8` | 2026-09-17T03:51:10.798Z | 8 | 26194 | 43193 | 2249.2 | 14.1 | 0 | 62.9 | 27 | 4584 | 3 | 15 | 54 | 0 |
| `tech-c8` | 2026-09-17T03:51:14.889Z | 8 | 24850 | 44426 | 4382.6 | 14.1 | 0 | 45.4 | 23 | 3316 | 3 | 15 | 54 | 0 |
| `tech-c8` | 2026-09-17T03:51:18.930Z | 8 | 24309 | 44722 | 943.9 | 14.1 | 0 | 43.3 | 23 | 3204 | 3 | 15 | 54 | 0 |
| `tech-c8` | 2026-09-17T03:51:22.979Z | 1 | 21521 | 46954 | 1131.4 | 14.1 | 0 | 16.2 | 10 | 593 | 3 | 15 | 54 | 0 |
| `tech-c8` | 2026-09-17T03:51:27.044Z | 0 | 21368 | 47085 | 1002 | 14.1 | 0 | 11.5 | 10 | 593 | 3 | 15 | 54 | 0 |


---

## 3. The fitted slope, with its uncertainty

Three fits over the same data, because they answer slightly different objections. `live` is the
fitted instantaneous concurrency (§1.4). Commit in MiB.

| fit | n | slope (MiB/turn) | 95 % CI | intercept (MiB) | r | r² | residual s.d. (MiB) | df |
|---|---|---|---|---|---|---|---|---|
| row-level, all samples | 74 | 363.5 | 308.3 … 418.6 | 20,640 | 0.8384 | 0.7029 | 710.9 | 72 |
| **row-level, steady state (live ≥ 1)** | **63** | **403.3** | **328.3 … 478.3** | **20,381** | **0.8063** | **0.6502** | **737.5** | **61** |
| **level-mean (one point per level)** | **6** | **402.3** | **271.5 … 533.0** | **20,409** | **0.9737** | **0.948** | **330.5** | **4** |

Independent cross-checks on the same rows:

| quantity | slope (MiB/turn) | 95 % CI | r | reading |
|---|---|---|---|---|
| `\Memory\Available MBytes` | −410.4 | −471.6 … −349.1 | −0.8617 | the OS's own free-memory number agrees with commit to within 2 % |
| node working set (all node processes) | +260.4 | +201.9 … +319.0 | 0.7482 | working set is not commit; a turn commits ~1.5× what it keeps resident |
| node process count, from the level means | +216 MiB/process | — | — | and **1.74 processes per turn**, so 216 × 1.74 = 376 MiB/turn — the same number a third way |

**The number to use: ≈ 400 MiB of commit per additional concurrent turn.** The honest interval is
the *union* of the two defensible estimates, **≈ 270–530 MiB**, because the row-level CI is too
narrow: rows within a level are a time series, so their residuals are autocorrelated and the
row-level s.e. understates uncertainty. The level-mean fit is the conservative one and it is the one
I would quote against a decision.

Two caveats that bound where this applies:

* **It is one node and one workload mix.** ZABZ-TECH, a fleet whose turns are ~12 s of
  model-and-tool work. A turn that reads a 200 MB file or builds a tree will commit more.
* **It is an extrapolation beyond 8 turns**, and the intercept (20,381 MiB) matches the measured
  idle floor (20,491 MiB) to within 0.5 %, which is the only check available that the line is
  straight over the range it was fitted on.

### 3.1 The constants, against the measurement

| constant | value | source | verdict against 403 MiB/turn |
|---|---|---|---|
| commit per **generating turn** | **0.81 GB** | `PROGRAM.md:75`, reused as MEASURED by `10-inventory.md:668`, `40-hardware-costs.md:22` | **REFUTED — 2.1× too high.** Even the top of my 95 % CI (478 MiB) is 42 % below it |
| commit per **node process** | **0.58 GB** | `60-verification.md` §2.2, regressing over the laptop's sampler history | **too high by 2.7× for this node** (measured 216 MiB/process); and a process is not what a broker counts |
| commit per node process, **the same file re-fit now** | **0.465 GB** | this stream, `harness-metrics.csv`, 1,478 rows, r = 0.8545, intercept 16.33 GB, residSd 2.16 GB | 60-verification's 0.575 GB **does not reproduce** on the file that produced it (477 rows then, 1,478 now) |

The repo's own comment (`scoring.js:22–24`) says *"one actively generating agent turn costs
~1 core (0.81 GB commit + ~1 core)"*. **Both halves of that sentence are now measurements, and both
are wrong in different directions:** the memory half is 2.1× too high, and the core half is
workload-dependent between 0.62 and 1.68 logical CPUs (§4.3).

---

## 4. The four questions

### 4.1 How many concurrent turns before commit, paging or loop lag degrade?

**Answer: not within the reachable range. The curve is flat through 8 concurrent turns, and the
first thing that moves is the engine's loop-lag *maximum*, at 8 tool-heavy turns.**

The shape, counter by counter:

**commit** — monotone, linear, unremarkable. 20,491 MiB idle → 23,499 MiB at 8 resident turns →
23,813 MiB at 8 working turns, i.e. 14.6 % and 16.2 % of a 69,269 MiB limit. Extrapolating the
measured slope and its CI: physical (65,173 MiB) is crossed at **93–136 turns**, the commit limit at
**101–149 turns**. Neither is reachable with 8 children, and neither is close.

**pagefile** — `\Paging File(_Total)\% Usage` is **14.1 % in every one of the 83 sample
(83 load-window samples + the 9-sample baseline), including the CPU-heaviest one. It does not move, so there is nothing to degrade. (It is
14.1 % because the pagefile is 4,096 MiB of a 69,269 MiB limit with 577 MB in use even at idle: the
counter is nearly blind by construction.)

**disk queue** — 0 idle, maximum **1** under load. `% Disk Time` was deliberately not used.

**pages input/sec** — the one counter that looks alarming and is not. Idle 0–100/s; at 2 turns
12.9/s mean; at 4, 6 and 8 turns 1,143 / 17,697 / 2,098/s means. Two things make it unusable as a
concurrency signal:

* its largest reading of the night, **233,604/s at 03:47:59Z, is a transient** in the first seconds
  of the N=6 fleet — 6 processes loading their module graph — and it is a single sample inside a
  level whose neighbouring samples read 1,000–6,000/s. It is also the whole of that level's mean.
* it does not scale with concurrency. N=6 (18 turns) shows a 8.4× higher mean than N=8 (32 turns),
  while N=8 commits 1.2 GiB more. On the laptop's own 1,478-row history the correlations are
  `pagesIn ~ commit` **0.123**, `pagesIn ~ node processes` **0.150**, `pagesIn ~ disk queue`
  **0.746** — and the largest reading in that record (**131,140/s**, up from the 62,865/s
  60-verification saw) occurs in the ≤ 14-node-process bucket.

  **Mechanism, and it matters:** under this workload a page-in is an *image/module* page-in paid at
  process start, not a reclaim of a working set. It is therefore a function of how many turns you
  *launch per second*, and it says nothing about memory pressure. The pagefile total proves it: it
  never grows.

**event-loop lag (the target's own engine, `GET /healthz`)** — the only counter that degrades, and
only in the tail:

| level | p50 ms | p95 ms | max ms |
|---|---|---|---|
| baseline | 2 | 16 | 18 |
| 8 resident turns | 3 | 15 | 19 |
| 8 **working** turns | 3 | 15 | **54** |

A 3× rise in the worst-case stall, with the median and p95 unmoved.

**Read that table with one caveat about the counter itself:** loop.maxMs is a **rolling maximum over a 512-sample window at 250 ms — about 128 seconds** (/healthz -> loop.window). It therefore has a long memory: the 54 ms reading is still shown in the two samples after the working fleet stopped, and the 18 ms baseline carries the tail of whatever ran before it. The 18 -> 54 ms change is a real stall that this level produced, but the field would not tell you it had *ended* for another two minutes, and it is not an instantaneous signal.

**This is the honest first
degradation signal for a fleet, and it is invisible to every counter the capacity contract publishes
today** — the contract has no lag field at all, and `agents.loopsRunning` reads 0 (§5.2).

**What would answer the part that is not answered:** the crossing is at 14–52 turns (below), so it
needs a window larger than the 8-child cap on a node nobody is using. 24 children for one 90 s window
on ZABZ-TECH, at resident and working prompts, would put the peak on the curve; ~8 minutes and
~150 turns.

### 4.2 What does one additional concurrent turn cost in MiB of commit?

**≈ 400 MiB, 95 % CI 270–530 MiB** — the fit in §3, and three independent counters agree:
commit +403, available −410, and process-count × processes-per-turn +376. A slope with an r, not a
point: **r = 0.974** on the level-mean fit.

The practical consequence, applied to the broker's own inputs: on ZABZ-TECH at 03:44Z
(`freeMiB` 48,335) the memory term computes
`floor((48335 − 3885) / 160) = 277 → capped 24`, while the measured memory ceiling is
`(65173 − 20491) / 403 = 111` turns. **The 160 MiB-per-slot constant is 2.5× the measured
per-turn commit cost (403 MiB is the turn; 160 MiB is one in-flight tool call inside it), and it is
not the quantity that limits this node.** §5.3.

### 4.3 Is `0.75 × physical cores` the right fraction?

**It lands in the measured band; the band is 14–39 turns wide, so the constant is not falsified — it
is unfalsifiable, and it should be replaced by a cost, not a fraction.**

Measured per level (Δ mean CPU % against baseline, × 32 logical CPUs, ÷ measured live turns):

| level | prompt | logical CPUs per turn |
|---|---|---|
| `tech-l2` | resident | 0.306 |
| `tech-l4` | resident | 0.575 |
| `tech-l6` | resident | 0.655 |
| `tech-l8` | resident | 0.632 |
| `tech-c8` | **working** | **1.679** |

The N=2 point is low because only 2 lanes of 8 possible were consuming the sampler's fixed overhead;
from N=4 on the figure is stable at **0.58–0.66 logical CPUs per resident turn**. A tool-heavy turn
costs **1.68**, i.e. **2.7×** a model-bound one.

Turning those into "how many turns fill this node" — the question `0.75 × cores` is trying to answer:

| | resident turn | working turn |
|---|---|---|
| turns to occupy all **32 logical** processors | ≈ **52** | ≈ **19** |
| turns to occupy **24 processors'** worth | ≈ **39** | ≈ **14** |

So the measured band for "24 cores' worth of turns" is **14 … 39**, and `floor(24 × 0.75) = 18` sits
inside it. **Verdict: about right for a fleet of tool-heavy turns, conservative by ~2× for a fleet of
model-bound turns, and it cannot be tightened without fixing the workload mix.**

**And the argument for it is wrong even though the number survives.** `scoring.js:23–24` derives the
core budget from *"this laptop's paging threshold is 13-14 concurrent turns on 16 physical cores"* —
a **paging** observation used to set a **CPU** budget. Section 2.3 of `60-verification.md` already
showed the 13–14 figure was not supported; §4.1 shows paging here is not a function of concurrency
at all. The two resources have nothing to do with each other, and the coincidence that
`floor(16 × 0.75) = 12` is near 13–14 is why a wrong argument produced a usable number.

There is also a units problem the constant hides: `\Processor(_Total)\% Processor Time` counts
**logical** processors, and `cpu.physical` counts **physical** ones. The conversion under SMT is not
measured here and the two are conflated in the constant. On ZABZ-TECH (24 physical / 32 logical)
that is a 33 % error waiting to happen.

**What would tighten it:** a sweep with the workload mix held fixed — one prompt class per level,
N = 0, 4, 8, 12, 16, 20 — on an otherwise idle node, ~15 minutes and ~400 turns.

### 4.4 Does swap at 90 % actually predict anything?

**No.** Three separate reasons, in order of how badly they break the constant.

**(a) The field is not swap.** `scripts/phone-gate.py:1110–1149`:
`swapUsedPct = max(0, committed − physical) / (commitLimit − physical) × 100`. On Windows that is the
share of the *pagefile-sized* commit band that is currently committed — a commit-headroom metric
wearing a swap name.

**(b) It is 0.0 across the entire useful range, on both nodes.**

| node | physical | commit limit | pagefile | `swapUsedPct` needs commit ≥ | … which is this far below the commit limit |
|---|---|---|---|---|---|
| ZABZ-TECH | 65,173 MiB | 69,269 MiB | 4,096 MiB | 68,859 MiB (**90 %**) | **410 MiB = 0.6 %** |
| ZABZ-TECH | | | | 66,631 MiB (60 %) | 2,638 MiB |
| ZABZ-YOGA | 32,373 MiB | 44,145 MiB | 11,776 MiB | 42,971 MiB (**90 %**) | **1,174 MiB = 2.7 %** |
| ZABZ-YOGA | | | | 39,439 MiB (60 %) | 4,706 MiB |

Measured values: **0.0 in every one of the 83 samples on ZABZ-TECH**, including the level that
consumed 41.5 % of all 32 logical CPUs; and **0.0 on ZABZ-YOGA at 03:54Z** with **28,532 MiB
committed of a 44,145 MiB limit, 10,692 MiB of RAM free, 1,469 MB resident in the pagefile and the
pagefile reading 12 % used.** The whole 60 % → 90 % band the constant reasons about is **3.5 GiB of
commit on the laptop and 2.2 GiB on the desktop** — 8 % and 3.2 % of their limits, all of it
crammed into the last gigabyte before an allocation fails.

**(c) So "90 %" is a near-OOM alarm, not a warning, and the comparison asked for is not measurable.**
"Is a node at 90 % worse than one at 60 % under identical load" requires a node in that band. To put
ZABZ-TECH at 60 % would take +46 GiB of commit, i.e. **≈117 concurrent turns — 14× the cap**;
to put it at 90 %, ≈120 turns, at which point the question answers itself. And the halving is
`Math.floor(before / 2)` for a *ranking* penalty (`scoring.js:151–162`), so at 90 % a 24-slot node is
ranked as 12 — while by then its free memory is ~1 GiB and a 12-child fleet cannot fit in it anyway.

**What to replace it with.** `\Paging File(_Total)\% Usage` is the counter that actually measures
pagefile occupancy (14.1 % on ZABZ-TECH, 12 % on ZABZ-YOGA) but it is insensitive here because the
pagefile is small. The sharpest available quantity is one the contract already carries and does not
use: **commit headroom**. `/healthz` publishes `system.probe.commitAvailableBytes` and
`commitLimitBytes`; on ZABZ-TECH that is **48,778 MiB of 69,269 MiB** at idle and 45,456 MiB at 8
resident turns. A term of the form *"free memory is real only up to the commit that is left"* —
`min(mem.freeMiB, commitAvailableMiB − reserve)` — is monotone, unclipped, and would have moved
during the whole night while `swapUsedPct` sat at 0.0.

---

## 5. Five things this changes in the broker, beyond the two constants

### 5.1 `mem.swapUsedPct` is misnamed and its threshold is in the wrong place
§4.4. The `90` is not merely uncalibrated; the field it is applied to cannot express the state the
threshold is written to detect.

### 5.2 `agents.loopsRunning` cannot see a fleet the mesh dispatched
In **every one of the 83 samples** — with 8 real concurrent turns, 3.0 GiB of extra commit and
41.5 % of the machine's CPU consumed — the target's `/healthz` reported
`sessions.agentLoopsRunning: 0` and `sessionsLive: 1`. A `dsh --profile headless` child is a
**separate process** booting its own profile; it never registers in the resident engine's session
store, and it takes no `governor` lease either (`governor.inUse` was 0 throughout).

Consequences:
* `60-verification.md` §6.3 proposed settling the per-turn constant by regressing commit on
  `/healthz`'s `agentLoopsRunning`. **That would have measured zero, at every load level.**
* The capacity contract's `agents` field is a measurement of the **resident engine only**, but §2.2
  of the design reads it as a measurement of the node's load. A node running 6 dispatched children
  looks exactly like an idle one. This is the same shape of defect as 60-verification §1.7's
  "the arithmetic is decorative": a published number that is a constant in the case that matters.

### 5.3 The memory term is decorative; the core term is the whole decision
`memorySlots` reaches the `maxSlots = 24` cap whenever `freeMiB ≥ 3,885 + 24 × 160 = 7,725 MiB`.
Both measured nodes clear that with room to spare (ZABZ-YOGA 10,600 MiB; ZABZ-TECH 47,000–48,000 MiB),
so on this fleet `min(memorySlots, coreSlots)` **is** `coreSlots`, always, and `floor((free −
3885)/160)` never affects a placement. Meanwhile the measured memory ceiling on ZABZ-TECH is ~111
turns — **6× the core term.** When memory does bind it will be because a node is already in trouble,
not as a ranking signal.

### 5.4 Node-process count is a bad proxy for turns, and a worse one than 60-verification thought
`60-verification.md` §6.3 said "instrument generating turns, not `node.exe` count". Measured: at
8 live turns the `node.exe` count inside a single level ranged **19 … 27**, non-monotonically,
because a turn's process count changes as it runs, and 60-verification's 0.58 GB/process does not
reproduce (0.465 GB/process on the re-fit). **Use a turn count or use nothing.**

### 5.5 Sampler discipline: a row's timestamp must be the moment it measured
§1.4.1. Stamping a row at the top of a loop that then spends 2.1 s in `Get-Counter` and another
~0.1 s in `Get-Process`/healthz **halved the apparent slope** (301 vs 403 MiB/turn) and would have
made the same mistake in the other direction against any counter read early in the loop. The fix is
cheap: stamp once at the end and use that, or fit the offset. **This is the third time in this
program that a counter's *timing* has misled a reader, after load average, `Pages free` and
`% Disk Time`.**

---

## 6. What I could not verify, and what would verify it

1. **ZABZ-YOGA's own curve — the one the constants were written for.** Blocked by this stream's own
   rule: the ≤ 4-children allowance is conditioned on commit staying under 26 GB, and the laptop was
   at **27.11 GiB by 03:45Z and 29.92 GiB by 03:54Z**, with **6 agent loops executing**, before any
   fleet was dispatched. *What would answer it:* run the same rig **from ZABZ-TECH** against
   `laptop-ts` (`mesh-run.ps1 -Node zabz-yoga-1`), so no driver, sampler or ssh client process is
   charged to the laptop — N = 2, 4, 6, 8, ~6 minutes, ~90 turns — **after** the overnight program's
   sessions have ended and yoga is back under ~12 GiB of commit. This is the single highest-value
   follow-up, because `0.75 × 16 = 12` is the number the core term actually uses in production.
2. **`secratary` and `zabz-tech-linux`.** No `/healthz` (plugin-health unmounted; mounting it needs
   the engine restart P210 forbids) and no `Get-Counter` on POSIX. **Recorded as a measurement gap,
   not worked around.** It matters more than it looks: `secratary` has **4 cores**, so 8 concurrent
   turns is a **2× oversubscription** — the only node in the fleet where the cap can actually reach
   the crossing, and the node stream O5 is simultaneously trying to bring under control. *What would
   answer it:* either mount plugin-health in a restart window, or sample `/proc/meminfo`
   (`Committed_AS`, `CommitLimit`, `SwapCached`) with `/proc/pressure/{cpu,memory,io}` and
   `/proc/<pid>/stat` — all of which need no engine at all.
3. **The region above 8 concurrent turns.** The highest measured point is 8 live turns on a
   24-physical-core node: **44 % of the core term, i.e. 8 of 18 slots, and 6.6 % of the measured memory ceiling.** The
   crossing is at 14–39 turns depending on workload. *What would answer it:* one 90-second window at
   N = 24 on a node nobody is using, ~8 minutes, ~150 turns.
4. **The exact bill.** §1.5's ≈ $0.9 (range $0.5–1.5) is an estimate derived from a decoded turn
   session's structure. The session store records `request/header` (26,181 B) and `system/message`
   (4,979 B) but **not per-call usage**, so it cannot be summed. *What would settle it:* the provider
   console export for 03:30–04:10Z.
5. **The real dispatcher's counter signature.** `mesh-run.ps1 -Prompt … -Children 2 -Node zabz-tech`
   **ran and succeeded** — its own log:
   `{"phase":"verify","node":"zabz-tech","meshHostLines":2,"transportHostLines":2,"childHosts":["zabz-tech"],"disagreements":[],"ok":true}`,
   `{"phase":"result","outcome":"completed"}`, 25,207 ms, exit 0 — which proves the production path
   dispatches 2 real children to that node. But the sampler started for that window died when the
   ssh session that launched it closed, so its CSV is empty and I have no counter signature for the
   real path. *What would answer it:* launch the sampler through the keep-alive shape
   `mcal-level-target.ps1` uses and run the dispatcher from a second connection.
6. **The logical-processor → physical-core conversion under SMT**, which the core term silently
   assumes is 1:1. Not measured.

---

## 7. What I deliberately did not do, and where every number came from

**Did not do:**
* **No fleet on ZABZ-YOGA** — the stop line was already crossed (§1.1).
* **Nothing on `secratary` or `zabz-tech-linux`.**
* **No engine restarted** anywhere, on any node. No plugin mounted, no serve config touched.
* **No process killed that this stream did not start.** Each level printed its sampler and driver
  pid; both exit on their own timers, and the *"killed while running"* line never appeared.
* **Nothing committed, pushed, branched or reset.** No `git` state change of any kind.
* **No journal entry.** This stream's brief names exactly one file, and `journal/` is a repository
  path that another stream is actively repairing tonight. The transferable lessons are therefore
  **in this document**, in §5.2, §5.5 and §3.1, and the manager should carry them into the journal —
  see §5.5 for the sampling rule and §5.2 for the finding that invalidates a proposed measurement
  method.
* **Two nodes were never loaded at once** — the sweep ran levels strictly in sequence on one node.

**Scratch, all outside the repository** (on ZABZ-YOGA under `%TEMP%`, on ZABZ-TECH under
`C:\Users\ezabz\AppData\Local\Temp`): `mcal-lib.ps1`, `mcal-level.ps1`, `mcal-level-target.ps1`,
`mcal-driver.mjs`, `mcal-sampler.ps1`, `mcal-sweep.ps1`, `mcal-analyze.mjs`, `mcal-avail.mjs`, and
`mcal\mcal-*.csv` / `mcal-*-events.json` / `analysis.txt`. They are left in place so every number
here can be regenerated; `node mcal-analyze.mjs <dir> tech-b0 tech-l2 tech-l4 tech-l6 tech-l8 tech-c8`
reproduces §2 and §3 exactly.

**Provenance of each claim.**

| claim | counter / source | where |
|---|---|---|
| the node's identity, cores, pagefile, capacity object | `Win32_ComputerSystem`, `Win32_PagefileUsage`, `GET /mesh/capacity` on the gate | §1.1, 03:36–03:38Z |
| every memory number and the slope | `\Memory\Committed Bytes`; cross-checked by `\Memory\Available MBytes` | §2, §3 |
| the paging claims | `\Memory\Pages Input/sec` and `\Paging File(_Total)\% Usage` | §4.1 |
| the disk claim | `\PhysicalDisk(_Total)\Current Disk Queue Length` (never `% Disk Time`) | §4.1 |
| the CPU claims | `\Processor(_Total)\% Processor Time`, level means | §4.3 |
| the loop-lag claims | the target engine's own `GET /healthz` (`loop.p50Ms/p95Ms/maxMs`), cookie minted as `phone-gate.py` mints it | §4.1 |
| instantaneous concurrency | the driver's own spawn/exit event log, offset-fitted against node working set | §1.4, §2.1 |
| the laptop's longitudinal history | `~/.dsh/metrics/harness-metrics.csv`, **1,478 rows, 2026-09-16T12:56:55 → 23:45:25 local, re-read live** (the sampler is running again — it was stale when `60-verification.md` read it) | §3.1, §4.1, §5.4 |
| the `swapUsedPct` formula and its platform split | `scripts/phone-gate.py:1110–1168` (read) | §4.4 |
| the reference ratio and the process-cost constant | `packages/plugin-remote-fanout/lib/remote-script.js:61–86`, `cordis.patch.yml:79` (read) | §1.2 |

**Bottom line for the two constants.** `0.81 GB per generating turn` is **refuted** (measured
403 MiB, CI 270–530). `0.75 × physical cores` is **inside the measured band (14–39 turns) but its
derivation is wrong** — it converts a paging observation into a CPU budget, and a turn costs 0.62 or
1.68 logical CPUs depending on what kind of turn it is. `SWAP_PENALTY_PCT = 90` is **wrong as
written**: the field it guards is commit-band occupancy, it reads 0.0 until the node is within
0.6–2.7 % of its commit limit, and the band between 60 % and 90 % is 2–4 GiB of commit wide. Replace
it with commit headroom, which the contract already publishes.
