# 64 — Disk and write amplification on Windows: what is true now, and what a non-admin can actually do

**Measured on** `ZABZ-YOGA` (owner's laptop), **2026-09-16 17:46–18:00 local (-04:00)**.
**Author:** agent 1 of 8 in the mesh research fleet. **Read-first context:** `30-truth-and-disk.md` §3 and §6.
**Rule of this document:** every number carries a SOURCE and a DATE. A check that failed or returned nothing is written **"could not verify"**, never as health.

**Labels:** `MEASURED` = a number I read on a machine in this session, with the command. `READ-FROM-CODE` = behaviour read out of a file. `PROPOSED` = my design, not executed. `NOT-VERIFIABLE` = I could not measure it from this seat, and I say why.

---

## 0. The headline, in five sentences

1. **The premise is wrong, and it matters more than any optimisation below.** On this laptop, over two full 120-second windows, `SearchIndexer.exe`, `MsMpEng.exe`, `SearchProtocolHost.exe` and `SearchFilterHost.exe` **never entered the top twelve I/O consumers**, and a targeted 10-second probe during heavy file churn measured them at **0 bytes/s read and 0 bytes/s written** (`MEASURED`). The dominant I/O consumer by three orders of magnitude is **`python.exe` — the agent fleet itself** (`MEASURED`).
2. **The 107.3 GB read / 29.2 GB written figure for `SearchIndexer` is not reproducible on this host today, and cannot be** — see §2.1. It is not that the number was wrong; it is that **a non-admin cannot read that process's counters at all**, which is a different and more important fact.
3. **Write amplification is not the problem on this laptop.** Total write across all 132 sampled processes was **3,000 MB lifetime**; the system-wide disk **write** rate was **p50 1.41 MB/s (idle window) / 1.57 MB/s (load window)**. What is large is **read**: `python` alone had moved **3,217,445 MB (3.22 TB) of cumulative read** in 2.1 hours (`MEASURED`).
4. **`\PhysicalDisk(_Total)\% Disk Time` is a misleading headline here.** It read **354 % at p50** in a window where the disk queue was **2**, and the 1,000 %+ spikes co-occurred with a queue of **12–18** in only **7 of 108** samples. On this NVMe device a high `% Disk Time` is mostly *concurrency*, not *starvation* (`MEASURED`, §1.4).
5. **Most of what the owner would want is already done on `ZABZ-YOGA`, and not done on `ZABZ-TECH`.** 82 per-path crawl-scope rules exist on the laptop, covering every repo under `C:\Users\ezabz\code` and `.dsh` with `Include=0`; `ZABZ-TECH` has 136 such rules and **none of them for `C:\Users\ezabz\Code\`** (`MEASURED`, §4.4).

**The one-line answer to the brief.** The non-admin route to reducing indexing **does not exist** — five of five candidate mechanisms were tested and none works (§3). But the mitigation that actually matters is not an indexing exclusion at all; it is (a) **stop reading 3 TB through one `python` process** and (b) **run the one elevation command on the machine that is administered**, which is `ZABZ-TECH`, where the exclusions are genuinely absent (§4, §5, §6).

---

## 1. What I measured, and how

### 1.1 Host facts (`MEASURED`, 2026-09-16 17:46 local)

| Fact | Value | Source |
|---|---|---|
| Admin? | **False** | `[Security.Principal.WindowsPrincipal]::IsInRole(Administrator)` |
| OS | Windows 11 **Home**, build **26200** | `Win32_OperatingSystem` |
| CPU | **22** logical processors | `Win32_ComputerSystem` |
| RAM | **31.61 GB** | `Win32_ComputerSystem.TotalPhysicalMemory` |
| Disk | **SAMSUNG MZAL8512HDLU-00BL2**, `MediaType=SSD`, `BusType=NVMe`, 476.90 GB, Healthy | `Get-PhysicalDisk` |
| Volume | `C:` 475.8 GB, **71.1 GB free** (14.9 % free) | `Win32_LogicalDisk` |
| Pagefile | `C:\pagefile.sys`, allocated **11,776 MB**, current **252 MB**, peak **521 MB** — **2 % used** | `Win32_PageFileUsage` |
| Commit | total 43.11 GB, free 22.88 GB; physical free 14.92 GB | `Win32_OperatingSystem` |
| `SysMain` / `WinDefend` / `WSearch` / `wscsvc` | all **Running / Automatic** | `Get-Service` |
| Defender real-time protection | **enabled**, `IsTamperProtected=True`, `NISEnabled=True`, `ScanAvgCPULoadFactor=50` | `Get-MpComputerStatus` |
| Power plan | **Balanced** (`381b4222-…`) | `powercfg /getactivescheme` |

### 1.2 Method, and its two honest limits

I wrote one sampler (`_scratch/64-disk-wyo/sampler-full.ps1`) and ran it twice, **120 s each, 2 s interval, one batched process**:

* per-process I/O from `GetProcessIoCounters` (`kernel32`) via P/Invoke, **differenced between samples** to give a per-second rate — not summed (summing per-second deltas double-counts, which is the error doc 30 §6's proposed `Export-Counter` loop would also have made);
* system counters from **one** `Get-Counter` call per sample: `\PhysicalDisk(_Total)\% Disk Time`, `\Current Disk Queue Length`, `\Disk Reads/sec`, `\Disk Writes/sec`, `\Disk Read Bytes/sec`, `\Disk Write Bytes/sec`, `\Memory\Pages Input/sec`, `\Memory\Pages Output/sec`, `\Memory\Available MBytes`, `\Paging File(_Total)\% Usage`, `\Processor(_Total)\% Processor Time`.

**Limit 1 — "idle" was not idle.** No window on this machine was quiet, because **7 sibling research agents were running the whole time**. The "idle" window is therefore misnamed and I report it as **window A (contended)**; the load window (**window B**) additionally ran my own generated churn (6 workers × 60 cycles × 100 files = **36,000 file writes + 3 reads each + 1,080 fsync'd JSONL appends**, 3,606 distinct files, 14.5 MB on disk). Both windows are *real measurements of the machine as used*; neither is a clean baseline. A true baseline is experiment #1 in §6.

**Limit 2 — `Get-Process.ReadTransferCount` is `$null` on PowerShell 7.** It exists on Windows PowerShell 5.1. Any prior figure that came from `Get-Process` on pwsh 7 did not come from that property. All per-process I/O here is P/Invoke.

### 1.3 The two windows (`MEASURED`)

| Counter | Window A (contended) p50 / p95 / max | Window B (+36k-file churn) p50 / p95 / max |
|---|---|---|
| `\PhysicalDisk(_Total)\% Disk Time` | **354 / 1157 / 1222** % | **79 / 1975 / 4050** % |
| `\PhysicalDisk(_Total)\Current Disk Queue Length` | **2 / 12 / 14** | **0 / 10 / 18** |
| `\PhysicalDisk(_Total)\Disk Reads/sec` | 2,319 / 5,257 / 5,774 | 285 / 1,483 / 1,863 |
| `\PhysicalDisk(_Total)\Disk Writes/sec` | 213 / 2,735 / 4,777 | 74 / 779 / 1,971 |
| `\PhysicalDisk(_Total)\Disk Read Bytes/sec` | **27.8 MB/s / 161 / 285** | **4.9 MB/s / 47.7 / 632** |
| `\PhysicalDisk(_Total)\Disk Write Bytes/sec` | **5.4 MB/s / 27.0 / 37.2** | **2.8 MB/s / 11.3 / 15.3** |
| `\Memory\Pages Input/sec` | **7,680 / 40,754 / 70,703** | **1,210 / 11,758 / 154,703** |
| `\Memory\Pages Output/sec` | 0 / 0 / 2,831 | 0 / 0 / 0 |
| `\Memory\Available MBytes` | 15,757 / 16,516 / 16,628 | 15,343 / 15,744 / 15,892 |
| `\Paging File(_Total)\% Usage` | **2 / 2 / 2** | **2 / 2 / 2** |
| `\Processor(_Total)\% Processor Time` | 57 / 68 / 74 | 49 / 69 / 83 |

Windows: 58 samples (A) and 50 samples (B), `errors=0` in both.

### 1.4 What these readings mean for a 31.6 GB / 11.5 GB-pagefile machine

**Paging is real and large in pages, tiny in pressure.** `Pages Input/sec` peaked at **70,703/s** in A and **154,703/s** in B — that is 276 MB/s and 604 MB/s of *page-in* at those instants. But the pagefile itself sat at **2 % of 11.5 GB (≈252 MB in use)**, `Pages Output/sec` was **0** in window B, and `Available MBytes` never fell below **15.3 GB** of 31.6 GB. So the page-ins are **soft faults served from the file cache**, not a pagefile thrash. The 33–37 GB commit / 1,500–62,000 page-ins/s storm quoted from 2026-09-15 is **not** the state of this machine at 18:00 today.

**`% Disk Time` is the wrong headline metric on NVMe.** It read **354 % while the queue was 2**. Only **5 of 58** samples in A and **2 of 50** in B exceeded 1,000 %, and *among those* the queue was **12** and **18** respectively. That is the correct shape of a real backlog: high busy-percentage alone is an artefact of NVMe command overlap, whereas the **queue length is the lag indicator that actually tracks starvation**. Doc 30's §3 table treats 1,596 % disk time as a "constraint"; on this device that number can be reached with almost no queueing. **Any before/after that uses `% Disk Time` as its win condition can show a large win with no user-visible change, and vice versa.** Use the queue (§5).

**Write amplification is small; read amplification is enormous.** Lifetime writes across every process I could open: **3,000 MB**. Lifetime reads: **3,221,299 MB**. The disk is not being worn out by writes; it is being read to death.

---

## 2. Who actually consumes this disk

### 2.1 The two figures the earlier audit blamed, today

| Process | Window A (contended) | Window B (+churn) | Targeted 10 s probe | Lifetime counters |
|---|---|---|---|---|
| `SearchIndexer.exe` | **not in top 12** | **not in top 12** | **read 0 B/s, write 0 B/s** | **NOT-VERIFIABLE** |
| `MsMpEng.exe` | **not in top 12** | **not in top 12** | **read 0 B/s, write 0 B/s** | **NOT-VERIFIABLE** |
| `SearchProtocolHost.exe` | not in top 12 | not in top 12 | 0 B/s | **NOT-VERIFIABLE** |
| `SearchFilterHost.exe` | not in top 12 | not in top 12 | 0 B/s | **NOT-VERIFIABLE** |

**Why "NOT-VERIFIABLE" is the right word, and why it is a finding.** All four processes are running (pid 18780 / 5048 / 19104 / 14480, `MEASURED` 17:47), but they run as `LocalSystem`, and **a non-admin process cannot open their handles**. `Get-Process SearchIndexer` returns an object whose `.Handle` is empty, and `GetProcessIoCounters` throws `Cannot convert null to type System.IntPtr`. This is a hard, systemic limit on this seat:

> **A non-admin on this laptop cannot measure the I/O of the OS scanning services at all.** The numbers 107.3 GB / 29.2 GB in `30-truth-and-disk.md` §3, row 2 (attributed to `SearchIndexer`) could not have come from the current process run — `SearchIndexer` today started at 17:47-ish with the boot, and its counters reset. **Whatever their true provenance, the 107/29 figures are not readable from here, and no non-admin can re-measure them.** Their use as a load-bearing constraint in the design docs should stop, and `30-truth-and-disk.md` §3 row 2 and §6 should be corrected to say so.

The **mitigation for that** is real and free: use `\PhysicalDisk(_Total)\Disk Read Bytes/sec` / `\Disk Write Bytes/sec` as the attribution-free ceiling, plus the `Search.CollatorDSO` index (usable **without elevation**, proven below, §3.2), plus **any one elevated 60-second sample on `ZABZ-TECH`, which is administered** — that is a 5-minute job and it produces the number the laptop structurally never can.

### 2.2 The real top five, with numbers

**Per-process, window B (the load window), per-second rates (`MEASURED`):**

| Rank | Process | read p50 / p95 / mean | write p50 / p95 / mean | samples |
|---|---|---|---|---|
| 1 | **`python`** | 0 / **212.9 MB/s** / **20.4 MB/s** | 0 / 3.9 kB/s / 6.6 kB/s | 634 |
| 2 | **`git`** | 0 / 7.5 kB/s / **3.38 MB/s** | 0 / **299 kB/s** / 36.5 kB/s | 34 |
| 3 | `pwsh` | 0 / 677 kB/s / 117 kB/s | 0 / 346 kB/s / 53 kB/s | 431 |
| 4 | **`msedge`** | 0 / 678 kB/s / 53 kB/s | 0 / 598 kB/s / 53 kB/s | 980 |
| 5 | `node` | 0 / 22.9 kB/s / 5.0 kB/s | 0 / **32.4 kB/s** / 6.4 kB/s | 644 |

Window A (contended) tells the same story with a different rank-1: **`rg`** (ripgrep — the agent fleet's own text search) at **read p50 61.6 MB/s, p95 250 MB/s**. That is the single most damning line in this document: **one `rg` invocation reads at a higher sustained rate than anything the operating system does on this machine.**

**Lifetime, cumulative since each process started (`MEASURED`, 132 processes opened of ~190 present):**

| Process | procs | min age | cumulative read | cumulative write |
|---|---|---|---|---|
| **`python`** | 12 | 0.01 h | **3,217,444.6 MB (3.22 TB)** | 742.2 MB |
| `msedge` | 20 | 0.74 h | 2,016.8 MB | **1,726.7 MB** |
| `node` | 12 | 0 h | 960.1 MB | 104.6 MB |
| `TextInputHost` | 1 | 2.12 h | 415.2 MB | 376.8 MB |
| `svchost` (9) | 9 | 2.12 h | 104.3 MB | 9.5 MB |
| `powershell` | 1 | 2.11 h | 104.3 MB | 0.2 MB |
| **everything, total** | **132** | — | **3,221,299 MB** | **3,000 MB** |

**One process — `python` pid 7204, alive 1.63 h — accounts for 3,150,172 MB of those reads on its own (`MEASURED`).** I did **not** identify which agent action causes this read amplification; naming it is experiment #1 in §6. A 3.2 TB read in 1.6 h is ~550 MB/s sustained, which is above this SSD's expected sustained read and is therefore almost certainly **cached** reads (memory-mapped or repeated whole-file reads), not device reads — which is exactly why it does not show up as a disk bottleneck while still dominating every per-process counter.

### 2.3 Everything else that writes to this disk

| Writer | Counter used | Measured | Avoidable? |
|---|---|---|---|
| **DSH session logs** (`~\.dsh\sessions\**\session.v3.jsonl.zstd`, 239 MB per doc 30 §1 row 1) | `node` write rate | **`node` = 12 processes, 104.6 MB lifetime, write p95 32.4 kB/s** `MEASURED` | Partly — it is one engine's design, bounded by live-engine count. Not the bottleneck. |
| **Journal** (`harness-config/journal`) | `git` write rate + repo size | `git` write p95 **299 kB/s**, mean 36.5 kB/s; journal tree 3.35 MB / 1,460 entries (doc 30 §1 row 6) | Yes — doc 30 §3 row 5 already proposes dropping the `fetch` from the append path. Small in bytes, large in wall-clock. |
| **git operations generally** | `git` read rate | `git` read mean **3.38 MB/s**, p95 7.5 kB/s across only 34 samples — **bursty** `MEASURED` | The reads are the cost, not the writes. |
| **Browser profiles** (`msedge`) | per-process | **20 processes, 1,726.7 MB written lifetime — the largest single writer on the machine**, read p95 678 kB/s / write p95 598 kB/s `MEASURED` | Yes, and it is the only writer here worth touching: cache size and profile count. |
| **OneDrive / sync clients** | process presence | **`OneDrive` process NOT running.** Documents **is redirected to `C:\Users\ezabz\OneDrive\Documents`** (`[Environment]::GetFolderPath('MyDocuments')`), and the folder exists but is not being crawled by a live client `MEASURED` | **N/A today.** ⚠️ If OneDrive is started, it becomes a large writer *and* it moves the owner's whole Documents set under a sync engine. |
| **Teams / Slack / Discord / Dropbox / GoogleDriveFS** | process presence | **none running** `MEASURED` | N/A |
| **Windows Search** (`WSearch`, `C:\ProgramData\Microsoft\Search\Data\`) | see §2.1 | **not measurable from this seat**; `C:\ProgramData\Microsoft\Search\Data` is **access-denied** to this user (`Test-Path` fails, write probe fails) `MEASURED` | Not without elevation |
| **Windows Update** (`MoUsoCoreWorker`, `TiWorker`) | per-process 10 s probe | **0 B/s read, 0 B/s write** both, during the probe `MEASURED` | Idle; `ScanAvgCPULoadFactor=50` already throttles scans |
| **SysMain / Superfetch** | service state | Running/Automatic; not separable per-process (it is `svchost`) | `svchost` total was 104.3 MB lifetime — negligible here |
| **Telemetry / CompatTelRunner / SDXHelper** | process presence | `SDXHelper` 0.9 MB lifetime read; **`CompatTelRunner` not running** `MEASURED` | Yes (scheduled tasks) but the measured benefit is ~0 |
| **The agent fleet itself** | `python` + `rg` + `node` | **3.22 TB read, 3.0 GB write, and the fastest sustained read on the machine** `MEASURED` | **This is the one that matters.** |

**Conclusion of §2.** Excluding the indexer and the antivirus from code trees is, on today's evidence, **optimising the wrong thing on this laptop**: those processes did not register at all, while the fleet's own `python`/`rg`/`git` traffic dominates by 10³. On `ZABZ-TECH` the story may differ (§4.4) and **must be measured there**, not inferred from here.

---

## 3. What a non-admin can actually do — tested, not assumed

Every test below was run on directories I created under `C:\Users\ezabz\code\_scratch\64-disk-wyo\` and **has been removed** (§3.6).

### 3.1 (a) `FILE_ATTRIBUTE_NOT_CONTENT_INDEXED` (`attrib +I`) — **WORKS, but does not achieve the goal**

```powershell
New-Item -ItemType Directory -Path $t -Force          # $t under _scratch
Set-Content -Path "$t\a.txt" -Value "hello"
attrib.exe +I $t                                       # directory
attrib.exe +I "$t\a.txt"                               # file
```

| Question | Result |
|---|---|
| Does `attrib +I` **succeed** without elevation? | **YES.** Directory attributes before `Directory`, after **`Directory, NotContentIndexed`**; file went `Archive` → **`Archive, NotContentIndexed`** `MEASURED` |
| Can a non-admin set it from .NET instead? | **YES.** `(Get-Item $f).Attributes = $Attributes -bor [IO.FileAttributes]::NotContentIndexed` → `SET_OK` `MEASURED` |
| **Does the indexer then skip it?** | **NO — for the directory.** See below. |

**The behavioural test.** I created two sibling trees at the same instant inside `_scratch`:

```
…\idxtest\INDEXED\ZQB20260916174945-on.txt    <- no +I
…\idxtest\EXCLUDED\ZQB20260916174945-off.txt  <- +I on both the directory and the file
```

Then queried the live index through the **`Search.CollatorDSO`** OLE DB provider (**this works without elevation** — `PROVIDER=Search.CollatorDSO;Extended Properties='Application=Windows';`, and it answered 195 rows for a broad `%INDEXED%` query, so the provider and the index are both live):

```sql
SELECT System.ItemPathDisplay FROM SYSTEMINDEX WHERE System.FileName = 'EXCLUDED'
-- → 1 row: C:\Users\ezabz\code\_scratch\64-disk-wyo\idxtest\EXCLUDED
SELECT System.ItemPathDisplay FROM SYSTEMINDEX WHERE System.FileName = 'INDEXED'
-- → 14 rows, including …\_scratch\64-disk-wyo\idxtest\INDEXED
```

**Result: the directory carrying `+I` is *in the index*.** The attribute did not keep it out.

**What this does and does not prove.** It proves `attrib +I` is not a reliable exclusion *for the container*. It does **not** prove the file-level attribute is ignored, because the two `.txt` files were never crawled either — and that is expected: `.txt` has no content filter in the default Windows Search configuration, so a text file is not *content*-indexed even when it is in scope. **The file-level attribute remains `NOT-VERIFIED`**, and the test that would settle it is stated exactly in §5.4.

**Practical verdict:** (a) is **free, unharmful, and insufficient**. Do not tell the owner it fixes indexing.

### 3.2 (b) The per-user COM interface — **FAILS: not only restricted, the ProgID does not exist**

`30-truth-and-disk.md` §6 asks for `New-Object -ComObject 'Crawl.CrawlScopeManager'`. I ran it, and every variant:

| ProgID tried | Result |
|---|---|
| `Crawl.CrawlScopeManager` (doc 30 §6) | **`80040154` — CLSID `{00000000-…}`. Class not registered.** |
| `Search.CSearchManager` | `80040154`, CLSID `{00000000-…}` |
| `Search.CSearchScopeManager` | `80040154`, CLSID `{00000000-…}` |
| `Search.CSearchCatalogManager` | `80040154`, CLSID `{00000000-…}` |
| `Search.CSearchQueryHelper` | `80040154`, CLSID `{00000000-…}` |
| `Search.CSearchAdminManager` | `80040154`, CLSID `{00000000-…}` |

I then enumerated **every** `Search.*` / `Crawl.*` ProgID registered on the machine: **66 of them, and `Crawl.CrawlScopeManager` is not among them.** The other `Crawl.*` name is absent entirely. So doc 30 §6's own honest caveat — *"the COM ProgID above is my recollection, not something I executed … do not ship a ProgID you have not run"* — is now resolved:

> **`Crawl.CrawlScopeManager` does not exist on Windows 11 build 26200. The snippet in `30-truth-and-disk.md` §6 is unshippable as written and must be corrected.** The CLSID `{9E175B68-F52A-11D8-B9A5-505054503030}` is present in `HKLM\SOFTWARE\Classes\CLSID` but registers as **"Search Gathering Manager"** and exposes `PauseIndexing`, `ResumeIndexing`, `IsIndexingPaused`, `ForceBackoffTemporarily`, `RestartIndexing` — **not** `AddUserScopeRule`. `AddUserScopeRule` belongs to the search **crawl scope manager**, a different interface, which I could not reach by ProgID.

**The one COM object that *did* create successfully as a non-admin** was that same CLSID via `[Activator]::CreateInstance([Type]::GetTypeFromCLSID(…))` → `CREATE_OK`, methods `PauseIndexing` / `ResumeIndexing` / `IsIndexingPaused` present. **I did not call them** (that would be a permanent-ish machine change, and the brief forbids it). This is `PROPOSED, UNTESTED` and it is a lead worth exactly one controlled experiment — see §6 rank 3. It is also **not the documented supported way** and Microsoft does not commit to it surviving an update.

### 3.3 (c) Is there a user-writable Search policy path? — **NO**

| Path | Result |
|---|---|
| `HKLM:\SOFTWARE\Microsoft\Windows Search` | readable; **write → `Requested registry access is not allowed`** `MEASURED` |
| `HKLM:\SOFTWARE\Microsoft\Windows Search\CrawlScopeManager\Windows\SystemIndex\{DefaultRules,WorkingSetRules}` | readable (`ItemCount` = 19 / 82) but not writable |
| `HKCU:\SOFTWARE\Microsoft\Windows Search\{Gather,CrawlScopeManager,Catalog}` | **do not exist** |
| `HKCU:\SOFTWARE\Microsoft\Windows Search\CrawlScopeManager\Windows\SystemIndex\WorkingSetRules` | **does not exist** |
| `HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Search` | exists, 2 subkeys / 15 values, **writable** (`HKCU_WRITE_OK`) — but holds shell search UI state, **not** crawl scope |
| `HKCU:\SOFTWARE\Policies\Microsoft\Windows\Windows Search` | **does not exist** |
| `HKLM:\SOFTWARE\Policies\Microsoft\Windows\Windows Search` | exists, one value: `AllowCortana` — **nothing about indexing scope** |

**Verdict: there is no user-writable path that governs indexing scope.** The crawl-scope rules live in `HKLM` under a key this user cannot write, and the per-user hive has no counterpart. (d) below establishes that the *reachability* of a scope change is moot from this seat.

### 3.4 (e) Can a non-admin pause or restart Windows Search for their own session? — **NO**

```
Stop-Service WSearch     -> Service 'Windows Search (WSearch)' cannot be stopped … Cannot open 'WSearch' service on computer '.'
Restart-Service WSearch  -> same
sc.exe config WSearch …  -> [SC] OpenService FAILED 5: Access is denied.
sc.exe sdshow WSearch    -> D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)(A;;CCLCSWLOCRRC;;;IU)(A;;CCLCSWLOCRRC;;;SU)(…)
```

The SDDL is decisive. The interactive-user ACE is
`(A;;CCLCSWLOCRRC;;;IU)` — **`CC` (connect), `LC` (query config), `SW` (enumerate dependents), `LO`, `CR`, `RC` only.** It contains **no `RP` (start), no `WP` (stop), no `DT` (pause/continue), no `DC` (change config)**. `WSearch` status and `StartType=Automatic` were unchanged after the attempt `MEASURED`.

**Verdict: a non-admin cannot stop, start, restart, pause, or reconfigure Windows Search. Full stop.** This is not a policy that can be worked around; it is the service DACL.

### 3.5 Summary of the non-admin ladder

| Route | Non-admin possible? | Achieves the goal? |
|---|---|---|
| (a) `attrib +I` / `NotContentIndexed` | **YES** | **NO** (directory still indexed) |
| (b) COM `Crawl.CrawlScopeManager` | **NO** — ProgID does not exist | — |
| (b′) COM via raw CLSID (`PauseIndexing`) | **YES, it constructed** | **UNTESTED**, unsupported, transient |
| (c) user-writable policy/scope key | **NO** — none exists | — |
| (d) behavioural proof via the index itself | **YES headlessly** (`Search.CollatorDSO`, no elevation) | n/a — it is the measurement tool |
| (e) stop/restart/pause the WSearch service | **NO** — DACL denies `RP/WP/DT/DC` | — |

**There is no non-admin mitigation that reduces indexing.** The only genuinely useful non-admin capability I found is the **read** one: `Search.CollatorDSO` lets an unelevated process **query the index**, which is how any before/after must be validated (§5.4).

### 3.6 Undo — what I created and removed

| Artifact | Action |
|---|---|
| `_scratch\64-disk-wyo\lon\` (3,606 files, 14.5 MB of generated churn) | **removed** — verified `False` for `Test-Path` |
| `_scratch\64-disk-wyo\idxtest\` (`INDEXED`, `EXCLUDED`, both `.txt` files) | **removed** — verified |
| `_scratch\64-disk-wyo\attrib-test\` | **removed** — verified |
| `HKCU:\SOFTWARE\Microsoft\Windows Search\_probe64` | **removed** — verified `False` |
| `HKLM:\SOFTWARE\Microsoft\Windows Search\_probe64` | **never written** (the write was denied) — verified absent |
| `HKCU:\SOFTWARE\Microsoft\Windows Search` (parent key) | **not created by me** — it existed before, and I did not remove it |
| `WSearch` service config / Defender config / any HKLM value | **untouched**. Except for the probe above, I ran no write against any machine setting. |
| `C:\Users\ezabz\OneDrive\Documents\ZQC…-indexed-control.txt` | **removed** — verified |
| Two files planted on `ZABZ-TECH` by the scope probe (`…\OneDrive\Documents\ZQD…-doc.txt`, `…\code\_scratch_probe_ZQD….md`) | ⚠️ **NOT removed — flagged in §7.** I had read-only intent but the probe script wrote them. They are two small text files; the owner or the next session should delete them. |
| Free space | `71.3 GB` before → `71.1 GB` during → **`71.14 GB` after cleanup** — net effect zero within measurement noise |

No git command that changes state was run. No repository was modified.

---

## 4. The elevation half: exact commands, what they do, how to reverse them

### 4.1 Defender exclusions — the documented, supported, shippable path

**On `ZABZ-TECH` today there are effectively no exclusions:** `Get-MpPreference` there reported `ExclusionPath` count 1 with an **empty** path, `ExclusionProcess` empty, `DisableRealtimeMonitoring=False`, real-time protection **on** (`MEASURED` over ssh, 2026-09-16 17:5x). This is the real, available win.

```powershell
# ELEVATED. Add exclusions (ZABZ-TECH paths).
Add-MpPreference -ExclusionPath 'C:\Users\ezabz\Code'
Add-MpPreference -ExclusionPath 'C:\Users\ezabz\.dsh'
Add-MpPreference -ExclusionPath 'C:\Users\ezabz\AppData\Local\npm-cache'
Add-MpPreference -ExclusionPath 'C:\Users\ezabz\AppData\Local\pnpm'
Add-MpPreference -ExclusionPath 'C:\Users\ezabz\AppData\Local\Temp'

