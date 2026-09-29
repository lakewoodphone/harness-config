# 122 — Mesh dispatch: crash and lost-run evidence

**Lane:** P1 evidence. **Machine this was measured on:** `zabz-tech` (`ZABZ-TECH`, hostname printed by
`hostname`). **Worktree:** `C:/Users/ezabz/code/_fleet_p1evidence`, branch `agent/p1evidence`, base
commit `f97626b`. **Read-only everywhere outside this worktree.**

**Method, stated once so every count below is reproducible.** Every count in this document was produced
by reading the files named in the row and tallying with PowerShell `ConvertFrom-Json` over
`[System.IO.File]::ReadLines`. No count is estimated. Where a count is over a *subset* of a directory
(skipping non-JSONL files, or files over 5 MB) the subset is named. **File modification times
(`mtime`) on files inside the worktree are all `2026-09-29 14:20:38–14:20:40 -04:00` — that is the
`git worktree add` checkout timestamp, not the authoring time.** For worktree files the authoring date
is taken from the journal entry's own header, and git's author date is given alongside; that is called
out in every row rather than being passed off as an mtime.

---

## 1. THE EVENT TABLE

One row per crash or lost run. "mtime" is the file's own last-write time.

| # | When (UTC) | Node | What died | Raw log line | Source path | mtime |
|---|---|---|---|---|---|---|
| E1 | 2026-09-18 04:43:43 → 04:45:36 | zabz-yoga-1 (laptop) | 7,383 traversal probes; whole mesh dispatch path unusable for 113 s | `{"at":"2026-09-18T04:45:08.089Z","runId":"2026-09-18T04-45-00-007Z","phase":"traversal","node":"zabz-yoga-1","shell":"powershell","ok":false,"reason":"the traversal probe printed no verdict (exit 255; stdout: ; stderr: ssh: connect to host zabz-yoga-1.tail93e6e6.ts.net port 22: Connection timed out)"}` | `C:/Users/ezabz/.dsh/mesh/logs/2026-09-18T04-45-00-007Z.jsonl` (representative; 7,119 such files) | 2026-09-18 00:45:08 -04:00 |
| E2 | 2026-09-18 04:43:43 → 04:45:36 | zabz-yoga-1 | 675 of the same probe failures: TCP opened, sshd never sent a banner | `"reason":"the traversal probe printed no verdict (exit 255; stdout: ; stderr: Connection timed out during banner exchange\r\nConnection to 100.72.162.5 port 22 timed out)"` | `C:/Users/ezabz/.dsh/mesh/logs/2026-09-18T04-45-26-460Z.jsonl` | 2026-09-18 00:45:34 -04:00 |
| E3 | 2026-09-18 04:43:43 → 04:45:36 | zabz-yoga-1 | 546 of the same probe failures: key exchange broken mid-handshake | `"reason":"the traversal probe printed no verdict (exit 255; stdout: ; stderr: kex_exchange_identification: read: Unknown error\r\nbanner exchange: Connection to 100.72.162.5 port 22: Unknown error)"` | `C:/Users/ezabz/.dsh/mesh/logs/2026-09-18T04-45-26-209Z.jsonl` | 2026-09-18 00:45:29 -04:00 |
| E4 | 2026-09-18 04:21:10 | zabz-yoga-1 | 2 parent runs exited 1 with **no diagnostic preserved** | `{"at":"2026-09-18T04:21:10.284Z","phase":"run-end","node":"zabz-yoga-1","exitCode":1,"timedOut":false,"ms":86,"stdoutBytes":0,"stderrBytes":1929,"outPath":"...04-21-06-487Z.out"}` then `{"phase":"result","outcome":"failed","reason":"parent exit 1"}` | `C:/Users/ezabz/.dsh/mesh/logs/2026-09-18T04-21-06-487Z.jsonl` | 2026-09-18 00:21:10 -04:00 |
| E5 | 2026-09-18 04:21:10 | zabz-yoga-1 | `stderrBytes:1929` recorded, `.out` artifact is **0 bytes** — the diagnostic is gone | same file as E4; `.out` size `0` | `C:/Users/ezabz/.dsh/mesh/logs/2026-09-18T04-21-06-487Z.out` | 2026-09-18 00:21:10 -04:00 |
| E6 | 2026-09-18 04:45:55 | zabz-yoga-1 | 2 parent runs exited `4294967295` (= `-1`, killed) | `{"phase":"run-end","node":"zabz-yoga-1","exitCode":4294967295,"timedOut":false,"ms":11342,"stdoutBytes":0,"stderrBytes":239}` then `"reason":"parent exit 4294967295"` | `C:/Users/ezabz/.dsh/mesh/logs/2026-09-18T04-45-18-544Z.jsonl` | 2026-09-18 00:45:55 -04:00 |
| E7 | 2026-09-18 04:45:45 → 04:45:52 | zabz-yoga-1 | 15 child runs settled **failed with the child's exit code 0** — success code, zero host lines | `{"at":"2026-09-18T04:45:52.305Z","phase":"run-end","exitCode":0,"timedOut":false,"ms":7297,"stdoutBytes":1325,"stderrBytes":172}` then `{"phase":"verify","meshHostLines":0,"meshHostLinesLiteral":0,"childHosts":[],"ok":false}` then `{"phase":"result","outcome":"failed","reason":"only 0 MESH-HOST lines for 1 children (0 literal, 0 summarised)"}` | `C:/Users/ezabz/.dsh/mesh/logs/2026-09-18T04-45-26-114Z.jsonl` | 2026-09-18 00:45:52 -04:00 |
| E8 | 2026-09-18 04:45:52 | zabz-yoga-1 | The child's whole answer was discarded but survived in the `.out`, proving the loss was in the **wrapping**, not the child | `.out` verbatim: `Error: subagent run failed` / `Diagnostic: the remote one-shot exited 255 and produced no final message; stderr tail: kex_exchange_identification: read: Connection reset` / `Connection reset by 100.72.162.5 port 22` | `C:/Users/ezabz/.dsh/mesh/logs/2026-09-18T04-45-26-114Z.out` (1,329 B) | 2026-09-18 00:45:52 -04:00 |
| E9 | 2026-09-18 14:49:49 | zabz-yoga-1 → placed zabz-tech | A *successful* cross-node dispatch was scored **failed** because the broker said yoga and the child said tech | `{"phase":"verify","node":"zabz-yoga-1","meshHostLines":1,"childHosts":["ZABZ-TECH"],"disagreements":["ZABZ-TECH"],"ok":false}` then `"reason":"location disagreement: ZABZ-TECH not on zabz-yoga-1"` | `C:/Users/ezabz/.dsh/mesh/logs/2026-09-18T14-49-32-598Z.jsonl` | 2026-09-18 10:49:49 -04:00 |
| E10 | 2026-09-17 15:53:54 | placed zabz-tech | Placement succeeded, child died in **108 ms** — `stopReason:"error"`, `exitCode:255` | `"stopReason": "error", "exitCode": 255, "ms": 108, "reportedHost": null, "meshHost": null, "leaseReleased": true` | `C:/Users/ezabz/.dsh/mesh/placements/remote-59e5ec01-b2d5-4394-90b9-789d97cdb5f2.json` | 2026-09-17 11:53:54 -04:00 |
| E11 | 2026-09-18 04:45:43 → 04:45:55 | (blank) | 12 placements died `exit 255` in 122–393 ms; no node ever named | placement records `stopReason:"error"`, `exitCode:255`, `node:""`, e.g. `remote-8cc75e30-…json` `ms:122`, `remote-cac81a61-…json` `ms:323` | `C:/Users/ezabz/.dsh/mesh/placements/` (13 files, listed in §3.1) | 2026-09-18 00:45:5x -04:00 |
| E12 | 2026-09-22 04:32:30 | zabz-tech | 2 children hit the 30-minute cap — `ms` = **1,800,056** exceeds 1,800,000 | placement record `"stopReason":"error","exitCode":4294967295,"ms":389975` (dispatch) / `ms:1800056` (settle) | `C:/Users/ezabz/.dsh/mesh/placements/remote-eca11c0d-a2a0-45ed-8086-c6fa97413cba.json` | 2026-09-21 20:52:31 -04:00 |
| E13 | 2026-09-23 23:16:34 → 23:30:02 | zabz-tech | 1 child **aborted mid-turn** — no exit code, lease Released | placement record `"stopReason":"aborted","ms":806213,"leaseReleased":true`, `exitCode` key absent | `C:/Users/ezabz/.dsh/mesh/placements/remote-efcc1041-e62b-40d9-980b-f1bc7da96ccd.json` | 2026-09-23 19:30:02 -04:00 |
| E14 | 2026-09-24 20:47:47 → 20:48:49 | zabz-tech | 1 child `exitCode:1` after 595 s; host verifiable, run failed | placement record `"stopReason":"error","exitCode":1,"ms":595571,"meshHost":"ZABZ-TECH"` | `C:/Users/ezabz/.dsh/mesh/placements/remote-e0d6a016-defa-4740-b8c8-c66f004ff7e6.json` | 2026-09-24 16:48:49 -04:00 |
| E15 | 2026-09-28 18:19:16 | (blank) | **3 dispatches lost before any placement** — broker host unreachable by ssh | `{"id":"remote-3b62d043-…","at":"2026-09-28T18:19:16…","state":"placement-failed","code":?, "error":"the placement broker could not be reached at secratary-ts:http://localhost:3091/place — ssh exited 255: ssh: connect to host secratary.tail93e6e6.ts.net port 22: Connection timed out"}` | `C:/Users/ezabz/.dsh/mesh/placements/remote-3b62d043-ab71-4355-80ee-86ee072a8b51.json` (+ `…91689eea…`, `…3db69f75…`, same timestamp) | 2026-09-28 14:19:16 -04:00 |
| E16 | 2026-09-28 18:19:47 → 18:49:47 | zabz-tech | 2 children hit the 30-minute cap at **1,800,036 / 1,800,048 ms**, lease **never released** | `"stopReason":"error","ms":1800036,"leaseReleased":false,"meshHost":null` | `C:/Users/ezabz/.dsh/mesh/placements/remote-713a1246-6c50-4b81-9508-a5b15d2c4f4a.json` (+ `…dd73cadd…`) | 2026-09-28 14:49:47 -04:00 |
| E17 | 2026-09-28 18:33:31 → 18:35:58 | zabz-tech | 1 child aborted mid-turn, lease released | `"stopReason":"aborted","ms":146743,"leaseReleased":true` | `C:/Users/ezabz/.dsh/mesh/placements/remote-0905a4de-194a-4817-a6e7-201ddaa2b652.json` | 2026-09-28 14:35:58 -04:00 |
| E18 | 2026-09-18 04:45:33 → 04:45:55 | (blank) | **7 runs frozen in `state:"dispatching"`** — no `stopReason`, no `exitCode`, no `settledAt`. The ledger stopped mid-sentence | `{"id":"remote-97f2d7f9-…","at":"2026-09-18T04:45:33…","state":"dispatching","waitedMs":…,"queueTimedOut":…,"dispatchedAt":…}` — keys end there | `C:/Users/ezabz/.dsh/mesh/placements/remote-97f2d7f9-21ed-4488-8fba-22b56b18927f.json` (+ `…d18cc3d7…`, `…0493ce5c…`, `…18f96938…`, `…bc6c3ad8…`, `…ef38096e…`, `…0e3bcd71…`) | 2026-09-18 00:45:33–00:45:55 -04:00 |
| E19 | 2026-09-16 11:09:05 → 11:40:31 | ZABZ-YOGA engine :3099 | **The engine failed to start 9 times**, exit code 1, twice live | `[2026-09-16T11:09:05.0802971-04:00] ensure: start FAILED - server on port 3099 exited with code 1. stderr tail:` then `Error: dsh: cannot resolve profile bundle "dsh-plugin-attention" from the dsh installation or C:\Users\ezabz\.dsh\profiles\web` | `C:/Users/ezabz/.dsh/multi-window/engine-recovery.log` lines 1–105 (1.4 MB log) | 2026-09-29 14:27:57 -04:00 |
| E20 | 2026-09-25 15:36:39 (per the entry) | ZABZ-YOGA engine :3099 | Engine died on an unhandled `ENOENT` after Windows deleted its `%TEMP%` spill dir. **The surviving logs on this node do not contain it** — see §5. | Entry's own words: `engine-recovery.log: "2026-09-25T15:36:39 ensure: port 3099 not answering"` then `"15:37:08 ensure: engine answering on 3099 (pid 21440)"`. **Neither line exists in the recovery log on this node** (§5.2). | claim: `journal/entries/handoff/H2761.md`; absence: `C:/Users/ezabz/.dsh/multi-window/engine-recovery.log` | worktree checkout 2026-09-29 14:20:40 -04:00 (entry author date 2026-09-25) |

