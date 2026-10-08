# WINDOW-KILLER.md — what closes the owner's DSH windows on ZABZ-YOGA

Hunt run 2026-09-18, 00:27–00:51 local (UTC−04:00). Host ZABZ-YOGA. Engine pid **4416** on :3099
**never restarted**; no owner window was ever closed to test; every close in this document was either
the owner's, another agent's, or one I made on a window I started myself.

Everything below is measured on this machine. Where a fact comes from a file, the file is named;
where a number is a reading, the tool that took it is named. Where I could not determine something,
it says so in §8 instead of guessing.

---

## 1. VERDICT

**There is no scheduled task, daemon, agent loop, policy or script on this machine that closes windows
on a cadence. Nothing was disabled, because there was nothing to disable — and disabling a plausible
but innocent task would have removed a real protection while leaving the real cause in place.**

The two things that actually happened tonight, in order of evidence:

1. **A hand-invoked `WM_CLOSE` during the sibling multi-window stream's recovery test, 23:41–00:02.**
   `_scratch/mw-win.ps1` — created **23:41:21**, three minutes before the first missing-window event —
   implements precisely `SendMessageW(hwnd, 0x0010)` (`WM_CLOSE`) with `list` and `close <handle>`
   modes, and `_scratch/mw-wins-before.txt` (**23:41:26**) is the handle list of the owner's five
   windows taken immediately before it. Every `missing`/`reopen` pair in `health.log` (23:44:35,
   23:48:03, 23:48:19, 23:52:38, 23:52:54, 00:01:16) lies inside that 21-minute window and includes two
   **16-second** pairs that the 4 m 57 s task cannot produce. The deaths stop when that stream stops.
   The sibling's own handoff (`_scratch/mw-j-handoff2.md`) records *"ONE slot was closed by hand"* and
   asserts every close was `WM_CLOSE` on a handle it created. **This is the leading explanation, not a
   proven one** — see §8.
2. **The owner closing windows.** The only *coordinated* death anyone observed — three of his five
   legacy windows gone between 00:22 and 00:25 — has no process anywhere in the system to explain it,
   and **no code path in the launcher or its tasks can close a window at all** (§4). Both observers saw
   it; the sibling's own best guess was the owner, who was awake and working.

**And the launcher is not innocent of *looking* like a killer.** Two real defects (§7) manufacture the
symptom: a liveness test that cannot see a window handed off into an already-running profile, and a
registry prune that permanently *forgets* a window on a single transient false negative. Those two
produced the 229-open stampede and the "window that comes back, then dies again" pattern.

**Correction to the brief's central premise, with a measurement (§6A):** `exit_type = Normal` plus a
fresh `Last Browser` write is **not** evidence of a graceful close. Every live browser on this machine
right now — including the owner's, up for three hours — reports `exit_type = Crashed`, `Last Browser`
is written at *startup* (+3 s after launch), and `Preferences` is rewritten periodically during a run.
A forced kill (`Stop-Process -Force`) I performed on my own window produced **no** Application event,
**no** Defender event, and left `Preferences` byte-identical. None of the markers the hunt relied on
can distinguish a graceful close from a hard kill.

---

## 2. WHAT I DISABLED

**Nothing.** No task was stopped, disabled, unregistered or edited; no scheduled-task action was
changed; no process table entry outside my own experiments was touched; the engine was not restarted.

The brief's instruction was explicit: *"if you cannot identify it with evidence, do not disable things
speculatively — a wrong disable leaves the killer running and removes a real protection."* The
strongest-looking candidate (`mesh-hygiene.ps1:824 CloseMainWindow()`) is **already unreachable** (§4.2)
and disabling it would have been a no-op that destroyed a legitimate reclaim tool's only switch.

---

## 3. TIMESTAMP CORRELATION TABLE

Local time, EDT. "Source" is where the reading came from; nothing here is inferred without a file.

