# 115 — How to run the mesh instruments (and the ways they will lie to you)

The two programs in `scripts/mesh/` are the only tools on this mesh that measure **what a fleet actually
costs a machine**. They were built on 2026-09-18 after four measurement defects were found by measurement,
and every one of those defects is a way this instrument can lie to you.

## The two files

- **`Start-AgentFleet.ps1`** — launches N concurrent headless agent turns **aimed at a named node** over
  redirected ssh, proves where they ran from each child's own `MESH-HOST:` line, samples an observed node
  at 1 Hz, then kills exactly the PIDs it started and verifies both ends.
- **`Get-NodeSample.ps1`** — the 1 Hz sampler. It is shipped to the observed node as a base64
  `-EncodedCommand`, so it must remain self-contained.

## Running it

```powershell
# from PowerShell 7 — see HAZARD 1
cd <repo>/scripts/mesh
.\Start-AgentFleet.ps1 -Node desktop-ts -Count 3 -SampleNode laptop-ts `
    -SampleSec 60 -MinAvailGiB 4 -HardTimeoutSec 90 -Tag B
```

| parameter | meaning |
|---|---|
| `-Node` | ssh alias of the node the **children** must run on |
| `-Count` | concurrent children, hard cap 3. **`0` = baseline**: launch nothing, just sample |
| `-SampleNode` | the node to sample (normally the one whose responsiveness you care about) |
| `-SampleSec` | length of the sampling window |
| `-MinAvailGiB` | **abort floor**: kills everything if available physical memory on `-SampleNode` falls below this |
| `-HardTimeoutSec` | wall-clock cap on the loaded phase |
| `-PostWindowWaitSec` | how long to let children finish their own turn so each can emit its own hostname |

A four-condition run — **A** baseline, **B** fleet on the desktop, **C** fleet on the laptop, **A2**
baseline again — is the shape that produced every number in `113`. **The A2 control is not optional:** the
noise band on this mesh is **0.145 GiB and 2.7 processes**, measured by exactly that second baseline, and a
single baseline cannot distinguish load from drift.

## The five ways it lies

**1. PowerShell 5.1 reports a healthy `ssh` as `COULD NOT ASK`.** Measured: 5.1 returns an **empty**
`Process.ExitCode` for `Start-Process -PassThru` with redirected output; PS 7 returns `0`. The instrument
then announces `COULD NOT ASK: ssh <node> hostname` about a node that answered perfectly. **Check
`$PSVersionTable.PSVersion.Major` and require 7.** The failure is the day's recurring error in miniature: a
blank read as a fact about the far end when it was a property of the near end.

**2. A headless turn prints ONLY its final assistant message.** A child killed mid-turn has **empty stdout
and can never prove where it ran**. That is why the driver waits for each child's `CHILD_PID=` line — proving
a live remote process exists — before opening the sampling window, and why it lets children finish their own
turn before killing them. **Any fleet that kills children on a timer will collect `COULD NOT ASK` where it
expected a hostname.**

**3. ssh session setup costs 2–25 s and is variable.** A fixed-duration child can die before the window
opens. The instrument sequences around this (launch, confirm, then sample); if you re-time it, do not
sequentially launch-and-sample.

**4. `alive == K` does not mean K children still hold memory.** Observed on the mac mini: two K=2 runs
plateaued with one child's worth of RSS while two others showed double. Cross-check the plateau against the
children's own summed RSS, and treat a bimodal level as a measurement problem rather than a finding.

**5. `Atomics.wait` blocks the event loop, and a parent that cannot reap its children cannot clean up.**
Measured on the mac mini: the first sampler slept with `Atomics.wait`, so Node never reaped the children —
they finished at ~2 s and became **unkillable zombies** (`remainingAfterKill:[75031]`). "The children hung"
was the sampler's fault, not the node's.

## Reading the output

The sampler emits one CSV line per tick:

```
RESOLVE,enginePid=<pid>,resolveMs=<ms>
S,<tick>,<elapsedSec>,<commitBytes>,<availPhysBytes>,<procCount>,<enginePid>,<engineRss>,<enginePrivate>,<engineAlive>
ABORT_MEM_FLOOR,<availPhysBytes>
END,<elapsedSec>,<ticks>
```

`enginePid` is the `node.exe` serving `bin.js web --port 3099` — the engine the owner types into. **Its RSS
running *lower* under load is a real and repeatable observation** (`113`: 381 MiB under load against 488–493
at baseline), so do not assume the engine is where the memory goes.

## Before you trust a number

- Did the children **prove** where they ran, from their own hostname? `placement=CONFIRMED` is the only
  acceptable value; a child not confirmed on the node it was aimed at must not be counted.
- Was the window covered? `coverage=ALIVE_THROUGH_WINDOW_END` for every child.
- Is there an **A2** control, and is its drift smaller than the effect you are claiming?
- What is the **metric**? Windows commit charge, Linux `Committed_AS` and the macOS analog are three
  different quantities. Do not compare across platforms without saying so.
- Are the PIDs gone at **both** ends? `VERIFY_ALIVE=0` remote and `stillAliveAfterKill=0` local.

## Not yet built

There is no **per-node child cap** and nothing measures a node's sshd latency before more children are
added. Five children on one node pushed its sshd handshake to **8,041 ms** and cost a child its turn
(journal `P332`). Until that is fixed, **spread a fan-out across nodes deliberately** — the broker will
concentrate it on the biggest node, because that is what its ranking is for. Two children per node is the
number that has worked.
