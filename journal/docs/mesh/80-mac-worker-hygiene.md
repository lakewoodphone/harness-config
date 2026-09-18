# 80 — The Mac mini as a worker node: reclaim policy, Chrome policy, and what is actually running there

**Program:** `docs/mesh/` (stream S4). Depends on `74-mac-mini.md` (stream S3's audit — the measured
problem this file answers) and `71-mesh-program.md` §1–§2.2 for placement arithmetic. Nothing
depends on it being read first.
**Machine:** `LakewooechsMini` (ssh `mac-mini-ts`), macOS 26.5.2, Mac16,10 (Apple M4), 10 cores,
16 GB, up 43 d 21 h at first measurement of this session. Console user `lpt` (uid 501); a second
login `moshemontrose` (uid 502) also has live processes.
**Dates:** every reading below is **2026-09-16 19:59–20:18 EDT (2026-09-16 23:59Z – 2026-09-17 00:18Z)**
unless it says otherwise.
**Author:** a delegated session (stream S4), not the owner.
**Owned files:** `scripts/mac-mini-worker-hygiene.sh` (the reclaim policy), this document.
**Explicitly NOT touched:** `scripts/phone-gate.py` — stream S1 owns it and was editing it during
this session; its darwin memory fix landed independently, see §7.

Every number carries its source and its moment. §8 states what could not be verified, as refusals.

---

## 1. The answer in one paragraph

The owner's two observations are both correct, and one of them is a **platform semantic rather than
a fault**:

1. *"Chrome doesn't need to be running so many tabs each time it opens."* — Chrome is now governed
   by a **machine-wide managed policy** at `/Library/Managed Preferences/com.google.Chrome.plist`
   setting `RestoreOnStartup = 5` (New Tab page), `BackgroundModeEnabled = false` and
   `MemorySaverModeEnabled = true`, installed and read back verbatim from disk (§3). What the
   *evidence did not support* is my briefing's premise that Chrome was configured to restore its
   session: **`session.restore_on_startup` is absent from all three of `lpt`'s Chrome profiles**
   (measured 20:10 EDT, §2.2), so Chrome was on its deterministic default — and `exit_type` is
   `Normal`. The 104-process / 7.1–7.3 GB state S3 measured was a **long-lived browser**, not a
   restart-driven storm. The policy still answers the observation, because it removes the
   possibility of restore-across-restarts entirely; it just matters *why*, and the reason is that
   the browser had been **up for a day and a half**, which is exactly the second observation.
2. *"Macs don't close down processes like on Windows — when I X things out they are still running."*
   — Correct and by design: the red button closes a **window**, the app keeps its memory. On a
   worker node nobody is looking at, the result is that reclaimable memory drifts down over days.
   That is now handled by a **launchd reclaim policy**
   (`com.lakewoodphone.mesh-worker-hygiene`) that acts only when the console has been idle ≥ 30 min
   *and* no process of the console user is holding the display awake (§4), and it was proved on
   real processes: **13 processes quit, 1,017,936 KB (993 MB) of resident memory released**, the
   machine's compressor falling **7.37 GiB → 6.57 GiB** (§5).

The most useful measurement of the session is not about Chrome at all: **the node is no longer
memory-poor.** S3 measured 111–148 MB of free pages and scored this node `maxChildren: 0`. At
20:16 EDT the same node reported **`freeMiB: 8053`, `maxChildren: 12`, `fleet: true`** (§7) —
because S1's darwin `_memory_bytes()` fix landed while this session ran, and because the reclaim
policy had already ended the two GUI applications that were holding the memory.

---

## 2. What was actually running, and the two things that were wrong with the briefing

### 2.1 Chrome was not the 104-process monster any more, and the reclaim job did not do that

Measured (source: `ps -axo pid=,uid=,user=,rss=,comm=`, all readings, `Date` column):

| moment (EDT) | `lpt` Chrome procs | `lpt` Chrome RSS | `lpt` Spotify RSS | `moshemontrose` Chrome |
|---|---|---|---|---|
| 19:59 | 5 | 482 MB | — | 7 procs, 184 MB |
| 20:10 | 5 | 486 MB | — | 7 procs, 202 MB |
| 20:11 (before any reclaim) | 5 | 486 MB | 508 MB | 7 procs |
| 20:15 (after the reclaim) | **0** | **0** | **0** | **7 procs** |

