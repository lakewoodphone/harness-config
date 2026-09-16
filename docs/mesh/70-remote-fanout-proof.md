# 70 — The remote fan-out proof: one agent on one node, children on another, no restart

**Program:** `docs/mesh/` (stream S6 — dispatch). **Depends on:** `71-mesh-program.md` §1, §2.2, §2.3,
§2.4, §5; `66-dsh-remote-capability.md` §2c/§3; `62-worker-runtime.md` §1.1/§2.3/§3.
**Date:** 2026-09-16 late / 2026-09-17 UTC. **Author:** a delegated build session, not the owner.
**What was NOT done:** no engine was started, stopped, restarted or reconfigured on any node; no git
push; `scripts/phone-gate.py` and `packages/mesh-broker/**` were read, never touched.

**The claim this document proves:** a parent agent running on one node dispatched three children that
each ran as a real DSH agent turn on a different node, the dispatcher verified *from each child's own
report* where it ran, and the node running the parent stayed flat. It used the mesh broker's
`POST /place` and `POST /done`, and nothing anywhere restarted.

---

## 1. What was built, file by file

| file | what it is |
|---|---|
| `packages/plugin-remote-fanout/package.json` | the package: `dsh.bundle.patch → cordis.patch.yml`, zero runtime dependencies |
| `packages/plugin-remote-fanout/lib/index.js` | the Cordis row. Registers a `SubagentProvider` on the existing `ctx.subagents` named-provider registry. `inject: ['subagents']`; every deployment fact is config, and a missing one fails the boot loudly (`lib/index.js:61` → `createSshTransport`) |
| `packages/plugin-remote-fanout/lib/provider.js` | the provider itself — `RemoteOneShotProvider`: `name`, `capabilities` (all false), `inheritsParentContext: false`, `start()`. It prepends the `MESH-HOST` instruction (`DEFAULT_TASK_PREAMBLE`, `lib/provider.js:88`), and it **fails the run** on either location disagreement (`lib/provider.js:262-275`) |
| `packages/plugin-remote-fanout/lib/ssh-transport.js` | the transport: one bounded `ssh` per child, both streams redirected to **files** (never pipes — §4.1), settled by the completion frame rather than by the client's exit (§4.2) |
| `packages/plugin-remote-fanout/lib/remote-script.js` | the pure half: build the target's script (PowerShell `-EncodedCommand`, or `sh -s` for a POSIX node) and parse the framed reply. No imports, no I/O — this is the unit-tested half (§5) |
| `packages/plugin-remote-fanout/cordis.patch.yml` | the two rows the bundle adds: the provider, and a **second** `@deepseek-ai/dsh-tool-subagent` instance bound to it as `subagent_remote` (the built-in `spawn` tool is untouched, so a parent chooses by tool name) |
| `packages/plugin-remote-fanout/bin/install-mesh-profile.mjs` | the keeper for the profile: writes `$DSH_HOME/profiles/mesh/{package.json,pnpm-workspace.yaml,cordis.patch.yml}`, links the package into the profile's `node_modules`, and **checks that every bundle resolves**. Idempotent; `--check` is read-only |
| `packages/plugin-remote-fanout/bin/mesh-run.mjs` | the dispatcher CLI — PLACE (broker) → CONFIGURE → RUN → VERIFY → DONE, with the frozen exit contract 0/10/1 (§3) |
| `packages/plugin-remote-fanout/test/{remote-script,ssh-transport,provider}.test.mjs` | 35 tests, 35 passing (§5) |
| `profiles/mesh/cordis.patch.yml` | the `mesh` profile's layer: the `agent-presets` row plus the provider's deployment config, all of it resolved from the environment at boot (§2) |

**Where it is mounted, and why that needs no restart.** The `mesh` PROFILE carries the composition
(`dsh-base` + `dsh-headless` + this bundle), and a profile is read at process start. So
`dsh --profile mesh headless "<task>"` is a dispatcher **on any node** whose children fan out across
the mesh, while a resident engine — including the laptop engine the owner is working in — is never
touched. `71` §5 asks for exactly this and calls it stream S6's deliverable; mounting the same
provider in a resident engine remains the upgrade for the first restart window.

