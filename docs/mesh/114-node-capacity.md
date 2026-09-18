# 114 — Node capacity: every measured number on the mesh, in one table

Consolidated 2026-09-18 by the orchestrator from seven measured workstreams. Every cell carries the date it
was measured and the method that produced it. **A cell marked `in flight` is not a guess and not a zero —
it has not been measured yet.**

## 1. Unit cost — what one extra concurrent agent turn costs, per node

| node | unit cost per turn | 95 % CI | R² | method | measured |
|---|---|---|---|---|---|
| `zabz-tech` (desktop, 32c) | **295 MiB** | 270–320 | 0.981 | `GlobalMemoryStatusEx` commit, K∈{0,2,4,6} × 5 runs, same-run anchor | 2026-09-18 |
| `zabz-tech-linux` (12c) | **113 MiB** | 110–117 | 0.9971 | `/proc/meminfo` `Committed_AS`, K∈{0,2,4,6} × 5 runs, same-run anchor | 2026-09-18 |
| `zabz-yoga-1` (owner's laptop, 22c) | **369–418 MiB** | — | — | independent reproduction by a different instrument (load-generator delta) | 2026-09-18 |
| `zabz-yoga-1` (earlier figure) | 403 MiB | 270–533 | 0.948 | the original level-mean fit | 2026-09-17 |
| `lakewooechsmini` (macOS, 10c) | **159 MiB** commit-analog / **229 MiB** resident | 142–176 / 193–264 | 0.961 / 0.949 | macOS anonymous+wired+compressor pages (swap constant); resident cross-check = child-tree RSS | 2026-09-18 |
| `secratary` (authority, 4c) | **~181 MiB RSS peak, lower bound** | — | — | one child only, 2 samples caught it alive | 2026-09-18 |

## 2. Two caveats that change how these numbers must be used

**The metric is not identical across platforms — and there are now THREE metrics, not two.** The desktop
and laptop figures come from Windows `GlobalMemoryStatusEx` commit charge; the Linux figure comes from
`/proc/meminfo` `Committed_AS`; and the mac mini could use neither, because **`GlobalMemoryStatusEx` does
not exist on macOS and has no counterpart** — its figure is an *analog* built from anonymous + wired +
compressor pages, with `swapUsed` pinned at a constant 1,743,582,658.56 B across 1,300+ samples so that it
cancels in every delta. Those three are *method-identical within a platform* and *suggestive across
platforms*, and nobody has shown any two of them count the same quantity. **Read every cross-node
comparison in this document as directional.** The mac mini's own runs carry a second, independent figure
(child-tree RSS, 229 MiB) that is *higher* than its commit-analog (159 MiB) precisely because the host is
swap-pressured — so even within one node the answer depends on which quantity you ask about.

**The plateau is a ramp, and the safer number is bigger.** On `zabz-tech-linux` the children were still
allocating at the last alive sample of every run (alive windows 3.2–4.4 s), so the plateau-median slope
understates what must actually be reserved. Sizing the same data by **peak** instead gives **140 MiB/turn
(CI 138–142, R² 0.9994)** against the headline 113. **For capacity planning use 140; for cross-node
comparison use 113**, because that is the method-identical figure.

## 3. Capacity and current readings

| node | cores | RAM total | available (measured) | disk free | OS / node | overcommit |
|---|---|---|---|---|---|---|
| `zabz-tech` | 32 | 63.6 GiB | 38.8 GiB | 185.5 GiB | Win 11 / v24.19.0 | Windows |
| `zabz-yoga-1` | 22 | 31.6 GiB | 13.7 GiB | 48.4 GiB | Win 11 / v24.12.0 | Windows |
| `zabz-tech-linux` | 12 | 11.4 GiB | 10.3 GiB | **20.9 GiB — the tightest** | Linux / v22.23.2 | **0 = advisory** |
| `secratary` | 4 | 22.9 GiB | 14.6–14.8 GiB | 134.8 GiB | Linux / v20.20.2 | **0 = advisory** |
| `lakewooechsmini` | 10 | 16 GiB | 6.6 GiB | 45.7 GiB | macOS / v24.19.0 | n/a |

## 4. What binds each node — the one thing that decides a placement

| node | the binding quantity | evidence |
|---|---|---|
| `zabz-tech` | nothing measured binds it. 38.8 GiB free, 185 GiB disk, 32 cores | — |
| `zabz-yoga-1` | **the owner is sitting at it.** Every other quantity is comfortable (25.0 GiB committed against a 43.1 GiB limit) | `113` |
| `zabz-tech-linux` | **disk: 20.9 GiB free, 96 % used** | workstream L |
| `secratary` | **swap: 712–716 kB free of 4 GiB — 0.017 %**, already below any sane abort floor *at rest* | workstream S |
| `lakewooechsmini` | **swap pressure: 54.1 % of swap already used** at start. Adding children EVICTS other processes' pages, which is why its resident figure (229) exceeds its commit-analog figure (159) | workstream M |

## 5. What is NOT a limit here, though it looks like one

**On both Linux nodes `vm.overcommit_memory = 0`, so `CommitLimit` and `Committed_AS` are REPORTED, not
ENFORCED.** On `secratary` `Committed_AS` sat at 84.5 % of `CommitLimit` for an entire 149-sample baseline
with nothing rejected; on `zabz-tech-linux` `CommitLimit` is arithmetically `SwapTotal + 50 % × MemTotal`.
Reporting either as a hard ceiling is a mistake this project has already made once, in the opposite
direction, and both workstreams flagged it independently.

**`v1 dispatch` on `secratary` is not blocked after all.** A prior record said that node's `DSH_HOME` holds
"only `node_modules` and `web`" so no headless child could run there. Workstream S listed the directory:
**`headless` exists**, dated Sep 17 03:57, and a real child ran on the authority and reported
`HOSTNAME=secratary`. The prior record was stale.

## 6. The authority, in one line, from measurement rather than reputation

`secratary` **can host one agent child**: one child cost ~181 MiB peak RSS (1.2 % of free RAM), **drew zero
swap**, and left both `mesh-broker.service` and `secretary-api` `active` in every one of 44 loaded samples.
The binding limit is the exhausted swap — an already-running process that starts growing cannot be paged
out, which is the "one runaway away from a global OOM" condition recorded in `112`. **Place small things
there; do not co-locate anything large with `secretary-api`.**

## 7. A hazard in our own verification, found by a child correcting itself

Workstream S's first message opened with `MESH-HOST: ZABZER` — **a value it had written before running
anything**, and which it then corrected to the measured `zabz-tech`. That is worth more attention than a
typo: **`MESH-HOST:` is a token the CHILD writes.** The mesh's entire placement-verification path compares
that token against the node the broker named, and treats agreement as proof the child ran there. A child
that guesses, or that reads the expected hostname out of its own brief, produces a "confirmation" without
having run anywhere.

Today's variant failed safely (the guess did not match), and the existing checks are not useless — the
transport also records `transport host` from the target shell *before* the agent starts, and the provider
matches that against the broker's node. But the weakness is real and specific: **any check whose only
evidence is a sentence the checked party writes is a check that can be satisfied by writing.** Recording it
here rather than as a defect to fix blind, because the right fix — a nonce the target shell must echo from
the dispatcher, which the child never sees — is a design change to the transport, not a patch.

## 8. Still in flight

- The laptop's **responsiveness** under load (workstream R) — the only measurement that speaks to the
  owner's actual word, *lagging*. Everything in this document is memory and capacity; none of it is speed.
- The mesh under **simultaneous** load across several nodes (workstream F2, lost once to a transport
  timeout and to be relaunched after the others land, so it does not re-concentrate on one node).
