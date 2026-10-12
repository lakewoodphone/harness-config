# 186 — THE PARENT/CHILD CHANNEL: what works, what was broken, and what needs an engine change

**Machine:** `zabz-tech-linux` (Linux, user `zabz`)
**Repo:** `/home/zabz/code/harness-config` (branch `main`)
**Written:** 2026-10-12
**Parent-of-record for this thread:** `zabz-yoga-1` (Windows) — every dispatch in
§3 was made **from `zabz-tech-linux` to `zabz-tech`/`zabz-tech-ts` (Windows)** so both
sides of a real cross-machine boundary are in the measurement.

---

## 0. The one-paragraph answer

The child→parent mailbox thread is now real and demonstrated: the dispatch **creates
the thread directory on the child's node before the child boots**, the child's progress
lines are **carried back inside the same ssh round trip** (and, if the child dies
mid-turn, fetched by one bounded read-only read-back), and the parent has a
`bin/mesh-thread.mjs` command that reads the thread from the child's node **while the
child is still running**. `mailbox = 0 message(s)` — which used to mean "empty", "absent",
and "read against the wrong disk" all at once — is replaced by `EMPTY`, `ABSENT`,
`COULD NOT CREATE`, or `UNREADABLE`. The **parent→child mid-turn direction still does
not exist** and cannot be built without an engine change (§6); the honest version of
"together" is a durable file channel in one direction plus a loud failure line, and that
is what is delivered.

---

## 1. What was measured before any code was written

### 1.1 The parent's own read is local, but the mailbox is on the child

`lib/provider.js` `readMailbox()` called `mergeThread()` / `collectThread()` from
`lib/mailbox.js`, both of which are plain `node:fs`. The path handed to them is the
**child's** path (`lib/provider.js` resolves the mailbox after placement from the placed
node's facts). When parent and child are different machines the parent reads a path that
exists only on the other disk.

Measured on the live node with the HEAD checkout (`/tmp/hc-head`), dispatching a real
child to `zabz-tech-ts` (`/tmp/channel-parent-probe.mjs`):

```
BASE=/tmp/hc-head/packages/plugin-remote-fanout
stopReason=completed
mailbox        = 0 message(s) in the thread at C:\Users\ezabz\.dsh-mesh-mailboxes\channel-demo-head-20261012
--- thread section present? ----
NO — no conversation thread rendered
```

The child **did** write (the same two lines the child reported), on the child's own disk:

```
$ ssh zabz-tech-ts cmd /c "type C:\Users\ezabz\.dsh-mesh-mailboxes\channel-demo-head-20261012\outbox.jsonl"
{"at":"2026-10-12T16:32:35Z","from":"child","kind":"progress","text":"probe line one"}
{"at":"2026-10-12T16:32:38Z","from":"child","kind":"progress","text":"probe line two"}
```

So `0 message(s)` was **not** "the child was silent". It was "the parent looked in the
wrong place", and the report could not tell the operator which.

### 1.2 Nothing created the thread directory at dispatch

`mkdirSync` appears in `lib/mailbox.js` only on the write side (`appendMessage`,
`mergeThread`). `provider.js` line ~570 claimed *"The child is told to create it"*, but
`childInstructions()` never says so. A child that writes nothing leaves **no thread at
all**, which is indistinguishable in the report from a thread the parent could not find.

### 1.3 The progress tee already existed and was never wired up

`lib/remote-script.js` has an opt-in `progressFile` (a target-side tee of the child's
stdout/stderr with `FANOUT_PROGRESS:START`/`EXIT`) and `parseProgress()` / `harvestOutput()`.
`grep -rn 'progressFile\|parseProgress' lib/*.js` shows **no caller outside
`remote-script.js`**: `provider.js`'s `runOnce()` built the script as
`{ ...spec, task: childTask, nonce }` and never passed it. The live-progress capability
was dead code.

### 1.4 The dispatch header itself can name the wrong machine's path

The header of *this* session's own dispatch, read from `/proc/<pid>/cmdline`, was:

```
MESH_MAILBOX={"dir":"C:\\Users\\ezabz\\.dsh-mesh-mailboxes\\remote-007fb72d-...", ...}
```

The child ran on `zabz-tech-linux` (Linux). The path is a Windows path, and it did not
exist on the child. Controlled reproduction of what that does on a POSIX node
(`buildPosixScript` with a Windows `mailbox.dir`, run under `sh`):

```
FANOUT_MAILBOX_deadbeef=READY C:\Users\ezabz\.dsh-mesh-mailboxes\wrong-platform
$ ls -la
drwxrwxr-x  2 zabz zabz 4096 ... C:\Users\ezabz\.dsh-mesh-mailboxes\wrong-platform
```