---

## 2. The commands, exactly

### 2.1 Install the profile (idempotent, from the repo)

```powershell
node C:\Users\ezabz\code\harness-config\packages\plugin-remote-fanout\bin\install-mesh-profile.mjs
```
```
dsh home      C:\Users\ezabz\.dsh
profile       C:\Users\ezabz\.dsh\profiles\mesh
plugin source C:\Users\ezabz\code\harness-config\packages\plugin-remote-fanout
plugin name   dsh-plugin-remote-fanout
manifest      written (@deepseek-ai/dsh-base, @deepseek-ai/dsh-headless, dsh-plugin-remote-fanout)
link          C:\Users\ezabz\.dsh\profiles\mesh\node_modules\dsh-plugin-remote-fanout -> C:\Users\ezabz\code\harness-config\packages\plugin-remote-fanout
patch         C:\Users\ezabz\code\harness-config\profiles\mesh\cordis.patch.yml -> C:\Users\ezabz\.dsh\profiles\mesh\cordis.patch.yml
bundles       checked against C:\Users\ezabz\.dsh\profiles\node_modules

install-mesh-profile: ready — dsh --profile mesh headless "<task>"
```

### 2.2 Dispatch, with the broker deciding the node

```powershell
node ...\packages\plugin-remote-fanout\bin\mesh-run.mjs `
  -Prompt (Get-Content C:\Users\ezabz\fanout-tmp\proof-task.txt -Raw) `
  -Children 3 -Exclude "zabz-yoga,secratary"
```

The two exclusions are the measured limits in §4.3 and §4.4, and they are passed to the broker as
`task.exclude`, so the broker's own `rationale` says so — it is not a silent override.

`mesh-run` — and not the model — owns the placement, exactly as `71` §2.3 freezes: PLACE, then start
the parent with the placed node in its environment, then VERIFY, then DONE.

### 2.3 The measurement, and the raw result

`C:\Users\ezabz\fanout-tmp\proof-driver.ps1` sampled the parent's node every 4 s around the run. That
directory was deleted at the end (§7), so the **authoritative, retained** record is the dispatcher's
own: `~/.dsh/mesh/logs/2026-09-16T23-27-44-800Z.jsonl` (3,190 B) and the matching `.out` (1,657 B),
both read for this document. The four runs of this session are retained there in full.

**Broker placement** (`mesh-run` log, 2026-09-16T23:27:44Z):

```json
{"phase":"place","ok":true,"node":"zabz-tech","position":0,"score":20,"eligible":1,"tier":"fits",
 "blockedBy":[],
 "rationale":["chosen from 4 configured node(s): 0 unreachable, 2 excluded by the caller, 0 switched off in the roster; tier=fits; chosen zabz-tech",
  "zabz-tech: 24 slot(s) of at most 24: floor((52242 MiB free - 3885 MiB reserve) / 160 MiB) = 302 slot(s), capped at maxSlots=24 -> 24, minus governor.inUse=0 -> 24",
  "zabz-tech: 20 free slot(s) of 24 (slots 24 = 24 raw - see above, minus 4 broker lease(s) running here; 0 queued)",
  "zabz-tech: disk 220 GiB free on C:/Users/ezabz/code vs 22 GiB required (20 GiB fleet floor + 2 GiB declared worktree) -> gate passes",
  "zabz-tech: 20 free slot(s) - 3 child(ren) = 17 >= 0 -> fits now",
  "position 0: 20 free slot(s) - 3 child(ren) = 17 >= 0 on a reachable node -> start now",
  "zabz-yoga: 22 free slot(s) of 24, 19 after 3 child(ren), excluded by the caller",
  "zabz-tech-linux: 22 free slot(s) of 24, 19 after 3 child(ren), disk 21 GiB < 22 GiB required",
  "secratary: 22 free slot(s) of 24, 19 after 3 child(ren), excluded by the caller",
  "lease mu4qdyk7-13752-e-de63068f (opaque, running) expires 2026-09-16T23:42:46.231Z; ttl 900 s, reclaimed by the broker at expiry so a dead dispatcher cannot wedge the mesh"],
 "lease":"mu4qdyk7-13752-e-de63068f"}
```