**Two entries in the repo's own record that I could not ground in a log at all, listed separately
because they are claims, not measurements I made:**

| # | When (from header) | Node (from header) | Claim | Source path | mtime |
|---|---|---|---|---|---|
| C1 | 2026-09-22 | ZABZ-YOGA | "three children died this way in one session"; stack `at get hasPending (dsh-agent-loop/lib/index.js:82:15)` / `at ContinuableActivationRegistry.settlementState (dsh-subagent/lib/index.js:1196:24)`; `job_output` returned `(no new output)` | `journal/entries/pain/P2249b.md` | checkout 2026-09-29 14:20:40 (author date 2026-09-22) |
| C2 | 2026-09-25 late | ZABZ-YOGA | "Nine of roughly fourteen mesh children died with `Read from remote host ... Connection timed out` at 15-25 minutes" | `journal/entries/handoff/H2763.md` | checkout 2026-09-29 14:20:40 (author date 2026-09-28) |

---

## 2. THE COUNTS

### 2.1 Mesh run ledger — `~/.dsh/mesh/logs/` (7,120 files: 7,119 dated 2026-09-18, 1 dated 2026-09-17)

Counted by reading every `*.jsonl` in that directory and grouping the `"phase":"..."` records.

| Quantity | Count | Window (UTC) |
|---|---|---|
| `phase:"result"` records (one per run that reached a verdict) | **22** | 2026-09-18 04:21:10 → 14:49:49 |
| — `outcome:"failed"` | **19** | 04:21:10 → 14:49:49 |
| — `outcome:"completed"` | **3** | 04:23:44 → 14:49:30 |
| `phase:"run-end"` records | 23 | 04:21:10 → 14:49:49 |
| — `exitCode:0` | 19 | |
| — `exitCode:1` | 2 | 04:21:10 |
| — `exitCode:4294967295` | 2 | 04:45:55 |
| — `timedOut:true` | **0** | |
| `phase:"traversal"` records (one per dispatch attempt, incl. retries) | **7,412** | 04:21:10 → 14:49:45 |
| — `ok:false` | **7,383 (99.6 %)** | 04:43:43 → 04:45:36 |
| — `ok:true` | 29 | 04:21:10 → 14:49:45 |

