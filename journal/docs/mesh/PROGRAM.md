# The mesh programme — the spine

**This is the document to read first.** It is the entry point to everything the mesh programme has
measured, built, broken and learned. Every number here has a source; every claim that is not measured says
so. Last updated **2026-09-18**.

The owner's words, and the specification for all of it: *"when I use DSH it is speedy without any lagging
… because it offloads properly"*, and *"whichever machine the owner uses (laptop, office desktop, iPhone)
must stay fast because agent work is placed across the always-on nodes."*

## 1. What the mesh is

Five machines on a Tailscale tailnet (`tail93e6e6.ts.net`), each able to run real agent turns for the
others:

| node | what it is | role today |
|---|---|---|
| `zabz-tech` | Windows desktop, 32 cores, 63.6 GB | the workhorse; the only node with real headroom |
| `zabz-yoga-1` | Windows laptop, 22 cores, 31.6 GB | **the machine the owner uses**; `prefer-remote` is ON here |
| `secratary` | Linux, 4 cores, 22.9 GB | the authority: business database, the company engine, and the placement broker |
| `zabz-tech-linux` | Linux, 12 cores, 11.4 GB | small deterministic jobs; the only node with `dsh` on PATH |
| `lakewooechsmini` | macOS, 10 cores, 16 GB | added to the roster 2026-09-18 after two days of wrongful exclusion |

A dispatcher on any node asks a **broker** (on `secratary`, port 3091) where to place a child; the broker
ranks by measured slots and **never refuses — it queues**. The child runs on the chosen node over ssh. Local
pressure on the *dispatching* machine is read by `packages/plugin-remote-fanout/lib/pressure.js`, which
excludes the local node above 85 % of physical commit and refuses local above 92 % **and** below 1.5 GiB
available.

## 2. The numbers, and where each came from

| node | unit cost per concurrent turn | CI | metric | source |
|---|---|---|---|---|
| `zabz-tech` | **295 MiB** | 270–320 | Windows commit | `114` |
| `lakewooechsmini` | **159** commit-analog / **229** resident | 142–176 / 193–264 | macOS analog / RSS | `114` |
| `zabz-yoga-1` | **369–418 MiB** | — | reproduction of 403 | `113` |
| `secratary` | **~181 MiB** RSS peak | — | one child, lower bound | `114` |
| `zabz-tech-linux` | **113** plateau / **140 peak** | 110–117 / 138–142 | Linux `Committed_AS` | `114` |

**Three different metrics, not one.** Windows commit charge, Linux `Committed_AS`, and a macOS analog built
from anonymous + wired + compressor pages. They are method-identical *within* a platform and merely
suggestive *across* platforms, and nobody has shown any two count the same quantity. **Every cross-node
comparison in these documents is directional.**

**What a fleet costs the machine the owner uses** (`113`, four 60 s windows, 58 one-second samples each):

- three children on the **desktop**: **+0.046 GiB commit, +2.2 processes** — indistinguishable from idle
- three children on the **laptop**: **+1.081 GiB commit, +25.9 processes**; process ranges do not overlap
- per child **369–418 MiB**; the noise band is 0.145 GiB / 2.7 processes, from two fleet-free baselines

## 3. What is measured, and what is NOT

**Measured and reproduced:** node capacity and current readings; unit costs as above; the laptop's cost
under load; that a fleet on the desktop is free for the laptop; that `secratary` can host one child
(~181 MiB, zero swap drawn, both services unaffected); that the mac mini's gate answers and a child runs
there in 2.9 s; that `zabz-tech-linux`'s dispatch works through its executor.

**NOT measured, and this is the important list:**

- **Whether any of this makes the owner's machine *feel* faster.** A responsiveness probe returned a **null
  result** — the A→A2 baseline drift (−3.9 ms) exceeded every effect measured — and the load was three
  *sleeping* children, not CPU-active ones. **"Lagging" is still unquantified.** Everything in this
  document is memory, process count and capacity. None of it is speed. A second probe (CPU-active load,
  N=6–8, longer windows, drift stated next to every effect) is the measurement that would answer it.
- The mesh under **simultaneous** multi-node load.
- Whether the Windows and Linux commit metrics count the same quantity.

