# 85 — Node hygiene: the reclaim policy, and the drift report that makes a node's slide visible

**Program:** stream **O4** of `docs/mesh/81-overnight-program.md` (§1 row O4, §2 standing rules, §3.4).
**Depends on:** `71-mesh-program.md` §2.1–§2.2 (the frozen capacity contract and the broker's
arithmetic), `74-mac-mini.md` (the measured incident this generalises from),
`80-mac-worker-hygiene.md` (the Mac policy, whose four rules and three traps are reused here).
**Owned files:** `scripts/mesh-hygiene.ps1` (Windows), `scripts/mesh-hygiene.sh` (Linux + macOS), this
document. **Nothing else was edited.** `scripts/phone-gate.py` was read, never written.
**Dates:** every reading below is **2026-09-17, 03:43–04:23Z** unless it says otherwise.
**Author:** a delegated session (stream O4), not the owner.

Every number carries its source and its moment. §10 states what could not be verified, as refusals.

---

## 1. The answer in one paragraph

The owner's complaint — *"macs don't close down processes like on Windows; when I X things out they
are still running"* — describes a class of waste that every node in this mesh can accumulate, and
which the broker cannot see: the capacity contract reports how much memory is **free**, not that a
node has been **losing** memory for days. O4 ships two things per platform: a **reclaim policy**
(`scripts/mesh-hygiene.ps1`, `scripts/mesh-hygiene.sh`) that acts only when the machine is genuinely
idle, touches only an explicit target list and explicit orphans of our own tooling, and prints a log
line with its reason and its bytes on **every** path including every decline; and a **drift series**
(`<status dir>/mesh-hygiene.{log,jsonl,json}`, one line per run) that carries `avail_mib`,
`reclaimable_rss_kb`, the broker's own placeable-children arithmetic, and the deltas and the rate —
so a node sliding out of the placeable set is visible **before** the broker stops choosing it.
Verified end to end on Windows (ZABZ-YOGA), Linux (secratary) and macOS (the Mac mini): a node
deliberately loaded to **`placeable=0`** (`avail 3849 MiB`, `swap 23.3%`, drift
`rate=-33031 MiB/h`, `placeable_d=-12`, `zero_children_in_h=0`) returned to **`placeable=12`** after
**one** run of the shipped policy, which reclaimed **9412 MiB** (`9637912 -> 0` bytes of reclaimable
RSS); on the way in, the same run proved the scope discipline by leaving a **non-listed** process and
**29 of the owner's Edge processes** untouched, and both decline paths (console active, lease held,
dispatch in flight) printed their reasons on real machines.

---

## 2. The policy: two classes, three gates, one off switch

### 2.1 The two reclaim classes, and what can never be returned

| class | what it is | how it is identified | why it can never hit something else |
|---|---|---|---|
| **A** | an application that outlived its window (browser, chat client, media player) | the process's **own executable path** lies under an entry of an explicit list of directory prefixes, **and** it belongs to the console user / console session | matching is on the executable path, so another vendor's helper, a WebView2 host or a standalone renderer cannot match; a path not in the list is structurally unreachable. No path readable → no match (fails closed) |
| **B** | an orphan of **our own** tooling | the recorded parent is gone (Windows: PPID is never rewritten; POSIX: `ppid == 1` or the parent is a reaper such as `systemd --user`), the command line matches one of our tool entry points, the process is older than `--min-orphan-age`/`-MinOrphanAgeSeconds` (default 300 s), and it holds **no listening socket** | a live probe has a live parent; a service is protected twice (pattern + listener); the engine is excluded by an explicit pattern |

The Windows target list is **24** directory prefixes (`Program Files`/`(x86)`/`LOCALAPPDATA`/`APPDATA` × Chrome, Edge, Brave, Firefox, Spotify, Opera, Vivaldi, Slack, Discord, Notion, Obsidian, WhatsApp, Teams, Zoom, Telegram — measured count from the shipped function: `count=24`); the POSIX list is the equivalent `.app` bundles and Linux install prefixes. The
shipped orphan patterns are our tool entry points — `tailscale` **only in its CLI form**
(`tailscale status|ip|debug|serve|funnel|netcheck|ping|whois|version`, never `tailscaled`, which
carries the tunnel), `phone-gate.py`, `mesh-run.mjs`, `mesh-capacity-probe`, `mesh-e2e`,
`mesh-health`, `governor.mjs`, `agent-fleet`, `journal.py`, `mesh-hygiene`. Both lists are
`-Targets`/`--targets` and `-OrphanPatterns`/`--orphan-patterns` overridable, and **the record names
which list produced a kill** (`target_list_source`), so a reader can always tell.

**Deliberately not in class B:** the DSH engine (`dsh/lib/bin.js web` — excluded by pattern), MCP
servers and the npm/npx shim class (`scripts/dsh-reap.ps1` owns those on Windows, its RULE 1/2, and
it is already scheduled on this node — two reapers with overlapping rules is how a machine gets
eaten), and anything invoked with `--listen-port`/`--engine-port`.

### 2.2 The three gates (81 §1), and the extra measurements that ride with them

The policy acts **only** when all three hold. Every failing gate is named in the log line and in the
record (`gates.failed`):