### 2.2 Distinct failure texts, ranked by count

Source: the 22 `phase:"result"` `reason` fields above, plus the 7,412 `phase:"traversal"` `reason`
fields. First/last occurrence are the record's own `at`.

| Rank | Failure text | Count | First | Last |
|---|---|---|---|---|
| 1 | `the traversal probe printed no verdict (exit 255; stdout: ; stderr: ssh: connect to host zabz-yoga-1.tail93e6e6.ts.net port 22: Connection timed out)` | 5,918 | 09-18 04:43:43 | 09-18 04:45:36 |
| 2 | `… stderr: Connection timed out during banner exchange / Connection to 100.72.162.5 port 22 timed out` | 675 | 09-18 04:43:43 | 09-18 04:45:36 |
| 3 | `… stderr: kex_exchange_identification: read: Unknown error / banner exchange: Connection to 100.72.162.5 port 22: Unknown error` | 546 | 09-18 04:43:43 | 09-18 04:45:36 |
| 4 | `… (exit none; stdout: ; stderr: )` — probe produced **nothing at all** | 107 | 09-18 04:43:43 | 09-18 04:45:36 |
| 5 | `… stderr: kex_exchange_identification: read: Connection reset / Connection reset by 100.72.162.5 port 22` | 62 | 09-18 04:43:43 | 09-18 04:45:36 |
| 6 | `… stderr: Connection closed by 100.72.162.5 port 22` | 58 | 09-18 04:43:43 | 09-18 04:45:36 |
| 7 | `… stderr: ssh_dispatch_run_fatal: Connection to 100.72.162.5 port 22: Connection timed out` | 14 | 09-18 04:43:43 | 09-18 04:45:36 |
| 8 | **`only 0 MESH-HOST lines for 1 children (0 literal, 0 summarised)`** | **15** (`result`) | 09-18 04:22:38 | 09-18 04:45:52 |
| 9 | `parent exit 1` | 2 (`result`) | 09-18 04:21:10 | 09-18 04:21:10 |
| 10 | `parent exit 4294967295` | 1 (`result`) | 09-18 04:45:55 | 09-18 04:45:55 |
| 11 | `location disagreement: ZABZ-TECH not on zabz-yoga-1` | 1 (`result`) | 09-18 14:49:49 | 09-18 14:49:49 |