i.e. POSIX `mkdir -p 'C:\Users\...'` **succeeds** by creating one file or directory
whose literal name contains backslashes. The fix below does not repair the wrong path —
that is the dispatcher's configuration defect (`profiles/mesh/cordis.patch.yml`
derives `remoteShell`/`remoteCwd` from `process.platform` and only the `MESH_REMOTE_*`
env overrides correct it) — but it makes the result **visible** (`FANOUT_MAILBOX=READY
<path>`) and makes the thread travel in-band, so a wrong path no longer silently voids
the channel.

---

## 2. What was changed

Files touched (all under `packages/plugin-remote-fanout/`):

| file | change |
|---|---|
| `lib/remote-script.js` | `markers()` gains `mailbox`, `threadBegin`, `threadMsg`, `threadEnd`. `buildPosixScript`/`buildPwshScript` gain a `mailbox` param: an idempotent `mkdir` **before** the child, and an in-band thread dump **after** the child's `end` and **before** the `exit` marker. New `buildThreadReaderScript()` — a read-only reader used by the read-back. |
| `lib/provider.js` | `runOnce()` passes `mailbox` to the builder. New `parseThreadDump()`, `mailboxStateLine()`, `failureHeadline()`. `readMailbox()` is now async and ordered: **in-band dump → bounded ssh read-back → local fs**. It returns `state ∈ OK/EMPTY/ABSENT/MKDIR-FAILED/UNREADABLE`. `renderReport()` prints `⚠ FAILED — …` on line 2 for any diagnostic, and the new mailbox-state line. |
| `bin/mesh-thread.mjs` | **new** parent-side CLI: reads one thread from the child's node over ssh, `--follow` to tail it live, distinct exit codes `0` read / `3` ABSENT / `4` READ FAILED. |
| `test/channel.test.mjs` | **new** 9 tests, all runnable on Linux (POSIX builder + real `sh`). Two of them pin the loud-failure line (`failureHeadline` and the `⚠ FAILED` line as report line 2); the other seven exercise the builder, the parser, the opt-out, the state lines and the read-back. |
| `package.json` | new test file added to `test`/`verify`; `node --check bin/mesh-thread.mjs` added. |

The in-band dump is placed **after `FANOUT_END` and before `FANOUT_EXIT`** on purpose:
`parseFanout()` slices the answer between `begin`/`end`, so the thread never leaks into
the child's final message, and the transport's completion-marker poll already has the
dump in the file by the time it sees `FANOUT_EXIT`.

The read-back is **gated** on `activeTransport.kind === 'ssh'` **and** a recorded target
host. That keeps the local same-filesystem path (and every existing test double)
unchanged, and means a node that never connected costs no extra wait.

---

## 3. The real end-to-end proof

### 3.1 A real child on a real remote node, patched

Parent: `zabz-tech-linux`. Child: a real `dsh --profile headless` agent on
`zabz-tech-ts` (Windows), over `ssh`. The task asked the child to append four progress
lines to its own outbox at 5-second intervals and then report.

```
$ DEMO_TARGET=zabz-tech-ts DEMO_THREAD=channel-demo-20261012 node /tmp/channel-parent.mjs
PARENT: dispatched child id=remote-ed71cbe7-2d49-4ac3-a5e8-9bb3346f4231 thread=channel-demo-20261012 target=zabz-tech-ts at 2026-10-12T16:29:58.315Z
PARENT: mailbox dir on the child = C:\Users\ezabz\.dsh-mesh-mailboxes\channel-demo-20261012
PARENT: settled after 60571 ms, stopReason=completed
...
mailbox        = 4 message(s) in the thread at C:\Users\ezabz\.dsh-mesh-mailboxes\channel-demo-20261012
transport host = ZABZ-TECH  (recorded by the target shell before the agent started)
exit = 0 in 60556 ms (ssh client terminated after the completion frame)
--- child final message ---
MESH-HOST: ZABZ-TECH
...
--- conversation thread (4 message(s); the child wrote as it worked) ---
<- CHILD  [PROGRESS] 2026-10-12T12:30:40.2163709-04:00
    t=0 child alive
<- CHILD  [PROGRESS] 2026-10-12T12:30:45.2274641-04:00
    t=5 still working
<- CHILD  [PROGRESS] 2026-10-12T12:30:50.2425620-04:00
    t=10 more progress
<- CHILD  [PROGRESS] 2026-10-12T12:30:55.2477174-04:00
    t=15 nearly done
--- end conversation thread ---
```

### 3.2 The same child, same node, before the change

```
BASE=/tmp/hc-head/packages/plugin-remote-fanout
mailbox        = 0 message(s) in the thread at C:\Users\ezabz\.dsh-mesh-mailboxes\channel-demo-head-20261012
NO — no conversation thread rendered
```