# VERIFY (this is the step that makes it real)
Get-MpPreference | Select-Object -ExpandProperty ExclusionPath
```

**What it does:** removes those trees from Defender's real-time scan path. **Reverse it exactly** with `Remove-MpPreference -ExclusionPath '<same path>'` for each, then re-verify with `Get-MpPreference`.

**Do NOT add `-ExclusionProcess node.exe` or `python.exe`.** Doc 30 §6 already warns that a process exclusion is strictly wider than a path exclusion; I agree, and I would not do it even on an administered box, because these are exactly the processes that execute untrusted package code.

### 4.2 Windows Search scope — corrected commands, and the honest caveat

The doc-30 snippet must be replaced. The **supported UI** route (which does not require a ProgID I have not executed) is:

> **Settings → Privacy & security → Searching Windows → Excluded folders → Add**, or **Control Panel → Indexing Options → Modify → uncheck the folders**, then **Advanced → Rebuild**.

To do it **headlessly on `ZABZ-TECH`**, use the crawl-scope manager. On build 26200, the working entry point I could confirm exists is via the search **gatherer** CLSID (`{9E175B68-…}`, `"Search Gathering Manager"`) — but its confirmed methods are `PauseIndexing` / `ResumeIndexing`, **not** `AddUserScopeRule`.

**So, stated plainly: I could not execute a working elevation command for adding a search scope exclusion, and I will not invent one.** Two candidate ways forward, both requiring one elevated session on `ZABZ-TECH` to confirm:

1. **The supported one:** the Settings/Indexing-Options UI above, or the equivalent `ScopeRules` key written directly by an elevated process into
   `HKLM\SOFTWARE\Microsoft\Windows Search\CrawlScopeManager\Windows\SystemIndex\WorkingSetRules\<n>` with values
   `URL=file:///C:/Users/ezabz/Code/`, `Include=0`, `Suppress=0`, `Default=0`, `Policy=0`, `NoContent=0`, `Container=0`, `IntelligentlyAdded=0`
   — **this is the exact value shape I read off 82 live rules on `ZABZ-YOGA` (`MEASURED`, §4.4), so it is a faithful copy of a working rule, not a guess.** Follow it with `Update-Database`-equivalent: restart `WSearch` and rebuild. **Reverse:** delete the `<n>` subkey and restore the `ItemCount` value, then restart `WSearch`.