| Time | Event | Source |
|---|---|---|
| 21:39:30 | Engine pid **4416** starts on :3099 — the engine that is still serving the owner | `Win32_Process.CreationDate`; `/healthz identity.startedAt` 01:39:30Z |
| 21:39:56 | Owner window **23492** opens (origin 3099, profile `w4`) | process table; `mw-wins-before.txt` |
| 21:43:00 | Owner window **9852** opens (origin 3099, profile `w1`) | process table; `mw-wins-before.txt` |
| 23:11:48 | Origins proxy restarts; bursts of `LISTEN FAILED EADDRINUSE` on 3200+ | `~/.dsh/multi-window/logs/origins.log` |
| 23:13:29.87, 23:13:52.99 | Shared-profile windows opened on 3200, 3201 (slots 1, 2) | `windows.log` (their `--user-data-dir` is `_shared`) |
| 23:21:28.57, 23:21:59.27 | Again (slots 1, 2) — the "unexplained pair" | `windows.log` |
| **23:41:21.82** | **`_scratch/mw-win.ps1` created — `SendMessageW(hwnd, 0x0010)` = `WM_CLOSE`, modes `list` / `close <handle>`** | file `CreationTime` |
| **23:41:26** | **`mw-wins-before.txt` — the five owner window handles captured (9852, 23492, 25832, 31256, 29520)** | file mtime |
| 23:43:06.96 | Slot-2 window opened on 3201 | `windows.log` |
| 23:44:34.65 | Slot-1 window opened on 3200 by `Invoke-WindowRecovery` | `windows.log`; `health.log` 23:44:35 `missing=1 opened=1` |
| **23:48:03.45** | Recovery finds slot 1 **already gone — 3 m 29 s after it opened** — and opens slot 2 | `health.log` 23:48:03 `missing=2 opened=1 (2) held=1 - main` |
| 23:48:19.58 | Second recovery run **16 s later** (impossible for the 4 m 57 s task ⇒ a hand run) | `health.log` |
| 23:52:38.80, 23:52:54.24 | Another 16-second pair; both slots held by the 600 s cooldown | `health.log` |
| 23:59:31 | `_scratch/run-open.cmd` written (`dshw.ps1 open -Slot 3`) | file mtime |
| 00:00:50.20 | Slot-3 window opened on 3202 by that hand run | `windows.log` |
| 00:01:16.40 / .79 | Recovery opens slots 1 and 2 together (`missing=2 opened=2`) | `windows.log`; `health.log` |
| 00:01:16.390 | `_shared` **`Last Version`** written — a browser *starting* (see §6A) | profile file mtime |
| 00:01:22.683 | `_shared` **`Last Browser`** written — also a startup write | profile file mtime |
| 00:01:30.31 | `_shared` `Preferences` + `Local State` written (periodic writes; `exit_type=Normal` at rest) | profile file mtime |
| **00:01:59.28** | **`windows-registry.json` rewritten — `Invoke-Restore`'s prune sets rows `1 - main` and `2` to `open:false` ⇒ the reopen loop ENDS here** | file mtime + the prune's own write shape (`dshw.ps1:1528-1536` writes `false` + origin port) |
| 00:11:54 → 00:47:15 | `DSH Window Fleet Watchdog` fires **9 consecutive times**: `registry-open-and-missing 0; reopened 0` | `logs/health-20260918.log` transcripts |
| 00:22:15 | Watchdog: `live origins [3099]` ⇒ **every** shared-profile window (00:00:50, 00:01:16 ×2) was gone by now | transcript |
| 00:22–00:25 | **Three of the owner's five legacy windows gone** (25832, 31256, 29520). No closing code path exists; no task fired | both observers; current process/handle truth |
| 00:30:01, 00:40:01, 00:50:01 | `DSH Process Reaper` ticks — `killed=0`, every one | `%LOCALAPPDATA%\dsh-reaper\reap.log` |
| 00:33:30–00:51:33 | **My bilateral watch: 18.1 min wall clock, 192 samples at 5 s** (owner's 2 windows + 2 of mine) | `%TEMP%\wk-experiment.log` |
| 00:38:11 | Positive control: I hard-killed **my own** window — detected in one 5 s sample; no OS record of any kind | `%TEMP%\wk-experiment.log` |
| 00:38:24–00:48:09 | **Race reproduction: 9.3 min, three windows in the launcher's exact pattern into one fresh profile — ZERO deaths** | `%TEMP%\wk-race.log` |
| 00:50:45 | Owner windows 9852 (since 21:43:00) and 23492 (since 21:39:56) still alive; engine 4416 uptime 3 h 11 m | process table |

---

## 4. RULED OUT, WITH THE METHOD FOR EACH

### 4.1 `DSH Process Reaper` — the 10-minute task — **innocent**
Action (from `scripts/hidden-tasks/DSH_Process_Reaper.vbs`): `pwsh … scripts\dsh-reap.ps1 -Apply -Quiet
-MinAgeMinutes 30`.

Read in full (180 lines). It targets only processes whose **name** matches `^(node|cmd|conhost|pwsh|powershell)\.exe$`
**and** whose command line matches the harness patterns (`dsh-reap.ps1:70-72`). Its header states, and
the code confirms, that it never touches *"any browser (msedge, chrome, msedgewebview2)"*
(`dsh-reap.ps1:21-25`). It kills with `taskkill /PID … /T /F` (`:173`) — a hard kill, not a graceful
close.

Its own log (`%LOCALAPPDATA%\dsh-reaper\reap.log`) — 19 consecutive ticks 21:10:02 → 00:20:01, plus
00:30:01, 00:40:01, 00:50:01 — every single line `orphans=0 staleMcp=0 … killed=0`. **It has never
killed anything in this window, including every tick that spans a death.**

### 4.2 `mesh-hygiene.ps1` — the only graceful closer in the repository — **not running, and cannot produce the observed asymmetry**
`scripts/mesh-hygiene.ps1:824` calls `[void]$p.CloseMainWindow()` — the graceful rung of its reclaim
ladder — and its class-A target list **does** match Edge: `Get-DefaultTargets` includes
`Join-Path $pf86 'Microsoft\Edge\Application\'` (`:160-168`). On 2026-09-17 its own record shows it
matching **29 Edge processes** as class A. So it *can* close windows — which is exactly why it had to be
settled rather than assumed.

It is exonerated four ways:
1. **It never ran.** Its record (`~/.dsh-sync-status/mesh-hygiene.log` / `.jsonl`) has **no entry after
   `2026-09-17T04:28:33Z` — about 20 hours before the deaths.** The only `mode=reclaim` runs ever
   recorded are 03:57:18Z and 03:57:36Z on 9/17, both hand-invoked with `idle_required_s=0` (which
   bypasses the console-idle gate — a task could not pass that).
2. **Nothing invokes it with `-Reclaim`.** No scheduled task exists for it (verified against every
   registered task's actions). A repo-wide grep for `-Reclaim` finds only header-comment examples
   (`:68`, `:72`, `:79` and `docs/mesh/85-hygiene.md`). All 34 standing work orders on the authority
   contain no reference to it. Its own `-Reclaim` gates (console idle ≥1800 s, no dispatch in flight,
   no unexpired governor lease) plus the fact that nobody calls it with the switch mean the kill path is
   **unreachable**, not merely unfired.
3. **Its selector is a path prefix, not an origin** — so it cannot produce the disciminator the parent
   asked me to use. It matches *every* `msedge.exe` under the Edge application directory, which would
   take the owner's legacy 3099 windows at the same instant as any shared-profile window. The observed
   pattern is the opposite: shared-profile windows died while the legacy ones held for hours.
4. Its `-Reclaim` mode also force-kills as its second rung (`:837`, `:845`), so even a "graceful"
   attribution would not have distinguished it from any other kill (§6A).

**Standing hazard, stated for the record:** if anyone ever schedules
`mesh-hygiene.ps1 -Reclaim`, its first rung will `CloseMainWindow()` **every browser on this machine by
executable path**. It should not be scheduled on the owner's workstation.

### 4.3 `DSH Mesh Restart When Idle` — the 15-minute task — **innocent**
Wrapper → `scripts/mesh-restart-when-idle.ps1`. Its decisions log
(`~/.dsh/mesh/restart-when-idle/decisions.log`) shows **every tick since 01:29Z is `DEFERRED`** ("the
owner is working", 2–19 running sessions) or `NO-EVIDENCE`; only three stamp directories exist, all
from 2026-09-17 morning. It restarts the *engine* at most, and it did not: engine 4416 has been up
since 21:39:30. It contains no window code.

### 4.4 `DSH Engine Watchdog (1m)` — **innocent**
→ `dshw.ps1 ensure` → `Invoke-Ensure`. It returns immediately when `Test-EngineAlive` answers
(`dshw.ps1:1835-1838`), which it did all night; the engine was never wedged. `Ensure-Engine` is
reachable only on two patient-probe failures and never fired. No window code on this path.

### 4.5 `DSH Window Fleet Watchdog` (PT5M) → `dshw health` — **opens windows, never closes one**
This is the only component that opens windows (`Invoke-WindowRecovery`, `dshw.ps1:2330`, at most 2 per
run with a 600 s per-slot cooldown and four other guards). A grep of `dshw.ps1` for
`CloseMainWindow|Stop-Process|taskkill|Close(` returns **no browser-closing call**; the only
`Stop-Process` is inside `Stop-ServerTree` (`:589-590`), which targets the *engine's own tree* and never
fired (the engine and all five of its 21:40:25 MCP bridges are still alive). `Invoke-Down` says it in
its own words: *"Browser windows are closed by you, or by closing them"* (`:1334`).

Its own transcript goes further than I can: **9 consecutive runs from 00:11:54 to 00:47:15, every one
`registry-open-and-missing 0; reopened 0`.** A component that is not opening windows is not replacing
casualties, and a component with no close call is not the closer.

### 4.6 Every other scheduled task's action script — **innocent**
Each `.vbs` in `scripts/hidden-tasks/` was read and mapped to the command it really runs. The only
process-ending code reachable from **any** registered task is `dsh-reap.ps1` (§4.1):

| Task | Really runs | Ends processes? |
|---|---|---|
| DSH Process Reaper (10 m) | `dsh-reap.ps1 -Apply -Quiet -MinAgeMinutes 30` | `taskkill /F`, node/cmd/conhost/pwsh only — killed 0 every tick |
| DSH Window Fleet Watchdog (5 m) | `dshw.ps1 health` | No close call exists |
| DSH Engine Watchdog (1 m) | `dshw.ps1 ensure` | No |
| DSH Multi-Window Launcher (logon) | `dshw.ps1 up -WindowsMode no` | No — `no` matches neither the `restore` nor the `yes/auto` branch, so it does not touch windows *or* the registry |
| DSH Phone Gate (5 m) | `scripts/phone-gate-ensure.ps1` | No (`Stop-Process` absent from it) |
| DSH Metrics Sampler (+Watchdog) | `scripts/harness-metrics.ps1` | No — it only *counts* `msedge` (`:185`) |
| DSH Mesh Restart When Idle (15 m) | `mesh-restart-when-idle.ps1` | Engine only, and it deferred every tick |
| DSH Mesh 0700 Restart (daily) | `mesh-restart-at-0700.ps1` | `dshw restart` — engine only; last run 07:00, result 1 |
| PersonalSecretary-HarnessSync (15 m) | `scripts/autosync.ps1` | No |
| PersonalSecretary-PushDSHSessions (1 h) | `scripts/push-dsh-sessions.mjs` | No |
| PersonalSecretary-PushVSCodeChats (1 h) | `push_vscode_chats.py` | No |
| PersonalSecretary-NodeAgent (1 h) | `scripts/mesh/node-agent.py` | No |
| DSH unified-search refresh (30 m) | `.usearch\bin\usearch-refresh.cmd` → `unified-search/scripts/sync.py` | No — its `p.kill()` calls target **its own** adapter subprocesses on timeout (`sync.py:321-415`) |
| LPT-* | backup / analysis scripts | No |

A second sweep over the **non-PowerShell** surface (`*.mjs,*.js,*.py,*.cmd,*.sh`) — because the first
grep only covered `.ps1` — found only self-targeted kills: `dshw-proxy.mjs:151`
`process.kill(pid, 0)` is a **liveness probe on its own pidfile**, not a kill;
`packages/plugin-remote-fanout/lib/ssh-transport.js:73` kills its own ssh child;
`question-card-*.py`, `phone-layout-check.py` terminate the headless Chrome *they* started;
`docs/dsh-at-scale/lock_stress.py:79` kills its own stress children.

### 4.7 Edge / enterprise policy (MDM) — **ruled out by the registry**
`HKLM\SOFTWARE\Policies\Microsoft\Edge` contains exactly one value: `QuicAllowed = 0`. There is no
`RelaunchNotification`, `RelaunchNotificationPeriod`, `BackgroundModeEnabled`, `StartupBoostEnabled`,
`SleepingTabsEnabled`, `RestoreOnStartup`, `ForceEphemeralProfiles` or `BrowserSignin` anywhere under
`HKLM\…\Policies` or `HKCU\…\Policies`, and no `EdgeUpdate` policy key. A **forced Edge relaunch**
(`RelaunchNotification=2`, which politely closes and reopens browsers and would look exactly like the
reported symptom) is the classic policy cause — **it is not configured here.** MDM enrollment keys
exist but carry no Edge policy.

### 4.8 Defender — **ruled out**
`AMRunningMode = Normal`, `RealTimeProtectionEnabled = True`. The Defender Operational log for the last
6 hours holds only client health reports (1150/1151), cloud-protection lookups (2010) and
configuration-change notices (5007) — **no detection, no remediation, nothing naming msedge.** And a
remediation would be a hard kill, which §6A shows is anyway indistinguishable.

### 4.9 Non-DSH scheduled tasks near the deaths — **ruled out**
The only non-DSH tasks that ran in 00:00–00:35 are OS/consumer noise: `Consolidator` 00:00:01,
`UsageAndQualityInsights-MaintenanceTask` 00:00:01, `LiveWallpaperDailyScheduleTask` 00:00:01,
`VerifiedPublisherCertStoreCheck` 00:00:18, `DmClientOnScenarioDownload` 00:11:13, `QueueReporting`
00:12:08, `RefreshCache` 00:12:10, `GoogleUpdaterTaskSystem` 00:14:20, `UsageDataReceiver` 00:22:05,
`GenericMessagingAddin_Pulsation` 00:32:00, `Quick Share Relaunch` 00:32:39,
`SoftLandingDeferralTask` 00:33:01. None has a 3–5 minute cadence; none is a window closer.
`MicrosoftEdgeUpdateTaskMachineUA` ran at 23:43:26 and 00:43:25 (hourly) — it appeared in the Edge
policy audit and is not a closer, but it is the one non-DSH task within ±5 min of a death, and §6A
means I cannot fully clear it from the file trace alone; it has no close mechanism and no
update-apply/close event in the Application log.

### 4.10 The browser's own evidence — **and why it cannot attribute a close**
- `%LOCALAPPDATA%\Microsoft\Edge\User Data\_shared\` **does not exist**; the launcher's shared profile
  is `~/.dsh/multi-window/browser/_shared` (the brief's path was the wrong one).
- **No `chrome_debug.log`** anywhere under the launcher's browser root.
- The Application log holds only **9** Edge/Chrome events in 75 minutes; the only `Edge` line is the
  `--no-startup-window` background process (pid 4272). **App windows do not log to the event log.**
- **Windows process-creation auditing is OFF** (`auditpol`: *Process Creation = No Auditing*; zero
  `4688` events in 30 minutes) and there is no Sysmon. A `WM_CLOSE` from another process therefore
  leaves **no trace anywhere** — which is why §8 exists.

---

## 5. THE SEPARATING EXPERIMENTS I RAN

Both used windows I started myself, on profiles of my own under `%TEMP%`. The owner's windows were never
touched, and the engine was never restarted.

### 5.1 Bilateral watch + positive control — `%TEMP%\wk-experiment.log`
16.2 minutes of samples — 00:33:30 → 00:51:33 wall clock, 192 samples at a nominal 5-second cadence,
watching every `msedge.exe` root app window (pid, origin, profile). I also armed a WMI
`Win32_ProcessStartTrace` subscription for the whole window, intending to attribute any process that
started within seconds of a death by name, pid, parent and command line.

Subjects: the owner's two legacy windows (23492, 9852) and my own **A** (proxy origin 3200, own
profile) and **B** (engine origin 3099, own profile).

Result: **the owner's two windows and my A window survived every sample across the whole window
(00:33:30 → 00:51:33).** Three deaths
appear in the record and **all three are mine**: the positive control at 00:38:11 (window B, §6A) and my
own cleanups at 00:50:10 (window A and the race profile's root). The watcher caught each within one
5 s sample, which validates the *liveness* half of the instrument.

**THE PROCESS-START TRACE DELIVERED NOTHING, AND THAT IS AN INSTRUMENT FAILURE, NOT EVIDENCE.** It
recorded **zero** events across 16 minutes on a machine where `pwsh.exe` demonstrably starts every
minute (`DSH Engine Watchdog`, `DSH Window Fleet Watchdog`) — which is impossible if it were working. I
validated the identical subscription in the foreground immediately afterwards: **30 events in 40
seconds** (netsh, node, pwsh, conhost, with parents), while an independent snapshot found 3 pwsh/node/cmd
starts in the same 45-second span. So the subscription simply does not deliver inside a background-job
runspace, and **I must not claim "no process started at any death"** — that reading is a refusal, not a
negative. What *does* bear on external action is a direct full enumeration I took mid-watch (00:37:40)
of every `pwsh|node|cmd|wscript|taskkill` process started in the preceding five minutes: only DSH
tool-call runners and an unrelated calibration rig, none of which touches windows. The load-bearing
negative is therefore the absence of any **death** to explain, and §4's independent exclusions — not a
silent trace.

### 5.2 Shared-profile launch-race reproduction — `%TEMP%\wk-race.log`
The obvious mechanical suspect for "a shared-profile window is gone within 3–5 minutes" was Edge's own
singleton/startup behaviour when a second process launches into a profile an existing browser already
owns. So I reproduced the launcher's **exact** pattern on a fresh profile of my own, at the exact
spacings seen in `windows.log`:

- `T+0` — origin 3202 (mimics the hand-opened slot-3 window at 00:00:50)
- `T+26.0` — origin 3200 (mimics 00:01:16.397)
- `T+26.4` — origin 3201 (mimics 00:01:16.787)

Result after **9.3 minutes** (00:38:24 → 00:48:09), 3-second cadence: **no window ever disappeared.**
Zero `RACE WINDOW GONE` lines; heartbeat steady at 1 visible origin-process, 51–52 msedge processes;
final `exit_type=Crashed` **while the browser was still alive**.

**Conclusion: the launch pattern does not kill windows.** The deaths were not an Edge-internal race.

### 5.3 What the watchdog saw while my windows were up
At 00:37:15 it reported `live origins [3099,3200]`, and at 00:42:15 `live origins [3099,3200,3201,3202]`
— i.e. it saw all three of my proxy-origin windows even though only **one** process carried an origin
(§6C). This proves the union's proxy leg works, and therefore that the earlier `missing=N` readings were
genuine absences rather than pure detection failure.

---

## 6. CORRECTIONS TO THE INCOMING EVIDENCE

### 6A. `exit_type = Normal` + a clean `Last Browser` write does **not** mean "closed gracefully"
Measured, right now, at 00:37:48:

| Browser | Alive since | `Default\Preferences` mtime | `exit_type` |
|---|---|---|---|
| owner 23492 (w4) | 21:39:56 | 00:12:54 | **Crashed** |
| owner 9852 (w1) | 21:43:00 | 00:33:41 | **Crashed** |
| my wk-a | 00:33:31 | 00:34:32 | **Crashed** |
| my wk-b | 00:33:56 | 00:35:06 | **Crashed** |

All four windows were alive and none had crashed. So `Crashed` is what these profiles carry **at rest**,
and `Preferences` is rewritten **during** a run (w1's at 00:33:41, after 2 h 50 m of life) — meaning the
value an investigator reads is whatever the browser last wrote, not a verdict on how it died.

`Last Browser` and `Last Version` are **startup** writes, measured: launch 00:33:31.036 → `Last Version`
00:33:31.411 → `Last Browser` 00:33:34.172; launch 21:39:56 → `Last Browser` 21:40:28; and in 5.2,
launch +0.24 s and +3.0 s. Therefore the `_shared` trace (`Last Version` 00:01:16.390,
`Last Browser` 00:01:22.683) records a browser **coming up**, not going down. My earlier reading of it as
"a clean shutdown 6 s after the opens" was **wrong**, and I am recording the error rather than the tidy
version.

**Positive control (`Stop-Process -Force` on my own live window B, pid 35928, 00:38:11):** no
Application-log event, no Defender event, `Preferences` mtime and `exit_type` **byte-identical** before
and after. A hard kill leaves `exit_type=Normal` untouched if that is what was there.

**Consequence:** every candidate that kills a browser — `taskkill /F`, `Stop-Process -Force`,
`TerminateProcess`, `CloseMainWindow()` — is compatible with the entire evidence set the hunt started
from. The "no Crashpad dump, no Application-error event, graceful" triple has **no discriminating power
here**; the exclusion of each candidate must rest on its own logs, cadence and reachability, which is
what §4 does.

### 6B. **pid 9852 never closed.** The three that died are 25832, 31256, 29520.
`mw-wins-before.txt` (23:41:26) lists the owner's five windows: **9852, 23492, 25832, 31256, 29520**.
Now only **23492** and **9852** exist, both with their original creation times (21:39:56, 21:43:00) and
both owning visible top-level windows. A process cannot die and return with the same pid *and* the same
creation time. So the vanished three are **25832, 31256, 29520**; the brief's list named 9852 in place
of 25832. This is the same measurement error the hunt is about — a liveness reading believed without a
second source — and it is worth knowing that the stream that produced the evidence was itself reading
windows unreliably.

### 6C. The liveness union still has a hole, measured twice
`Get-OpenOriginPorts` unions (A) the proxy's per-port live-connection count with (B/C) a process scan
keyed on `--app=http://127.0.0.1:<port>`. But **only the window that created a profile's browser process
carries that origin in a live command line** — every later window is handed off. Measured:
- my **C** window (origin 3099, profile `wk-a`, launched 00:34:21) never appeared as an origin-carrying
  process; only **A** (origin 3200, the profile's first window) did;
- in 5.2, **R2** (3200) and **R3** (3201) never appeared; only **R1** (3202) did.

So for every proxy origin except the profile's first, **leg A is load-bearing**, and a live window whose
page is not currently connected is invisible to both legs. That is the residual false-negative class —
and it is what makes §7B destructive.

---

## 7. THE TWO DEFECTS THAT MAKE THE LAUNCHER LOOK LIKE A KILLER

### 7A. `Invoke-Restore`'s prune forgets a window on a single false negative
`dshw.ps1:1526-1536` marks a recorded-open window **closed** whenever `Get-WindowCount` says it is not
live. By §6C a transient miss (proxy restarting, page still connecting, handoff not yet visible) is
enough. That is precisely what happened at **00:01:59**: a `restore`-path run pruned rows `1 - main` and
`2` to `open:false` — the only two rows in the file that carried their slot's current origin port, which
is the prune's write shape — and with `open:false` in place, `Invoke-WindowRecovery`'s guard 1 short-
circuits forever. **The reopen loop ended because the registry was pruned, not because the deaths
stopped.**

### 7B. `Sync-WindowRegistry` is dead code
`dshw.ps1:1470` defines a proper reconciler ("a slot recorded as open whose window is gone was closed by
the owner") — and **nothing calls it.** The only reconciliation in the live system is 7A's prune, which
is the destructive one. This is exactly the parent's point 4: a path that can never run. Either call it
or delete it; as written, the safe reconciler is decoration and the unsafe one is the only one wired up.

---

## 8. WHAT I COULD NOT DETERMINE

1. **Who sent each individual close between 23:44 and 00:01.** Windows process-creation auditing is
   off, there is no Sysmon, and a `WM_CLOSE` leaves no OS record — I proved that a close and a force-kill
   are indistinguishable from the file evidence (§6A). `_scratch/mw-win.ps1` exists (23:41:21), the
   owner's handles were listed (23:41:26), the events cluster inside that stream's active window and stop
   with it, and the sibling's handoff admits one hand close — that is the ranking, and it is **not** a
   per-event proof. The one honest way to settle it was closed before I arrived.
2. **Whether the owner or that stream closed the three legacy windows at 00:22–00:25.** No process
   anywhere explains it; no launcher path can close a window; both accounts name the same three. Beyond
   "a human did it", I cannot separate them.
3. **Whether the `_shared` browser shut down at all** at 00:01:22–00:01:30, since the files the earlier
   stream read as shutdown evidence are startup and periodic writes (§6A).
4. **What `run-open.cmd` and the 16-second hand runs did between 23:48 and 00:02** — the commands
   themselves are not logged anywhere; only their effects on `windows.log`, `health.log` and the
   registry survive.
5. **Whether any short-lived process acted on a window during my watch.** My `Win32_ProcessStartTrace`
   subscription captured nothing inside the background job even though the same subscription captured
   30 events in 40 s in the foreground (§5.1) — so that instrument failed and its silence proves
   nothing. Direct snapshots found no window-touching process, but a snapshot can miss a sub-second
   actor, and I am not going to dress that up as a clean negative.

An unidentified killer with a precise ruled-out list is a useful result; a guess that disables the wrong
task is not. **§4 is the ruled-out list, §5.2 is the experiment that separated the last mechanical
candidate, and §1 is what remains.**

---

## 9. THE OBSERVATION WINDOW (the "holding steady" proof)

| Cadence | Verdict over the window | Evidence |
|---|---|---|
| **10 min** (`DSH Process Reaper`) | **five consecutive cycles, `killed=0` each** — 00:00:03, 00:10:01, 00:20:01, 00:30:01, 00:40:01, 00:50:01; and 19 more back to 21:10:02 | `reap.log` |
| **5 min** (`DSH Window Fleet Watchdog`) | **9 consecutive runs, `registry-open-and-missing 0; reopened 0`** — 00:11:54, 00:12:15, 00:17:15, 00:22:15, 00:27:15, 00:32:15, 00:37:15, 00:42:15, 00:47:15 | `health-20260918.log` |
| **1 min** (`DSH Engine Watchdog`) | engine 4416 answering throughout; never restarted (uptime 3 h 11 m at 00:50:45) | `Win32_Process`; `/healthz` |
| **one of mine, ~5 s, 18.1 min (192 samples)** | owner's 9852 + 23492 alive at **every** sample; the only deaths in the record are the three I made myself | `wk-experiment.log` |
| **one of mine, 3 s, 9.3 min** | 3 windows in the launcher's exact pattern: **no death** | `wk-race.log` |

That is more than two cycles of every cadence that exists, plus a validated instrument (my control death
was detected within one sample). **The window count held steady.**

---

## 10. WHAT I CHANGED

1. **`docs/multi-window/WINDOW-KILLER.md`** — this file.
2. **`~/.dsh/multi-window/windows-registry.json`** — **12 stale rows closed** (keys `3,4,5,6,7,8,9,10,
   11,12,13 - auto,14 - auto`), which is the reconciliation the parent stream explicitly instructed.
   - **14 rows kept. Nothing deleted.**
   - How each was proved dead, per row: its recorded port is `3099`, its slot's *current* origin is
     `3202…3213` (origins map 3200+ in `windows.json` order), so `Invoke-WindowRecovery`'s **guard 2 can
     never match it**, and at reconcile time the only live origin on the machine was `3099` (held by the
     owner's two windows) — its slot origin held **no** window. Verified with the live process scan
     after my own windows were closed, so the check ran against a clean set.
   - Rows `1 - main` and `2` were already `open:false` (pruned at 00:01:59) and were left as they were.
   - The original `at` timestamp is preserved per row as `wasOpenAt`; a `why` field records the rule.
   - **Consequence, stated plainly:** the remembered set is now empty, so a future `dshw restore` opens
     one window rather than twelve. That is strictly better than the 12-window storm a stale registry
     would have produced, and it is the truthful state — the owner's actual working set is the two
     legacy 3099 windows, which the launcher's slot model cannot represent at all.
   - Backup: `%TEMP%\windows-registry.backup-20260918-005023.json`.
3. Instrument logs of my own, under `%TEMP%`: `wk-experiment.log`, `wk-race.log`. My four test windows
   were opened by me and closed by me. The owner's two windows were never touched; the engine was never
   restarted; no task, gate, broker, journal entry or git state was altered.

---

## 11. FOR THE NEXT SESSION

1. **The logon-restore question is unblocked on the "killer" half**: nothing on this machine closes
   windows on a cadence (§4, §5.2, §9). The remaining reason to hold it is the registry/representation
   problem, not a killer.
2. **Do not schedule `mesh-hygiene.ps1 -Reclaim` on this workstation** (§4.2) — its first rung closes
   every browser by path.
3. **Fix the prune before trusting the registry as evidence** (§7A): require negative evidence from two
   independent legs before marking a window closed, and consider whether a *live-but-disconnected*
   window should ever be forgotten by a background task.
4. **Wire up or delete `Sync-WindowRegistry`** (§7B) — the safe reconciler is currently dead code while
   the unsafe one runs inside `restore`.
5. **If attribution is ever needed again, turn on process-creation auditing** (`auditpol /set
   /subcategory:"Process Creation" /success:enable` plus `4688` with a command line) **before** the
   incident. Without it, "who closed this window" is unanswerable on this machine, and that cost this
   hunt its conclusion.

---

## 12. THE THREE FIXES TO THE LAUNCHER, AND A HAZARD WORTH WRITING DOWN

Written 2026-09-18, 01:00–01:35 local (UTC−04:00), by a second stream on the same machine, after the
hunt above. Engine pid **4416** on :3099 **was never restarted**; **no window of the owner's was opened
or closed**; every experiment ran against a throwaway config, state dir, registry and profileRoot under
`%TEMP%`, so the owner's own registry was never written to by any test
(`windows-registry.json` sha256 `9F43EF78…6F12FB` before and after every run in this section).

Files changed: `multi-window/dshw.ps1` and this document — plus **one generated artefact** the launcher
rewrites for itself (§12.3), which is how `autostart` has always worked.

### 12.1 FIX 1 — the prune no longer forgets a window on one negative reading

The inline prune in `Invoke-Restore` (the one that set rows `1 - main` and `2` to `open:false` at
00:01:59) is **deleted**. The rule now lives in `Sync-WindowRegistry` (`dshw.ps1:1570-1670`) and has two
arms, each requiring the evidence it actually needs:

| Arm | Evidence required | Recorded as |
|---|---|---|
| `rule=port-mismatch` | **no liveness reading at all**: the row's recorded port is not this slot's current origin, so no window the launcher can open can ever match it again | `closedBy: reconcile` — a rule, not a guess |
| `rule=two-confirmed-negatives` | two readings of the same slot **at least `$WindowPruneConfirmSeconds` (15 s, `dshw.ps1:1470`) apart**, the second taken with **every memo dropped**, and the origins proxy answering at both | `closedBy: prune` — an inference, and the row says so |

Three things about that are load-bearing and were measured, not assumed:

1. **The second reading had to be made possible before it could be required.** `Get-OpenOriginPorts`
   memoised its answer, so a "two consecutive negatives" rule built on it would have read *one*
   measurement twice — the 00:01:59 bug wearing the costume of a safeguard. The legs are now a
   separate function (`Get-OriginLiveLegs`, `dshw.ps1:1918-1983`) with a `-Fresh` switch that drops all
   four memos. Verified in the probe: two plain calls return the **same** object; `-Fresh` returns a
   **new** measurement.
2. **A negative from a leg that did not answer is not a negative.** With origins enabled the proxy leg
   is load-bearing (§6C: only a profile's *first* window carries `--app=<origin>`), so if the proxy is
   not answering, **nothing is closed at all** and the row is reported as `unconfirmed`. That is also
   the state the machine was in at 23:11:48 on the night of the hunt.
3. **A row this run just opened is never a candidate** (`-Skip`). "It has not connected in the
   milliseconds since we launched it" is not evidence that it is not there.

**Provenance, which is FIX 1's second half.** Every closure now carries `closedBy`, `closedAt`,
`evidence`, `confirmations`, and the `at` of the state being replaced kept as `wasOpenAt`. The
vocabulary is fixed and written into the code: `prune` = this launcher's inference, `reconcile` = a
person or agent proved it dead by a stronger rule and said so in `why`, `owner` = a deliberate close
(**nothing in the script can infer this**), `unknown` = written before the field existed. A census of
that field is printed by `health` and by `plan`, so a reader can now tell a wrong guess from a decision
— and the live registry reads **12 recorded as a decision, 2 unattributed** (the two 00:01:59 rows,
whose provenance is unrecoverable and is now *counted as unrecoverable* rather than indistinguishable
from a decision). Writes also **merge** now: the old `Set-WindowRegistryEntry` rebuilt each entry from
scratch, so the hand-written `why` / `reconciledBy` / `wasOpenAt` the reconcile above wrote would have
been destroyed the next time the launcher touched that row.

Measured, on a throwaway registry (`%TEMP%\mw-reconcile-probe.ps1`, real functions, stubbed liveness
only):

- port mismatch → `closedBy=reconcile`, `evidence=rule=port-mismatch; recorded=3099; slot-origin=3202;
  no liveness reading was used`, hand-written `why` and `wasOpenAt` **kept**;
- two negatives → `closedBy=prune`, `confirmations=2`, `evidence=rule=two-confirmed-negatives;
  confirmations=2; interval=2s; r1=…; r2=…; legA(proxy)=no/no; legB(procscan)=no/no; proxyAnswered=yes`;
- **the sparing rule**: a row the second reading found live was **spared**, `closed=0`, the row left
  `open:true` — i.e. the single reading that would have forgotten it was survived;
- **the proxy gate**: `closed=0, unconfirmed=1`, the row untouched;
- **the merge**: a hand-written `why` and `wasOpenAt` survived a reopen, with the closure fields cleared.

### 12.2 FIX 2 — the safe reconciler is wired in; the unsafe inline one is gone

**Decision: wire it in, and delete the inline duplicate.** Deleting `Sync-WindowRegistry` instead would
have removed the last safe path and left only the one that mis-fired at 00:01:59 — and a safety
mechanism nothing calls is the failure class this estate keeps producing. It now has **two callers**:
`Invoke-Restore` (`dshw.ps1:1762`) and `Invoke-Health` (`dshw.ps1:2825`).

The two callers carry different jobs, and that division is deliberate rather than accidental:

- **`restore`** passes `-Skip` for every remembered row it just touched, which is exactly the class the
  confirmed-negative arm could ever act on. So in `restore` that arm has **no candidates by
  construction**, and what `restore` contributes is `rule=port-mismatch` — the twelve rows the hunt had
  to close **by hand** are now closed by code, with no reading and therefore no false negative possible.
- **`health`** runs every five minutes over a machine in steady state, where "it was there last tick
  and it is not there now" is a statement a liveness test can honestly make. This is where the
  confirmed-negative rule belongs, and it runs **before** `Invoke-WindowRecovery` so that guard 1 stops
  treating a window the owner closed as a reopen candidate, while recovery running after means the
  reconciler never sees a window it just had us open.

`dshw restore -DryRun` / **`dshw plan`** (`dshw.ps1:54`, `3016`) is the third surface: it prints what
both would do and changes nothing — no window, no registry write, and it cannot start the origins
proxy (`Ensure-OriginsProxy` is guarded by `-not $DryRun`). Without a reachable dry run the switch
would have been another path that can never run, which is the disease being fixed here.

### 12.3 FIX 3 — restore at logon (source changed, task re-registered, plan observed)

`Invoke-Autostart` (`dshw.ps1:2586-2621`) registered `up -WindowsMode no`, which starts the **engine**
and nothing else: `no` matches neither the `restore` branch nor the `yes/auto` branch of `Invoke-Up`, so
the registry was never consulted and no window ever came back (§4.6). It now registers
`up -WindowsMode restore` — engine first, then the remembered working set, and no more than one window
when nothing is remembered. `restore` rather than `yes`, because `yes` opens **all sixteen** enabled
slots.

Applied, not just edited: the task was re-registered. **The exported task XML is byte-identical before
and after** — same `wscript.exe` action, same `.vbs` path, same `LogonTrigger` for `ZABZ-YOGA\ezabz`,
`InteractiveToken`, `StartWhenAvailable`, `ExecutionTimeLimit=PT0S`. The only thing that changed is the
argument inside the generated wrapper:

```
before: … dshw.ps1 up -ConfigPath …\windows.json -WindowsMode no
after:  … dshw.ps1 up -ConfigPath …\windows.json -WindowsMode restore
```

`RunLevel` stayed **Limited**: `Invoke-Autostart` now preserves the run level of an existing
registration instead of taking it from whichever elevated shell happens to run `autostart on`
(re-registering from an elevated session would otherwise have silently escalated this task to
`Highest`).

**The plan, exercised in isolation because the machine was not rebooted** — the only safe means
available, and the output is quoted verbatim:

```
restore plan: no window is remembered as open, so a restore opens exactly one - the first enabled slot:
  [would open]  1 - main (origin :3200)
  [reconcile]   considered 0 recorded-open slot(s): would forget 0, spare 0, unconfirmed 0
  [registry]    closed rows: 0 inferred by this launcher (closedBy=prune), 12 recorded as a decision, 2 unattributed (written before the field existed)
```

**One window, not twelve** — which is the state §10 left the registry in, and it is the correct one.
`restore` wrote nothing (`sha256` unchanged) and opened nothing.

The same path was then run for real, because `plan` is not the scheduled task: a live `dshw health`
pass printed
`windows: reconcile considered 0 recorded-open slot(s) - closed 0 (0 by port mismatch, 0 by two fresh
negatives 15s apart), spared 0, unconfirmed 0` … `windows: live origins [3099];
registry-open-and-missing 0; reopened 0`. The new code executes, opens nothing, and leaves the
registry byte-identical.

**A note on the other available instrument.** The scratch probe from the previous stream
(`C:\Users\ezabz\code\_scratch\mw-restore-plan.ps1`) was also run against the changed file. It loads
(`176,798 bytes, cut at 172,761 — dispatch excluded`), reports `live origin ports … 3099`, the same
per-slot table, `Invoke-WindowRecovery -DryRun → missing=0 opened=0`, and `real registry untouched:
True` — so it still works and its findings agree. **But its restore model is incomplete in exactly one
branch and it under-reports the plan:** it prints `PLAN: restore would open 0 window(s)`, while the real
`Invoke-Restore` opens **one**, because a registry with no `open:true` row takes the
`$wanted.Count -eq 0` fallback that gives the owner one window rather than none. That probe re-derives
the decision from the registry instead of calling the code; `dshw plan` runs the real `Invoke-Restore`
and is the authoritative reading. A future reader must not conclude from the scratch probe that a
restore is a no-op at logon — that would be the opposite of the FIX 3 behaviour.

### 12.4 STANDING HAZARD — never schedule `mesh-hygiene.ps1 -Reclaim` on this workstation

`mesh-hygiene.ps1:824` calls `[void]$p.CloseMainWindow()` — its **first** rung — and its class-A target
list matches every browser under the Edge application directory **by executable path**
(`:160-168`), not by origin. On 2026-09-17 its own record shows it matching **29 Edge processes** as
class A. On a machine whose owner works in thirteen DSH windows, scheduling it is a self-inflicted
outage: it would close **all of them at the same instant**, the owner's and the fleet's alike, with no
way to tell a DSH window from an ordinary browser. Its second rung (`:837`, `:845`) force-kills, so even
the "graceful" attribution would not survive scrutiny (§12.5). It has never run with `-Reclaim` except
twice by hand on 9/17; **it should stay that way.** Any future cleanup automation on this box must
select by *origin* (127.0.0.1:3200-3223, 3099), never by executable path.

### 12.5 ITS COROLLARY — a graceful close and a hard kill are indistinguishable here

Measured, §6A, and repeated here because it is the rule a future investigator will get wrong: a
graceful close and a hard kill **cannot be told apart** by `exit_type`, by the `Last Browser` / `Last
Version` files, or by `Preferences`. Every live browser on this machine reports `exit_type = Crashed`
**at rest**; `Last Browser` is written **at startup** (+3 s after launch, measured three times); and
`Preferences` is rewritten periodically *during* a run. A `Stop-Process -Force` control left
`Preferences` and `exit_type` **byte-identical**. So: **do not treat any of those three markers as
evidence of a close, in either direction.** Attribution on this machine requires either process-creation
auditing enabled *before* the incident (§11.5) or a component's own log — never a browser-side file.

### 12.6 WHAT IS STILL UNPROVEN

1. **The logon path itself.** No reboot was performed and none should be, and the change was verified by
   the decision it makes, not by firing it. What *is* proven: the task's command now says `restore`, the
   generated wrapper really contains it, the task definition is otherwise unchanged, and `restore`
   against the current registry opens one window on origin :3200. What a reboot would still test, and
   the only thing it would test, is that the logon trigger fires and the launcher survives the boot
   environment — the restore *decision* itself is settled.
2. **`Set-TaskHidden.ps1 -Restore` would resurrect the bug.** The hidden-task manifest
   `scripts/hidden-tasks/DSH_Multi-Window_Launcher.json` still records the **pre-conversion** action,
   which carries `-WindowsMode no`. Anyone who runs `Set-TaskHidden.ps1 -Restore` for this task must
   follow it with `dshw autostart on`, or the engine-only logon path is back. Left untouched on purpose:
   it is a generated manifest outside the two files this session was allowed to change.
3. **`Invoke-WindowRecovery`'s reopen decision still rests on a single reading** of the same two-legged
   union (guard 4). The false-negative class of §6C therefore still applies to *opening a duplicate*,
   bounded by guard 3 (the origin must have a listener), guard 5 (600 s per-slot cooldown) and a
   two-opens-per-run cap. Not changed here: FIX 1 was the prune, and the reconcile above is what keeps
   recovery's guard-1 input honest. It is the obvious next thing to give a confirmation rule.
4. **The two unattributed rows are unattributed forever.** `1 - main` and `2` were pruned at 00:01:59 by
   code that recorded no provenance; no amount of later reading recovers whether a false negative or a
   real close produced them. They are now *counted* as unattributed, which is the honest state.