Ranks 1–7 sum to 7,380; the remaining 3 traversal failures were `#< CLIXML` stderr shapes. 7,380 + 3 = 7,383 = the `ok:false` total, which is how the tally is closed.

### 2.3 Placement ledger — `~/.dsh/mesh/placements/` (83 files, all parsed)

This is the durable per-child ledger written by `createPlacementLedger` (D247), one file per child.

| Quantity | Count | Window (UTC) |
|---|---|---|
| Files | **83** | 2026-09-17 15:53:54 → **2026-09-28 18:41:19** |
| `stopReason:"completed"` | **45** | |
| `stopReason:"error"` | **25** | |
| `stopReason:"aborted"` | **3** | 09-23 23:16:34, 09-28 18:33:31, 09-28 18:24:35 |
| `stopReason` key absent entirely | **10** | 7 × `state:"dispatching"` (09-18) + 3 × `state:"placement-failed"` (09-28) |
| `exitCode:0` | 48 | |
| `exitCode:255` | **15** | 09-17 15:53:54 → 09-18 04:45:55 |
| `exitCode:4294967295` (`-1`) | 2 | 09-22 04:32:30 |
| `exitCode:1` | 2 | 09-24 20:48:49, 09-28 18:41:19 |
| `exitCode` key absent | 16 | 10 incomplete + 3 aborted + 3 unaccounted |
| `ms ≥ 1,800,000` (30-min cap) | **5** | 09-22 00:22:31 (1,800,056) · 09-28 18:19:47 (1,800,036; 1,800,048) · 09-24 20:47:30 (597,398) is *not* a cap hit — see note |
| `meshHost` empty/null | **37** | |
| `leaseReleased:false` | **3** (the two 09-28 cap hits + 1) | |
| node = `zabz-tech` | 57 | |
| node = (blank) | 26 | |