## 4. Open defects, each with what is known

| id | what | status |
|---|---|---|
| **P331(a)** | `mesh-run -Node <node>` and `MESH_TARGET_NODE` do not constrain where a subagent goes. **Eliminated by measurement:** the env *does* reach a `--profile mesh` child (`echo` printed `[secratary-ts]`), and the profile flag *is* honoured (a bogus profile fails loudly, exit 1). The cause is inside placement. | open, narrowed |
| **P332** | Fan-out concentrated on one node costs children. Five children on `zabz-tech` pushed its sshd handshake to 8,041 ms and one dispatch died on `ConnectTimeout=10`. **Fixed** by raising the hop timeout to 25 s; **not fixed** is the absence of any cap on children per node. | half fixed |
| **P269** | A mesh child can never appear in the Subagents UI. Pinned to two lines — `dsh-subagent` writes the catalogue only when the provider exposes `localAgent`, and the remote provider returns `undefined` by design. Remedy is two core changes, documented in `110`. | understood |
| **P270** | A page that survives an engine restart keeps a stale job list. **Downgraded to an unconfirmed hypothesis** — the observation was real, the explanation was a guess, and the client does reset correctly on a new baseline. | unconfirmed |
| **MESH-HOST** | The placement check compares **a token the child writes**. A child was observed opening its reply with a fabricated `MESH-HOST: ZABZER` before measuring anything. Today it failed safely; the check is satisfiable by writing. The `transport host` line, written by the target shell *before* the agent starts, is the part carrying real weight. | open; patch in flight |
| **journal divergence** | `zabz-tech`'s clone: `ahead 7 / behind 52`, **39 id collisions**, **nine ids meaning two different entries**. Root cause is mechanical — autosync refuses to fast-forward a diverged history, so the id ceiling cannot see unfetched refs. This machine's own four collisions were repaired and published on 2026-09-18. | open on that machine |
| **swap on `secratary`** | **FIXED 2026-09-18.** The swap is a 4 GiB `/swap.img` on the ext4 root LV — not tmpfs (a tmpfs cannot be a swap device; the old note named the right directory for the wrong reason). The holder was **not a process**: largest process 14 MiB, all processes together 63 MiB of the 4,093 MiB used. It was **swapped-out tmpfs pages from `/tmp`**, charged 3.69 GiB to `user-1000.slice`. Pruned in two guarded passes (3,770 stale entries; `.git` directories, logs and databases kept, and SQLite companions kept if their sibling was fresh): **swap 4,095 used / 980 kB free → 943 used / 3,152,000 kB free**, `/tmp` **7.2 G → 2.3 G**, RAM used **8,896 → 6,589 MB**, with `mesh-broker`, `secretary-api`, `secretary-dashboard` and `vscode-tunnel` all still `active running` and the API answering HTTP 200. Manifest at `/home/zabz/tmp-prune-manifest-20260918.txt`. | **fixed** |

## 5. What was changed, and what it bought

| change | evidence it works |
|---|---|
| `prefer-remote` policy in `pressure.js` — exclude the local node whenever the broker's own eligible set holds another node | **live and verified from a real dispatch**: `prefer-remote is ON and needed no exclusion`; 112/112 package tests pass |
| Remote child turn cap `300000` → `1800000` ms | verified by observation: children ran 449 s and 504 s, exit 0, past the old ceiling |
| `enableRunInBackground: true` on the mesh subagent rows | three children returned durable job ids instantly instead of blocking the turn |
| `dshw.ps1` `Get-WindowCount` in shared-profile mode | `status` went from sixteen rows of `windows 1` to `1 window(s) open`; `dshw new` opened slot 2 |
| Dispatch hop `ConnectTimeout` 10 → 25 s | live on the hop: `-o ConnectTimeout=25` |
| `lakewooechsmini` added to the broker roster | the live broker reports **five nodes**; a real child ran there in 2.9 s |
| `_scratch/` gitignored | `agent-fleet doctor` went from refusing to **READY** |

## 6. The instruments

