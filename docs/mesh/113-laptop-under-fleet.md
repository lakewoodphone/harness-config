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

## The responsiveness measurement, taken the same day, and it is NEGATIVE

Built as a second probe on the same four conditions: every tick, before the memory sample, the cost of a
fixed pinned native operation — `Measure-Command { cmd.exe /c exit }` — was timed. It measures
**process-creation latency**, one facet of responsiveness, not UI frame latency. Its own baseline cost is
**p50 28.1 ms / p95 49.0 ms**, present identically in all four conditions, so A↔C is a fair comparison.

| condition | n | p50 ms | p95 ms | max ms | commit delta | proc delta |
|---|---|---|---|---|---|---|
| **A** baseline | 90 | 28.1 | 49.0 | 54.7 | 0 (23.606 GiB) | 0 (327.0) |
| **B** 3 children on the DESKTOP | 90 | 25.7 | 48.2 | 81.4 | −0.07 GiB | +0.9 |
| **C** 3 children on the LAPTOP | 90 | 25.7 | 42.1 | 66.4 | **+1.05 GiB** | **+25.2** |
| **A2** baseline again | 90 | 24.2 | 38.4 | 71.8 | +0.33 GiB | −1.7 |

**The A→A2 baseline drift is −3.9 ms (−13.9 %), and it is LARGER than any effect measured.** A→C is
−2.4 ms and A→B is the same −2.4 ms. The laptop also drifted *within* A (p50 25.2 ms over ticks 1–30,
31.5 ms over ticks 61–90) while A2 was flat. **So the honest answer is "not distinguished", not "no
effect": this probe cannot separate load from drift at N=3.**

What that means, stated carefully:
- **The memory result reproduces exactly** — C is +1.05 GiB commit and +25.2 processes against earlier
  measurements of +1.081 GiB and +25.9 — and condition C's process delta is precisely 3 children, so no
  foreign fleet contaminated the windows.
- **The speed result is null.** Three children on the laptop cost ~1.05 GiB and ~25 processes and produced
  **no measurable slowdown in process-spawn latency**. The load was three *memory-resident, sleeping*
  children — not CPU-spinning — on a 31.6 GiB machine with 15.2 GiB still free.
- **"Lagging" therefore remains unquantified for the case that would actually cause it**: a CPU-active
  load, or a fleet larger than the 3-child ceiling this workstream was bound to. A null result at N=3
  says nothing about N=30, and the next probe must raise N or make the children work rather than sleep.

**Consequence for `prefer-remote`:** it is justified on **memory and process count**, which are measured
and reproduced — ~1.05 GiB and ~25 processes returned to the machine the owner uses whenever an eligible
alternative exists — and **not** on a measured improvement in speed, which this work does not show.

## An instrument defect worth more than the null result

Driven from Windows PowerShell **5.1**, `Start-AgentFleet.ps1` declared
`COULD NOT ASK: ssh laptop-ts hostname` with an *empty* exit code on a **healthy** ssh — because 5.1
returns an empty `Process.ExitCode` for `Start-Process -PassThru` with redirected output, while PS 7
returns 0. **The instrument must be driven from PS 7.** The failure mode is exactly the class this
programme keeps finding: a blank read as a negative about the *far end*, when it was a property of the
*near end*. The tool's own header should say which shell drives it, and the workstream that used it was
right to say so in its report rather than quietly upgrade.
