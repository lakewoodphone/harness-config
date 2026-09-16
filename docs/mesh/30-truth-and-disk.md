# 30 — Truth and Disk: state ownership and write distribution across a 6-node mesh

**Status:** design, first pass. Written 2026-09-16 on `ZABZ-YOGA` (host name MEASURED: `zabz-yoga`), 16:0x local.
**Labels:** `MEASURED` = a number I read on a machine in this session, with the command; `READ-FROM-CODE` = behaviour read out of a real file at a cited line; `PROPOSED` = my design, not yet built; `CANNOT DETERMINE` = I did not have the access to answer it.

**The brief, in the owner's words:** *"a big part of the problem is disk writing … maybe have every few agents writing to a different disk on the mesh and have some way of reconciling all of them to have a single source of truth."*

**Method limit, stated up front.** This pass was written with **no network access to the other five nodes**. Every measurement below is from `ZABZ-YOGA` itself or from code in this checkout. Anything that requires `secratary`, `ZABZ-TECH`, `zabz-tech-linux` or the VPS is marked `CANNOT DETERMINE (no access this session)` rather than guessed. Any future ssh to complete this must use `-o BatchMode=yes -o ConnectTimeout=8` and record an unreachable node as unreachable.

---

## 1. The state that exists today, by class

Sizes are from `ZABZ-YOGA` only.