S3 measured **104 processes and 7.1–7.3 GB** at 23:06–23:45Z. Between then and 19:59 EDT this
session's first reading, `lpt`'s Chrome had fallen to 5 processes and ~482 MB, and its framework
was **152.0.7977.84** while the surviving `moshemontrose` instance was still on **151.0.7922.108** —
the signature of a browser that was still running from before an in-place Chrome update
(the app bundle on disk is 152.0.7977.84). **The 7.3 GB browser exited on its own before this
session's first measurement of it.** Nothing in this session quit it, and the document says so
rather than taking credit: the first reclaim run (§5, 20:13:48Z) reported `pids=13` = 5 Chrome + 8
Spotify, i.e. ~993 MB, not 7.3 GB.

**A second agent was active on the machine throughout this session** — `/tmp/_shlock_mac*.sh`,
`/tmp/dbg-gate.log`, `/tmp/fake-start.txt` and `/tmp/fake-ts-pids.txt` appear with mtimes 20:06–20:12
EDT and are not this stream's. Whether that stream ended the Chrome instance is **not established
here**; it is named because a reader of both audits would otherwise see an unexplained disappearance.

### 2.2 The root cause I was briefed with is not what the evidence says

The briefing said Chrome "is configured to restore the entire previous session". Measured
(20:10:37Z, `python3` reading the profile JSON directly):

```
Default  : restore_on_startup=None startup_urls=None background_mode=None exit_type='Normal'
Profile 1: restore_on_startup=None startup_urls=None background_mode=None exit_type='Normal'
Profile 8: restore_on_startup=None startup_urls=None background_mode=None exit_type='Normal'
```

`None` means the key is **absent** — Chrome is on its built-in default startup behaviour (the New
Tab page, i.e. *not* session restore), and `exit_type: Normal` says it shut down cleanly. So
"restores every tab on launch" was **not** this machine's state at 20:10 EDT.

This does not make the owner's observation wrong; it locates it. The tabs were not reopened by a
restart — **they accumulated in one browser that had been up for roughly a day and a half**, and
`lpt`'s Chrome carried a **`Profile 1` whose `Preferences` was last written 2026-09-16 19:54:37**,
four minutes before this session began. `Local State` names `last_used: Profile 1`, which is the
profile a human actually uses. (S3's audit did not read these keys; its 104-process finding is
consistent with either cause, and this file separates them.)

### 2.3 The genuinely stale session on this machine is still `moshemontrose`

35 d 21 h old, 7 Chrome processes (**framework 151, i.e. pre-update**), last touched 35 days ago,
not the console user. S3 left it alone (§6.2 of `74`) and **so does the reclaim job**: acting only
for the user who owns `/dev/console` is enforced in code, not by convention (§4.3), and the
before/after in §5 confirms `moshemontrose`'s 7 processes were untouched by a run that killed 13
processes belonging to `lpt`.

---

## 3. Observation 1 — the Chrome managed policy

### 3.1 Installed, and read back from disk

**File:** `/Library/Managed Preferences/com.google.Chrome.plist` — `root:wheel`, mode 644, 3247 bytes,
sha256 `61aa36908372eed14ce656b138ea49985ed6958558f888a186de855bc535ae6a`, installed 20:10 EDT.

Placement note: at `/Library/Managed Preferences/`, **not** under `MacOSX/`. The `MacOSX`
subdirectory is the per-user overlay; the top level is the machine-wide policy Chrome reads for
every profile. Before this session that directory existed and was **empty** (`total 0`,
`drwxr-xr-x root wheel`, created Feb 3 2026).

```
$ defaults read "/Library/Managed Preferences/com.google.Chrome"
{
    BackgroundModeEnabled = 0;
    MemorySaverModeEnabled = 1;
    RestoreOnStartup = 5;
}
$ plutil -lint "/Library/Managed Preferences/com.google.Chrome.plist"
/Library/Managed Preferences/com.google.Chrome.plist: OK
```

**Chrome version this applies to:** `CFBundleShortVersionString = 152.0.7977.84`, `KSVersion =
152.0.7977.84`, from `/Applications/Google Chrome.app/Contents/Info.plist`.

The keys, and why each value:

| key | value | reasoning |
|---|---|---|
| `RestoreOnStartup` | `5` | Open the **New Tab page**. Chromium's enum: `1` restore last session, `2` home page, `4` a URL list, `5` New Tab page. `4` is rejected deliberately — a URL list is a thing that goes stale; `5` needs no configuration and cannot rot. |
| `BackgroundModeEnabled` | `false` | The owner's second observation, for Chrome specifically: with background mode on, Chrome stays alive after its last window closes so extensions can run; off means *closed* actually means closed. |
| `MemorySaverModeEnabled` | `true` | Chrome's own memory saver — background tabs stop holding memory. Directly answers "so many tabs" on a 16 GB machine. Not verified as honoured on this build, §8.2. |

**Revert:** `sudo rm "/Library/Managed Preferences/com.google.Chrome.plist"`. Nothing else depends
on it.