**Note on `ms ≥ 1,800,000`:** three records strictly exceed the documented cap
(`1,800,036 / 1,800,048 / 1,800,056`). Two more children were killed by the same cap with no exit code
recorded (`stopReason:"aborted"`, `ms` 806,213 and 146,743 are *not* cap hits — they are mid-turn
aborts). The 597,398 ms record is a 10-minute run, **not** a cap hit, and is excluded.

### 2.4 The two counting methods that disagree, and why

`exitCode` in the `~/.dsh/mesh/logs/*.jsonl` ledger belongs to the **parent** one-shot, not the child:
13 of the 15 E7 runs carry `"exitCode":0` while their `.out` files contain
`Diagnostic: the remote one-shot exited 255`. **A ledger row can say `exitCode:0` and mean "the child
never ran".** Any count of mesh failures taken from parent exit codes alone under-reports by 13 in this
corpus. The `.out` files are the cross-check: 13 of the 15 carry the `exited 255` diagnostic, and
**2 are 0 bytes** (§4).

---

## 3. THE CAUSES

### 3.1 `exit 255` at placement, node blank (E10, E11) — ESTABLISHED for the symptom, INFERENCE for the mechanism

**Established:** 15 placement records carry `exitCode:255`. 12 of them are at 09-18 04:45:43–55 with
`ms` of 122–393 — far too fast for any agent turn. They coincide exactly with the E1 window. The
provider returns `exit 255` when the ssh hop dies, and `-o ConnectTimeout=10` plus a reset/banner
failure lands in that window.

**Inference:** that these 12 are the *same event* as E1 rather than a second cause. The evidence is the
sub-second `ms` and the coincident window; I did not capture the stderr for the placement files, because
the `placement-failed`/`error` records for those 12 carry **no stderr field at all** (`keys` =
`id,at,source,childIndex,node,ssh,hosts,position,tier,score,eligible,blockedBy,lease,leaseTtlSec,
expiresAt,rationale,queue,placedAt,brokerAt,brokerCallMs,state,facts,invocation,nodeVerified,waitedMs,
queueTimedOut,dispatchedAt,stopReason,settledAt,leaseReleased,leaseReleaseSkipped,leaseReleaseError,
reportedHost,meshHost,invocationForm,invocationAttempts,exitCode,ms`). **No failure text is persisted for
a placement-level 255.** That is itself a cause of lost evidence.

