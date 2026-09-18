# 113 — What a fleet actually does to the owner's laptop, measured

Produced 2026-09-18 by workstream E. Deliverable: the instrument this programme was missing, and the
first measured answer to *"when I use DSH it is speedy without any lagging … because it offloads
properly"*.

**Instruments (in this repo, runnable):**
- `scripts/mesh/Start-AgentFleet.ps1` — launches N headless agent turns aimed at a named node over the
  remote-ssh route and **proves where they ran from each child's own `MESH-HOST:` line**; samples an
  observed node at 1 Hz; kills exactly the PIDs it started and verifies they are gone.
- `scripts/mesh/Get-NodeSample.ps1` — the 1 Hz sampler, shipped to the observed node as an encoded command.

Both were taken from disk on ZABZ-TECH rather than from the child's pasted text, which contained a
transcription slip (`${walls}` for `${wall}`) on the final report line. Both parse with 0 errors.

## Why the instrument had to be built this way (four defects, each found by measurement)

| measured fact | evidence |
|---|---|
| Redirected ssh works; piped forms avoided entirely | `ssh laptop-ts hostname` → exit 0 in 1.46 s, stdout `zabz-yoga` |
| `-EncodedCommand` survives the cmd→ssh→PowerShell boundary | probe → `BIN_EXISTS=True`, `HOST=zabz-yoga` |
| **a headless turn prints ONLY its final assistant message** — a child killed mid-turn has empty stdout and can never prove placement | a smoke child produced `CHILD_PID=16048` and no `MESH-HOST:` at all |
| ssh session setup costs **2–25 s** and is variable, so a fixed-duration child dies before the sampling window opens | run C: `expected_host = 'zabz-yoga' (ssh exit=0, 11.72s)` |

So the driver waits until every child has printed `CHILD_PID=` — proving a live remote process exists —
and only then opens the sampling window, and it lets children **finish their own turn** before killing
them. All six children across conditions B and C ran `coverage=ALIVE_THROUGH_WINDOW_END`.

## The measurement

Four 60-second windows, **58 one-second samples each**, all on `laptop-ts` (`ZABZ-YOGA`).
`commitCharge = ullTotalPageFile − ullAvailPageFile` via `GlobalMemoryStatusEx`. Engine = the `node.exe`
serving `bin.js web --port 3099`, pid **20724**, `engineAlive=1` in every tick.

| condition | commit base | commit peak | commit mean | peak − base | procs base | procs peak | procs mean | procs mean − base | engine RSS mean | RSS peak − base |
|---|---|---|---|---|---|---|---|---|---|---|
| **A** baseline | 23.910 GiB | 24.893 | 23.741 | +1006 MiB | 333 | 334 | 327.2 | +1 | 493 MiB | +18 MiB |
| **B** fleet on DESKTOP | 23.670 GiB | 24.095 | 23.786 | +435 MiB | 327 | 336 | 329.5 | +9 | 460 MiB | +8 MiB |
| **C** fleet on LAPTOP | 25.071 GiB | 25.379 | 24.822 | +315 MiB | 351 | 361 | 353.1 | +10 | 381 MiB | +19 MiB |
| **A2** control after C | 23.657 GiB | 24.399 | 23.596 | +760 MiB | 323 | 332 | 324.5 | +9 | 488 MiB | +51 MiB |

Mean-of-window differences, with the second control that makes them interpretable:

- **A vs A2** — both fleet-free, five minutes apart — differ by **0.145 GiB** of commit and **2.7**
  processes. That is the ambient noise band; anything inside it is not a signal.
- **B − A**: commit **+0.046 GiB**, processes **+2.2**. **A fleet on the desktop is indistinguishable
  from an idle laptop by either measure.**
- **C − A**: commit **+1.081 GiB**, processes **+25.9**; **C − A2**: **+1.226 GiB**, **+28.6**.
- Process ranges **do not overlap**: A [324,334], B [325,336], **C [347,361]**. The process-count signal
  is the firmer of the two, because the laptop's own commit swung 1.32 GiB inside a single baseline window.
- **Per child**: (C−B)/3 = **354 MiB** commit, 7.9 processes; against both baselines the range is
  **≈369–418 MiB per child**, bracketing the quoted 403 MiB unit cost (CI 270–533).
- **The DSH engine did not grow under load** — RSS mean 381 MiB in C against 488–493 MiB at baseline.
- Available physical stayed at **15.24 GiB minimum** in C; the 4 GiB abort floor never armed.

**Placement was confirmed by the children's own hostnames, not the dispatcher's intent:**
`C child1/2/3 → MESH-HOST: zabz-yoga`, `B child1/2/3 → MESH-HOST: zabz-tech`, all
`placement=CONFIRMED coverage=ALIVE_THROUGH_WINDOW_END`.

**Cleanup verified, both ends:** remote `KILL,…,ALREADY_GONE` ×3 and `VERIFY_ALIVE=0`;
local `ssh PIDs started=… stillAliveAfterKill=0`; a post-hoc sweep of the laptop found exactly one
`node` process with `bin.js` — the pre-existing engine.

## What this means, and what it does not

**It means offloading works and is measurable.** Three children on the desktop cost the laptop nothing
distinguishable from idle; the same three on the laptop cost ~1.1 GiB of commit and ~26 processes. That
is precisely the difference `prefer-remote` (`docs/mesh/111` §6, journal W210) exists to move from C to B,
and it is now quantified rather than argued.

**It does NOT mean the laptop feels fast.** This instrument measures memory and process count. It took
**no** keystroke latency, no input-to-photon delay, no CPU time and no disk queue. So it can say what a
fleet *occupies* on the machine; it cannot say whether the owner *feels* it. **"The fleet does not make
ZABZ-YOGA feel slow" is not supported by this work** — and that, not memory, is the sentence the owner
actually used.

**Also not measured:** the children were resident and sleeping during the window, so this is a live
fleet's steady-state footprint, not its peak cost while thinking. The ~370–418 MiB per child rests on
cross-condition means from single 60 s windows per condition, not on repeated runs — the 403 MiB figure it
brackets came from five runs at each of K=0/2/4/6. Ambient load was not under the child's control (other
workstreams were running on the desktop throughout), which is exactly why the A2 control was needed.

**The next measurement, and it is the one that answers the owner:** a responsiveness probe on the laptop —
sample the cost of a fixed local operation (a shell round trip through the engine, or `Measure-Command` on
a pinned command) at 1 Hz through the same four conditions, and report its p50/p95 against condition A.
Until that exists, "lagging" remains unquantified, and the honest position is that offloading is proven
cheap while the *feeling* is not.