The message count now matches what is on the child's disk, and the child's early words
are in the parent's result.

### 3.3 Lines were visible **while the child was still running**

The parent tailed the thread from the child's node with the new CLI at the same time as
the dispatch above. The child settled at `16:30:58`; the poll at `16:30:46` already saw
two lines:

```
$ node bin/mesh-thread.mjs --target zabz-tech-ts --shell powershell \
      --dir 'C:\Users\ezabz\.dsh-mesh-mailboxes\channel-demo-20261012' --json --quiet
16:30:19 poll=1 exit=0 lines=0
16:30:28 poll=2 exit=0 lines=0
16:30:37 poll=3 exit=0 lines=0
16:30:46 poll=4 exit=0 lines=2
    {"at":"2026-10-12T12:30:40.2163709-04:00","from":"child","kind":"progress","text":"t=0 child alive"}
    {"at":"2026-10-12T12:30:45.2274641-04:00","from":"child","kind":"progress","text":"t=5 still working"}
16:30:55 poll=5 exit=0 lines=4
    ... all four ...
```

Poll 1 (`16:30:19`) is the `EMPTY` state — the directory exists, the child has not
written yet — and reports cleanly instead of failing.

### 3.4 The dispatch created the directory, with no child output at all

`test/channel.test.mjs` runs the generated POSIX program under a real `sh` with
`command: true` (the child writes nothing):

```
ok - the dispatch creates the thread directory on the child, even when the child writes nothing
ok - a message written by the child travels back in-band and is parsed once
ok - a child that dies before the in-band dump is read back over the ssh transport
```

### 3.5 Independent re-verification on the same thread (second dispatch)

This section was added by a second dispatch on the same thread. It re-ran the two real
cross-machine proofs from scratch rather than trusting §3.1–§3.4.

**Live two-way read, re-run.** Parent `zabz-tech-linux` → a real headless DSH child on
`zabz-tech-ts` (Windows), thread `channel-verify-163746`, dispatched `16:37:47Z`. The parent
polled the child's own node with the new CLI *while the child was working*:

```
16:37:51  mesh-thread: PRESENT — 0 message(s)        (directory exists, child not yet written)
16:37:58  mesh-thread: PRESENT — 0 message(s)
16:38:05  mesh-thread: PRESENT — 2 message(s)
    {"at":"2026-10-12T16:37:59Z","from":"child","kind":"progress","text":"t=0 child alive"}
    {"at":"2026-10-12T16:38:04Z","from":"child","kind":"progress","text":"t=5 still working"}
16:38:11  mesh-thread: PRESENT — 3 message(s)
16:38:18  mesh-thread: PRESENT — 5 message(s)        (child's own final report line included)
```

The child's closing line was written at `16:38:16Z`; the `16:38:05` and `16:38:11` reads are
therefore genuinely mid-turn. The parent's own final report then carried the thread in-band:

```
stopReason     = completed
mailbox        = 5 message(s) in the thread at C:\Users\ezabz\.dsh-mesh-mailboxes\channel-verify-163746
--- conversation thread (5 message(s); the child wrote as it worked) ---
```

**The explicit step-2 proof, re-run.** A second real child on `zabz-tech-ts` was told to write
nothing (`channel-empty-164016`). Its report names the directory and the emptiness instead of a
fake count:

```
stopReason = completed
mailbox    = EMPTY — the thread directory exists at C:\Users\ezabz\.dsh-mesh-mailboxes\channel-empty-164016 and the child wrote nothing
```

**Tests, re-run.** Full package suite, patched: **179 pass / 5 fail / 24 cancelled** (208
total). The same suite against a clean `git worktree` of the parent commit `8b176117`
(`/tmp/hc-head2`): **170 pass / 5 fail / 24 cancelled** (199 total). All 9 added tests pass;
the 5 failures and 24 cancellations are unchanged by the change.