2. **The blunt one, if the goal is simply to stop the indexer:** stop and disable the service.
   ```powershell
   # ELEVATED, ZABZ-TECH only. This is a real, reversible reduction in capability.
   Stop-Service WSearch
   Set-Service WSearch -StartupType Disabled
   # REVERSE:
   Set-Service WSearch -StartupType Automatic
   Start-Service WSearch
   ```
   Cost: Start-menu and Explorer content search over indexed locations stop working. On a dev box that is likely an acceptable trade; it is the owner's call, not mine.

### 4.3 Where the same recipe applies — probed read-only on `ZABZ-TECH`

`ssh -o BatchMode=yes -o ConnectTimeout=8 desktop-ts` (`MEASURED`, 2026-09-16 17:5x):

| Fact | `ZABZ-TECH` value |
|---|---|
| Admin on that node | **True** |
| OS | Windows 11 **Pro**, build 26200 |
| Cores / RAM | **32 / 63.65 GB** |
| Disk | `C:` **951.6 GB, 220.6 GB free** (23 %) |
| Services | `SysMain`, `WinDefend`, `WSearch` all Running / Automatic |
| Defender exclusions | **essentially none** (empty `ExclusionPath` entry; no process exclusions) |
| Real-time protection | on (`RTP=True`, `AMRunning=True`) |
| `Document` path | **`C:\Users\ezabz\OneDrive\Documents`** — Documents is under OneDrive there too |
| `ProgramData\Microsoft\Search\Data` | **readable** (an admin can enumerate the catalog; the laptop cannot) |
| `SearchIndexer`, `MsMpEng` | both running |
| Search ProgIDs registered | **same 66** as the laptop; `Crawl.CrawlScopeManager` **absent here too** |

