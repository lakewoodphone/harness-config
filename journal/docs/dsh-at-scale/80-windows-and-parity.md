# 80 — Windows/browser cost audit + second-machine parity

**Measured:** 2026-09-16, 10:16–10:28 local, on `ZABZ-YOGA` (the laptop).
**Scope:** read-only. No DSH engine was started, stopped or restarted; no browser window was opened or
closed. The only file written is this report.

**Headline:** the "8.18 GB of Edge" figure is real but it is the **sum of `WorkingSet` across all
processes**, which double-counts shared pages. The honest private-bytes number for the same 12 windows is
**3.90 GB**. And 4 of those 12 windows are slots `windows.json` marks `enabled: false` — they cost
**1.73 GB, ~44 % of the whole browser footprint**, and they exist because `up` never checks whether a
window is already open.

---

## 1. Where the 8.18 GB actually goes

### 1.1 The two counters disagree by 4.3 GB, and that is the whole story

| counter | how it was read | value | what it means |
|---|---|---|---|
| Σ `WorkingSet` over `msedge` | `Get-Process msedge \| Measure-Object WorkingSet64 -Sum` | **8,181.6 MB** | every process's total resident pages. **Shared pages counted once per process** |
| Σ `WorkingSetPrivate` per pid | `Win32_PerfRawData_PerfProc_Process` → `.WorkingSetPrivate`, mapped by `IDProcess` | **3,622.9 MB → 3,898.1 MB** | only pages private to that process. Shared pages counted once |