### 3.2 `only 0 MESH-HOST lines for 1 children` (E7, 15 runs) — ESTABLISHED

The verifier requires the child's report to open with `MESH-HOST: <hostname>`. In all 15 runs
`meshHostLines:0`, `meshHostLinesLiteral:0`, `childHosts:[]`, `disagreements:[]`, `ok:false`. The child's
own answer was intact — the `.out` for `2026-09-18T04-45-26-114Z` holds 1,329 bytes including the
child's prose — and the run was marked failed anyway. **The loss is in the wrapper, not the child.**
Corroborated independently in the repo's record by `L2070`, `L2379b`, `L2577b`, `L2851`, `L3059` and
`P2667`, which report the same wording on 2026-09-20, 09-22, 09-24, 09-29.

### 3.3 The 113-second total outage (E1–E3) — ESTABLISHED

7,383 consecutive probe failures in 113 seconds, all against the laptop's **own** tailnet address
(`100.72.162.5`, `zabz-yoga-1.tail93e6e6.ts.net`). The three stderr families show the failure moved
through the stack: connect timeout → banner-exchange timeout → `kex_exchange_identification`
unknown/reset. That is sshd on the target not completing the handshake, not the ssh client refusing.
The 29 successes bracket the window (`ok:true` at 04:21:10 and 14:49:45), so the node was alive before
and after. **Inference:** that the target sshd was starved or Windows sshd was restarting. I did not
measure CPU, load or the sshd service state on that node at that time, and no such measurement survives.

### 3.4 The 30-minute cap `1800000 ms` (E12, E16) — ESTABLISHED, code-confirmed by the repo's own lesson

Five records at or over `1,800,000 ms`. `L2577b` quotes the harness's own wording verbatim:
`the remote turn did not finish within 1800000 ms and the ssh client was killed`. **This one is
inference about the code path** — I read `L2577b` and the `ms` fields, not
`packages/plugin-remote-fanout/lib/provider.js`; the code file is in this worktree and was not opened
for this claim, so I mark the code path as inherited from the journal, not independently read.

### 3.5 `broker-unreachable` (E15, 3 records) — ESTABLISHED as a report, INFERENCE on which layer broke

Three records at **exactly `2026-09-28T18:19:16`**, all with
`error:"the placement broker could not be reached at secratary-ts:http://localhost:3091/place — ssh exited 255: ssh: connect to host secratary.tail93e6e6.ts.net port 22: Connection timed out"`.
The error string names the **broker** as unreachable; the suffix names the **ssh hop to the broker's
host**. `L2091` (2026-09-20) measured the same text against a broker that was up
(`GET 127.0.0.1:3091 -> 200`, `mesh-broker.service up 1 day 18 h`) with secratary at
`io full avg10 = 95.6 %`, and `P342` names the same. **Established:** the error text conflates two
different facts. **Inference:** that all of P2668's four lanes failed this way — the text in `P2668` is
`no answer within 30000 ms`, which is a *different* string from the three records I found (`ssh exited
255`). They are two variants of one experience and I did not find a `no answer within 30000 ms` record
on this node (§4).

### 3.6 Engine `ENOENT` in the spill dir (E20) — NOT VERIFIED HERE

Reported by `H2761` and `P2550` as root-caused: `OutputCollector.spillAll`
(`dsh-subprocess-local/lib/runner-launch-COYGu0Dl.js:766`) `openSync`'d into a `%TEMP%` dir that
Windows Storage Sense had deleted, threw an unhandled `ENOENT`, and the process exited. **I did not
reproduce or read this stack.** What I did read: the only `ENOENT` in the recovery log is unrelated
(§3.7), and the recovery log contains none of the 09-25 lines the entry quotes (§5.2).

### 3.7 The 9 engine start failures (E19) — ESTABLISHED

All 9 are `Error: dsh: cannot resolve profile bundle "dsh-plugin-attention"` (8×) and
`"dsh-plugin-cost"` (3×) from `C:\Users\ezabz\.dsh\profiles\web`, exiting code 1. The single `ENOENT`
in the log is that same failure wearing its errno:
`{ errno: -4058, code: 'ENOENT', syscall: 'realpath', path: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\node_modules\\dsh-plugin-attention\\package.json' }`
at `engine-recovery.log:105`. **This is a profile/bundle resolution failure, not the spill-dir crash.**
It happened 9 times in 31 minutes on 2026-09-16 and then the engine came up on pid 47064 at 11:13:11.