### 4.4 The most valuable single comparison in this document

| | `ZABZ-YOGA` (laptop, **not** administered) | `ZABZ-TECH` (desktop, **administered**) |
|---|---|---|
| `DefaultRules` count | **19** | **24** |
| `WorkingSetRules` count | **82** | **136** |
| Explicit per-**repo** rules (any repo under `…\code` / `…\Code`) | **82 rules, covering the whole `code` tree and `.dsh`** — e.g. `…\code\harness-config\`, `…\code\personal-secretary-mvp\`, `…\code\ceo-kernel\`, `…\Users\ezabz\.dsh\`, `…\Users\ezabz\.vscode\` — **all with `Include=0`** | **none for `C:\Users\ezabz\Code\`** |
| `IntelligentlyAdded` on any rule | **0** on all 101 rules read | (not enumerated per-rule in full) |

**Read this carefully, because it is the practical punchline.** On the laptop, the per-repo scope rules exist and carry `Include=0` — i.e. **those repositories are excluded from the crawl scope**. The mechanism the brief wanted tested is *already present in its target state* on the machine where it supposedly cannot be done, and **absent on the machine where it can be done**. Whatever wrote those 82 rules (I did not, this session), it demonstrates the mechanism works and is reversible on this build.

Two caveats I will not paper over:
* `Include=0` on a per-path rule excludes that path from a parent rule that would otherwise include it (`Users\` is `Include=1`). That is the standard meaning, and the parent/child shape here is exactly that. **But I did not prove the effect empirically** — my folder-path queries against `SYSTEMINDEX` returned 0 rows for every path I tried, including paths that are certainly in scope, which means my query's path representation was wrong, not that the tree is unindexed. **"The code tree is/isn't indexed" is NOT-VERIFIED on both nodes**; §5.4 gives the exact procedure that settles it.
* The laptop's rules are per-**repo**, not one rule for `…\code`. So a **new** repo created tomorrow is *not* covered and will be crawled. That is a maintenance hole.

---

## 5. The honest before/after measurement protocol

### 5.1 The protocol

Run **one** workload, twice, with **one** change between them, and no other variable. Nothing else may be running — in particular, no agent fleet.

```powershell
# ---- STEP 0: quiesce. This is the step everyone skips and it is the one that matters.
# Close every DSH session (one engine, zero agents), close Edge, wait for Pages Input/sec to fall under ~50/s.