### 3.2 Why a policy and not a preference

`~/Library/Application Support/Google/Chrome/*/Preferences` is **rewritten by Chrome on exit**
(observed: `Profile 1`'s Preferences mtime moved to 19:54:37, minutes before this session). A
hand-edit there cannot be durable. A file under `/Library/Managed Preferences/` is machine
configuration Chrome **reads** and does not write.

The host is not MDM-enrolled (`profiles status -type enrollment` → `Enrolled via DEP: No`,
`MDM enrollment: No`), so these arrive as machine policy from the file itself, not from a profile
pushed by a server — which is exactly the mechanism that makes a hand-placed plist sufficient here.

---

## 4. Observation 2 — the reclaim policy (a launchd daemon)

### 4.1 What it is, where it lives, and the one-command off switch

| piece | path |
|---|---|
| the policy (conditions + target list) | `/usr/local/lib/lakewoodphone/mac-mini-worker-hygiene.sh` — `root:wheel` 755, 34850 bytes, sha256 `78a36cddbdd63b48040cfa3f7e4906c2ed8e88de79846c47d42b7047a113038b` |
| the schedule | `/Library/LaunchDaemons/com.lakewoodphone.mesh-worker-hygiene.plist` — `root:wheel` 644, sha256 `ae6e99bc83a050093223e3fdcd5822a02236897ebd6b71e570a1cbab8bd0cf3e` |
| action log | `/var/log/lakewoodphone-worker-hygiene.log` |
| decision record (JSONL) | `/var/log/lakewoodphone-worker-hygiene.jsonl` |
| launchd's own sinks | `/var/log/lakewoodphone-worker-hygiene.{out,err}.log` — both **0 bytes**, as expected: the script does its own logging |

**Off switch, exactly one command:**

```
sudo launchctl bootout system/com.lakewoodphone.mesh-worker-hygiene
```

and back on with `sudo launchctl bootstrap system /Library/LaunchDaemons/com.lakewoodphone.mesh-worker-hygiene.plist`.
The plist does not have to be deleted and no other job is touched. (Bootout/bootstrap was exercised
during this session; see §5.4.)

Shape copied from the two jobs S3 installed and verified — `com.lakewoodphone.mesh-engine` and
`com.lakewoodphone.mesh-gate` — same file layout, same `StandardOutPath`/`StandardErrorPath` split,
same explicit PATH with `/opt/homebrew/bin` first. It deliberately does **not** copy their
`UserName` (=`lpt`) or `KeepAlive`:

* **no `UserName`** → the job runs as **root**, which it needs to reach a GUI session through
  `launchctl asuser`. The privilege buys reach, not licence: the script refuses to act on any
  process that is not on its explicit list and not owned by the console user (§4.3).
* **no `KeepAlive`** → this is a periodic job, not a service; `KeepAlive` would hold a process
  permanently for nothing.
* `StartInterval 300` and `RunAtLoad true`. Five minutes is frequent enough to return memory within
  five minutes of a console going idle and rare enough that the node spends almost no CPU on
  hygiene (a run that finds the console active exits in well under a second). Measured volume: one
  log line is ~350–700 bytes; at 288 runs/day that is ≈150 KB/day, ≈55 MB/year.

### 4.2 The four non-negotiable rules, and where each is enforced

The brief's rules are not aspirations; each is a specific piece of code.

1. **Never touch a process that is not on its explicit list.** `TARGETS` is an array of exact
   application bundle paths (Chrome, Spotify, Slack, Discord, Docker, Figma, Notion, Obsidian,
   zoom.us, Microsoft Teams). A path that is not running costs nothing; **a path not in the array
   can never be returned by `target_processes()`**. A second filter requires the process to belong
   to the **console user**, which is what kept `moshemontrose`'s Chrome alive while 13 of `lpt`'s
   processes died (§5).
2. **Must not run while the console is active or a user is typing.** Two independent tests, either
   of which blocks: root-domain `HIDIdleTime` from IOKit (≥ 1800 s required), and a scan of
   `pmset -g assertions` for `UserIsActive` / `PreventUserIdleDisplaySleep` /
   `PreventUserIdleSystemSleep` / `InternalPreventDisplaySleep` owned by a **process of the console
   user**. The header counts (`UserIsActive   0`) are **not** used as the gate, because they count
   daemon-owned assertions too — see §4.5.
3. **Idempotent.** The action path only runs when `target_processes` returns something; when it
   returns nothing the run logs a decline reading *"nothing on the explicit TARGETS list is running
   -- already clean"*. Proved by running the real default configuration twice — the second run
   declined (line 3 of the log in §5.3). A per-run `mkdir` lock also makes two concurrent runs
   impossible.
4. **A log line every time it acts and every time it declines, with the reclaimed bytes.** Two
   sinks written on every path out of the script: a line-oriented log, and one JSON object per run
   on its own line. Neither is conditional on the outcome.

### 4.3 The one design decision a reader should check: scope is the console user

`target_processes()` filters on the **console user's uid** before matching anything. This machine
has a second human's browser alive (35 days old), and a reclaim policy has no business ending
another person's session because the machine's console happens to be idle. The before/after in §5
is the proof it works: 13 of `lpt`'s processes stopped, **all 7 of `moshemontrose`'s kept running**.

### 4.4 The `--idle-seconds` lever, and why it is not a force-flag

The action branch can only be reached when the console's idle time exceeds the threshold, and idle
time is a fact about a human's desk that a test cannot set. The script therefore takes
`--idle-seconds N`, which is **the same comparison at a different N**, not a bypass — the blocking
assertion test still runs, and the console-user scope still applies:

* `--idle-seconds 0` reaches the **action** path on a console that has not yet been idle 30 minutes.
* `--idle-seconds 100000` reaches the **decline** path on a console that *is* already idle past the
  default 1800 s — which is the busy-console condition modelled, without waiting for a human to come
  back and use the keyboard.
* A console freshly idle past 30 minutes with no display assertion needs **neither**: the default
  *is* the condition, and the job acts on its own. That happened unaided at 20:14:46Z (§5.3, line 4
  of the archived log).

### 4.5 Two formats that were guessed wrong, and the capture that fixed it

Worth recording because both were invisible failures — the code ran, reported nothing, and looked
like a healthy machine:

* **`pmset -g assertions` does not contain the word "created" on an assertion line.** The real
  grammar, captured on this machine at 20:05:10 EDT, is

  ```
  Listed by owning process:
     pid 412(runningboardd): [0x002f5f8000018706] 00:00:00 PreventUserIdleSystemSleep named: "osservice<…>"
  	Created for PID: 632.
  ```

  `Created for PID:` is a separate **tab-indented** continuation line, present only sometimes. The
  first version of the parser matched `/created/` and could therefore never detect anything. The
  shipped version finds the **kind by the `HH:MM:SS` token**, so it does not depend on the owning
  process's name having no spaces. Additionally, **`pmset -g assertionslog` hangs forever on this
  build** (killed at 120 s) and is never called.
* **macOS `ps -o comm=` returns the full path *including its spaces* as one column**, so reading
  `$NF` yields the word `Chrome`, `Helper` or `(Renderer)`. The first version of the matcher
  therefore found **1 of 5** Chrome processes and reported `targets (live) : 1` while 486 MB was
  resident — and a reclaim that leaves the renderers is not a reclaim. Fixed by rebuilding `comm`
  from fields 5..NF with `ps -ww` (without `-ww` it can truncate to the terminal width).

### 4.6 The self-test, and why its input is synthetic

`mac-mini-worker-hygiene.sh --self-test` (read-only) is the regression test for the blocker parser.
The live machine has **zero** display assertions — a genuinely idle console — so "a console-user
assertion blocks" and "a daemon-owned one does not" cannot both be observed on it at once. Shaking
the mouse to manufacture a `UserIsActive` would mean touching a human's desk to make a test pass.
So the parser is fed a listing written in the **grammar captured from this machine**, carrying all
five cases:

| case | assertion | owner | expectation |
|---|---|---|---|
| A | `UserIsActive` | console user | **MUST block** |
| B | `PreventUserIdleSystemSleep` | console user | **MUST block** |
| C | `UserIsActive` | root (pid 1) | MUST NOT block |
| D | `PreventUserActivitySleep` | console user | MUST NOT block (not an awake kind) |
| E | `BackgroundTask` | console user | MUST NOT block |

The A/B/D/E pids are **real pids chosen for their owner** (this shell for the blocking cases, pid 1
for the non-blocking one), because `ps -o user=` resolves ownership for real and an invented pid
would make the user-attribution stage drop every case — the test would then pass vacuously. The
parser is also run against the machine's live listing, to prove it does not invent a blocker.

**Result (20:11:20Z and after, every run):**

```
parser output (kind|pid|user):
  UserIsActive|18942|lpt
  PreventUserIdleSystemSleep|18942|lpt

  PASS  A  console-user UserIsActive blocks
  PASS  B  console-user PreventUserIdleSystemSleep blocks
  PASS  C  root-owned (pid 1) UserIsActive does NOT block
  PASS  D  PreventUserActivitySleep is not an awake kind
  PASS  E  BackgroundTask is not an awake kind
against the machine's LIVE pmset listing:
  PASS  live listing yields no blocker
SELF-TEST: ALL CASES PASSED
```

The one-line bug this self-test caught is worth stating because it was invisible in every other
mode: **`uid` is a bash readonly builtin**, and the shell loop `while IFS='|' read -r kind p` runs
in a subshell that inherited `-v uid=` from the pipeline. The assignment failed, the loop body
never executed, and the function returned nothing — which every earlier check had read as "no
blockers". Renaming the variable to `_want_uid` is the whole fix.

---

## 5. Proof: both branches, on real processes, with log lines

### 5.1 The counter, defined exactly

```
reclaimable = (Pages free + Pages inactive + Pages speculative + Pages purgeable) x hw.pagesize
```

**Not `Pages free`.** macOS keeps almost everything as cache; S3 measured `Pages free` at 148 MB on
this 16 GB machine while 5.7 GB sat in the compressor, so that number describes a machine that is
merely caching as though it were critical. Source: `/usr/bin/vm_stat -c 5 1` (a 5-sample average 1 s
apart, not a spike sample), `sysctl -n hw.pagesize` = **16384 B**. Columns are resolved **by name**
from the header line, because `vm_stat` prints its field names on their own header line, not on the
data lines.

The **compressor** is reported with every measurement, because it is where this machine's memory
actually goes and a reclaim that only prints "free pages" can miss it entirely:

```
compressor : occupied 483703 pages = 7.38 GiB of real RAM holding 1360 MiB of compressed data
```

### 5.2 BEFORE — the state the job was installed into (20:11:28Z)

```
console user    : lpt (uid 501)
idle seconds    : 4568  (required: 1800)
blockers        : none
RECLAIMABLE     : 8014381056 bytes = 7.46 GiB
  counter       : pages free=19195 inactive=313725 speculative=150240 purgeable=5999 total=489159 x 16384B
  compressor    : occupied 483703 pages = 7.38 GiB of real RAM holding 1360 MiB of compressed data
targets (live)  : 13
  lpt chrome procs : 5      lpt chrome RSS : 486.0 MB      lpt Spotify RSS : 508.0 MB
  log exists before any run? NO
```

### 5.3 BRANCH 1 — it acts (20:13:48Z, `--idle-seconds 0`)

```
2026-09-17T00:13:48Z | 2026-09-16 20:13:48 EDT | v1.0.0 | mode=reclaim | outcome=acted |
  idle_s=4683 | idle_required_s=0 | blockers=none |
  reclaimable_before=7.54 GiB | reclaimable_after=7.94 GiB |
  reclaim_before_bytes=8095514624 | reclaim_after_bytes=8526217216 |
  pids=13 pids(13 total, first 8: 14152 14157 14158 14160 81651 50636 54852 54915 ) |
  reason=reclaimed Google Chrome,Spotify: 1017936 KB resident let go;
         reclaimable 7.54 GiB -> 7.94 GiB; app_rss_kb 1017936 -> 0
```

| measurement (same counter, same window) | before 20:13:19Z | after 20:13:48Z | change |
|---|---|---|---|
| `lpt` Chrome processes | 5 | **0** | −5 |
| `lpt` Spotify processes | 8 | **0** | −8 |
| target-process RSS total | **1,017,936 KB = 993 MB** | **0** | **−993 MB** |
| `Pages free` | 25,028 | 50,965 | +25,937 (≈ +405 MB) |
| `Pages inactive` | 313,676 | 310,369 | −3,307 |
| `Pages speculative` | 149,430 | 152,338 | +2,908 |
| **reclaimable** | **8,095,514,624 (7.54 GiB)** | **8,526,217,216 (7.94 GiB)** | **+402 MB** |
| **compressor occupied** | **483,703 pages = 7.37 GiB** | **430,423 pages = 6.57 GiB** | **−53,280 pages ≈ −813 MB** |
| compressed data stored | 1360 MiB | 1269 MiB | −91 MiB compiled-out |
| `moshemontrose` Chrome processes | 7 | **7** | **0 — untouched** |

The honest reading of the memory numbers: the reclaimable counter moved **+402 MB**, while the
**compressor gave back ~813 MB of real RAM** — and the two do not have to agree, because the
headline counter is sampled seconds apart and the machine is not otherwise idle. The one number
this session would trust over either is the **target RSS**, which is exact: **993 MB of application
memory stopped being resident**, and the compressor's 813 MB released is where most of it went.

`reason=` is the log line; the same run wrote an equivalent JSON object to
`/var/log/lakewoodphone-worker-hygiene.jsonl` (`"outcome":"acted"`, `"app_rss_kb_before":1017936
app_rss_kb_after=0`). **No SIGKILL escalation was recorded** — the graceful `osascript` quit (and
SIGTERM for anything that did not take it) was enough for all 13, which is the intended path.

### 5.4 BRANCH 2 — it declines, with the reason (20:14:01Z, `--idle-seconds 100000`)

```
2026-09-17T00:14:01Z | 2026-09-16 20:14:01 EDT | v1.0.0 | mode=reclaim | outcome=decline |
  idle_s=4721 | idle_required_s=100000 | blockers=none |
  reclaimable_before=7.91 GiB | reclaimable_after=unmeasured | pids=none |
  reason=console active: idle 4721s < required 100000s
```

The threshold is raised above the machine's measured idle time, which is precisely the busy-console
condition; the run takes **4 seconds** and quits nothing.

### 5.5 BRANCH 3 — idempotence and the job's own unaided run

```
2026-09-17T00:14:05Z | outcome=decline | idle_s=4725 | idle_required_s=1800 |
  reason=nothing on the explicit TARGETS list is running -- already clean
2026-09-17T00:14:46Z | outcome=decline | idle_s=4766 | idle_required_s=1800 |
  reason=nothing on the explicit TARGETS list is running -- already clean
```

The second of those two is **launchd's own run** — the job was bootstrapped at `00:14:41Z`, fired by
`RunAtLoad`, and wrote its own line 5 seconds later with no help. That is the default configuration
doing its job: idle 4766 s > 1800 s required, no blockers, and nothing left to reclaim, so it
declined and said so.

### 5.6 `launchctl print` — the job is loaded, and what it runs

```
$ sudo launchctl print system/com.lakewoodphone.mesh-worker-hygiene
system/com.lakewoodphone.mesh-worker-hygiene = {
	active count = 1
	path = /Library/LaunchDaemons/com.lakewoodphone.mesh-worker-hygiene.plist
	type = LaunchDaemon
	state = running
	program = /bin/bash
	arguments = { /bin/bash  /usr/local/lib/lakewoodphone/mac-mini-worker-hygiene.sh  --reclaim }
	stdout path = /var/log/lakewoodphone-worker-hygiene.out.log
	stderr path = /var/log/lakewoodphone-worker-hygiene.err.log
	environment = {
		HYGIENE_DECISIONS => /var/log/lakewoodphone-worker-hygiene.jsonl
		HYGIENE_LOG => /var/log/lakewoodphone-worker-hygiene.log
		PATH => /opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
	}
	domain = system
	runs = 1
	pid = 23063
```

Later: `state = not running`, `runs = 1`, `last exit code = 0` — which is the correct resting state
for a periodic job that runs for ~5 seconds every 300.

`plutil -p /Library/LaunchDaemons/com.lakewoodphone.mesh-worker-hygiene.plist` →
`RunAtLoad => true`, `StartInterval => 300`, `ProcessType => Background`, `Label =>
com.lakewoodphone.mesh-worker-hygiene`, and the three `EnvironmentVariables` above. **There is no
`UserName` key**, i.e. the job runs as root (see §4.1).

### 5.7 The decision record parses

The JSONL is the machine-readable half of the evidence, so it is validated rather than eyeballed:

```
$ python3 -c '…json.loads per line…'
  line 1: VALID   outcome=decline  idle_s=4886 req=100000  prev=None
  line 2: VALID   outcome=decline  idle_s=4890 req=1800    prev=None
  => 2 record(s), 0 invalid
```

An earlier batch of three records was written with an empty `"prev":` field — `printf '%s'` on an
unset variable emits nothing, which is **not** JSON. The fix (`_json_str_or_null`) is in the shipped
bytes, and the invalid records were **archived, not deleted**:
`/var/log/lakewoodphone-worker-hygiene{.log,.jsonl}.archived-20260916T201500Z` and `…201630Z`.

---

## 6. What was changed on the machine — the complete list

Nothing outside this list was touched.

| # | path | change | revert |
|---|---|---|---|
| 1 | `/Library/Managed Preferences/com.google.Chrome.plist` | **created** (3247 B, root:wheel 644, sha256 `61aa3690…`) | `sudo rm` it |
| 2 | `/usr/local/lib/lakewoodphone/mac-mini-worker-hygiene.sh` | **created** (34850 B, root:wheel 755, sha256 `78a36cdd…`) | `sudo rm -r /usr/local/lib/lakewoodphone` |
| 3 | `/Library/LaunchDaemons/com.lakewoodphone.mesh-worker-hygiene.plist` | **created** (4663 B, root:wheel 644, sha256 `ae6e99bc…`) and **loaded** | `sudo launchctl bootout system/com.lakewoodphone.mesh-worker-hygiene` |
| 4 | `/var/log/lakewoodphone-worker-hygiene.{log,jsonl,out.log,err.log}` + two `*.archived-*` pairs | **created** (the job's own record) | `sudo rm /var/log/lakewoodphone-worker-hygiene*` |
| 5 | `lpt`'s Chrome (5 procs) and Spotify (8 procs) | **quit** by one reclaim run, 20:13:48Z, gracefully | relaunch; Chrome's tabs are restorable from its own history and now open the New Tab page |
| 6 | the loaded job itself, twice | bootout + bootstrap, to prove the off switch and to pick up corrected bytes | — |

**Not changed:** `moshemontrose`'s Chrome or any of its 7 processes; `smd`; the Tailscale app,
extension or `tailscaled`; the wallpaper store; any `pmset` power setting; `/usr/local/bin/tailscale`;
the engine or gate plists; `scripts/phone-gate.py`; anything in another stream's files.

One bookkeeping note, stated because it is visible in `ls`: `/tmp` on this machine carries scratch
files from more than one session (`_shlock_mac*.sh`, `dbg-gate.*`, `fake-start.txt` at 20:06–20:12
EDT are not this stream's). This session's own `/tmp` scratch (`/tmp/push/`, `/tmp/stage/`,
`/tmp/*.sh`, `/tmp/dbg.*`) is disposable and was left for a later reader to see what was run.

---

## 7. The node is no longer memory-poor — and it was S1's fix plus this reclaim, not either alone

S3 measured `freeMiB: null` on this node because `phone-gate.py`'s `_memory_bytes()` had no darwin
branch, and scored it `maxChildren: 0` with the reason *"free memory could not be measured on this
node"* (`74` §7.3). **That fix has landed** — S1 owns the file and it changed during this session.
Measured this session, 20:14:51Z and 20:16Z:

```json
{"schema": 1, "node": "lakewooechsmini", "fqdn": "lakewooechsmini.tail93e6e6.ts.net",
 "at": "2026-09-17T00:14:51Z",
 "cpu": {"logical": 10, "physical": 10, "load1": 1.48},
 "mem": {"totalMiB": 16384, "freeMiB": 8176, "swapUsedPct": 58.8},
 "disk": {"workRoot": "/Users/lpt/code", "freeGiB": 46.1},
 "governor": {"budgetSlots": 24, "inUse": 0, "queued": 0},
 "accepts": {"oneShot": true, "fleet": true, "maxChildren": 12, "reason": null}}
```

| field | S3, 23:37Z | this session, 00:14Z–00:16Z |
|---|---|---|
| `mem.freeMiB` | `null` (unmeasurable) | **8176**, then **8053** |
| `mem.totalMiB` | `null` | **16384** |
| `cpu.physical` | `null` | **10** |
| `swapUsedPct` | 84.3 | **58.8** |
| `accepts.fleet` | `false` | **true** |
| `accepts.maxChildren` | **0** | **12** |
| `accepts.reason` | "free memory could not be measured…" | `null` |

So the *reason* this node was ineligible is gone (S1's fix), and the *condition* that made it
correct — 111–148 MB of free pages — is also gone (7.9 GiB reclaimable, of which ~8053 MB is
`freeMiB` by the gate's own definition). **`maxChildren: 12` is now a measured number rather than a
declaration.** Which of the two causes moved it more cannot be separated from these two readings
alone, and is not claimed: the gate could not measure this node before the fix regardless of how
much memory was free, and the memory would still have been short without the reclaim.

Two caveats a placement decision must carry, both measured:

* the machine is **still somebody's workstation** (`74` §8.3). Its `freeMiB` depends on a human's
  browser being closed, and this session watched exactly that fluctuate — `freeMiB`/reclaimable
  moved by hundreds of MB between readings minutes apart.
* the path to it is **relayed and flapping** (`74` §7.4). This session re-confirmed it: the first
  `ssh` attempt failed, and the tailnet dropped connection three more times during the work
  (`connect … port 22: Connection timed out`, recovering on retry each time), and `scp`'s separate
  sftp channel failed four consecutive times while a plain `ssh` command succeeded — the reason
  every file in this session was pushed over a single `ssh` stdin pipe rather than `scp`.

---

## 8. What could not be verified — stated as refusals

1. **Whether Chrome honours the three policy keys on this build.** The plist is on disk and reads
   back correctly, which is what this session can prove. The authoritative check is `chrome://policy`
   in a **running GUI Chrome**, which needs a human at that desk; this session must not sit at the
   GUI and must not launch a browser on somebody's desktop. A **headless** probe *was* attempted
   (`--headless=new --user-data-dir=<temp> --dump-dom chrome://policy`, no display, temp profile, no
   GUI instance touched): it produced **101,116 bytes of DOM but none of the three keys, and the page
   never mentions the word "policy"**, because `chrome://policy` fills its table from JavaScript
   after load and `--dump-dom` snapshots before that settles. **That is a refusal, not a negative
   result** — it must not be read as "the policy is not applied". What *is* established: the file
   exists with the right contents and permissions, the domain name is Chrome's own bundle id, and
   the host is not MDM-enrolled so no server is involved. `MemorySaverModeEnabled` is additionally
   the one of the three whose support is version-dependent; S3 wrote the briefing as *"if this
   Chrome build honours it"*, and this session cannot settle it from a shell.
2. **Whether the policy survives a Chrome update.** Nothing tests that; it is machine configuration
   and should, but "should" is not a measurement.
3. **The mechanism by which `lpt`'s 7.3 GB Chrome disappeared between S3's audit and this session's
   first reading.** Measured: it was 104 procs / 7.1–7.3 GB at 23:06–23:45Z and 5 procs / 482 MB at
   23:59Z. A second agent was demonstrably active on the machine in that window (§2.1). Not attributed.
4. **`caffeinate`-style display assertions.** `launchctl asuser 501 caffeinate -d -t 25` **exited
   immediately** on this machine (verified: `ps` found no such pid 3 s later) and the system-wide
   `PreventUserIdleDisplaySleep` count stayed at **0** throughout, so a genuine
   `PreventUserIdleDisplaySleep` assertion could not be observed *created*. The parser is therefore
   validated against the **grammar** captured from this machine's real daemon-owned assertions
   (`PreventUserIdleSystemSleep`, `InternalPreventSleep`, `ApplePushServiceTask`,
   `BackgroundTask` — all observed in the 20:05:10 EDT capture) plus one synthetic line of each
   blocking kind. The kinds it blocks on are the documented ones; no *blocking* case has been
   observed live, because a genuinely idle console has nothing to block on.
5. **The idle condition during a real human session.** Not exercised: the console was idle for the
   whole session, so the "human is typing" branch was reached by raising the threshold (§4.4) rather
   than by a person typing. The `HIDIdleTime` reading itself is the machine's own and was watched
   holding at 4,683–4,890 s.
6. **Long-run behaviour.** The job has run 1 time under launchd. Its `StartInterval` scheduling, its
   log growth (≈150 KB/day by arithmetic) and its behaviour across a reboot are unsoaked.
7. **`smd`'s physical cost** and the general question of what else on this machine holds compressed
   memory: not investigated here; S3's §9.8 stands.
8. **Whether the TARGETS list is the right list.** It was chosen from what is *installed* on this
   machine (measured: `Slack`, `Discord`, `Docker`, `Figma`, `Notion`, `Obsidian`, `zoom.us` and
   `Microsoft Teams` are all **absent**; only Chrome and Spotify are present), plus the browsers and
   chat clients a worker node commonly accumulates. A path for an absent application costs nothing
   and never matches, so the list is safe, but nothing has yet measured the cost of any target other
   than Chrome and Spotify.

---

## 9. One-paragraph summary for the manager

Two new files are owned: `scripts/mac-mini-worker-hygiene.sh`, a macOS reclaim policy, and this
document. On the machine there are three new things and nothing else: a **Chrome managed policy**
(`RestoreOnStartup=5`, `BackgroundModeEnabled=false`, `MemorySaverModeEnabled=true`, read back
verbatim, §3), the **script**, and a **launchd job** that runs it every 300 s and is disabled with
one `launchctl bootout` (§4). The job acts only when the console has been idle ≥ 30 min and no
process of the console user holds the display awake, quits only applications on an explicit list,
only for the console user, and writes a line every run whether it acts or declines. It was proved
both ways on real processes: a run at 20:13:48Z quit **13 processes and released 993 MB of resident
memory** (compressor 7.37 → 6.57 GiB) while leaving **another user's 7 Chrome processes alone**, and
runs at 20:14:01Z and 20:14:46Z declined with their reasons in the log (§5). Two corrections to the
briefing are recorded rather than smoothed over: **Chrome's profiles contain no
`restore_on_startup` at all** — the tabs were accumulated in a browser up for ~36 hours, not
reopened by a restart (§2.2) — and the reclaim job did **not** release the 7.3 GB, because that
browser had already exited before this session's first measurement (§2.1). The most consequential
number is not about Chrome: `/mesh/capacity` now reports **`freeMiB: 8053`, `maxChildren: 12`,
`fleet: true`** where S3 measured 111–148 MB and `maxChildren: 0` (§7) — S1's darwin memory reader
landed during this session, so the node's ineligibility reason is gone and its memory condition has
also improved. What remains unverified is whether this Chrome build honours the policy keys, which
only a human at `chrome://policy` can settle (§8.1).