**The dispatcher's own record** (same file, same run):

```json
{"phase":"run-end","node":"zab-tech","exitCode":0,"timedOut":false,"ms":64346,"stdoutBytes":1657}
{"phase":"verify","node":"zabz-tech","meshHostLines":6,"transportHostLines":3,"childHosts":["zabz-tech"],"disagreements":[],"ok":true}
{"phase":"done","ok":true,"lease":"mu4qdyk7-13752-e-de63068f","brokerSaid":{"ok":true,"released":true,"heldMs":65074}}
{"phase":"result","outcome":"completed","node":"zabz-tech","childHosts":["zabz-tech"]}
```
*(`node` is spelled `zabz-tech` in the run records; the typo above is in this document only — the log
file is authoritative and was read, not retyped.)*

**The parent's own final message**, verbatim from the dispatcher's stdout (698→1657 bytes):

```
PARENT_HOST=zabz-yoga ; PARENT_FILE=LAPTOP-MARKER-9f3c1a ;
CHILD=1 MESH_HOST=MESH-HOST: zabz-tech TRANSPORT=transport host = ZABZ-TECH  (recorded by the target shell before the agent started) REPORT=MESH-HOST: zabz-tech ... CHILD_FILE=DESKTOP-MARKER-9f3c1a ; TOKEN=REMOTE-CHILD-1 ; CHILD_OK ;
CHILD=2 MESH_HOST=MESH-HOST: zabz-tech TRANSPORT=transport host = ZABZ-TECH  (recorded by the target shell before the agent started) REPORT=... CHILD_FILE=DESKTOP-MARKER-9f3c1a ; TOKEN=REMOTE-CHILD-2 ; CHILD_OK ;
CHILD=3 MESH_HOST=MESH-HOST: zabz-tech TRANSPORT=transport host = ZABZ-TECH  (recorded by the target shell before the agent started) REPORT=... CHILD_FILE=DESKTOP-MARKER-9f3c1a ; TOKEN=REMOTE-CHILD-3 ; CHILD_OK ;
PARENT_DONE
```

**What each of those lines is evidence of.**

| line | what it proves |
|---|---|
| `PARENT_HOST=zabz-yoga` (+ `PARENT_FILE=LAPTOP-MARKER-9f3c1a`) | the PARENT ran on the laptop: only that machine's `C:\Users\ezabz\fanout-tmp\child-marker.txt` contains that string |
| `MESH-HOST: zabz-tech` (×3) | each CHILD ran its own `hostname` and reported `zabz-tech` — the frozen proof of location (`71` §2.4) |
| `transport host = ZABZ-TECH` (×3) | the same three children, recorded by the **target's own shell** before any model ran. This is not a model claim; it is the transport measuring the machine it landed on |
| `CHILD_FILE=DESKTOP-MARKER-9f3c1a` (×3) | each child **read a real file on its own filesystem**: the same path holds `LAPTOP-MARKER-9f3c1a` on the laptop, so this line distinguishes which filesystem the read happened on |
| `CHILD=1/2/3` with distinct `TOKEN=` | three distinct dispatches, not one result repeated |
| `disagreements: []`, `meshHostLines: 6` | the dispatcher compared every `MESH-HOST:` line and every `transport host =` line against the node the broker named, and found none that disagreed |

### 2.4 The parent's node stayed flat

Sampled on `ZABZ-YOGA` (the node the parent ran on) by `proof-driver.ps1`, every 4 s, 2026-09-16:

| | commit charge used | available physical | node.exe processes | node working-set sum |
|---|---|---|---|---|
| **BEFORE** 23:27:44.517Z | 24,008,372,224 B (22.36 GiB) | 15,971,024,896 B | 17 | 2,039,877,632 B |
| **AFTER** 23:28:53.270Z | 23,643,631,616 B (22.02 GiB) | 16,179,982,336 B | 12 | 1,738,199,040 B |
| **delta** | **−364,740,608 B (−0.34 GiB)** | +208,957,440 B | −5 | −301,678,592 B |