| # | Class | Where it actually lives (path) | Who writes it | Authority today | Size on this node (MEASURED) |
|---|---|---|---|---|---|
| 1 | **DSH session logs** | `C:\Users\ezabz\.dsh\sessions\--C-Users-ezabz-code--\<session-id>\session.v3.jsonl.zstd` | exactly one engine that owns that `DSH_HOME` (READ-FROM-CODE: `dsh-session-persistence-jsonl\lib\index.js:913` `sessionDir(root,cwd,id)`; `dsh-home-paths\lib\index.js:73-76` resolves the root as configured → `$DSH_HOME` → `~/.dsh`) | **per-node, single-writer** | 436 files / 251,054,028 B = **239 MB** (`Get-ChildItem -Recurse`; largest 12,838,292 B) |
| 2 | **Session projection cache** | `C:\Users\ezabz\.dsh\storages\session_projcache\sessions\<id>.json` | the engine, one whole-file fsync'd atomic rewrite per checkpoint | **derived, per-node, disposable** | 432 files / **12.8 MB** (MEASURED) |
| 3 | **Other DSH storage-json units** | `C:\Users\ezabz\.dsh\storages\workspace.json` | engine; **no lock, last-write-wins by design** (READ-FROM-CODE, per `docs/dsh-at-scale/10-dsh-source-audit.md:347` citing `dsh-storage-json\lib\index.js:14-15`) | per-node scratch | 3,292 B (MEASURED) |
| 4 | **DSH attachments** | `C:\Users\ezabz\.dsh\attachments\` | engine, per-node | per-node, but **content-addressed input to sessions** → replicated by need | 71 files / **8.75 MB** (MEASURED) |
| 5 | **DSH profile / module tree** | `C:\Users\ezabz\.dsh\profiles\**` (`node_modules`, `.pnpm`, module-fallback) + `C:\Users\ezabz\.dsh\tools\mcp\**` | `pnpm` / install, per node | **per-node, reproducible artifact** — the truth is the lockfile, not the tree | `tools\mcp` 14,185 files / **123 MB** (MEASURED). `profiles\` subtree is **CANNOT DETERMINE** this pass — `Get-ChildItem -Recurse -File` returned 0 files there while a plain listing showed 15 entries, which is a tooling/reparse-point refusal, not evidence of emptiness. A second `dir /s` run reported **2,218,317,619 B (2.07 GB)** for `.dsh` overall against 1,926.7 MB (1.88 GB) from `Get-ChildItem`, so the two methods disagree and **neither is yet trustworthy for `profiles\`**. |
| 6 | **Journal — the log** | `C:\Users\ezabz\code\harness-config\journal\entries\<kind>\<id>.md` (append-only, one file per entry) + `state/`, `index/` | only `journal/tools/journal.py append`, serialised by an OS lock (`msvcrt.locking(LK_NBLCK)` on Windows, `flock` elsewhere — READ-FROM-CODE `journal.py:2597`, `:2678-2700`) | **authoritative = the git repo**, remote on the authority (`git remote -v` → `secretary-ts:/home/zabz/harness-config.git`, MEASURED) | 1,456 entry files / 3,507,826 B = **3.35 MB**; `index/` 8.97 MB of which `journal.db` 7.6 MB (MEASURED) |
| 7 | **Journal — generated caches** | `journal/index/entries.tsv`, `aliases.tsv`, `stamp.json`, `journal.db` (FTS5) | regenerated from `entries/`; `journal.py index --force` | **derived, disposable, never a source** (`README.md:37 "entries/ is the truth"`) | 8.97 MB incl. a leaked `.journal.db.tmp35748` 1,024,000 B + `-journal` 26,112 B (MEASURED) |
| 8 | **Company database** | authoritative on `secratary`; replicas read by Windows programs | the FastAPI service on the authority | **authoritative on the authority; replicas are read-only by contract** | Local copy `personal-secretary-mvp\data\secretary.db` = **514,322,432 B (490 MB)**, WAL + `busy_timeout=10000` + `journal_size_limit=64MB` (READ-FROM-CODE `app/database.py:308-319`) |
| 9 | **Vector store (Chroma)** | `personal-secretary-mvp\data\chromadb\chroma.sqlite3` (+ `data\mem0\chroma.sqlite3`) | the app; per-node if run locally | **derived index over company data** — rebuildable, but expensive and currently unsynced | **2,255,781,888 B (2.10 GB)** + 33,267,712 B (MEASURED) — the single largest state object on this node |
| 10 | **Git working trees / repos** | `C:\Users\ezabz\code\*` (22 repos) | per-node, human/agent commits; `harness-config` pushes to `secretary-ts` | **git is the authority for code and for the journal**; each node is a replica with its own working tree | `harness-config` pack = **17.86 MiB across 5 packs**, 8,159 objects (`git count-objects -vH`, MEASURED) |
| 11 | **Worktrees (fleet isolation)** | `git worktree`-created sibling dirs off each repo | the orchestrator / each subagent | per-node scratch, **must be a branch, never a shared working dir** | `CANNOT DETERMINE` (not enumerated this pass) |
| 12 | **Credentials** | `C:\Users\ezabz\.dsh\.credentials.yaml` (277 B) + `settings.yaml`; `.dsh-atomic-write` `withFileLock` (READ-FROM-CODE, audit `:345`) | one writer, per node | **per-node, never replicated as files**; secret material belongs in the vault/env, not a synced dir | 277 B (MEASURED) |
| 13 | **Node scratch / test junk** | `personal-secretary-mvp\.ptmp-r3\`, `.ptmp-r11b\`, `.ptmp-r21\` (each holding `q.db`/`w.db` at 1,593,344 B) | pytest runs | **scratch; deletable** | ~dozens of 1.5 MB files, MEASURED by enumeration |
| 14 | **Leaked temp files** | `index\.journal.db.tmp35748`, `storages\session_projcache\sessions\.<id>.tmp` (82,179 B, per audit `:331`) | crashed/interrupted atomic writes | scratch, unreaped | MEASURED |
| 15 | **Defender + Search index state** | `C:\ProgramData\Microsoft\Windows Defender\`, `C:\ProgramData\Microsoft\Search\Data\` | OS services | per-node, OS-owned, **not ours to reconcile** | the measured top I/O consumer (`SearchIndexer.exe` 107 GB read / 29 GB written); `CANNOT DETERMINE` fresh counter this session |

---

## 2. The single-source-of-truth rule, per class

One rule cannot cover all fifteen. Two classes need the **opposite** answer, and I will defend both.

| Class group | What "the truth" is | May be a replica | May be per-node scratch | Must **never** be forked |
|---|---|---|---|---|
| **Session logs (1, 2, 3, 4)** | The single engine that owns that `DSH_HOME`. A session is **owned by one node for its whole life**. | A *closed* session log may be copied to the authority for archival/search. A live one may not. | Yes — that is what they are. | ⚠️ **Never write one session log from two engines.** READ-FROM-CODE: the composition itself says *"Two dsh web processes on one home have been observed writing duplicate sequence numbers into one session log and making the whole history unloadable"* (audit `:374`, quoting `dsh-base` docs; warning string at `:1101`). |
| **Journal log (6)** | `entries/<kind>/<id>.md` **on `master`, as pushed to `secretary-ts`**. | Every checkout on every node is a replica. `index/` is a derived cache of a replica. | `_scratch/`. | ⚠️ **Never fork an id.** An id is a permanent handle; `L41b` exists because two machines chose 41 twice (`README.md:133-135`). |
| **Journal derived (7)** | Nothing — `entries/` is the truth; `index/` is rebuildable. | n/a | Yes, freely. | Nothing. Deleting `index/` must cost nothing. |
| **Company DB (8)** | **The instance on `secratary`.** | A read replica is legitimate **only if it carries its provenance and age** — a stale replica produced a confidently wrong report once (`README.md:175`, `L2`). | A local test DB is scratch. | ⚠️ **Never let a replica become a writer.** Never let two SQLite files both be "the company". |
| **Vector store (9)** | The **text it indexes** — i.e. company data. The Chroma file is an index, not a source. | Yes, rebuildable. | Yes. | Never treat a vector hit as evidence of current company state. |
| **Code + git (10, 11)** | The remote (`secretary-ts` for `harness-config`; each repo's own origin). A working tree is a replica. | Yes, by definition. | Worktrees are scratch, but **must be on a branch**. | ⚠️ **Never two writers to one working tree.** Partition by file — that is the whole reason worktrees exist. |
| **Credentials (12)** | The per-node vault/env. | **No.** | n/a | ⚠️ Never replicate a credential file through a code-sync path. |
| **Scratch + temps (13, 14, 15)** | Nobody. | n/a | Yes. | Nothing. |
| **Defender/Search (15)** | The OS on that node. | n/a | n/a | n/a |

**The defence of the split.** Sessions are *writes-forever, read-once, low-value-per-byte*. Forcing them into one shared store would put the highest-frequency writer in the system onto the slowest, most contended path — and it is exactly the workload that already produced 1,596 % disk time. The company DB is *low-frequency, read-often, correctness-critical*. It must be single-writer, and it is already on the authority. So: **sessions stay local and authoritative-per-node; the company DB stays authoritative-on-one-host.** Both rules are needed, and they are not in tension — they are the two ends of a frequency/consistency trade-off.

---

## 3. Where the write/read amplification actually comes from

| Source | Mechanism | Fix | Expected saving | How it would be verified |
|---|---|---|---|---|
| **Defender real-time scan over code trees** | Every file open/write in `C:\Users\ezabz\code` and `~\.dsh` is scanned; `node_modules` is tens of thousands of small files | **(b) exclude** | Large but **CANNOT DETERMINE** the exact number without a before/after counter | `Get-MpPerformanceReport -TopFilesPerExclusionPath` and `-TopProcesses` before and after; plus `\PhysicalDisk(*)\% Disk Time` sampled under a fixed workload |
| **Windows Search indexing code trees** | `SearchIndexer.exe` **107 GB read / 29 GB written** (given, MEASURED earlier) — the largest single I/O consumer in the system | **(b) exclude** code + `.dsh`; **(d) leave** user Documents | The dominant share of the 107/29 GB | `Get-SearchIndexerStatus`? No — verification is the **indexer's own per-path counters via `Get-PnpDevice`? also no.** Honest answer: verify by sampling `SearchIndexer.exe` I/O counters (`Get-Counter "\Process(SearchIndexer)\IO Read Bytes/sec"`) for 10 min before and after, with the indexer reset (`Control Panel → Indexing Options → Advanced → Rebuild`) so leftover crawl of an excluded path cannot flatter the result |
| **`chromadb/chroma.sqlite3` at 2.10 GB** | Every app start opens + migrates a 2 GB SQLite; WAL churn on top | **(c) move to another node/device** — it is derived | Removes ~2.1 GB of hot file and its WAL from the laptop's disk | `Get-ChildItem data\chromadb -Recurse` before/after + confirm `chroma.sqlite3` absent from the local node |
| **Pagefile under commit pressure** | One generating agent turn ≈ **0.81 GB commit + ~1 core**; 31.6 GB physical; commit crossed it (33–37 GB) → 1,500–62,000 page-ins/s (given) | **(a) stop it** — cap concurrency so commit stays under physical | Removes the page-in storm entirely | `Get-Counter "\Memory\Pages Input/sec"` and `\Paging File(_Total)\% Usage` under load, before/after, at the same agent count |
| **git operations on `harness-config`** | Every `journal.py append` does `git grep` over the **working tree, `HEAD`, and up to 25 remote refs** (READ-FROM-CODE `journal.py:2832-2872`) plus a `fetch`. Append costs **~2.5 s** (given) | **(d) leave the mechanism, (a) stop the `fetch` on the hot path** | ~25 s of the timeout budget and one network round trip per append | Time 20 appends with `--no-fetch` vs default; compare wall clock and `git` child-process count |
| **`node_modules` churn** | `profiles\` + 22 repos × `node_modules` = the highest *inode count* in the system; installs rewrite thousands of files | **(b) exclude from Defender/Search** (above); **(d) leave the bytes** | Same exclusion as row 1; the bytes themselves are not the problem, the scan is | `fsutil` inode counts per tree, plus the Defender counter |
| **Agent session-log writes** | Per tool call and per request: `open`+`write`+`fsync`+`close` plus **synchronous zstd on the main thread** (READ-FROM-CODE audit `:356-359`); `libuv` threadpool default 4 serves all of it | **(d) leave the design, (a) bound the number of live engines per node** | Already why one engine with 12 windows is the rule; adding engines multiplies flush rate linearly | `Get-Counter "\Process(node)\IO Write Bytes/sec"` at 1 vs 2 engines |
| **`msedge` writing gigabytes** | Browser cache/profile writes | **(b) exclude its cache from search indexing**; leave the browser | Unknown | Same counter, per-process |
| **Leaked `.tmp` files** | Interrupted atomic writes never reaped | **(a) stop it** — add a reaper; costs nothing | Small bytes, disproportionate clutter | Count `.tmp` under `index/` and `storages/`; assert 0 |

**What I am *not* claiming.** I do not have a fresh per-process I/O counter from this session, so I give no "saving X GB" number for the Defender/Search rows. The given figures (1,596 % disk time; SearchIndexer 107 GB read / 29 GB written) are quoted as constraints, not re-measured by me.

---

## 4. The distribution design

### 4.1 The options, honestly costed

| Option | Cost | What breaks under partition | Conflict resolution | Stays fast? |
|---|---|---|---|---|
| **A. Per-node local disks + a reconcile layer** | One sync daemon per class; you must write and *test* a merge rule per class | Nothing — the node keeps working; only convergence is delayed | Must be defined per class (see §5) | **Yes** — local writes are the fastest write there is |
| **B. One shared network store (SMB/NFS/MinIO)** | A single point of failure and a single spindle/file-server queue | **Everything stops.** No local write path | None needed if truly single-writer — but every writer now serialises on the network | **No.** This is the design that fails here: SQLite WAL over SMB is unsafe, and the journal's lock is an **OS file lock** (`journal.py:2597`) whose semantics over SMB/NFS are not dependable. |
| **C. Git as the transport for append-only data** | Rebase/merge work; `git` on every append path is already 2.5 s | Node diverges, resolves later — git is *built* for this | Already proven for the journal: id ceilings computed over `entries/`+index+**every remote ref** (`journal.py:2810-2873`) | **Yes for the journal (small files, one writer at a time), no for session logs (239 MB of binary-ish zstd churn)** |
| **D. A queue / single-writer-per-store** | One broker; one consumer per store | Writes queue, reads continue from local replica | Trivially: there is one writer, so there is nothing to merge | Yes for the DB, **no for session logs** (a session log is not a stream of independent messages; it is a file that one engine mutates) |
| **E. One engine per node, several nodes** | Nodes are the unit of parallelism | Each node is independent | Reconciliation happens at the class level, not the process level | Yes |

### 4.2 Recommendation

**Recommend E + A + C: one engine per node, per-node local disks, and reconciliaton by class through the transports that already exist — git for the journal and for code, the authority for the company DB, and replication-on-close for sessions.**

Concretely:
- **Write locally, always.** No agent ever writes across the network.
- **Every class declares its own transport.** Journal → `git` (already is). Code → `git` (already is). Company DB → the API on `secratary` (already is). Sessions → local, replicated only after the session is closed. Chroma → owned by whichever node hosts the app; other nodes query the API instead of opening the file.
- **The mesh unit is the node, not the agent.** Agents within a node coordinate through the existing governor; nodes coordinate through git + the authority. This is the smallest change that removes the shared-spindle contention, because today the contention is *on one laptop*, not across the mesh.

**What I reject, and why:**
- **Reject B (shared network store) as the primary design.** SQLite over SMB is a corruption vector, the OS file lock the journal depends on is not dependable over network filesystems, and partition means no work happens at all. A shared store is the right answer for exactly one thing — read-mostly artifacts — and it already exists in the form of *replicas*.
- **Reject C for session logs.** 239 MB of mixed zstd/binary churn through git would make every fetch painful and every merge meaningless. A session log is not a mergeable document.
- **Reject "every few agents write to a different disk" literally.** Agents are processes; disks are devices. You cannot pin an agent to a disk in any way the filesystem honours. **The realisable form of his idea is: each *node* writes to its own disk, and one *class* of data per disk per node** (journal + code on the working volume, caches and vector stores on a second volume). That gets the parallelism he wants without inventing a mechanism the OS does not have.
- **Reject D for everything except the company DB**, where it is already how it works.

**Status of the "6-node mesh": `CANNOT DETERMINE`.** From this node I can reach one remote by name (`secretary-ts` in the git remote, MEASURED). I did not verify node count, disk layout, or per-node free space this session. The design above is deliberately node-count-agnostic; §5's tests are what would settle it.

---

## 5. Reconciliation mechanics

### 5.1 Per class

| Class | Conflict detection | Merge unit | Offline node catches up | Re-establishing truth after divergence | Test that proves it |
|---|---|---|---|---|---|
| **Journal** | Two ids meaning two different entries, or one identity written twice | **One entry file**, `<kind>/<id>.md` | `git fetch` then `journal.py append` — the ceiling is recomputed over `entries/`, index, legacy sources **and every remote ref** | `journal.py repair-ids --apply` renumbers the later one and records an alias; `dedupe --apply` moves an exact duplicate to `archive/duplicates/` and leaves an alias | `journal.py check` (exits non-zero **only** on a real error) + `journal.py verify` (frozen v1 parser proves no loss by identity) |
| **Code** | git, normally | Commit | `git fetch` + rebase; worktrees keep two writers off one tree | normal git conflict resolution by a human/agent | CI + a build on the merged tree |
| **Company DB** | A replica cannot conflict, because **it cannot write** | n/a — single writer | re-read from the authority; a replica is *replaced*, never merged | restore/rebuild the replica from the authority | the query's answer must carry the authority's own timestamp; a stale replica must be *visible as stale*, not merely wrong |
| **Sessions** | none by design (one owner) | the whole session directory | copy-on-close from the owning node to the archive | never merge a session; if two engines wrote one log, the log is **damaged** and is quarantined | `stream_reader`, not `.decompress()` — the log is multi-frame; a partial read is a false negative |
| **Chroma / indexes** | none — they are derived | n/a | rebuild from source | rebuild | rebuild produces the same hit count on a fixed query set |

### 5.2 The two failures that already bit this system

**(a) Two machines assigned the same journal id to different entries — 18 of them.**
MEASURED history, quoted from the shipped fix: on 2026-09-15 on `ZABZ-TECH`, **fourteen ids** meant two different entries (`D185, D186, H322-H328, L1637-L1639, W149, W150`), and the cause is named in code: `git grep` with **no ref** greps the working tree, the second call greps `HEAD`, and **neither can see a number that exists only on `origin`** — so `cmd_append` fetched and then ignored what it fetched (`journal.py:2847-2858`). The earlier incident was larger: **161 collided ids on 2026-09-14** from two writers entering the same lock (`journal.py:2649-2651`, `:2590-2595`).

The fix is structural and is my model for the whole mesh: **the allocator's ceiling is the maximum over every source that could have claimed a number** (`allocation_ceiling`, `journal.py:2781-2791`: `entries/` + index + legacy + **every remote ref**, capped at 25 refs so a writer path cannot hang). An id is never renumbered downward; a gap costs nothing and a reused number destroys every citation to it. Verify with `journal.py pairs` (historical base-id collisions) and `journal.py check`.

**(b) A stale DB replica produced a confidently wrong report.**
This is the incident that makes "single source of truth" load-bearing (`README.md:175`, rule `L2`). The mechanical answer is not "sync harder". It is: **a number that cannot name its source and its age is not evidence.** So every read from a replica must carry the replica's own `MAX(rowid)`/file mtime/authority timestamp, and the tooling must refuse to print a figure it cannot attribute. `journal.py questions --offline` is the existing shape of this: it reads the *mirror* and says so.

### 5.3 The test that proves the whole thing works

A mesh-wide convergent test, PROPOSED, runnable without network:

1. Create a scratch journal tree (`--root`), append 20 entries on "node A" and 20 on "node B" from the **same starting commit**, with B never fetching. → **Assert** `journal.py pairs` reports 0 base-id collisions, because the ceiling saw B's refs (or, with `--no-fetch`, that it reports the collision loudly rather than silently reusing a number).
2. Kill the engine mid-append. → **Assert** the OS lock is released by the kernel and the next writer proceeds (no stale-lock wedge).
3. Corrupt one entry's sha. → **Assert** `journal.py check` exits non-zero and `check --fix` re-emits it canonically.
4. Take a DB replica, hold it at T-1 day, run the reporting path. → **Assert** the output names its age, or refuses. A silent wrong number is a **test failure**, not a warning.
5. Point two engines at one `DSH_HOME`, one session open. → **Assert** the second refuses (the composition warns; the test proves the refusal is real). This is the one test that must never be run against a real home — it corrupts a session log by construction.

---

## 6. The Windows tax

`SearchIndexer.exe` at **107 GB read / 29 GB written** is the largest non-work consumer of disk in the measured system. Defender real-time protection is second. Both are fixable with exclusions, and the cost of the fix is honest: **you lose the ability to search your code from the Start menu / Explorer, and you lose real-time malware scanning of those trees.**

**Exclusions — Search indexing (PROPOSED, elevated PowerShell):**

```powershell
# Paths to exclude from the indexer
$paths = @(
  'C:\Users\ezabz\code',
  'C:\Users\ezabz\.dsh',
  'C:\Users\ezabz\AppData\Local\npm-cache',
  'C:\Users\ezabz\AppData\Local\pnpm',
  'C:\Users\ezabz\AppData\Local\Temp'
)
foreach ($p in $paths) {
  # Microsoft.Search's documented interface, not a registry hack
  $s = New-Object -ComObject 'Crawl.CrawlScopeManager'   # PROPOSED: verify the ProgID exists on this host before relying on it
  $s.AddUserScopeRule($p, 0, 1, 1)
}
```

> **Honest note:** the COM ProgID above is my recollection, not something I executed — I ran nothing in this pass. **CANNOT DETERMINE** the exact supported interface on this build. The low-risk, always-available alternative is the documented UI: **Indexing Options → Modify → uncheck the code and cache folders**, and **Advanced → Rebuild**. On Windows 11 there is also `Settings → Privacy & security → Searching Windows → Excluded folders`, which is per-folder and scriptable only through the registry. **Verify before scripting; do not ship a ProgID you have not run.**

**Exclusions — Defender (documented cmdlets, safe to state as READ-FROM-DOCS-not-run):**

```powershell
Add-MpPreference -ExclusionPath 'C:\Users\ezabz\code'
Add-MpPreference -ExclusionPath 'C:\Users\ezabz\.dsh'
Add-MpPreference -ExclusionPath 'C:\Users\ezabz\AppData\Local\npm-cache'
Add-MpPreference -ExclusionProcess 'node.exe'     # only if you accept the risk; widens the hole
Get-MpPreference | Select-Object -ExpandProperty ExclusionPath   # verify
```

**Capability lost, stated plainly:** excluded trees are no longer real-time scanned, so a malicious npm package installed into `node_modules` will not be caught on write — only if something later executes a scanned binary or a scheduled scan covers it. Excluding `node.exe` as a *process* is wider than excluding a *path* and I would not do it by default. The honest trade is: exclude **code trees, `.dsh`, and package caches**; keep scanning downloads, Documents, and the company data directory.

**How to verify the saving:**

```powershell
# Before
Get-MpPerformanceReport -TopFilesPerExclusionPath 20 | Out-File before-mp.txt
Get-Counter '\Process(SearchIndexer)\IO Read Bytes/sec','\Process(SearchIndexer)\IO Write Bytes/sec' -SampleInterval 5 -MaxSamples 120 | Export-Counter -Path searchindexer-before.blg
Get-Counter '\PhysicalDisk(_Total)\% Disk Time' -SampleInterval 2 -MaxSamples 300 | Export-Counter -Path disk-before.blg
# ... apply exclusions, rebuild the index, run the SAME workload ...
# After, compare. A saving you cannot see in the same counter under the same workload is not a saving.
```

**What a Linux node does not pay.** On `secratary` there is no Defender and no Windows Search: a file write is a write. Linux nodes pay only their own filesystem and page cache. That asymmetry is the argument for putting the *hot, high-inode-count* work (vector stores, package installs, build caches) on the Linux nodes and keeping Windows nodes for what needs Windows.

---

## 7. The three highest-value changes

1. **Exclude `code`, `.dsh`, and package caches from Defender + Windows Search on every Windows node** — targets the measured **107 GB read / 29 GB written** and the second-largest consumer, both attributable to scanning, not to work. Saving: **the dominant share of the 1,596 % disk-time constraint**; exact GB `CANNOT DETERMINE` without the before/after counters in §6. Cost: no real-time scan of code trees, no Start-menu search of code. Verify with `Get-MpPerformanceReport` + `\PhysicalDisk(_Total)\% Disk Time` under a fixed workload.
2. **Move the derived 2.10 GB Chroma store off the laptop** (and stop any node but the app host from opening a Chroma file). Saving: **~2.1 GB of hot file plus its WAL** removed from the constrained device, and the app host becomes the only writer. Verify by enumerating `data\chromadb` before/after and confirming absence locally.
3. **Make the journal's id ceiling the single, mesh-wide allocator — and never let a second writer into an id range.** The mechanism already exists (`allocation_ceiling`, every remote ref, capped at 25 refs); the change is to make it non-optional (no silent `--no-fetch` on the writer path) and to add `journal.py pairs` to the pre-flight of any session that appends. This is what prevents a repeat of **161 collided ids (2026-09-14)** and **14 duplicated ids (2026-09-15, ZABZ-TECH)**. Saving: sessions, not gigabytes — each collision costs a session to repair.

**Recorded as PROPOSED, not done.** Nothing in this document has been applied: no exclusion made, no file moved, no config changed. This pass read and measured only.

---

### Provenance

- Every MEASURED figure: a `Get-ChildItem`/`cmd dir /s`/`git count-objects` run in this session on `ZABZ-YOGA`, 2026-09-16 ~16:0x local. Where the two methods disagree (`.dsh` 1.88 GB vs 2.07 GB), both are reported and `profiles\` is marked undetermined.
- Every READ-FROM-CODE figure: the cited `path:line` in `harness-config/journal/tools/journal.py`, `harness-config/journal/README.md`, `personal-secretary-mvp/app/database.py`, or `harness-config/docs/dsh-at-scale/10-dsh-source-audit.md`, plus `@deepseek-ai/dsh-home-paths/lib/index.js:73-76`.
- The given constraints (1,596 % disk time; SearchIndexer 107/29 GB; 0.81 GB commit per generating turn; 31.6 GB physical; 33–37 GB commit; 1,500–62,000 page-ins/s; journal append ~2.5 s; `secretary.db` 486 MB–2.4 GB) are quoted from the brief, **not re-measured by me**.
- Unreachable this session, hence undetermined: node inventory and disk layout; the authority's live `secretary.db` size and WAL state; per-node free space; whether the 6-node mesh includes the VPS and the macOS mini in the counts.