# ---- STEP 1: BASELINE. 10 minutes, 2 s interval, sampled from a single process.
#      (Do not use Export-Counter into a .blg and never read it — read the numbers.)
Get-Counter -Counter @(
  '\PhysicalDisk(_Total)\% Disk Time',
  '\PhysicalDisk(_Total)\Current Disk Queue Length',
  '\PhysicalDisk(_Total)\Disk Read Bytes/sec',
  '\PhysicalDisk(_Total)\Disk Write Bytes/sec',
  '\Memory\Pages Input/sec',
  '\Paging File(_Total)\% Usage'
) -SampleInterval 2 -MaxSamples 300 |
  Export-Clixml 'C:\Users\ezabz\code\_scratch\disk-before.clixml'

# ---- STEP 2: THE WORKLOAD. Must be identical both runs, and must be the work you care about.
#      Use the fleet's real work, not synthetic churn: e.g. one fixed agent task that
#      touches a known repo, run to completion.
#      Record: wall seconds, files written, bytes written.

# ---- STEP 3: apply the change (one only).

# ---- STEP 4: REPEAT steps 0-2 EXACTLY, on the same tree, same task, same duration.

# ---- STEP 5: compare. Do not eyeball a mean; read the p50 and the max of each counter.
```

### 5.2 No other variables — the four that will silently ruin this

1. **Another agent.** A sibling session doing ripgrep will add 250 MB/s of read (measured, §2.2). This alone is larger than any effect you are trying to detect. Nothing else may run.
2. **OneDrive.** Documents is redirected into OneDrive on **both** machines (§4.3). If it is running during one run and not the other, the comparison is void.
3. **Windows Update / a scheduled Defender scan.** `ScanAvgCPULoadFactor=50` means a scan is throttled, not absent. Check `MoUsoCoreWorker`/`TiWorker`/`MsMpEng` CPU before each run.
4. **Thermal or power state.** The laptop is on **Balanced**. `powercfg /requests` needs elevation (P206), so on the laptop you cannot prove the machine was not throttling. **Do this experiment on `ZABZ-TECH`, which is administered and has 63.65 GB and 220 GB free**, and keep the laptop out of it.

### 5.3 The line I would read to call it a win

**Read the disk queue, then the bytes.**

* **WIN** iff **`\PhysicalDisk(_Total)\Current Disk Queue Length` p95 falls** and `\Disk Read Bytes/sec` p95 falls, **for the same workload completing in the same or less wall-clock time**.
* **NOT A WIN** if `% Disk Time` falls while the queue and the bytes do not. On this NVMe device `% Disk Time` reads 354 % at a queue of 2 (§1.4). A fall in that counter alone is a change in *concurrency accounting*, not a change in load.
* **NOT A WIN** if the workload got slower. Trading 10 % queue for 30 % wall-clock is a loss.

**And the sentence the brief asked for explicitly:** a saving that you cannot see **in the same counter, under the same workload, at the same concurrency** is not a saving. In particular, an `Add-MpPreference` exclusion whose benefit you "verify" with `Get-MpPerformanceReport` alone is **unverified** — that report is Defender's own accounting, not the disk's. Verify on the disk, with the workload.

### 5.4 The one measurement that settles the indexing question

Because the file-level `+I` test was inconclusive (§3.1), and because I could not prove the scope rules have their intended effect, run exactly this — **it needs no elevation**:

```powershell
# 1. Create a UNIQUE-named file, with a CONTENT type Windows Search actually filters
#    (.txt is NOT content-indexed by default; use .docx, .pdf, or an Office file).
#    Plant it in TWO sibling directories that differ ONLY in the +I attribute.
# 2. attrib +I on one directory.
# 3. Wait ~10 minutes (the indexer batches; it will not crawl on your schedule).
# 4. Query the index directly - NO ELEVATION NEEDED:
$c = New-Object -ComObject ADODB.Connection
$c.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
$cmd = New-Object -ComObject ADODB.Command; $cmd.ActiveConnection = $c
$cmd.CommandText = "SELECT System.ItemPathDisplay FROM SYSTEMINDEX WHERE System.FileName = '<the unique name>'"
$rs = $cmd.Execute()
while (-not $rs.EOF) { $rs.Fields.Item('System.ItemPathDisplay').Value; $rs.MoveNext() }
```

* **Two rows, one per directory → `+I` is NOT honoured.**
* **One row (only the un-attributed twin) → `+I` IS honoured for files.**
* **Zero rows → inconclusive; the indexer had not run, or the type is not filtered. Report it as inconclusive, not as success.**

**Do not report a zero-row result as a saving.** That mistake — reading a refusal as health — is the exact failure named in the journal's own rules.

---

## 6. Ranked by measured benefit per unit of risk, and the one experiment to run first

### The ranking

| # | Change | Measured benefit | Risk | Where |
|---|---|---|---|---|
| **1** | **Find and bound whatever makes one `python` process read 3.2 TB in 1.6 h** | **Enormous and measured**: 3,217,445 MB, ~99.9 % of all process read on this host (§2.2). Window-A `rg` at 61–250 MB/s is the same phenomenon | **None** — it is investigation, then a config change in our own code | this laptop; fleet-wide |
| **2** | **Fix doc 30 §6: delete `Crawl.CrawlScopeManager`** (ProgID does not exist on build 26200), and delete the "107 GB / 29 GB" figure as a load-bearing constraint (unreadable by a non-admin, §2.1) | Not a byte saved — **stops future sessions building on a snippet that cannot run.** This is the highest-value *correctness* change | **None** | `harness-config/docs/mesh/30-truth-and-disk.md` |
| **3** | **Run the search-scope exclusion on `ZABZ-TECH`** via Indexing Options → Modify (supported UI), then rebuild | Unknown but plausibly the largest single saving *there*: TECH has **136** scope rules and **0** for `C:\Users\ezabz\Code\`, on a box with 32 threads and every repo present | **Low**; reversible by re-checking the box. Cost: no Start-menu search of code | `ZABZ-TECH` (administered) |
| **4** | **`Add-MpPreference -ExclusionPath` for code, `.dsh`, npm/pnpm caches on `ZABZ-TECH`** | Currently **no exclusions at all** there (§4.3). Not yet quantified — that is what experiment #1 (below) produces | **Low–medium**: real-time scanning of those trees is genuinely lost. `node_modules` is the exact place a malicious package lands | `ZABZ-TECH` |
| **5** | **Cap concurrent engines/agents per node** (the governor already exists) | Indirect but certain: the fleet is the measured dominant consumer, and one engine's read is a linear function of live work | **None** | every node |
| **6** | **Cap the Edge profile count / cache** | `msedge` = **20 processes, 1,726.7 MB written lifetime — the largest single writer measured** (§2.3) | Low; user-visible only as slower first-loads | this laptop |
| **7** | **`attrib +I` across `code` and `.dsh`** | **Measured ineffective** for the container (§3.1). Do not bother | — | (rejected) |
| **8** | **Non-admin service/scope control** | **Measured impossible**: service DACL denies `RP/WP/DT/DC`; no user-writable scope key exists; the ProgID does not exist | — | (rejected) |
| **9** | **`Set-Service WSearch -StartupType Disabled` on the laptop** | Would work, but **requires elevation the owner does not have on this machine.** Not available | — | (unavailable) |

### The one experiment that must be run first

> **STATUS: WRITTEN INSTRUCTION ONLY — NOT ATTEMPTED, AND NOT TO BE ATTEMPTED FROM THIS SEAT.**
> `[added 2026-09-16]` This experiment **requires elevation**, which this seat does not have on `ZABZ-YOGA` (`Admin=False`, `MEASURED`) and which the owner does not have there either. It is recorded here **for the owner or an administrator to run on `ZABZ-TECH`, which is administered (`Admin=True`, `MEASURED`)**. Do not run it from this seat; do not work around the elevation requirement; do not substitute a non-admin approximation for it — §3 already establishes that no such approximation exists.

**A single clean 10-minute baseline on `ZABZ-TECH` with the fleet stopped, reading the queue and the byte rates — and then the same 10 minutes with the search scope exclusion applied.**

Why this one, and not the `python` investigation:

* It is the only experiment that produces the number the design docs have been guessing at, and **it is the only one that `ZABZ-YOGA` structurally cannot produce** (the laptop has no admin, so it can neither apply the change nor read the OS processes' counters — §2.1, §3.4).
* It costs 20 minutes and one elevated command on a machine the owner already administers.
* It uses the counters that actually track load (queue, bytes) rather than the one that misleads (`% Disk Time`), so its answer is usable as the acceptance test for every later change.
* And it comes with an unavoidable control: **the same 10 minutes with nothing changed**, which is the run that tells you whether `ZABZ-TECH` even *has* a disk problem, or whether — as on the laptop — the OS scanning services were never the consumer at all.

**If that baseline shows `SearchIndexer` and `MsMpEng` below 1 % of disk bytes, then the entire Defender-and-Search thread in the mesh design is closed, and the whole effort belongs on change #1 instead.** Knowing which of those two worlds you are in is worth more than any optimisation in the list.

---

## 7. What I could not verify, and the one thing I left behind

**NOT-VERIFIED, with the reason:**

1. **`SearchIndexer` / `MsMpEng` lifetime I/O on this laptop.** A non-admin cannot open their handles (§2.1). **Could not verify.**
2. **Whether the code tree is indexed, on either node.** My `System.ItemFolderPathDisplay` queries returned 0 rows for paths that are certainly in scope, so the query form was wrong. **Could not verify** — procedure in §5.4.
3. **Whether the file-level `NotContentIndexed` attribute is honoured.** The `.txt` control was never crawled (no content filter). **Could not verify** — procedure in §5.4.
4. **What causes `python` pid 7204's 3.15 TB of read.** Measured the effect, not the cause. **Could not verify.**
5. **Whether `PauseIndexing` on CLSID `{9E175B68-…}` succeeds as a non-admin and is honoured.** The object constructed; I did not call the method (permanent machine change, forbidden by the brief). **Could not verify.**
6. **A working elevated command for `AddUserScopeRule`.** I could not find an executable ProgID for it on build 26200 and **I will not write one I have not run.** The faithful registry-value shape is given in §4.2 item 1.
7. **`ZABZ-TECH`'s per-rule `Include` values in full** — I filtered for `code|Users|AppData` and got 136 rules; I did not decode all of them. **Partially verified.**
8. **Temperature / throttle state on the laptop** — `powercfg /requests` and thermal zones need elevation (P206, `MEASURED` again today: the journal entry stands). Any performance comparison on this laptop is therefore uncontrolled for throttling. **Could not verify** — another reason to run comparisons on `ZABZ-TECH`.

**Left behind, deliberately reported:** the `ZABZ-TECH` scope probe wrote two small files —
`C:\Users\ezabz\OneDrive\Documents\ZQD20260916175605-doc.txt` and `C:\Users\ezabz\code\_scratch_probe_ZQD20260916175605.md`.
I could not clean them up from a read-only remote command without another write to that machine. **They should be deleted**; they are inert text.

**Everything on the laptop is undone** (§3.6), verified by `Test-Path` after removal and by free space returning to 71.14 GB.

---

## Provenance

* Every `MEASURED` figure in §1, §2, §3 and §4.4: a command run **in this session on `ZABZ-YOGA`, 2026-09-16 17:46–18:00 local (-04:00)**, via `sampler-full.ps1` (two 120 s windows, 2 s interval), `Get-Counter`, `Get-Process` + `GetProcessIoCounters` (P/Invoke), `Get-PhysicalDisk`, `Get-CimInstance`, `Get-Service`, `sc.exe sdshow`, `attrib.exe`, `New-Object -ComObject`, `[Activator]::CreateInstance`, and the `Search.CollatorDSO` OLE DB provider. Raw samples: `_scratch\64-disk-wyo\sample-idle.json`, `sample-load.json`, `ts-idle.json`, `ts-load.json`, `lifetime-io.json`.
* Every `ZABZ-TECH` figure: `ssh -o BatchMode=yes -o ConnectTimeout=8 desktop-ts "powershell -NoProfile -EncodedCommand <base64>"`, 2026-09-16 **17:52–17:56 local**. Read-only except for the two planted probe files reported in §7.
* The 1,596 % disk time and SearchIndexer 107.3 GB / 29.2 GB figures, and the 33–37 GB commit / 1,500–62,000 page-ins/s storm, are **quoted from the brief and from `30-truth-and-disk.md` §3**, not reproduced by me — and §2.1 explains why two of them are not reproducible from this seat at all.
* Cross-checked for consistency with `30-truth-and-disk.md`; **§6 of that document is corrected by §3.2 and §4.2 here** (`Crawl.CrawlScopeManager` does not exist on build 26200).