1. **no console user active** — no interactive session at all, *or* one that has been input-idle for
   ≥ `--idle-seconds`/`-IdleSeconds` (default 1800 s). Windows reads `GetLastInputInfo` when the
   script runs inside the console session; macOS reads root-domain `IOHIDSystem.HIDIdleTime`; Linux
   reads `who -u`'s own idle column (parsed from the right, because `LOGIN@` is one field for today's
   login and two for an older one). **If a session exists and its idle time cannot be measured from
   where the script runs, it DECLINES** — an unmeasured idle time is never read as idle.
2. **no dispatch in flight** — no live process whose command line carries `--profile headless`, the
   frozen dispatch shape of 71 §2.3. A *resident* agent-loop session is deliberately **not** a
   dispatch: a hybrid node must still be able to clean itself, and the console gate is what protects
   the human.
3. **no lease held** — no admission-governor lease whose own heartbeat is unexpired. Liveness is
   `expiresAt` (epoch **milliseconds**), never a pid guess; `packages/plugin-health/lib/governor.js`
   says why a pid check would either reap a live holder or keep a dead one. The lease files are
   `$DSH_HOME/governor/leases/slot-NN.lease`.

### 2.3 Nothing is killed unless you ask, and the off switch is one command

* `mesh-hygiene.ps1` with no switches is a **read-only report**. `-Reclaim` is required to act.
* `mesh-hygiene.sh` with no switches is a **read-only report**. `--reclaim` is required to act.
* A kill ladder, in order, and each step recorded: Windows — `CloseMainWindow()` (the request a human
  makes with the X, which is precisely what does **not** close the app: the owner's own observation),
  then `Stop-Process -Force` after the grace window (`-NoEscalate` to stop at the request); POSIX —
  on macOS the application's own quit through the console user's session
  (`launchctl asuser <uid> osascript … quit`), then `SIGTERM`, then `SIGKILL` after the grace window
  (`--no-escalate` to stop at `SIGTERM`). Escalated pids are recorded (`escalated_pids`) because an
  escalated kill is the one that can cost a human something unsaved.
* Neither script installs anything. The install commands are in each file's header and in §9 below;
  the disable commands are `Unregister-ScheduledTask -TaskName 'DSH Mesh Hygiene' -Confirm:$false`
  (Windows) and `sudo systemctl disable --now mesh-hygiene.timer` (Linux).

---

## 3. The drift report — the half that was missing

The capacity contract answers *"how empty is this node right now"*. Nothing answered *"is it getting
emptier or fuller, and how fast"*. A node that drifts is not reported broken: the broker reads memory
honestly, so it is simply not chosen (`74-mac-mini.md` §8: 111–148 MB of free pages against a
4,045 MB threshold, `maxChildren: 0`, and nobody was told).

### 3.1 Where it lives, and what a human looks at

| platform | status dir | files |
|---|---|---|
| Windows | `%USERPROFILE%\.dsh-sync-status\` (the idiom `status.json`, `mesh-health.json`, `phone-gate.json` already use) | `mesh-hygiene.log`, `mesh-hygiene.jsonl`, `mesh-hygiene.json` |
| Linux / macOS | `/var/log` when writable, else `$HOME/.dsh-sync-status` (the dir actually used is printed and recorded as `status_dir`) | same three names |

* `mesh-hygiene.log` — **one human line per run**, on every path including every decline. This is the
  file to read first: `tail -1` answers "what did it just do and why".
* `mesh-hygiene.jsonl` — one JSON object per run, append-only, chronological. This is the series.
* `mesh-hygiene.json` — the latest object alone, for a monitor to read in one shot.

**To see drift, in one command:**

```
# Windows
pwsh -File scripts\mesh-hygiene.ps1 -Drift -Last 20     # the table for this node
pwsh -File scripts\mesh-hygiene.ps1 -Collect            # every node's latest record, one command
# Linux / macOS
mesh-hygiene.sh --drift 20
mesh-hygiene.sh --collect
```

`-Drift`/`--drift` prints, per record: `at(UTC)`, `outcome`, `availMiB`, the **delta since the
previous reading**, `placeable`, `reclaimableKB`, targets live, orphans live, `trend` and the reason.
`-Collect` reads each node's `mesh-hygiene.json` over ssh and prints one line per node — **that is the
broker-visible half of this stream**: the broker itself cannot read another node's filesystem, so the
fleet-wide view is a reader, not a push. (A future broker could publish the same three fields on the
gate's `/mesh/capacity` route; the field names are stable and §6.3 says exactly which.)

### 3.2 The three counters, each defined once

| field | definition | source |
|---|---|---|
| `memory.avail_mib` | **the capacity contract's own number**, so the drift report and the broker cannot disagree about the same machine in the same second | Windows: `GlobalMemoryStatusEx().ullAvailPhys` (what node's `os.freemem()` returns); Linux: `/proc/meminfo` `MemAvailable`; macOS: `vm_stat` `Pages free + inactive + speculative + purgeable` × `hw.pagesize`. Every record names which one it used in `memory.avail_source` |
| `reclaim.reclaimable_rss_kb` | bytes held **right now** by processes this policy may reclaim (class A RSS + class B RSS). This is the accumulating quantity. | the process table it just built |
| `capacity.placeable_children` | the children the broker's frozen formula would place here now: `memorySlots = min(floor((availMiB − 3885)/160), 24) − governor.inUse`; `coreSlots = floor(physicalCores × 0.75)`; `slots = min(memorySlots, coreSlots)`; `swap ≥ 90%` halves it | 71 §2.2, **reproduced** — the record says so in `capacity.formula`, and `disk`/`transport` terms are deliberately **not** in it |

Derived per run, in `drift`: `secs_since_prev`, `d_avail_mib`, `d_placeable`,
`d_reclaimable_rss_kb`; the baseline is the **oldest record inside the last 24 h**, giving
`baseline_hours`, `avail_mib_per_hour`, `hours_to_zero_children`, and `trend`
(`shrinking`/`growing`/`stable` with a 256 MiB/h dead band, or `insufficient-window` when the series
is younger than the window).

The headline a human wants is `hours_to_zero_children`: at the measured rate, how long until this node
has no slots left. The line printed during the load test in §5.2 — `rate=-33031 MiB/h …
placeable_d=-12 zero_children_in_h=0 trend=shrinking` — is that sentence about a real machine, written
before the reclaim ran.

### 3.3 The record, verbatim (one run, one line, 1905 bytes on the Mac)

```json
{"schema":1,"tool":"mesh-hygiene","version":"1.0.0","at":"2026-09-17T04:22:06Z","at_epoch":1789618926,
 "host":"LakewooechsMini","node":"lakewooechsmini","platform":"Darwin","mode":"report","outcome":"reported",
 "reason":"report only (pass --reclaim to act); all three gates pass; 0 target(s) and 0 orphan(s) would be reclaimed",
 "gates":{"failed":null,"idle_required_s":1800,"bypassed_for_selftest":false},
 "console":{"user":"lpt","uid":501,"present":true,"idle_seconds":19468,"idle_source":"IOHIDSystem.HIDIdleTime"},
 "work":{"dispatch_in_flight":"","dispatch_count":0,"leases_held":0,"lease_holders":"","lease_root":"/Users/lpt/.dsh/governor","agent_loops":null},
 "memory":{"total_mib":16384,"avail_mib":7529,"avail_source":"vm_stat free+inactive+speculative+purgeable x hw.pagesize","swap_used_pct":58.0},
 "capacity":{"formula":"71 s2.2 (memory + cores; disk and transport terms NOT included)","reserve_mib":3885,"per_child_mib":160,
   "memory_slots":22,"core_slots":7,"slots":7,"placeable_children":7},
 "gate":{"url":"http://127.0.0.1:3086/mesh/capacity","reachable":true,"error":"","free_mib":7519,"max_children":12,"fleet":true},
 "reclaim":{"targets_live":0,"targets_rss_kb":0,"orphans_live":0,"orphans_rss_kb":0,"reclaimable_rss_kb":0,
   "reclaimed_rss_kb":0,"after_rss_kb":0,"acted_pids":null,"escalated_pids":null,"target_list_source":"default",
   "orphan_patterns":"tailscale (status|ip|…)|phone-gate\\.py|…|mesh-hygiene","listener_protection":"lsof","candidates":null,"spared":null},
 "drift":{"secs_since_prev":null,"d_avail_mib":null,"d_placeable":null,"d_reclaimable_rss_kb":null,
   "baseline_at":null,"baseline_hours":null,"avail_mib_per_hour":null,"hours_to_zero_children":null,"trend":"no-history"},
 "status_dir":"/Users/lpt/.dsh-sync-status","log":"/Users/lpt/.dsh-sync-status/mesh-hygiene.log"}
```

`schema` is 1 and the field names are the same on both platforms; the Windows record carries the same
keys plus `console.session`, `console.sessions`, `work.lease_dir_present`, `capacity.swap_halved`,
`gate.elapsed_ms`, `reclaim.listener_protection` and `drift.d24_*`.

---

## 4. Installation: what is running on every node after this stream

**Nothing is installed. Nothing is scheduled. Nothing is configured.** Both scripts were run by hand
throughout; the only files created anywhere are the status files listed in §3.1, which are the policy's
own record. This is deliberate — 81 §2 and the brief both ask for a script a human can run and read
over a daemon nobody can turn off, and the owner's laptop was running seven other streams at the time.

The install command for each platform is in the script header and repeated here, with its off switch:

```powershell
# Windows, every 5 minutes, as SYSTEM (see §8.2 for why SYSTEM declines when a human is logged on):
$a = New-ScheduledTaskAction -Execute 'pwsh.exe' -Argument '-NoProfile -File C:\Users\ezabz\code\harness-config\scripts\mesh-hygiene.ps1 -Reclaim -Quiet'
$t = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName 'DSH Mesh Hygiene' -Action $a -Trigger $t -RunLevel Highest -User 'SYSTEM'
# OFF: Unregister-ScheduledTask -TaskName 'DSH Mesh Hygiene' -Confirm:$false
```

```bash
# Linux, systemd timer:
sudo install -m 755 mesh-hygiene.sh /usr/local/lib/lakewoodphone/mesh-hygiene.sh
# mesh-hygiene.service: ExecStart=/bin/bash /usr/local/lib/lakewoodphone/mesh-hygiene.sh --reclaim --quiet
# mesh-hygiene.timer:   OnUnitActiveSec=5min
sudo systemctl enable --now mesh-hygiene.timer
# OFF: sudo systemctl disable --now mesh-hygiene.timer
```

**macOS is left alone on purpose.** The Mac mini already runs its own reclaim job
(`com.lakewoodphone.mesh-worker-hygiene`, `80-mac-worker-hygiene.md` §4) which this stream does not
replace, and the brief for O4 says explicitly not to touch it. `mesh-hygiene.sh` runs there today as a
**read-only** reporter (`--report`, `--self-test`), which is what §5.4 shows. If the two are ever
combined, the Mac job's `--idle-seconds` lever and this script's gates are the same idea with two
implementations, and the right outcome is to keep one.

---

## 5. Verification, with raw output

### 5.1 Windows on ZABZ-YOGA (Windows 11 Home, build 26200, 22 logical / 16 physical cores, 31.6 GiB)

**The decline path, with the shipped defaults (`-Reclaim`, 2026-09-17 03:49:38Z):**

```
2026-09-17T03:49:38Z | ZABZ-YOGA | v1.0.0 | mode=reclaim | outcome=declined |
  console=ZABZ-YOGA\ezabz session=1 idle_s=251 idle_required_s=1800 idle_source=GetLastInputInfo(same-session) |
  work dispatch=0 leases=1 loops=7 | mem avail=12926MiB swap=0% |
  placeable=12 (memSlots=23 coreSlots=12) gate_free=12921MiB gate_maxchildren=12 |
  reclaimable_rss=3201MiB targets=29 orphans=0 spared=1 reclaimed=0MiB |
  drift prev_d=127 MiB in 226 s rate=15855 MiB/h over 0.11 h placeable_d=0 zero_children_in_h=none trend=growing |
  reason=console active: idle 251s < required 1800s (user ZABZ-YOGA\ezabz, session 1); a governor lease is held:
  pid 1784 overnight-build [slot-01] expires in 13484s -- 7 streams: …
```

Two gates fired and both were named. The 29 target processes are the owner's Edge browser — measured
across the evening as 29–30 processes and 2.9–3.4 GiB resident (`Get-Process msedge` → 30 at 03:47Z,
29 / 2,925 MB at 04:26Z; the run's own count: 29) — it was **not** touched, and that is the same run's
sparing proof for class A: the gate declined, so nothing was killed.

**The self-test, both branches on real processes:**

```
  hog A        : mesh-hygiene-hog-a.ps1   -- matches the SHIPPED orphan pattern (mesh-hygiene)
  hog B        : unlisted-hog-b.ps1       -- matches nothing; it MUST survive
  hog processes found before reclaim: 2  (pids 28780 32392)
2026-09-17T03:49:20Z | … mode=selftest | outcome=acted | … reclaimable_rss=99MiB targets=0 orphans=1 spared=2
  reclaimed=99MiB | reason=reclaimed 1 process(es) [pwsh.exe/28780]: 99 MiB resident let go;
  reclaimable_rss_kb 101436 -> 0
  A mesh-hygiene-hog (matches shipped pattern) alive now: 0  -> PASS
  B unlisted-hog      (matches nothing)       alive now: 1  -> PASS (spared)
SELF-TEST: ALL CASES PASSED
```

The `101436 -> 0` after-reading is a real re-measurement, not arithmetic: the first version of this
test printed `179572 -> 179572` because it re-filtered a **cached** process table (§8.1).

The self-test also runs under **Windows PowerShell 5.1** (`powershell.exe -File …`) with identical
numbers, which is why the script avoids PS7-only syntax and guards `-NoProxy` behind the
HttpClient idiom.

### 5.2 The loaded-then-abandoned test: `placeable 12 → 0 → 12`, with the drift line

The load was a real process **I started and can name**, and it was left to become a **real orphan**
(its spawning shell exited; `Get-CimInstance Win32_Process` showed the recorded parent pid no longer
existed):

* `node %TEMP%\hygiene-lab\mesh-hygiene-hog-a.mjs 10.2` — 10.2 GiB allocated and touched with
  `randomFillSync`, resident **10,369 MB** measured 35 s after start;
* plus `unlisted-hog-b.ps1` (tiny, matches no pattern — the sparing case), a **copy of `cmd.exe` under
  the lab directory** (so it is inside a `-Targets` prefix — the class-A case), and the **System32
  `cmd.exe`** (same binary, not under the prefix — the class-A sparing case).

| moment (UTC) | counter | value |
|---|---|---|
| 03:51:05Z | gate `/mesh/capacity` | `freeMiB 12453`, `budgetSlots 24`, `inUse 1`, `maxChildren 12` |
| 03:51:11Z | hygiene report | `avail=12394MiB`, **`placeable=12`** (`memSlots=23 coreSlots=12`), `reclaimable_rss=3358MiB`, `targets=29` |
| 03:56:26Z | gate, under load | `freeMiB 4163`, **`swapUsedPct 20.3`**, `budgetSlots 4`, `inUse 2`, **`maxChildren 2`**, `loopsRunning 11` |
| 03:56:36Z | hygiene report, under load | `avail=3849MiB swap=23.3%`, **`placeable=0 (memSlots=-3 coreSlots=12)`**, `gate_free=3995MiB gate_maxchildren=2`, drift **`prev_d=-8611 MiB in 262 s rate=-33031 MiB/h placeable_d=-12 zero_children_in_h=0 trend=shrinking`** |
| 03:57:18Z | **reclaim run 1**, class A only | `outcome=acted … reason=reclaimed 1 process(es) [listed-cmd.exe/19708]: 7 MiB resident let go; … escalated to force-kill for pids 19708` |
| 03:57:36Z | **reclaim run 2**, class B | `outcome=acted … reason=reclaimed 1 process(es) [node.exe/17688]: 9412 MiB resident let go; reclaimable_rss_kb 9637912 -> 0` |
| 03:57:37Z | gate, one second later | `freeMiB 14477`, **`swapUsedPct 0.0`**, `budgetSlots 24`, `maxChildren 12` |
| 03:58:01Z | hygiene report | `avail=14319MiB swap=0%`, **`placeable=12`**, drift **`prev_d=10819 MiB in 25 s rate=12525 MiB/h placeable_d=12 … trend=growing`** |

**The sparing proofs from those two action runs** (the honest half of the test):

```
after: pid 17688 (the 10.2 GiB hog, matched)   GONE     <- reclaimed, 9412 MiB
       pid 19708 (cmd.exe under the lab prefix) GONE    <- class A, path under the explicit prefix
       pid 23304 (unlisted-hog-b.ps1, matched by NOTHING) ALIVE  rss 88MB
       pid 12304 (C:\Windows\System32\cmd.exe, same binary but NOT under the prefix) ALIVE  rss 6MB
       the owner's 29 Edge processes: not in the target prefix, never candidates, untouched
```

Both reclaim runs used two levers that the *production* job never passes, and the report says so
plainly: `-IdleSeconds 0` (the Mac policy's own lever — the same comparison at a different N, needed
because the owner was at the keyboard) and `-GovernorRoot <scratch dir>` (because the overnight
program held a real lease: the gate's own reason at 03:49Z names it). Run 1 additionally used a
90-second `-Targets` prefix pointing at the lab directory so that **only** the lab copy of `cmd.exe`
was in class A.

### 5.3 Linux on secratary (4 physical cores, 23.4 GiB)

```
$ bash mesh-hygiene.sh --status-dir /tmp/hygiene-sec          # read-only report
memory          : avail=12058MiB total=23421MiB swap=11.1%  [MemAvailable(/proc/meminfo)]
capacity (71 2.2): memSlots=24 coreSlots=3 slots=3 -> placeable children=3
gate (localhost): reachable=true free=12059MiB maxChildren=12 fleet=true node=secratary
console user    : none (uid 0) idle=unmeasureds required=1800s source=no-active-session
```

The orphan class with the **shipped patterns**, on two real orphans:

```
matched orphan pid=2081059  unlisted orphan pid=2060534
2026-09-17T04:15:41Z | secratary | v1.0.0 | mode=reclaim | outcome=acted | … orphans=0 … reclaimed=7MiB |
  reason=reclaimed 1 process(es) [ mesh-health-probe2081059 ]: 7 MiB resident let go; reclaimable_rss_kb 7780 -> 0
matched orphan alive after : no          <- it was in argv[0]: `exec -a mesh-health-probe sleep 300`
unlisted orphan alive after: YES         <- a plain `sleep 300`
```

Both decline paths that Linux can show, with their log lines:

```
=== B. decline: a governor lease is held ===
… outcome=declined … leases=1 … reason=a governor lease is held: pid 1 o4-lease-decline-test [slot-01.lease]

=== C. decline: a dispatch is in flight ===
2087353 dsh-headless-probe -c import time;time.sleep(300) --profile headless
… outcome=declined … dispatch=1 … reason=a dispatch is in flight: pids 2087353
```

The lease was a **fake** lease written into a scratch `--governor-root` for one run (expiry 10 min in
the future) — created only to prove the gate fires, deleted immediately after. `--self-test` on
secratary: **ALL CASES PASSED**.

### 5.4 macOS on the Mac mini (macOS 26.5.2, 10 cores, 16 GiB)

```
$ bash /tmp/mesh-hygiene.sh                                  # read-only report, run as lpt
console user    : lpt (uid 501) idle=19172s required=1800s source=IOHIDSystem.HIDIdleTime
memory          : avail=7071MiB total=16384MiB swap=58.0%  [vm_stat free+inactive+speculative+purgeable x hw.pagesize]
capacity (71 2.2): memSlots=19 coreSlots=7 slots=7 -> placeable children=7
gate (localhost): reachable=true free=7070MiB maxChildren=12 fleet=true node=lakewooechsmini
reclaimable now : 0 MiB in 0 target(s) + 0 orphan(s); 0 spared
```

`--self-test`: **ALL CASES PASSED** (hog A reclaimed, hog B spared) — on macOS's **bash 3.2**, which
is why the script uses no associative arrays, no `${var,,}`, no `mapfile`.

Two cross-checks worth naming: the script's `avail_mib` (7071, from `vm_stat`) and the **gate's own**
`freeMiB` (7070) agree to 1 MiB in the same second — the darwin memory definition `74-mac-mini.md`
§7.3 had to add is the one this report uses; and `console idle=19172s` is a machine nobody is sitting
at, which is the condition under which class A *would* act.

### 5.5 The fleet view, one command, from either platform

```
$ pwsh -File scripts\mesh-hygiene.ps1 -Collect              # from ZABZ-YOGA (Windows)
node               at(UTC)                availMiB  place    reclaimKB drift
zabz-yoga-1        2026-09-17T04:28:33Z      13709     12      3071520 trend=growing rate=3285MiB/h zero_in=h
zabz-tech          -                             -      -            - no record (ssh exit 1 via zabz-tech-ts: either the node
                                                                       has no record, or this host cannot reach/authenticate to it)
secratary          2026-09-17T04:16:20Z      12680      3            0 trend=insufficient-window rate=MiB/h zero_in=h
zabz-tech-linux    -                             -      -            - no record (ssh exit 1 via linux-pc-ts: …)
lakewooechsmini    2026-09-17T04:22:06Z       7529      7            0 trend=no-history rate=MiB/h zero_in=h

$ bash /tmp/mesh-hygiene.sh --collect                        # the same thing from the Linux authority
zabz-yoga-1        2026-09-17T04:28:33Z      13709     12      3071520 trend=growing rate=3285MiB/h zero_in=h
secratary          -                             -      -            - no record (ssh exit 255: …)
lakewooechsmini    2026-09-17T04:22:06Z       7529      7            0 trend=no-history rate=MiB/h zero_in=h
```

Three nodes have records; the rows without one **say so** with the ssh exit code, because "the node
has no record" and "this host cannot reach it" are different facts and `exit 1` (ssh worked, the file
is not there) is distinguishable from `exit 255` (authentication failed — measured: secratary cannot
ssh to `secratary-ts`, i.e. to itself). The POSIX collector takes `--nodes "name=ssh-alias=kind …"`
(`kind` is `win` or `posix`) because the remote read is a different program on each platform: a
Windows row needs `cmd /c type "%USERPROFILE%\.dsh-sync-status\mesh-hygiene.json"` and a POSIX row
needs `cat`, and one line cannot be both (`cmd.exe` cannot parse `2>/dev/null` — measured, that is
exactly how the Windows rows first came back empty). The default list is this fleet's aliases; on a
host whose ssh config names nodes differently, pass `--nodes`/`-Nodes`.


---

## 6. What the drift report found that the capacity contract does not say

### 6.1 The gate and the broker disagree about "how many children fit", by up to 4×

`scripts/phone-gate.py` computes `accepts.maxChildren = min(budgetSlots − inUse, MESH_MAX_CHILDREN)`
where `budgetSlots = min(floor((freeMiB − max(2 GiB, 12% of physical))/160), 24)` **floored at 4** and
`MESH_MAX_CHILDREN = 12`. The broker (71 §2.2) computes
`min(memorySlots − inUse, floor(physical × 0.75))` with **no floor** and a **core term**. Measured in
the same seconds:

| node | cores | gate `maxChildren` | broker formula `placeable_children` |
|---|---|---|---|
| ZABZ-YOGA | 16 physical | 12 | 12 (memory 23, cores 12) |
| secratary | 4 physical | **12** | **3** |
| Mac mini | 10 physical | **12** | **7** |

The gate has no core term at all, so on a 4-core node it advertises four times what the broker's
arithmetic will place. This is adjacent to 81 §3.2's open item (the gate's reserve `max(2 GiB, 12%)`
and the broker's flat 3885 MiB are two different reserves) and it is **not O4's to decide**; what O4
does is stop either number being read alone: every record carries **both**, under
`capacity.placeable_children` (broker, with `capacity.formula` naming its source) and
`gate.max_children` (the gate's own answer, read over HTTP from `127.0.0.1:3086`).
For O1's acceptance harness: a mesh that passes §0's item 1–6 on the laptop and the desktop may still
mis-place on the 4-core authority, and the drift report is where that difference is visible.

### 6.2 The gate floors its budget at 4 slots; the broker does not

Under the deliberate load of §5.2 the gate answered `maxChildren: 2` for a node whose broker-formula
score was **0** (`memSlots = -3`). The gate's own `71 §2.1` rule — "floored at 4" — is why: it never
reports a negative budget, so at the very edge it still offers slots. Both numbers were true and they
described different things.

### 6.3 What a future broker should read, if it wants drift without ssh

The record is stable and the three fields that matter are `memory.avail_mib`,
`capacity.placeable_children` and `drift.avail_mib_per_hour` (+ `drift.hours_to_zero_children`).
Publishing them on the gate's `/mesh/capacity` document would make drift broker-visible; that route is
`scripts/phone-gate.py`, which this stream does not own. Today the reader is `-Collect`/`--collect`.

---

## 7. Relationship to what already existed

| thing | relation |
|---|---|
| `scripts/dsh-reap.ps1` + the `DSH Process Reaper` task (already running on ZABZ-YOGA every 10 min) | owns the **npm/npx shim and stale-MCP-generation** class on Windows. Its log tail on 2026-09-16 23:10–23:30 reads `orphans=0 staleMcp=0 candidates=4 reclaimMB=0` — i.e. it is working and has nothing to do right now. `mesh-hygiene` deliberately does **not** duplicate its rules; both are idempotent and can run side by side |
| the Mac mini's `com.lakewoodphone.mesh-worker-hygiene` job | the model, and still the Mac's own policy. §4 explains why this stream did not touch it |
| the admission governor (`admission_governor`, `governor.mjs`) | the **source** of gate 3: `mesh-hygiene` reads the lease directory and never acquires, renews or releases a lease |
| the capacity contract | the source of `memory.avail_mib`'s definition and of gate-style thinking about honesty; `mesh-hygiene` **reads** the local gate over `127.0.0.1:3086` and never writes anything a gate serves |
| `phone-gate.py:44`'s stale `tailscale` call shape (81 §3.1) | one of the two places the macOS orphan class can be recreated. `mesh-hygiene` never calls `tailscale` at all; it only recognises the CLI form. The orphan that shape creates is exactly what class B reclaims |

---

## 8. Traps found, each with the measurement that found it

These are the reason the scripts look the way they do. Each was hit for real in this session, and each
cost a wrong-looking test result before it was understood.

### 8.1 Four traps in my own code, found by the verifications failing

1. **A cached process table made the "after" number equal the "before".** The self-test printed
   `reclaimable_rss_kb 179572 -> 179572` on a run that had just killed both processes. The
   after-measurement re-filtered the cached table; it must re-read (`Get-ProcessTable`) first.
2. **An age floor checked before the pattern check** labelled a human's `ping` and an unrelated
   sleeper as "matches our tooling". The message was false; the pattern test now runs first, and
   "not-yet" means only "ours but too young".
3. **An etime conversion applied twice** turned every age into 0 (`etime_to_seconds("6")` has one
   field and returns 0) so no orphan ever passed the floor and the self-test reported "already clean"
   with two eligible orphans in front of it.
4. **Inconsistent row layouts between writer and reader** (`pid|class|exe|rss|…` written,
   `pid|class|rss|…` read) summed an executable's *name* as bytes — every orphan's RSS became 0 — and
   then did arithmetic on the string `sh`, dying under `set -u` with `sh: unbound variable`. One
   layout, written down in the file, is the fix.

### 8.2 Windows-specific, measured here

* **`WTSINFOEX_LEVEL1.LastInputTime` and `WTSINFO.LastInputTime` are 0 for a console session on
  Windows 11 build 26200** (raw: `sid=1 state=0 user='ZABZ-YOGA\ezabz' ws='Console'
  lastInput=0 now=134340898695453374`). `GetLastInputInfo` in the same second answered
  `108109 ms`. Consequence: a **SYSTEM** scheduled task (session 0) cannot measure the console's
  idle time from the WTS APIs on this build, so the script **declines** with
  `console_present_idle_unmeasurable` rather than guessing. Two honest deployments follow, and the
  header of the .ps1 names them: register the job **as the console user** if class A matters, or run
  it as SYSTEM and accept that it reclaims class B only while no interactive session exists.
  *(The session-0 run itself is a refusal — §10.2.)*
* **`quser.exe`/`query.exe` are not present on this machine** (`Test-Path` false for all three of
  `quser.exe`, `query.exe`, `qwinsta.exe`), which is why the idle test is not built on them.
* **A PowerShell memory hog is not a memory hog.** `New-Object byte[] N` + `[Array]::Fill[byte]`
  touched ~2.8 MB/s (a 2 GB fill did not finish in 120 s), and filling every page with the *same*
  byte is the wrong shape anyway — Windows page-combining can merge identical pages into one physical
  page (the first attempt reported `WorkingSet 126 MB`, `PrivateMemorySize 41 MB`,
  `VirtualMemorySize 2.1 TB` for a "10 GiB" array). The load that worked was Node:
  `Buffer.alloc` + `randomFillSync` → `RESIDENT … rss=8936 MiB` in seconds.
* **`Start-Process -Wait` waits for the process *and its descendants*** on Windows, so a self-test
  that spawns a 900-second hog and waits hung until the tool call was killed at 120 s.
  `-PassThru` + `WaitForExit(ms)` on the intermediate alone is the fix.
* **A parent's `ExecutablePath` may be unreadable for another user's process**, so class A fails
  closed: no path, no match.
* **The node's own gate is parentless by design and matches our tooling.** The first report of this
  script classified pid 24148 (`pythonw … phone-gate.py --listen-port 3086`, recorded parent gone, age
  12234 s) as a reclaimable orphan. It is the node's front door. Two protections now stand in front of
  that class: a **listening socket is never an orphan candidate** (measured live:
  `24148 spared: holds a LISTENING socket, so it is a service this node depends on`), and
  `--listen-port`/`--engine-port`/`tailscaled`/the engine's `dsh/lib/bin.js web` are never candidates.

### 8.3 POSIX-specific, inherited and confirmed

* **`uid` is a bash readonly builtin** (`80-mac-worker-hygiene.md` §4.6) — the variables here are
  `CONSOLE_UID`, `puid`, `want_uid`; a new sibling was found the same day: **`PPID` is readonly too**
  (`/tmp/dbg-linux.sh: line 12: PPID: readonly variable`), so the local is `ppid`.
* **`ps -o comm=` on macOS returns a path including its spaces as one column** — the table is built
  with `-ww` and "everything from field 6 on is the command".
* **`pmset -g assertionslog` hangs forever** on macOS — never called. Everything potentially hanging
  goes through `run_bounded`, which uses perl's `setpgrp(0,0)` so the kill reaches the process group
  (the shape `74-mac-mini.md` §4.2 established).
* **A bare `tailscale` on macOS is a shim in front of a GUI binary that never answers** — this script
  never invokes it, and the pattern matches the CLI form only, so `tailscaled` (which carries the
  tunnel) can never match.
* **Orphan reparenting differs by platform**: measured on secratary, an abandoned `sh` was reparented
  to **pid 1**; on a host with a per-user `systemd` (or any `PR_SET_CHILD_SUBREAPER`) the parent is a
  live reaper, so "parent gone" is implemented as *ppid is 1, or the parent is not in the table, or
  the parent is a reaper*.

---

## 9. The one-line answer to "what do I run"

```
# Windows node, read-only then acting:
pwsh -File scripts\mesh-hygiene.ps1                    ; pwsh -File scripts\mesh-hygiene.ps1 -Reclaim
# Linux node:
bash scripts/mesh-hygiene.sh                           ; bash scripts/mesh-hygiene.sh --reclaim
# Is any node drifting?
pwsh -File scripts\mesh-hygiene.ps1 -Collect           # or: bash scripts/mesh-hygiene.sh --collect
```

Exit codes, both platforms: **0** ran (reported / acted / declined), **1** usage or a failing
self-test, **3** the primary counter could not be measured — nothing was touched.

---

## 10. What could not be verified — stated as refusals

1. **No soak.** Nothing is scheduled anywhere, so the policy has been run by hand only: the
   `StartInterval`/`OnUnitActiveSec` behaviour over hours, the log growth (arithmetic: one ~700-byte
   line per run at 5-minute intervals ≈ **200 KB/day**, ≈ 73 MB/year) and behaviour across a reboot
   are all unsoaked. Every claim above is about a single invocation of the same command a schedule
   would run.
2. **A scheduled task running as SYSTEM (session 0) was not executed**: this session is not elevated
   (`IsInRole(Administrator)` → **False**), so a run as SYSTEM could not be created. What *is*
   measured is the API fact that makes it decline (§8.2) and the code path itself, which is
   deterministic (`idle_seconds = null` → `console_present_idle_unmeasurable`). The claim "a SYSTEM
   run with a human logged on declines" is therefore an inference from a measurement, and it is
   labelled as one.
3. **Class A was never exercised on macOS against a real application.** No listed application was
   running for the console user during the session, and quitting a human's browser on a machine the
   owner did not ask me to change is not mine to do. What is verified on macOS: the read-only report,
   the idle measurement, the capacity and gate numbers, the self-test's matching/kill/sparing, and
   the class-A *matching* code path (0 live targets, correctly). The class-A action path is verified
   on Windows (§5.2, real processes) and Linux (the same shareable code path, `--self-test`).
4. **A `no record` row cannot distinguish "this node has no record" from "this host cannot reach it".**
   Measured: the collector reads over ssh, so a missing alias, a refused key or a down host produce the
   same row as a node that never ran the script — the row now carries the ssh exit code (`1` = the read
   ran and found nothing; `255` = authentication failed), which is the most a read-only collector can
   distinguish. `--collect` **is** verified from both platforms (§5.5), including a Windows row read
   from the Linux authority through the `cmd /c type` branch and a macOS row from Windows.
5. **Whether the shipped target list is the right list** is a taste question, not a measurement. It
   was chosen from what these machines actually accumulate; a prefix for an absent application costs
   nothing and can never match.
6. **The Windows-page-combining explanation in §8.2 is a hypothesis** attached to a measurement
   (`WorkingSet 126 MB` / `PrivateMemorySize 41 MB` / `VirtualMemorySize 2.1 TB`). The measurement is
   what matters — the observation is that a same-byte fill does not produce resident memory; the
   mechanism (identical-page merging) is the most likely one and was not proved.
7. **Which single line produced the one `bash -n` syntax error** (§8.1 is about a different, later
   bug) was not isolated: the three shapes in the offending lines were each re-tested in isolation and
   all parse (`bash 5.3.9`, `/tmp/tA.sh`, `tB.sh`, `tC.sh`). What is recorded is the observation and
   the fix — one value per line — not a theory.
8. **The gate/broker divergence in §6.1 is reported, not adjudicated.** Which number a placement
   decision should trust is 81 §3.2's open item and the broker's (stream S5) to settle.

---

## 11. One-paragraph summary for the manager

Two scripts and this document. `scripts/mesh-hygiene.ps1` and `scripts/mesh-hygiene.sh` are a
read-only-by-default reclaim policy with the **same record format** on Windows, Linux and macOS: it
acts only when no console user is active, no `--profile headless` dispatch is in flight and no
governor lease is held, touches only an explicit target-prefix list (class A) and only orphans of our
own tooling that are parentless, older than the age floor and not listening on a socket (class B), and
writes one line plus one JSON object per run on **every** path including every decline. Alongside it,
a drift series per node (`mesh-hygiene.{log,jsonl,json}` in `~/.dsh-sync-status` on Windows and
`/var/log` (else `~/.dsh-sync-status`) on POSIX) carrying `avail_mib` **in the capacity contract's own
definition**, `reclaimable_rss_kb`, the broker's frozen placeable-children arithmetic, and the delta
and rate against the oldest reading in 24 h — with `-Drift`/`--drift` and a cross-node `-Collect`/
`--collect` as the two commands a human runs. Verified with raw numbers on all three platforms: a
deliberately loaded ZABZ-YOGA went `placeable 12 → 0` (`avail 3849 MiB`, `swap 23.3%`,
`gate maxChildren 2`, drift `rate=-33031 MiB/h`, `placeable_d=-12`, `zero_children_in_h=0`) and back
to `placeable 12` after **one** run that reclaimed **9412 MiB**; that run left a non-listed process and
the owner's 29 Edge processes untouched; the declines print `console active: idle 251s < required
1800s`, `a governor lease is held: pid 1784 overnight-build`, and `a dispatch is in flight: pids
2087353`; and `--self-test` passes on Windows (PS 7 and 5.1), Linux and macOS (bash 3.2) by killing the
hog that matches the shipped pattern and sparing the one that does not. **Nothing was installed, and
the Mac's own reclaim job was not touched.** Two findings belong to other streams: the gate's
`maxChildren` has no core term and reads **12** on the 4-core authority where the broker's arithmetic
says **3** (§6.1, adjacent to 81 §3.2), and the node's own parentless gate was the first thing class B
tried to reclaim until a listening socket was made disqualifying (§8.2) — so a fleet that enables
class B without that protection would kill its own front door on the first clean run.