**Cleanup, re-checked.** `tasklist` on `zabz-tech-ts` shows no `channel-` child process from
either run (the matching node processes are the machine's own services). No parent process
was left; scratch is under `/tmp`.

---

## 4. Failure visibility: current behaviour vs. the change

Measured against a genuinely unreachable node (`unreachable-node-xyz.invalid`, `/tmp/negative-demo.mjs`), HEAD vs. patched.

| case | HEAD (before) | now |
|---|---|---|
| **transport / node unreachable** | first line of the report is `MESH-HOST: (not reported)`; the failure is only at the **bottom**, `diagnostic = the remote one-shot exited 255 …`; the thread line reads `mailbox = 0 message(s) at /tmp/probe-mailboxes/probe-unreachable` — indistinguishable from a silent child | report line 2 is `⚠ FAILED — the remote one-shot exited 255 and produced no final message`; the thread line is `⚠ mailbox = UNREADABLE at … : read with the parent's own filesystem …; a child on node "UNKNOWN" keeps its thread on that node` |
| **child wrote nothing, dispatch ok** | `mailbox = 0 message(s)` | `mailbox = EMPTY — the thread directory exists at … and the child wrote nothing` |
| **thread directory not created** | `mailbox = 0 message(s)` | `⚠ mailbox = COULD NOT CREATE … on the child's node: <error>` (from the `FANOUT_MAILBOX=<nonce>FAILED` frame) |
| **child died mid-turn, before the closing frame** | local fs read; across machines, 0 | one bounded read-only ssh read-back; if it answers, the early messages are attached and counted (test `ok 9`, fake ssh transport) |
| **exited 0 but printed no completion frame** | no headline; the only copy of the reason is `diagnostic = the remote process exited 0 but printed no completion frame …` at the bottom | report line 2 is `⚠ FAILED — the remote process exited 0 but printed no completion frame` |
| **cannot be placed** | already logged `remote-fanout: child <id> could NOT be placed — <code>: <message>` and `start()` rejects with the same; unchanged | unchanged (already loud). Measured with a placer that throws `MESH_SATURATED`: `start()` rejected `remote-fanout: MESH_SATURATED: every node is saturated (freeSlots 0/2)` and the logger carried the same line — one immediate line naming the failure, no run published |

The unreachable-node run also shows the existing retry machinery working (3 transport
attempts, then stop); nothing in the change weakens that.

---

## 5. What cannot be fixed with the current engine

**Parent → child mid-turn does not exist and cannot be made to exist by this plugin.**
A remote mesh child is a fresh `dsh --profile headless` one-shot process on another
node. It is never a *resident continuable* child, and the seam's `send_message`
requires one. Measured live from a child on this mesh (docs/mesh/160, re-confirmed):

```
list_agents  -> (no subagents)
send_message <remote id> -> Error: subagent "<id>" is unavailable
```

The durable mailbox is the honest substitute and is now two-way in the only sense the
engine permits:

* **child → parent, live:** the child appends JSON lines to its outbox; the parent runs
  `bin/mesh-thread.mjs --follow` and sees them within one poll interval while the child
  still runs (§3.3).
* **parent → child, between turns:** the parent writes `inbox.jsonl` on the child's node
  (`appendMessage(inbox, { from: 'parent', … })`) and the next dispatch on the same
  `threadId` is told to read it first. That is a turn-boundary channel, not a live one.

**The engine change that would make the owner's sentence literally true:** a remote
provider needs an *Activation ownership contract* so a remote child becomes a resident,
addressable activation — i.e. the remote process advertises an id the parent's
`ctx.subagents` registry can hold, and `send_message` can enqueue a turn for it while it
runs. Until that exists, no amount of ssh scripting gives mid-turn parent→child, and this
document does not claim otherwise.

---

## 6. Using it

```
# tail one child's thread from its own node, live
node packages/plugin-remote-fanout/bin/mesh-thread.mjs \
    --target zabz-tech-ts --shell powershell \
    --thread remote-abc123 --root 'C:\Users\ezabz\.dsh-mesh-mailboxes' --follow

# one-shot read; exit 3 = ABSENT, 4 = READ FAILED
node packages/plugin-remote-fanout/bin/mesh-thread.mjs \
    --target zabz-tech-ts --shell posix --dir /home/zabz/code/.dsh-mesh-mailboxes/remote-abc123
```

A dispatched child's report now always carries the thread when there is one, and always
names the thread state when there is not.

## 7. Tests

`node --test` on the package: **179 pass / 5 fail / 24 cancelled** (208 total) with the 9 new
`channel.test.mjs` tests included. The 5 failures and 24 cancellations are **pre-existing
on Linux**: I ran the identical suite against a clean `git worktree` of the parent commit
`8b176117` (`/tmp/hc-head2`) and got **170 / 5 / 24** (199 total). The 9 added tests all
pass; the difference is exactly the added tests. The 5 failures are the four
`conversation.test.mjs` cases plus the `mailbox is placed on the CHILD node path` case,
all of which hard-code `shell: 'powershell'` while running on Linux, so `mailboxPaths`
derives `\tmp\...` with `path.win32.join` while the assertion checks the POSIX path. They
pass on a Windows runner (the sibling measurement on `zabz-tech` reported 20/20 there).
They are not caused by this change and are left as measured.

## 8. Cleaning up

No child was left running; the demo children exited and the target was checked for
stray `node.exe` processes matching `channel-demo` (none). All scratch files are under
`/tmp`. The literal-backslash directories the Windows-shaped-path tests create inside
the repo were removed.