Sixteen samples were taken during the run; the peak commit charge observed was 24,090,886,720 B
(22.44 GiB), i.e. **+0.08 GiB over the before reading**. Commit limit at the time:
46,293,966,848 B (43.11 GiB), derived as `Win32_OperatingSystem.TotalVirtualMemorySize −
FreeVirtualMemory` — the formula `20-placement.md`'s correction row 3 insists on. That derivation was
cross-checked against `\Memory\Committed Bytes` **on ZABZ-TECH**, not on ZABZ-YOGA (the laptop was not
counter-probed): derived 16,305,594,368 B vs counter 16,421,019,648 B, 0.7 % apart, 22:49:53Z. On the
laptop only the derived number was taken, so the laptop's *absolute* value carries that 0.7 %
uncertainty; the **delta** does not, because both readings use the same formula seconds apart.

**Verdict: flat**, and it is flat for a structural reason: the parent process spawns nothing but ssh
clients, and each child's whole agent turn happens in the target's process. `71` §4.4's bar was ±1 GB;
the measured change is −0.34 GiB.

### 2.5 The exit contract

```powershell
node ...\bin\mesh-run.mjs -Prompt "<one-child task>" -Node zabz-tech -Children 1
```
```json
{"phase":"run-end","node":"zabz-tech","exitCode":0,"timedOut":false,"ms":28433}
{"phase":"verify","node":"zabz-tech","meshHostLines":2,"transportHostLines":1,"childHosts":["zabz-tech"],"disagreements":[]}
{"phase":"result","outcome":"completed","node":"zabz-tech","childHosts":["zabz-tech"]}
MESHRUN_EXIT_CODE=0
```
`0` completed ✓. The other two codes are implemented and their paths are exercised by unit tests and
by the failed runs recorded in §4.4 and §4.5 — `10` queued is only reachable when the broker answers
`position > 0`, and **no placement in this session was ever queued** (§6.3).

---

## 3. How the dispatcher fits the frozen interfaces

| frozen interface | how this satisfies it |
|---|---|
| `71` §2.2 `POST /place` | `mesh-run` sends `{"task":{"kind":"fleet","children":N,"worktreeGiB":2,"prefer":null,"exclude":[…]}}`, branches on `position`, and **refuses to proceed without a non-empty `rationale`** (`bin/mesh-run.mjs` — "the broker named a node without a rationale") |
| `71` §2.2 `POST /done` | sent on success **and** on failure, with the lease's own state echoed back (`released: true, heldMs: 65074`) |
| `71` §2.2 broker reachability | over ssh to `secratary-ts` (`curl -s -XPOST localhost:3091/place …`), because the broker is deliberately loopback-only. **This is the right call and should stay**: a tailnet whose ACL is allow-all must not expose job submission to every device. If it is ever published, it needs an authenticated path in front of it — the same argument `66` §3.1 makes for the plugin route, and it is not won by "it is only on our tailnet" |
| `71` §2.3 v1 transport | `ssh <alias> node <dsh>/lib/bin.js --profile headless "<prompt>"`, wrapped with a hard timeout, exit code, and stdout/stderr captured under `~/.dsh/mesh/logs/` |
| `71` §2.3 exit contract | `0` completed · `10` queued · `1` failed, and nothing else |
| `71` §2.3 record | one JSONL per run: node, start, end, exit code, host the child reported, bytes of output |
| `71` §2.4 proof of location | the instruction is prepended by the **wrapper** (the provider), and verified twice: the transport's recorded host must be one of the configured target hosts, and the child's own `MESH-HOST:` line must equal it. Either disagreement is `stopReason: 'error'` |

---

## 4. Findings that changed the build (each measured, each dated)

### 4.1 Win32-OpenSSH's client does not exit when its **stdout is a pipe**

This one cost the first two hours and it is invisible unless measured. On `ZABZ-TECH`, against
`ZABZ-YOGA`, running the identical command `ssh laptop-ts hostname` (2026-09-17):

