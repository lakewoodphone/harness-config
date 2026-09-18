# 81 — The overnight program: finish the mesh end to end

Owner's mandate, 2026-09-17 ~00:30Z: *"get to work now robustly and fully auditing and analyzing and
researching this work through the night with orchestration and multiple research agents and
implementation agents. I want to wake up tomorrow and the entire thing is end to end robustly and
fully built."*

This file is the contract for that night. Read `71-mesh-program.md` (the architecture and the frozen
interfaces) and `78-acceptance.md` (the harness) first. Everything below is in addition to those.

## 0. What "fully built" means — the definition, so it is not interpreted

The mesh is DONE when `pwsh -File scripts/mesh-e2e.ps1 -Strict` exits **0 with zero SKIPs**, and
its report contains, with raw output:

1. every node answering a schema-1 capacity object that matches an independent measurement;
2. a placement whose `rationale` names the arithmetic that chose it, and which moves to another
   node when that one is forced to zero;
3. **a real six-child fleet, dispatched for real, whose every `MESH-HOST:` line matches the node
   the broker named — on at least two distinct nodes;**
4. **the client's commit flat within ±1 GiB while those children run**, and no new agent loops on
   the client;
5. **a node killed mid-run**: the run fails naming that node, the lease is reclaimed on its own
   TTL, and the next run succeeds elsewhere with no manual repair;
6. thirty concurrent placements against five slots: every caller gets a node and a position, at
   least one position > 0, zero non-200 responses.

Plus two things the harness cannot assert for us:
7. **one measured load, not a modelled one**: run a fleet large enough to sustain several turns on
   ONE node and record what the machine actually did (commit, page-ins, loop lag, swap) — this is
   what turns `0.75 x physical cores` and the `90% swap` threshold from reasoned heuristics into
   measured constants, or replaces them;
8. **the authority's broker survives a reboot**: it is a hand-started process today.

## 1. Workstreams, owner per file

| # | stream | owns | deliverable | done when |
|---|---|---|---|---|
| O1 | **the acceptance gate** | `docs/mesh/82-e2e-run.md` only | run §0's 1–6 for real and report raw output | the harness exits 0 with zero SKIPs, or every remaining SKIP has a written reason the owner must accept |
| O2 | **transport v2** | `packages/plugin-mesh-http/**`, `docs/mesh/83-http-transport.md` | a plugin-owned HTTP route on a node that runs one dispatched child, HMAC-authenticated, reached through the gate — so dispatch stops depending on ssh | one child runs on a node with ssh disabled for the test and the `MESH-HOST:` line proves it |
| O3 | **calibration** | `docs/mesh/84-calibration.md` | sustained-load measurement on one node: how many concurrent turns before commit/paging/loop-lag degrade, and what the per-turn memory and core cost actually is | the two constants are either confirmed with numbers or replaced with measured ones |
| O4 | **node hygiene** | `packages/plugin-*/` is NOT yours; `scripts/mesh-hygiene-*.ps1|sh`, `docs/mesh/85-hygiene.md` | every node can return itself to a placeable state, and the capacity contract reports memory *drift* so a node leaving the placeable set is visible | a node deliberately loaded and abandoned returns to placeable within one interval, with the numbers |
| O5 | **the authority** | `docs/mesh/86-authority.md` + a systemd unit under `packages/mesh-broker/deploy/` | the broker as a supervised service that survives a reboot, and the authority's swap brought under control | broker restarts itself; swap is not at 100% |
| O6 | **the fork** | `docs/mesh/87-harness-fork.md` | `harness-config` on `secratary` merged deliberately on a branch, backed up first, with the journal's own tools | every machine can `git pull --ff-only` again, and `journal.py check` is 0 errors |
| O7 | **research: the elastic tier** | `docs/mesh/88-elastic-build.md` | the provisioner + teardown design against the REAL broker API, with the trigger as `tier != "fits"` twice ≥60 s apart, and the cost of a forgotten node named | a written, runnable design, or a written refusal with the measurement that kills it |

Nothing in a later stream is needed by an earlier one, except that O1 consumes O2/O3's results if
they land first — O1 must not WAIT for them; it runs the acceptance on whatever exists and records
exactly what failed.

## 2. Standing rules for every stream, without exception

* **No engine restart on ZABZ-YOGA.** (pid 1784 runs the owner's live session.) Other nodes may
  restart theirs ONLY if you say so first in your report and nothing of the owner's is running.
* **Never kill a process you did not start.** The acceptance harness proved what happens otherwise.
* **Never destroy data.** No `rm -rf`, no `git reset --hard`, no force push, no dropping tables. A
  merge that needs history rewritten is a stop-and-report.
* **Measure, never assume.** Every number carries its source and its moment. "Could not verify" is
  a correct and expected answer; a confident wrong number is the failure this whole program exists
  to stop.
* **A report is a claim, not evidence.** Reproduce before believing — including your own earlier
  finding. Two streams tonight were overturned by a third measuring the same thing.
* **Commit nothing.** Write your files, report them, and the manager integrates.
* **Prefer the in-process tools** (read/grep/glob/edit) over shell calls: ~0.8 ms against ~700 ms.
  Batch shell work into one call. Every ssh is `-o BatchMode=yes -o ConnectTimeout=15` with a
  retry, and a remote command needing quoting goes in a file you scp, never inline.
* **The tailnet path to the Mac Mini is relayed and flaky** (four drops in one session, `scp` can
  fail repeatedly while `ssh` works). Push files over an ssh stdin pipe there.
* **Proxy off on every HTTP call** (`-NoProxy`): this laptop's .pac proxy invents 502s.

## 3. The known-open list this night must close or explain

1. `phone-redirector.py:44` still has the old `tailscale` call shape — the last place the macOS
   orphan can be recreated.
2. The gate and the broker use two DIFFERENT reserves (the gate reproduces the governor's
   `max(2 GiB, 12%)`; §2.2's broker uses 3885 MiB). One of them is wrong; decide which and say why.
3. `secratary`'s transport is `null` (no headless profile on that node) and `zabz-tech-linux` is
   `NO` — so two capacity-visible nodes cannot yet receive dispatched work. Either fix it or state
   the measurement that says why not.
4. The Mac Mini reports `agents: null` (no plugin-health there) and its gate has no `fleet` caveat
   even though a human's browser can return to it.
5. The harness's §4.5 kill-half needed a ruling; it now has one (stub-gate half stands, fleet-death
   half deferred to O1). O1 executes the deferred half.
6. Load averages, `Pages free`, and `% Disk Time` are all counters that have already misled this
   program once each. Do not build on any of them.

## 4. How to report

One message per stream when it is done, plus `docs/mesh/8x-*.md`. In the message: the files, the
exact commands, the raw output lines that decided each claim, what you deliberately did not do, and
what you could not verify. If you find that a premise in THIS file is wrong, say so plainly and
correct it in your document rather than working around it — three of tonight's best findings were
premises in a brief that turned out to be false.