`8,181.6 MB` is **exactly** the `8.18 GB` that has been quoted as the browser's cost since 2026-09-15.
That figure is not a lie, but it is not the machine's cost either: Chromium maps the same shared
read-only pages (code, V8 snapshot, ICU data, the bundled fonts) into every renderer, GPU and utility
process. Summing `WorkingSet` charges the machine for those pages once per process. `WorkingSetPrivate`
is the counter that does not, and it is the same counter `PERFORMANCE-MEASURED.md:142` already chose
("memory is **private bytes**, because summing `WorkingSet` across 90 Chromium processes double-counts
shared pages") — the 8.18 GB reading was taken with the other one.

The cross-check that the private figure is the right one: Σ `WorkingSet` across *every* process on the
machine is 20.6 GB against 31.61 GB of physical RAM, which agrees with commit charge (20.65 GB) — the
machine is not holding 8.18 GB of Edge out of 31.61 GB while also reporting 14.26 GB free.

### 1.2 Method (repeatable, exact)

```powershell
# 1. one process-table read, with the private-pages counter for the same instants
$mem=@{}
Get-CimInstance Win32_PerfRawData_PerfProc_Process |
  ForEach-Object { $mem[[int]$_.IDProcess]=[int64]$_.WorkingSetPrivate }

# 2. attribute each msedge process to its window by --user-data-dir, and type by --type
$rows = Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" | ForEach-Object {
  $cl=$_.CommandLine
  $prof = if ($cl -match '--user-data-dir=(?:"([^"]+)"|(\S+))') {
            if($matches[1]){Split-Path $matches[1] -Leaf}else{Split-Path $matches[2] -Leaf} } else {''}
  $type = if ($cl -match '--type=([a-zA-Z\-]+)') { $matches[1] } else { 'browser' }
  [pscustomobject]@{Pid=$_.ProcessId;Type=$type;MB=[math]::Round(($mem[[int]$_.ProcessId])/1MB,1);Profile=$prof} }

# 3. group
$rows | Group-Object Profile | ForEach-Object { ... }      # per window
$rows | Group-Object Type    | ForEach-Object { ... }      # per role
```

Why `--user-data-dir` is a sound grouping key: `Open-SlotWindow` gives every window its own profile
directory (`dshw.ps1:849-852`, `$profDir = Join-Path $Cfg.browser.profileRoot $slot.profile`), and the
profile path is inherited by that window's children. The attribution is therefore exact, not statistical.

**Count of `--app=` roots is the count of windows** — one `--app=` root per window, and children carry
`--type=`, so `CommandLine -match '--app=' ` and `-notmatch '--type='` yields exactly one row per window.

### 1.3 Result, taken 2026-09-16T10:25:21 (113 processes, 12 windows)

| slot | procs | private MB | | slot | procs | private MB |
|---|---|---|---|---|---|---|
| w1 | 10 | 259.7 | | w7 | 9 | 249.9 |
| w2 | 10 | 305.8 | | **w8** | 9 | **229.9** (leanest) |
| w3 | 9 | 247.5 | | **w9** | 10 | **800.8** (heaviest — this is my own session) |
| w4 | 9 | 233.0 | | w10 | 9 | 354.7 |
| w5 | 10 | 314.8 | | w11 | 9 | 286.2 |
| w6 | 10 | 326.6 | | w12 | 9 | 289.2 |

**Total 3,898.1 MB private / 113 processes. Mean 324.8 MB per window.**

| role | n | private MB | note |
|---|---|---|---|
| renderer | 24 | 1,952.9 | **exactly 2 per window** |
| gpu-process | 12 | 1,159.4 | **one per window — 96.6 MB each** |
| browser | 12 | 500.1 | one per window, 41.7 MB each |
| utility | 53 | 264.6 | 4–5 per window; includes a network service |
| crashpad-handler | 12 | 21.1 | one per window |

**Each window costs 1 browser + 1 GPU + 2 renderers + 4–5 utility + 1 crashpad = 9–10 processes.**

### 1.4 Shared vs per-window, from the data not from theory

Grouping by profile yields **exactly 12 disjoint process sets with no process in two sets** — there is no
shared browser process, no shared GPU process, and no shared renderer. The only sharing is the file-level
mapping of Edge's own binaries and data files, which is what the `WorkingSet`−`WorkingSetPrivate`
difference of **4,282.7 MB** is: read-only code and data pages mapped into 113 processes.

So: **per-window cost = ~325 MB private, of which ~81 MB is the browser+GPU+utility overhead of merely
existing and ~163 MB is renderer.** The remaining ~81 MB of renderer private bytes is the page itself.

Working-set counters drift upward as a window warms: the same fleet read 3,622.9 MB at 10:23:0x and
3,898.1 MB at 10:25:21 — **+275 MB in ~2 min across 12 windows (≈23 MB/min fleet-wide)**, because this
audit's own window (w9, 800.8 MB) is the one doing work. Any single reading is a snapshot, not a plateau.

### 1.5 Windows open vs slots enabled — the divergence

| | count |
|---|---|
| `windows.json` rows defined | 12 |
| rows with `enabled: true` (`windows.json:36-133`) | **8** (`w1`–`w8`) |
| rows with `enabled: false` | **4** (`w9`, `w10`, `w11`, `w12`) |
| `--app=` windows actually open | **12** |
| difference | **+4** |

The four disabled-slot windows (`w9`, `w10`, `w11`, `w12`) are **37 processes / 1,731 MB private** —
**44.4 % of the 3,898 MB Edge footprint and 11.1 % of a 31.61 GB machine.**

---

## 2. The `Invoke-New` defect

### 2.1 Confirmed, verbatim

`C:\Users\ezabz\code\harness-config\multi-window\dshw.ps1:1482`:

```powershell
    foreach ($slot in $slots) { $slot.enabled = $true }
```

It sits between the "is there a free slot" test and the actual window open:

```powershell
1460:     $free = @($slots | Where-Object { (Get-WindowCount $_ $procTable) -eq 0 }) | Select-Object -First 1
...
1482:     foreach ($slot in $slots) { $slot.enabled = $true }
1483:     [void](Open-SlotWindow $free $state)
```

`$slots` is not a copy. `Get-Slots` (`dshw.ps1:302-306`) builds the array out of
`Resolve-SlotInfo`, which returns `enabled = [bool]$slot.enabled` (`dshw.ps1:294`) — a fresh PSCustomObject
per call, so this mutation is confined to the one process. **The config file is never rewritten**, and so
the defect does not corrupt `windows.json`; it corrupts the launcher's *view* of it for the rest of that
invocation.

### 2.2 User-visible consequence, stated exactly

`$free` at line 1460 is chosen from **all 12 rows**, ignoring `enabled`. The reference to `windows.json`
says `enabled: false` "keeps the slot defined but **never opens it**". The line at 1482 exists purely so
that the slot picked at 1460 is not then rejected by any downstream `enabled` filter.

The consequence is a **one-way ratchet**: once the owner has disabled a slot to save memory, clicking
"new window" silently re-enables every disabled slot in that run and the next window opens into one of
them. Nothing ever writes `enabled: true` back to the disk, so `dshw status` and `dshw doctor` will keep
printing "8 enabled, 4 disabled" (`dshw.ps1:1542-1543`) **while 12 windows are on screen**, and the extra
four stay open until they are closed by hand. There is no self-correction: the file says disabled, the
machine says open, and the only thing that reconciles them is a human closing windows.

That is the state this machine is in right now (1.5): 8 enabled, 12 open, 4 extra windows, 1.73 GB.

### 2.3 Why the line exists, and what the "dead port" concern actually requires

The line is there to guarantee that `$free`, once picked, can be opened. The real invariant the author was
protecting is *"never hand the owner a window that cannot reach an engine"*, and `Invoke-New` already
handles that explicitly and correctly in the block at `dshw.ps1:1461-1481`: if no slot is free it ensures
an engine exists on `Get-PrimaryPort` before reporting. Line 1482 adds nothing to that guarantee — because
in `mode: "single"` **every slot resolves to the same port**, so the engine question is settled by the
port, not by the slot's `enabled` flag.

### 2.4 Minimal patch — proposed, NOT applied

Replace line 1482 with a filter. Behaviour changes in exactly one way: a slot the owner disabled is no
longer silently opened, while a genuinely new window still opens whenever an enabled slot is free.

```diff
--- a/multi-window/dshw.ps1
+++ b/multi-window/dshw.ps1
@@ -1453,9 +1453,13 @@ function Invoke-New {
     $state = Get-State
     $slots = Get-Slots
     # Counting open windows needs a full process-table read, which is the single most
     # expensive thing in this script on a loaded machine (measured 15-35 s, and it is what
     # made `up` appear to hang). It runs here only because `new` must pick a free slot;
     # `up` never pays for it.
     $procTable = Get-WindowProcs
-    $free = @($slots | Where-Object { (Get-WindowCount $_ $procTable) -eq 0 }) | Select-Object -First 1
+    # NEVER OPEN A SLOT THE CONFIG DISABLED. Measured 2026-09-16 on ZABZ-YOGA: this line used to be
+    # followed by `foreach ($slot in $slots) { $slot.enabled = $true }`, which force-enabled every row
+    # in windows.json before the pick -- so "new window" opened w9..w12, four rows the config marks
+    # `enabled: false`, and the fleet sat at 12 live windows against 8 enabled, +4 windows / 1.73 GB
+    # private. The disk was never rewritten, so status/doctor kept reporting 8 while 12 were on screen.
+    # `new` must narrow to what the config allows, not widen the config to fit what it picked.
+    $free = @($slots | Where-Object { $_.enabled -and (Get-WindowCount $_ $procTable) -eq 0 }) | Select-Object -First 1
     if (-not $free) {
         # NO FREE SLOT IS NOT THE SAME AS NOTHING TO DO.
         #
@@ -1479,7 +1483,6 @@ function Invoke-New {
         Write-Host "all $($slots.Count) window slots are already open. Add another row to windows.json." -ForegroundColor Yellow
         exit 0
     }
-    foreach ($slot in $slots) { $slot.enabled = $true }
     [void](Open-SlotWindow $free $state)
```

**Never lands the owner on a dead port.** The existing block at 1461–1481 is untouched, so the path that
starts an engine when no slot is free still runs first. With the filter, `$free` is `$null` only when every
*enabled* slot is occupied, which is precisely when the owner should be told to add a row — and the engine
is still ensured before that message. In `mode: "single"` the port is `Get-PrimaryPort` for every slot, so
no filtering can change which engine a window talks to.

Two smaller notes, both left unpatched because they are not bare minimum:

- The message at 1479 still counts `$slots.Count` (12) rather than the enabled count (8). It is now only
  reachable when all enabled slots are occupied, so it would read better as *"all N enabled window slots
  are already open"* with `N = @($slots | Where-Object { $_.enabled }).Count`.
- `Open-SlotWindow` sends geometry from the row (`--window-size`/`--window-position`), so a window opened
  into a disabled slot also takes that row's position — `w9`–`w12` all reuse `0,0 / 700,0 / 0,440 /
  700,440`, i.e. **the four extra windows stack exactly on top of `w1`–`w4`.**

---

## 3. Lean flags: what is on the live command line today

Command line read from a live `--app=` root, 2026-09-16 10:23:

```
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
  --app=http://127.0.0.1:3099/?token=<redacted>
  --user-data-dir="C:\Users\ezabz\.dsh\multi-window\browser\w1"
  --no-first-run --no-default-browser-check
  --disable-extensions --disable-component-extensions-with-background-pages
  --disable-background-networking --disable-component-update --disable-sync
  --disable-features=Translate,MediaRouter,msEdgeSidebarV2,msEdgeCollections,msEdgeShoppingAssistant,EdgeWallet,msEdgeIdentityFeature
  --window-size=700,440 --window-position=0,0
  --flag-switches-begin --flag-switches-end --do-not-de-elevate
```

| flag | on the line today? | what it is for | cost to capability |
|---|---|---|---|
| `--app=<tokenized url>` | **yes** | the app-window shape itself | none |
| `--user-data-dir=<profile>` | **yes** | per-window cookie jar + localStorage; also what makes geometry apply | none (it is the mechanism) |
| `--no-first-run` | **yes** | skips the import/onboarding flow | none |
| `--no-default-browser-check` | **yes** | skips "make Edge default" prompt | none |
| `--disable-extensions` | **yes** | no extension host, no extension renderers | none for DSH; **would break** any workflow that needs a browser extension |
| `--disable-component-extensions-with-background-pages` | **yes** | no Edge component extension background pages | none |
| `--disable-background-networking` | **yes** | stops the component/update/telemetry chatter | none |
| `--disable-component-update` | **yes** | no Edge component updater | none |
| `--disable-sync` | **yes** | no profile sync | none (profiles are local-only by design) |
| `--disable-features=Translate,MediaRouter,msEdgeSidebarV2,msEdgeCollections,msEdgeShoppingAssistant,EdgeWallet,msEdgeIdentityFeature` | **yes** | the 7 Edge panels/widgets that never render in a 700×440 app window | none for this use |
| `--window-size=700,440`, `--window-position=X,Y` | **yes** | the 4×2 grid | none |
| `--flag-switches-begin/--flag-switches-end` | **yes** | Edge's own marker pair, emitted by Edge | none |
| `--do-not-de-elevate` | **yes** | Edge-internal elevation marker | none |

**Every flag recorded in `PERFORMANCE-MEASURED.md:76-78` and in `dshw.ps1:864-876` is present on the live
command line. Nothing regressed or was dropped.** The set is exactly the 9 launch flags the launcher
documents plus Edge's own 3 internal switches.

**No flag in the set costs responsiveness or capability.** I will not claim a saving I cannot defend: none
of the nine disables a feature DSH uses. The one item that *would* touch capability is already present and
is the reason this fleet works at all — `--user-data-dir`, which costs ~97 MB per window in GPU process
that a shared profile would not pay (see §4).

**A flag that is NOT present and would save CPU** (raised as a candidate, not a recommendation, because it
is untested here): `--disable-renderer-backgrounding` is absent, so backgrounded windows are not throttled.
Measured cost of the 12 idle windows is **2.27 of 22 cores over a 10 s window** (msedge 22.69 cpu-seconds,
node 0.70 core). That is consistent with the prior per-window figure of 0.24–0.28 core idle
(`PERFORMANCE-MEASURED.md:171`). It is a real cost but it is not the binding constraint (§6), and I did not
test the flag, so I am not proposing it.

---

## 4. Is 12 windows the right shape?

### 4.1 Edge does not share processes across windows with different `--user-data-dir` — proved

Not inferred. The per-profile grouping in §1.3 partitions 113 processes into **12 disjoint sets**:

- **12 `gpu-process` processes, one per profile** (1,159.4 MB total). A shared profile gets one GPU
  process for the whole browser; 12 windows on 12 profiles got 12. **~96.6 MB per window is a pure
  consequence of profile separation.**
- **12 `browser` processes, one per profile** (500.1 MB total, 41.7 MB each).
- **24 renderers, exactly 2 per profile** — no renderer serves two windows.
- **12 `crashpad-handler` processes, one per profile.**

There is no cross-profile sharing of any process. So each window pays its own browser + GPU + crashpad, and
the only genuine sharing left is the read-only file mappings (4,282.7 MB of `WorkingSet`).

### 4.2 Cost of N windows vs one window with N tabs

| shape | browser procs | GPU procs | renderers | estimated private |
|---|---|---|---|---|
| 12 `--app=` windows, 12 profiles (**today**) | 12 | 12 | 24 | **3,898 MB (measured)** |
| 1 window, 12 tabs, 1 profile | 1 | 1 | 12–24 | **~1,900–2,100 MB (PROJECTED)** |
| 8 windows (the enabled set) | 8 | 8 | 16 | **~2,170 MB (PROJECTED ≈ 4/12 × 3,898 + heavy w9 share)** |

The projection subtracts the 11 browser processes (459 MB), 11 GPU processes (1,063 MB) and 11 crashpads
(19 MB) that a single-window shape would not create, and keeps a renderer per tab. **Projected, not
measured** — I did not open the single-window configuration, because this task was read-only.

### 4.3 Why the tab shape does not give him the same workflow — this is decisive, not a preference

`ANALYSIS-AND-DECISION.md:71-76`, from the installed bundles and verified against on-disk LevelDB:

> Session choice lives in **`localStorage["dsh.sessions.current"]`**, keyed by **origin**
> (scheme+host+**port**), read once at page load (`dsh-api-session-controller/lib/client.js:3058`).
> **Consequence:** two windows on the same port share that one key — **last writer wins on reload**.

Two facts combine:

1. `research-session-urls.md:144-145` — "the only URL that means anything is `http://<host>:<port>/`… **Session
   identity is never in the URL**." No `pushState`, no `#`, no query parameter reads a session id; the SPA
   serves `index.html` **only at `/`** and every other path 404s.
2. `localStorage` is per-origin and **shared across every tab of that origin** — including tabs of the same
   window.

Therefore **N tabs in ONE window on ONE port do not give N independent sessions; they give one session
slot written by N pages.** Whichever tab wrote `dsh.sessions.current` last wins, and any other tab that
reloads lands on *that* session. A tab-based shape therefore collapses the owner's "many sessions in
parallel" workflow to a single session — unless every tab is a **different origin**, i.e. a different port,
i.e. a second engine (`mode: "multi"`), which `windows.json:5` rules out for the measured reason that two
`dsh web` processes on one `DSH_HOME` wrote duplicate sequence numbers into one session log and made the
whole history unloadable.

**So the isolation he is buying with 12 windows is not a luxury that a tab would also provide. It is the
only thing that provides it.** Independent parallel sessions on one engine require independent origins, and
`--user-data-dir` per window is how this build gets them without a second engine.

What tabs *would* keep is memory, and what they *would* break is exactly the thing the owner asked for.
That is why the answer to "is 12 the right shape" is **not "use tabs"** — it is "8 windows is the right
shape, and 12 is the wrong number for a different reason".

### 4.4 What the restore limitation means for a tab-based shape

"Restore the window, then click the session" (`ANALYSIS-AND-DECISION.md:78`) is a **one-click-per-window**
tax — with 8 windows, 8 clicks after a reboot. A tab-based shape does not remove the tax, it *adds* to it:
restoring 8 tabs in one window restores 8 pages that all read the same `dsh.sessions.current` key, so only
one of them opens on the session it had, and the other seven open on **each other's** sessions. The
restore mechanism depends on the browser profile being a stable per-session container. Take the profile
away and the restore story gets worse, not better.

### 4.5 Verdict

- **12 windows is the wrong number: it should be 8.** Not because 12 is unaffordable — it is affordable,
  §6 — but because 4 of them are slots the owner explicitly disabled and they cost 1,731 MB, ~44 % of the
  browser footprint, for capability he turned off on purpose.
- **The window shape is correct.** One window with N tabs cannot deliver N parallel sessions on one engine
  (§4.3). 8 windows × ~271 MB is the shape that fits this machine with headroom.
- **The cost driver to watch is not the window count, it is the renderer of whichever window is streaming**
  (`PERFORMANCE-MEASURED.md:170-171`), which is why `w9` reads 800.8 MB here against a 229.9 MB floor.

---

## 5. ZABZ-TECH parity — **NOT TAKEN. SSH is unavailable.**

**No counterpart measurement exists. Every ZABZ-TECH field below is unmeasured.**

### 5.1 What was tried, in the order specified

| # | command | result |
|---|---|---|
| 1 | `ssh -o BatchMode=yes -o ConnectTimeout=10 zabz-tech hostname` | `ssh: connect to host 192.168.50.138 port 22: Connection timed out` |
| 2 | `ssh -o BatchMode=yes -o ConnectTimeout=10 desktop hostname` | `ssh: connect to host 192.168.50.138 port 22: Connection timed out` |
| 3 | `ssh -o BatchMode=yes -o ConnectTimeout=10 desktop-ts hostname` | `ssh: Could not resolve hostname zabz-tech.tail93e6e6.ts.net: No such host is known.` |
| 4 | `ssh -o BatchMode=yes -o ConnectTimeout=10 zabz-tech-pc-lan hostname` | `ssh: connect to host 192.168.50.138 port 22: Connection timed out` |

All four alias shapes are defined in `C:\Users\ezabz\.ssh\config`; the LAN aliases all resolve to
`192.168.50.138`, the mesh aliases to `zabz-tech.tail93e6e6.ts.net`.

### 5.2 Why each failed — measured, not assumed

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' ip -4
# no current Tailscale IPs; state: NoState
& '...tailscale.exe' status --json | ConvertFrom-Json | Select -Expand BackendState
# NoState
```

- **This laptop is not on the network it is documented as being on.** `netcheck` reported
  `portmap: monitor: gateway and self IP changed: gw=192.168.12.1 self=192.168.12.104`. The addresses in
  `~/.ssh/config` (office `192.168.50.x`, home `192.168.50.244`) are both `192.168.50.x`; this machine
  holds `192.168.12.104` on `Ethernet`, with `NetworkCategory Public`. It is on neither documented network.
- **The tailnet interface is down**, not merely slow: `Get-NetIPAddress` shows the `Tailscale` adapter with
  `169.254.83.107` (APIPA) and `Get-NetConnectionProfile` reports it `NoTraffic`. MagicDNS therefore cannot
  resolve `zabz-tech.tail93e6e6.ts.net` — the failure at #3.
- **Tailscale is not dead, it is unstarted for this network.** `tailscale status` lists every peer
  including `100.85.153.96 zabz-tech windows` and `100.84.72.88 secratary linux`, and its own header says
  `# Health check: - Tailscale is starting. Please wait.` `netcheck` succeeded from the public path
  (`UDP: true`, `IPv4: yes 172.59.215.73:1209`, nearest DERP `nyc 43.4 ms`). Confirmed by direct dial:
  `Test-NetConnection 100.85.153.96 -Port 22` → **False**; `100.84.72.88` → **False**. **ZABZ-TECH is not
  the only unreachable peer — the authority (`secratary`) is unreachable from here too.**
- `desktop-cf` / `zabz-tech-cloudflare` was considered and **not tried**: its `ProxyCommand` runs through
  `CloudflaredAccessSshProxy.ps1 -Hostname %h` against `desktop-ssh.abletelsolutions.com`, which is a
  different path and was outside the four aliases specified; and with the tailnet down it is not obviously
  a working alternative. No fix was attempted, per instruction.

**Precedent, found while reading the evidence base:** `research-resource-cost.md:60-61` records the same
wall on 2026-09-11 — *"`ZABZ-TECH` (i9 / 64 GB) was **not reachable from this session** … the only path is
Tailscale. I did not attempt to measure it. `UNVERIFIED:` all ZABZ-TECH figures"*. This is a recurring
condition, not a one-off.

### 5.3 Fields requested and why each is unmeasured

| field | status |
|---|---|
| OS build | **NOT MEASURED** |
| logical cores | **NOT MEASURED** |
| total / available memory | **NOT MEASURED** |
| commit charge | **NOT MEASURED** |
| process count / node process count | **NOT MEASURED** |
| number of `dsh web` engines and ports | **NOT MEASURED** |
| live MCP server processes, duplicate generations | **NOT MEASURED** |
| `~/.dsh/settings.yaml` `agent-loop.maxParallelToolCalls` | **NOT MEASURED** |
| `C:\Users\ezabz\.dsh\tools\mcp` exists | **NOT MEASURED** |
| `NODE_COMPILE_CACHE` set | **NOT MEASURED** |
| browser windows / processes | **NOT MEASURED** |
| `harness-config` at the same commit | **NOT MEASURED** |

For reference so the comparison can be finished mechanically when the path is up, **ZABZ-YOGA's** values
for the same fields are in the final table (§7).

---

## 6. A per-machine resource budget, from measurement

### 6.1 ZABZ-YOGA, measured 2026-09-16 ~10:25

| quantity | value | source |
|---|---|---|
| physical RAM | **31.61 GB** | `Win32_ComputerSystem.TotalPhysicalMemory` |
| free physical | **14.26 GB** | `Win32_OperatingSystem.FreePhysicalMemory` |
| commit limit | **43.11 GB** | `TotalVirtualMemorySize` |
| commit charge | **20.65 GB** | limit − `FreeVirtualMemory` |
| commit available | **22.47 GB** | `FreeVirtualMemory` |
| pagefile | **11.5 GB allocated, 0.016 GB used** | `Win32_PageFileUsage` (CurrentUsage 16 MB, PeakUsage 16 MB) |
| logical cores | 22 | `NumberOfLogicalProcessors` |
| processes | 405 | `(Get-Process).Count` |
| msedge | 113 procs, 3,898 MB private | §1.3 |
| engine tree (pid 15960 + descendants) | 21 procs, **1,564 MB private** | walk of `ParentProcessId` |
| MCP bridges | **8 node procs, ~355 MB** (4 local + 2 npx + 2 other) | engine tree by name + command line |

### 6.2 What "paging starts" means here, precisely

The tripwire is documented at `PERFORMANCE-MEASURED.md:182-184`: *"**if commit crosses 31.61 GB the machine
starts paging** to an 11.5 GB pagefile, and that is the point at which it will feel genuinely slow."* The
commit **limit** is 43.11 GB, so Windows will not refuse an allocation until 43.11 GB — but past 31.61 GB
it must back pages with the pagefile instead of RAM, and that is when a human notices. The measured
current state is far from it: **pagefile usage 16 MB of 11.5 GB allocated, peak 16 MB** — this machine has
not paged at all in this boot.

**Therefore the budget is against 31.61 GB, not 43.11 GB.**

```
headroom to the tripwire   = 31.61 GB (physical) − 20.65 GB (commit now)
                           = 10.96 GB
```

### 6.3 Browser windows

The commit charge already contains the 12 live windows, so the marginal figure is the per-window private
cost, using the measured current fleet:

```
marginal cost per window   = 3,898.1 MB / 12 = 324.8 MB
```

| windows | marginal GB | commit after | headroom to 31.61 GB |
|---|---|---|---|
| 12 (today) | 3.90 | 20.65 (measured) | **10.96 GB** |
| 16 | 5.20 | 21.95 | 9.66 GB |
| 24 | 7.80 | 24.55 | 7.06 GB |
| 32 | 10.39 | 27.14 | 4.47 GB |
| **40** | **12.99** | **29.74** | **1.87 GB** |
| 46 | 14.94 | 31.69 | **−0.08 GB → paging** |

**At 12 windows the machine still has 10.96 GB of headroom.** The arithmetic puts the paging threshold at
**~46 windows** with agents idle. That is the honest shape of this budget: *the window count is nowhere
near the binding constraint*, which is why §4.5 says the fix for the 4 spare windows is correctness, not
memory — 1.73 GB reclaimed is real but it is 16 % of the headroom, not a rescue.

Note the marginal figure understates the heavy case: `w9` reads 800.8 MB because it is running this audit.
A window whose agent is streaming costs ~750 MB private (`PERFORMANCE-MEASURED.md:170`). **32 windows all
streaming would be ~24 GB and would page.** So the constraint is not "windows", it is "windows that are
working".

### 6.4 Concurrently RUNNING agent turns

Two independent costs, both measured, and they add:

**(a) The engine's own agent loop.** The engine tree is **1,564 MB at 12 sessions attached**, of which the
`dsh web` root alone is **828 MB private** (pid 15960). Prior measurement: *"an idle fully-bootstrapped
engine with no session and no MCP is 200 MB private"* (`research-resource-cost.md:18`). So 12 attached
sessions cost the engine `1564 − 200 = 1,364 MB`, i.e. **~114 MB per attached session** while idle-ish.
The engine's loop does not multiply per running turn — it is one event loop, measured at 0.08 of one core
over 2.5 h (`PERFORMANCE-MEASURED.md:154`).

**(b) The per-turn cost is in the windows and the tool runners, not the engine.** Measured:

```
per window whose agent is generating : ~750 MB private, 1.0-1.1 of one core   (PERFORMANCE-MEASURED.md:170)
per window sitting quiet             : 467-783 MB private, 0.24-0.28 of one core (PERFORMANCE-MEASURED.md:171)
per parallel tool call               : ~57 MB (dsh-subprocess-local runner)     (research-resource-cost.md:20)
```

The prior run of **10 windows all running = commit 28.6–28.8 GB of 31.61 GB, 2.8–3.3 GB headroom, free RAM
draining ~370 MB/min** (`PERFORMANCE-MEASURED.md:178-179`). That is the measured envelope, and it is the
number to budget from — not my 20.65 GB, which is a semi-idle fleet.

```
measured:  10 running turns → commit 28.7 GB → headroom 2.9 GB
slope:     (28.7 − 20.65) GB / (10 − 0) turns = 0.81 GB per running turn
```

| concurrently RUNNING turns | commit ≈ | headroom to 31.61 GB |
|---|---|---|
| 0–2 (today, measured) | 20.65 GB | **10.96 GB** |
| 4 | 23.9 GB | 7.7 GB |
| 6 | 25.5 GB | 6.1 GB |
| 8 | 27.1 GB | 4.5 GB |
| **10 (measured)** | **28.7 GB** | **2.9 GB** |
| 12 | 30.4 GB | 1.2 GB |
| 13 | 31.2 GB | 0.4 GB |
| **14** | **32.0 GB** | **paging** |

**At 10 running turns the machine still has 2.9 GB of headroom** — measured, not modelled. The paging
threshold on the running-turn axis is **~13–14 simultaneous running turns** *with 8–12 windows attached
and no other load*. This is the binding constraint on this machine, and it is ~0.81 GB per turn, which is
why the answer to "how many windows" (§6.3, ~46) and "how many running turns" (~13) are so different.

### 6.5 In-flight shell tool calls

```
per in-flight shell tool call = 57.3 MB mean (dsh-subprocess-local runner, n=10, research-resource-cost.md:20)
maxParallelToolCalls          = 20  (~/.dsh/settings.yaml, this machine)
```

Worst case at the configured ceiling, assuming a shell call per slot:

```
20 × 57.3 MB = 1,146 MB = 1.12 GB
```

| in-flight shell calls | marginal | fits at 10 running turns (2.9 GB headroom)? |
|---|---|---|
| 4 | 0.23 GB | yes, 2.67 GB left |
| 10 | 0.57 GB | yes, 2.33 GB left |
| **20 (current ceiling)** | **1.12 GB** | **yes, 1.78 GB left** |
| 50 | 2.87 GB | **no — this is the paging line at 10 turns** |

**The configured `maxParallelToolCalls: 20` sits inside the budget with 1.78 GB to spare at 10 running
turns.** Raising it to 50 would not. Note the ceiling is per-turn, so N turns each fanning out to 20 calls
multiplies — the numbers above hold for one turn fanning out, and 10 turns × 20 calls would need 11.5 GB,
which does not fit.

### 6.6 The budget, stated as capability and not as a cap

- **At 12 windows / 0–2 running turns: 10.96 GB headroom** (measured 20.65 GB commit).
- **At 10 running turns with 8–12 windows: 2.9 GB headroom** (measured 28.7 GB commit).
- **At 10 running turns and 20 in-flight shell calls: 1.78 GB headroom.**
- The first thing to go is not windows and not CPU — it is **commit, once more than ~13 turns run at
  once**, and the second is **free RAM draining ~370 MB/min** while they run.
- CPU has 22 cores and the current fleet uses **~3 cores** (msedge 2.27, node 0.70 over a 10 s window).
  **CPU is not a constraint at any fleet size measured here.**

---

## 7. ZABZ-YOGA vs ZABZ-TECH

| field | ZABZ-YOGA (measured 2026-09-16) | ZABZ-TECH |
|---|---|---|
| OS | Windows 11 Home, 10.0.**26200** | **NOT MEASURED — SSH unreachable** |
| logical cores | **22** | **NOT MEASURED** |
| total physical RAM | **31.61 GB** | **NOT MEASURED** (documented as 64 GB, unverified) |
| free physical | **14.26 GB** | **NOT MEASURED** |
| commit charge | **20.65 GB** | **NOT MEASURED** |
| commit limit | **43.11 GB** | **NOT MEASURED** |
| commit available | **22.47 GB** | **NOT MEASURED** |
| pagefile | 11.5 GB alloc, **16 MB used** | **NOT MEASURED** |
| total processes | **405** | **NOT MEASURED** |
| node processes | **12** (1 engine, 8 MCP bridges, 2 dev servers, 1 npx) | **NOT MEASURED** |
| `dsh web` engines | **1** (pid 15960, port **3099**) | **NOT MEASURED** |
| MCP server processes | **8 node procs, ~355 MB**; **two generations present** — 4 from `C:\Users\ezabz\.dsh\tools\mcp` (182 MB) and 2 from the `_npx` cache (89 MB), 2 other (84 MB) | **NOT MEASURED** |
| duplicate MCP generations | **YES — local `.dsh\tools\mcp` install co-exists with npx-cached copies** | **NOT MEASURED** |
| `agent-loop.maxParallelToolCalls` | **20** | **NOT MEASURED** |
| `C:\Users\ezabz\.dsh\tools\mcp` exists | **YES** (full dependency tree present) | **NOT MEASURED** |
| `NODE_COMPILE_CACHE` | **set** = `C:\Users\ezabz\AppData\Local\node-compile-cache` (User scope) | **NOT MEASURED** |
| browser windows | **12** (8 enabled, 4 disabled-and-open) | **NOT MEASURED** |
| browser processes | **113**, 3,898 MB private / 8,181.6 MB Σ WorkingSet | **NOT MEASURED** |
| `harness-config` commit | **`75cdbca`** (+ 3 modified tracked files, several `_scratch/` untracked) | **NOT MEASURED** |
| Tailscale | **`NoState`** — tailnet iface APIPA `169.254.83.107`, `NoTraffic`, peers listed but undialable | — |

**Whether ZABZ-TECH is in better or worse shape: UNKNOWN.** There is no measurement. Given 64 GB vs
31.61 GB it has roughly twice the commit headroom per §6.2's arithmetic, but that is the documented spec,
not a reading, and I did not verify it.

---

## 8. Summary of what could not be measured

1. **Every ZABZ-TECH field in §5.3 and §7.** SSH unreachable on all four prescribed aliases; the laptop is
   on an undocumented network (`192.168.12.104`) and its Tailscale interface is in `NoState`/APIPA, so the
   mesh path is down as well. The authority `secratary` (`100.84.72.88`) is unreachable from here too.
   Per instruction, no fix was attempted.
2. **The single-window/12-tab configuration (§4.2).** The tab-shape figure of ~1,900–2,100 MB is a
   projection from the measured per-role costs; building it would have meant opening browser windows,
   which this task forbade.
3. **The exact `windows.json` in force at 10:16:56 today.** 12 windows were created in one 250 ms-staggered
   burst (`windows.log`) — the signature of `Invoke-Up -WindowsMode` iterating `$enabledWindows`
   (`dshw.ps1:1040`), which reads 8 today and read 8 in every commit back to `f40579e` (2026-09-11), with
   the working tree byte-identical to `HEAD`. I could not reconcile the burst with the 8-enabled filter and
   am reporting the discrepancy rather than guessing: **the live/window-count divergence in §1.5 is
   established fact; the call path that produced today's 12 is not.** The `Invoke-New` mechanism in §2 is
   confirmed by reading, and is sufficient to produce the same state; `dshw new` also logs through
   `Init-WindowLog`, so both paths write the same log line.
4. **`session/list` for the running-turn count.** The engine returned **401 Unauthorized** for
   `session/list`, `session/health` and `company/status` at `http://127.0.0.1:3099/api/<method>`, so the
   "N of M sessions running" figure could not be read live. §6.4 uses the prior session's measured
   10-running-turn envelope (`PERFORMANCE-MEASURED.md:138,178`) instead.
5. **A `--disable-renderer-backgrounding` A/B.** Raised in §3 as a CPU candidate, not tested.