| stdio | outcome |
|---|---|
| `['ignore', 'pipe', 'pipe']` | **output "zabz-yoga" arrived, client STILL ALIVE at 20 s** (killed) |
| `['pipe', 'pipe', 'pipe']` | same — hung |
| `['inherit', 'pipe', 'pipe']` | same — hung |
| `['ignore', <file fd>, 'pipe']` | exit 0 in **1075 ms** |
| `['ignore', <file fd>, <file fd>]` | exit 0 in **1049 ms** |
| `['ignore', <file fd>, <file fd>]` + `powershell -EncodedCommand` | exit 0 in **2115 ms**, correct output |

So the failure is the *stdout handle type*, not the command, the host, or the auth. The transport now
redirects both streams to temp files and unlinks them in a `finally`, and a unit test asserts the
stdio array never hands ssh a stdout pipe (`test/ssh-transport.test.mjs`, "the transport never hands
ssh a stdout PIPE").

### 4.2 A Windows ssh client can hold the session open AFTER the work is done

Even with file redirection, a client was measured still alive 75 s after the remote script had
printed its closing marker and called `exit`. Two changes make the transport independent of that:

* the remote script ends with `[Environment]::Exit($code)` rather than `exit $code`, so PowerShell's
  own teardown (which waits on handles a native child may still hold) is skipped;
* **the transport settles on the frame**: it polls the captured stdout for the run's own
  `FANOUT_EXIT_<nonce>=` line and, once that line is present and the file has stopped growing,
  resolves the run and kills the client. The nonce is per-run, so a child cannot forge it.

Measured effect: the successful runs report `(ssh client terminated after the completion frame)` and
each child settles in 8.5–16 s instead of hanging to the timeout.

### 4.3 `$DSH_HOME/profiles/node_modules` is owned by the harness — do not pre-create it

`dsh-app-boot/lib/index.js:657` (`healProfilesModuleFallback`) `mkdirSync`s that directory and mirrors
the installation's dependency closure into it **on every profile launch**. Pre-creating it as a
junction made that mkdir throw `UNKNOWN: unknown error, mkdir '…\profiles\node_modules'` and the
child never booted. The harness builds it, and the correct boundary is:

* **installation shared, state isolated** — a child home whose `profiles` directory links to the real
  one, while `sessions`, `storages` and `.credentials.yaml` stay in the child's own home.

That shape works and is what §4.4 below then made unnecessary for the final proof.

### 4.4 The laptop cannot accept ssh dispatch at all — this is the finding that changed the direction

`ssh <laptop> node <dsh>/lib/bin.js --profile headless "<task>"` **cannot work on this fleet** for a
structural reason. DSH resolves a profile's bundles through `$DSH_HOME/profiles/node_modules`, where
each package is a **symlink** into the installation. A process launched by the laptop's sshd cannot
traverse those symlinks. The same probe binary, run locally and over ssh, on 2026-09-17:

| | local (laptop shell) | launched by the laptop's sshd |
|---|---|---|
| `lstat @deepseek-ai/dsh-llm` | `symlink=true` | `symlink=true` (the link itself is visible) |
| read a file **through** the link | OK, 2228 bytes | **`UNKNOWN` (-4094)** |
| `require.resolve('@deepseek-ai/dsh-llm')` | the npx cache | **`MODULE_NOT_FOUND`** |
| `ssh <node> dsh --profile headless` | works | **`plugin tree failed to load … loader entries failed to apply`** |

The desktop's sshd session resolves the same symlinks fine — its `mesh` parent booted **over ssh** and
loaded this plugin, and the earlier proven `REMOTE OK` run is the same shape. So the mesh's working
direction today is **laptop → desktop**, and that is the direction the owner wants anyway: the machine
he is working on stays flat and the work lands on the idle 32-core desktop.

**This is a report for S1/S5, not a workaround to hide:** the broker will happily place a job on
`zabz-yoga` (it did, at 23:24Z: `node=zabz-yoga, position=0, score=22`) while that node cannot accept
it over the ssh transport. Either `accepts` must carry this fact, or the transport for that node must
be the v2 route. `mesh-run` therefore takes `-Exclude`, and the exclusion is visible in the broker's
own `rationale` (`"zabz-yoga: … excluded by the caller"`). A silent exclusion would be the bug, not
the exclusion.

### 4.5 The remote **shell** is a property of the target, not of the caller

The first broker-placed run landed on **secratary** (Linux) because the broker saw 24 free slots there
— and every child died with:

```
remote one-shot exited 127, stderr: bash: line 1: powershell: command not found
```

The profile had derived the remote shell from `process.platform` — the **parent's** platform. It now
comes from `MESH_REMOTE_SHELL`, set by the dispatcher from its node table, alongside the target's node
interpreter, dsh entry point and working directory. The node table is in `bin/mesh-run.mjs` and each
row records whether its two paths were ever **measured** on that node.

### 4.6 The verification regexes must be unanchored

The first completed three-child run **failed verification** with `meshHostLines: 0` while the child
reports were sitting right there in the output — a parent agent that summarises its children writes
`CHILD=1 MESH_HOST=MESH-HOST: zabz-tech TRANSPORT=transport host = ZABZ-TECH`, i.e. mid-line. Anchored
`^MESH-HOST:` patterns found none of three and failed a run that had actually succeeded. The matcher
is now unanchored and filters out the `(not reported)` placeholder a failed child produces.

### 4.7 Two smaller traps, recorded so they are not re-hit

* **`@deepseek-ai/dsh-agent-presets` is a ROW, not a bundle.** It declares no `dsh.bundle`; naming it
  in a profile's bundle list fails the boot with `profile bundle "@deepseek-ai/dsh-agent-presets"
  declares no dsh.bundle`. It is inserted by the profile's patch instead — which is what
  `62-worker-runtime.md` §4.4 says the right way is.
* **A `!!js` expression in a patch must be quoted.** Every ternary contains `: `, which is a YAML
  mapping separator in a plain scalar: the boot dies with `bad indentation of a mapping entry`. The
  expressions in `profiles/mesh/cordis.patch.yml` are double-quoted and use forward slashes.

---

## 5. Verification that is not the proof

```bash
cd packages/plugin-remote-fanout && node --test test/*.test.mjs
```
```
ℹ tests 35   ℹ pass 35   ℹ fail 0   (2026-09-17)
```

What the 35 cover: quoting and framing in both shells; the parser, including a child that prints the
marker words itself and cannot truncate the frame; the transport's file redirection, byte cap, timeout
kill, spawn failure, frame-settled completion and temp-file cleanup; the provider's settlement
vocabulary (completed / error / aborted / pre-flight cancellation / idempotent dispose); and **every
location-proof branch** — a child that reports the wrong host, a child that omits `MESH-HOST`, a
transport that lands on an unexpected machine, and the honest "recorded but not checked" wording when
no target hosts are configured.

An end-to-end run against a real node is the only thing that proves the transport, which is why §2
exists; a green unit suite over a fake ssh client proves nothing about a real one.

---

## 6. What is not there yet, and what could not be verified

### 6.1 One-shot only — follow-up messages to a remote child are NOT supported

`prepareContinuable` is deliberately absent, so the seam rejects continuable starts on this provider
and a remote child is one prompt, one final message. The `dsh-subagent` README names the missing
contract itself: *"remote providers need an Activation ownership contract before they can support
continuable children"* (`README.md:170`), and `README.md:188` names the durable mailbox and
cross-process lease that would be needed. **One-shot fan-out is what a fleet is**, and that is what
this proves; continuation is a separate contract that does not exist yet.

### 6.2 Not verified, stated as refusals

* **`posix` end to end.** The POSIX script builder is unit-tested and its first real use exposed §4.5,
  but **no Linux node has completed a child turn** through this transport. `zabz-tech-linux` has no
  Node runtime at all (`62` §3.1, re-read 2026-09-16) and installing one was out of scope.
* **A queued placement.** No `-Children` value provoked `position > 0`, so exit code `10` was never
  observed in the field; only its code path and the broker's own `position` arithmetic were read.
* **The `-Json` output mode** was not exercised.
* **`MESH_TARGET_HOSTS` empty.** The "recorded but not checked" branch is unit-tested, never run
  against a live node.
* **The desktop's node as a dispatcher.** `--profile mesh` boots there (the parent ran over ssh on the
  desktop and loaded the plugin), but that was true only while the plugin copy lived in the proof
  directory; that copy was deleted with it (§7), so the desktop currently has no `mesh` profile.

### 6.3 Observations from the mesh that the other streams should have

* At 23:24Z the broker placed a 3-child fleet on **zabz-yoga** with `score=22`, beating `zabz-tech` on
  free slots — correctly, by its own arithmetic. That node cannot accept the job (§4.4).
* At 23:26Z the broker reported **`zabz-yoga … unreachable (timed out after 1500 ms)`** while the
  laptop was otherwise healthy. A 1500 ms capacity read is a tight bound for a node that is running
  eleven agent loops; worth watching, because an unreachable node is *excluded* from placement and
  that is indistinguishable from a busy one at the caller.
* Six live leases existed on the mesh from other streams' testing during this session
  (`/nodes?fresh=1`, 23:23:59Z: `live: 6, byNode {zabz-tech: 3, zabz-tech-linux: 1, secratary: 1,
  zabz-yoga: 1}, oldestAgeSec: 182`). The TTL is doing its job; no cleanup was needed.

---

## 7. Nodes started, stopped, and left behind

**Started / stopped (all fresh one-shot processes; no engine, no daemon):**

| what | where | count | how it ended |
|---|---|---|---|
| `dsh --profile mesh headless` parent runs | ZABZ-YOGA | 4 | each printed its answer and exited 0 |
| `dsh --profile headless` child turns | ZABZ-TECH | 4 (3 in the proof, 1 in the exit-contract check) | each exited 0 after 8.5–16 s |
| `node bin.js --profile headless` probes | ZABZ-YOGA (local) | 3 | exit 0 |
| `ssh` clients | ZABZ-YOGA ↔ ZABZ-TECH | 2 per child | settled on the frame, killed |

**No engine was started, stopped or restarted anywhere.** Evidence: `ZABZ-YOGA`'s engine
(pid 1784, `bin.js web --port 3099`) was up since 15:49 and was still up at the end of every run;
`ZABZ-TECH`'s engine (pid 23188, `--port 3099`) was likewise never touched — the dispatcher's own
processes were separate `--profile mesh` one-shots against the same `DSH_HOME`.

**Left behind (deliberately):**

* `~/.dsh/profiles/mesh/` **on ZABZ-YOGA** — the deliverable, installed by the keeper, linked to the
  repo package, and checkable with `install-mesh-profile.mjs --check` (exit 0).
* `~/.dsh/mesh/logs/*.jsonl` and `*.out` **on ZABZ-YOGA** — the run records the dispatcher is
  specified to write (`71` §2.3). They are the evidence for §2.3.
* The four repo files/paths in §1 are the source of truth; nothing was pushed to git.

**Removed:** `C:\Users\ezabz\fanout-tmp\` on **both** nodes (scripts, markers, the desktop's plugin
copy), and `~/.dsh/profiles/mesh/` **on ZABZ-TECH**, whose plugin link pointed into that directory —
a dangling bundle junction is exactly the failure `install-client-plugins.ps1:65-85` was written to
prevent. Verified afterwards: `PROOF_DIR_REMOVED=True`, `PROFILE_REMOVED=True`,
`WEB_PROFILE_INTACT=True`, `PROFILES_NODE_MODULES_INTACT=True` on the desktop, and on the laptop
`MESH_PROFILE_STILL_OK=True`, `PLUGIN_LINK_ALIVE=True`. No scheduled task was created on any node and
no stray process was left running.

---

## 8. What this changes in the program

1. **`71` §2.3's v1 transport is correct but not universally usable.** `ssh <alias> dsh --profile
   headless` works station→station on Windows and does **not** work into `zabz-yoga` (§4.4). The
   transport is right; the *node capability* is what is missing, and it belongs in `accepts`.
2. **The dispatcher, not the profile, owns per-node facts** (§4.5). A profile cannot describe a
   machine it is not running on.
3. **`mesh-run` is the caller-side product; the `mesh` profile is the agent-side one.** `mesh-run`
   decides and verifies; `dsh --profile mesh headless "<task>"` is what a parent agent that fans out
   its own children runs in. Both are one file and one profile.
4. **The one genuinely missing contract is unchanged**: continuable remote children (§6.1).