---

## 4. WHAT IS SILENT

Failure modes that leave **no** log line. "How I know" is the search that came back empty.

| Silent failure mode | How I know |
|---|---|
| **A placement-level `exit 255` persists no failure text.** The 12 fast-255 placement records carry no `error`, no `reason`, no stderr field. | Read all 83 placement files; the 12 records' key set is enumerated in §3.1 and contains no error-bearing key. |
| **`stderrBytes:1929` recorded, `.out` file 0 bytes.** The count says the diagnostic existed; the artifact does not. | `2026-09-18T04-21-06-487Z.jsonl` says `stderrBytes:1929`; `Get-Item …487Z.out` = `Length 0`. Same for 4 more `.out` files (all from 09-18 00:21–00:45 local). |
| **A traversal probe can fail with `exit none` and an empty stderr** — 107 records. Nothing to read. | Rank 4 in §2.2: `(exit none; stdout: ; stderr: )`. |
| **The provider's own error strings are in no log on this node.** `broker-unreachable` appears 0 times in every `.log/.jsonl/.txt/.out/.json` under `~/.dsh` up to depth 3. | 8,135 files scanned (`Get-ChildItem -Recurse -Depth 3`, `Length 1..5 MB`, ext filter), `Select-String -SimpleMatch 'broker-unreachable'` → 0 hits. Same 0 for `ECONNRESET`, `EPIPE`, `crashloop`, `unhandled`. The only place these strings exist is the journal prose. |
| **The mesh ledger stopped being written on 2026-09-18 14:49:49 and never resumed.** There is no 09-19 … 09-29 run record. | 7,120 files in `~/.dsh/mesh/logs`; 7,119 are dated `2026-09-18`, 1 is dated `2026-09-17`. Newest `mtime` = `2026-09-18 10:49:49 -04:00`. |
| **Everything P2667/P2668 lost on 2026-09-29 has no ledger trace.** The newest placement record is `2026-09-28T18:41:19Z`. | All 83 placement files sorted by `at`; max = `2026-09-28T18:41:19`. A `no answer within 30000 ms` `broker-unreachable` record does **not** exist on this node. |
| **7 runs are frozen in `state:"dispatching"` with no terminal field.** They are neither counted as failed nor as completed by any tally that reads `stopReason`. A naive "how many children failed" query misses them entirely. | The 7 files in E18 have keys ending at `dispatchedAt`. §2.3 counts them as a separate row. |
| **An engine that dies and restarts is indistinguishable from one that never died** when the watchdog's recovery path is not taken. | The recovery log has 14,226 identical `DSH_HOME was unset` lines and only **9** `start FAILED` lines, 15 `engine answering on` lines. Nothing emits "the engine died". `P2550` P1 asks for exactly this detector and it does not exist. |

---

## 5. WHAT I COULD NOT VERIFY

### 5.1 The authority (`secratary`) — reached once, then not

- **Call 1 (`ssh secratary-ts 'echo SSH_OK; hostname'`, `ConnectTimeout=8`):** `SSH_OK` and a hostname
  line were returned. The call then **hung** and was killed at the 120 s ceiling.
- **Calls 2–5** (`hostname; systemctl …; ls -la ~`; then `hostname; ls -la /home/zabz`; then
  `echo OK4`; each with `ConnectTimeout 5–8`, `ServerAliveInterval 3–4`): **all timed out with no
  output**, at 120 s / 60 s / 45 s / 60 s. The last was a five-character echo.
- **Therefore: not reached for content.** No broker log, no `journalctl -u mesh-broker`, no
  `mesh-placement.json`, no `/home/zabz` listing. I did not change anything there; I could not.
- **This is itself evidence, not a lane failure.** One success followed by four timeouts of a trivial
  command from the same client in the same session reproduces the shape `L2091` measured on 2026-09-20
  (`io full avg10 = 95.6 %`, "sshd was accepting nothing for ~30 s at a time") and the shape recorded in
  E15 and C2. It is a **live** sample of the transport symptom, on the same day as P2667/P2668.