- `scripts/mesh/Start-AgentFleet.ps1` — launches N bounded headless turns **aimed at a named node** and
  proves placement from each child's own `MESH-HOST:` line; samples an observed node at 1 Hz; kills exactly
  the PIDs it started and verifies both ends. **Drive it from PowerShell 7** (5.1 returns an empty exit code
  for redirected `Start-Process`, which reports a healthy ssh as COULD NOT ASK).
- `scripts/mesh/Get-NodeSample.ps1` — the 1 Hz sampler, shipped to the observed node as an encoded command.

Three facts that will cost a child its turn if they are not respected: a headless turn prints **only** its
final assistant message, so a child killed mid-turn can never prove where it ran; ssh session setup costs
**2–25 s** and is variable; and on Windows an `ssh` whose stdout is **piped** never returns — only
`Start-Process -RedirectStandardOutput <file>` does.

## 7. The phase plan

0. **Prove the fifth node.** *Done* — gate answers 200, a child ran in 2.9 s, roster updated, broker reports five.
1. **Calibrate every node.** *Done* — all five have a unit cost, with the three-metric caveat stated.
2. **Make the local half of the promise measurable.** *Half done* — memory is measured and reproduced; a
   responsiveness probe ran and returned a **null**, so a CPU-active probe at higher N is the next measurement.
3. **Presence.** *Done for the laptop* — `prefer-remote` is ON there and verified live. Waiting on step 4 to
   widen it to any machine with a human at it.
4. **The scheduler proper.** Rank on measured unit cost *and* free capacity, queue rather than refuse, and
   record every placement with its reason so the ledger can be read back. Not started.
5. **The single-source-of-truth and disk-write layer** (`112`). Designed, not implemented.

## 8. The rules this programme has paid for

1. **A blank is not a zero.** Four wrong conclusions in one day — `node` on PATH, `engine:3099` on macOS,
   `secratary`'s commit figures, "zabz-tech is isolated" — all from reading a check's inability to look as a
   check that found nothing. Every probe must be able to answer **`COULD NOT ASK`**, and its report format
   must have a slot for that.
2. **Reproduce an agent's report before believing it.** The rule that caught the isolation falsehood: the
   wrong answer arrived with a confident paragraph, the right answer from a four-line script.
3. **Never apply a diff you read out of a chat message.** One arrived truncated mid-hunk; take it from the
   artefact and `git apply --check` it first.
4. **Never write a journal entry with a shell.** Three invariants — LF endings, heading position, a
   self-hash — are maintained by `journal.py` and by nothing else.
5. **Run `--dump-config` before committing a profile edit.** A profile that does not parse is a machine that
   does not start, and the check takes one second.
6. **A tool that can match itself is not a check.** I killed my own shell by filtering for a string my own
   command line contained.
7. **Concentrating a fan-out on one node costs children.** No cap on children per node exists anywhere.

## 9. Document index

| doc | what it holds |
|---|---|
| `109-node-inventory.md` | the first measured inventory, with two corrections kept inline |
| `110-subagent-visibility.md` | why a mesh child can never appear in the Subagents UI, pinned to two lines |
| `111-placement-design.md` | the placement rules in order, and where children actually land |
| `112-single-source-of-truth.md` | state classification, the unreachable-authority rule, and the reconciliation procedure |
| `113-laptop-under-fleet.md` | what a fleet costs the owner's laptop, and the responsiveness null |
| `114-node-capacity.md` | every node's capacity, unit cost, and binding constraint in one table |
| `115-instruments.md` | how to run the load generator and sampler — and the five ways they lie |
| `116-runbook.md` | add a node, verify the mesh, recover from the ways it breaks |
| `117-journal-divergence.md` | the ten cross-machine id collisions on the desktop, two tools that are blind to them, and the reap plan |
| `118-hardware-plan.md` | the costed plan: $0 of ranked interventions, and the one purchase gated on a demand number nobody has taken |
| `docs/agent-brief-template-mesh.md` | the brief template built from the four failures of 2026-09-18 |
| `preserve/` | preserved artefacts — currently the 113 untracked journal entries rescued off the desktop |
| journal | `L2000`, `L2001`, `L2056`, `L2060`, `L2063`, `L2064`, `P330`-`P332`, `W209`-`W218` and the handoffs |