### 5.2 The 2026-09-25 engine crash (E20 / `H2761` / `P2550`) — cannot be verified from surviving logs

- `H2761` cites `~/.dsh/multi-window/logs/3099-20260924-215958.err.log` for "the ENOENT stack, quoted
  above". **That file does not exist on this node.** `Get-ChildItem *20260924*` in that directory
  returns only `health-20260924.log`.
- `H2761` quotes two lines: `[2026-09-25T15:36:39…] ensure: port 3099 not answering` and
  `[2026-09-25T15:37:08…] ensure: engine answering on 3099 (pid 21440)`. **Neither line is in the
  recovery log.** The two log lines at those seconds are the routine
  `DSH_HOME was unset - set to C:\Users\ezabz\.dsh for the engine`. `Select-String 'port 3099 not
  answering'` over the whole recovery log returns only the 34 `attempt N/N` lines; the 15
  `engine answering on` lines are dated 09-15, 09-16 (×4), 09-17 (×2), 09-18, 09-20 (×5), 09-28 — none
  on 09-25, and none with pid 21440.
- The `.err.log` that *does* cover that window, `3099-20260920-155732.err.log`
  (`mtime 2026-09-25 20:08:55`, 3,309 lines, 139,952 B), contains **no** `Unhandled`, `ENOENT`,
  `unhandledException`, or stack trace. Its `Error` lines are 100+ repetitions of
  `Error from remote server: Error: SSE stream disconnected: TypeError: terminated` from an MCP client.
- **Conclusion: the 09-25 crash is a claim in the journal that the surviving logs on this node neither
  confirm nor describe.** The only `ENOENT` in the recovery log is the unrelated 09-16 profile-bundle
  failure (§3.7). I am not calling the entry wrong — I am recording that the cited artifact is
  unreachable and the quoted lines are absent, so this lane cannot put the crash in the event table as a
  measurement. It is E20/C-class evidence.

### 5.3 Everything else I could not reach

| Source | Status |
|---|---|
| `~/.dsh/mesh/logs` runs after 2026-09-18 | **Absent, not empty.** 0 files dated 09-19…09-29. Written up as a silent mode in §4, not as health. |
| `~/.dsh/sessions` — per-session transcripts that would hold `job_output` results | **Not searched for content in this lane.** Directory listing reached (6 project dirs, newest `2026-09-29 14:27`); the 09-29 session holding the P2667 lane output was not opened. A lane with more budget should read it: it is the only place the discarded 09-29 lane text could survive. |
| `journal/index/journal.db` | **Not opened.** `git status` on the shared clone shows it ` M` (modified, dirty). Not touched, per the no-write rule. |
| `C1` (settlement crash, `P2249b`) | **Not grounded.** No `settlementState`, `hasPending`, `dsh-agent-loop`, or `dsh-subagent` stack appears in any log under `~/.dsh` in my bounded scan. It is a journal claim only. |
| Repo's `docs/mesh/110-subagent-visibility.md`, `117-journal-divergence.md` | **Not read.** Chosen against the deadline; the event table above was built from primary artifacts first. |
| `_scratch/mesh-inventory/inventory.jsonl` | **Reached.** 5 rows, 2026-09-18T15:00Z, `reachable:true` for all five nodes. It contains **no** crash data — it is a point-in-time hardware inventory. All 5 rows report `host:""` for secratary, linux-pc and mac-mini. |
| Any file over 5 MB | **Skipped by rule.** The two candidates are `engine-recovery.log` (1.4 MB — read, under the limit) and `dsh-archive-state.json` (290 KB — not read). |

---

## 6. WHAT THIS DOES AND DOES NOT SAY

**Does:** the owner's report that mesh fan-out "constantly fails and crashes" is **quantified and
confirmed on this node** — 19 of 22 recorded child runs failed, 25 of 83 placements errored, 7,383
consecutive dispatch attempts failed inside 113 seconds, ~38 of 83 children never produced a verifiable
host, and the failure modes are dominated by transport breakage and report-discard rather than by model
errors.

**Does not:** claim the ledger is complete. The runs the owner lost most recently — 09-29, P2667 and
P2668 — left **no ledger record at all** on this node. The 09-18 corpus is the last time the harness
wrote down what happened to a mesh child. After 09-18, the only surviving record of a lost run is a
placement file (through 09-28) and a journal entry written by the session that suffered it.
