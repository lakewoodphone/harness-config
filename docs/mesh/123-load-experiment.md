# 123 — load experiment: where mesh dispatch actually breaks

Run on the DSH mesh from `zabz-tech` (Windows, ssh alias `desktop-ts`), 2026-09-29,
18:25Z–18:42Z. Branch `agent/p1experiment`, worktree `C:/Users/ezabz/Code/_fleet_p1experiment`
at base `f97626b`. Four controlled experiments: the double-quote hypothesis, batch
reliability, what a batch does to the broker roster, and the local cost on this node.

Every number below carries the command that produced it and the minute it was read.
Reader-local clock is `America/New_York`; all times in this file are UTC (`Z`), which is
what the tools themselves print.

## 1. The instruments, and how each was invoked

All work happened in the worktree beside the shared clone; nothing inside
`C:/Users/ezabz/Code/harness-config` was touched.

| Instrument | Path | Invocation |
| --- | --- | --- |
| the repo's dispatcher | `packages/plugin-remote-fanout/bin/mesh-run.mjs` | `node packages/plugin-remote-fanout/bin/mesh-run.mjs -Prompt <brief> [-Node <node>] [-Children N] [-TimeoutMs 180000]` |
| its help | same file | `node packages/plugin-remote-fanout/bin/mesh-run.mjs --help` → prints `mesh-run -Prompt "<task>" [-Node <name>] [-Children N] [-Workdir PATH] [-Json] [-DshBin <path>] [-TimeoutMs <n>] [-Exclude a,b] [-NoWait]` and `exit: 0 completed, 10 queued, 1 failed` |
| broker roster | the authority, loopback-only | `ssh -o BatchMode=yes secratary-ts "curl -s --max-time 12 http://127.0.0.1:3091/nodes"` |
| the provider's own remote path | `lib/ssh-transport.js` + `lib/remote-script.js` | imported directly by a driver outside the repo, using the same two calls `provider.js:480,484` makes (`buildPosixScript`/`buildPwshScript`, then `transport.start({shell, script, timeoutMs, completeMarker})`) |
| local cost | this node | `Get-CimInstance Win32_OperatingSystem`, `Get-Counter "\\Memory\\Committed Bytes"`, `Get-Process -Name node` |
| ps-mesh | `scripts/ps-mesh.mjs` | `node scripts/ps-mesh.mjs --help` → `ps-mesh --help: needs a host. Try: ps-mesh hosts`; the file's header is the usage I read |

**Every brief was written to a file first and read from that file.** No probe character was
ever typed into a shell string: `run-probes.mjs` and `run-batch.mjs` do
`readFileSync(file, 'utf8')` and pass the result as one argv element to `spawn`.
Character census of the six probe files (`node check-probes.mjs`, 18:27Z):

```
{"probe":"A","bytes":517,"doubleQuotes":0,"backticks":0,"apostrophes":0,"dollars":0,"spike":"none"}
{"probe":"B","bytes":549,"doubleQuotes":0,"backticks":0,"apostrophes":2,"dollars":0,"spike":"owner's"}
{"probe":"C","bytes":586,"doubleQuotes":2,"backticks":0,"apostrophes":0,"dollars":0,"spike":"say \"quoted\" once"}
{"probe":"D","bytes":613,"doubleQuotes":0,"backticks":0,"apostrophes":4,"dollars":0,"spike":"say ''quoted'' once"}
{"probe":"E","bytes":642,"doubleQuotes":0,"backticks":2,"apostrophes":0,"dollars":0,"spike":"run `hostname` here"}
{"probe":"F","bytes":509,"doubleQuotes":0,"backticks":0,"apostrophes":0,"dollars":1,"spike":"paid $5 today"}
```

### The finding that reframes Experiments 1 and 2

`mesh-run.mjs` **does not place the child on the node it names.** It prints this on stderr,
verbatim, on every run: `mesh-run: NOTE — this child runs on <this machine>, the machine you
are invoking this from. -Node <node> sets the dispatch target the child's own subagents will
be aimed at (via MESH_TARGET_NODE="<alias>"); it does NOT place this child.` Measured in
probe A (18:26:54Z): the broker placed `zabz-tech`, the dispatcher's `run` record says
`node: zabz-tech, alias: desktop-ts`, and the child that actually answered ran locally — its
`phase: verify` found `transportHostLines: 0`, because nothing exercised a remote shell.

## 2. Experiment 1 — the double-quote hypothesis

Six probes, each one dispatch, `-TimeoutMs 180000`, sequentially (18:26:54Z–18:28:04Z).
"Message back" means the child's own framed final answer appeared in the dispatcher output.

| Probe | Character | Exit | Message back | Final ms | Node it ran on | Verify result | Spike line returned |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | none | 0 | yes | 6815 | zabz-tech (local) | `meshHostLines: 1, disagreements: [], ok: true` | `SPIKE: none` |
| B | apostrophe | 0 | yes | 5922 | zabz-tech (local) | same | `SPIKE: owner's` |
| C | double-quote ×2 | 0 | yes | 5804 | zabz-tech (local) | same | `SPIKE: say "quoted" once` |
| D | `''` pair ×2 | 0 | yes | 6244 | zabz-tech (local) | same | `SPIKE: say ''quoted'' once` |
| E | backtick ×2 | 0 | yes | 6104 | zabz-tech (local) | same | ``SPIKE: run `hostname` here`` |
| F | dollar sign | 0 | yes | 6187 | zabz-tech (local) | same | `SPIKE: paid $5 today` |

**No probe was fatal.** Every one exited 0, returned a final message, named `zabz-tech`
(one `MESH-HOST:` line, zero disagreements), and the spike character came back byte-identical.
The only stderr was the same 325-byte local-placement NOTE quoted above, on all six.

The prior measurement this tested — "a double-quote kills the remote one-shot with exit 1, no
output and no error" — **is not reproduced here**: probe C with two double quotes and probe A
with none differ by 1.0 s of wall clock and by no other observable. Nothing was *expanded*,
either: probe E's child saw the backticks as text (it did not run the command inside them),
and probe F's child saw a literal `$5`.

### The character test on the two paths that are not the local one

`-Node <remote>` (18:29:05Z, 18:29:10Z):

| Probe | `-Node` | Exit | Message back | Final ms | Child reported | Verbatim diagnostic |
| --- | --- | --- | --- | --- | --- | --- |
| C | `zabz-tech-linux` | 1 | yes, correct content | 5045 | `zabz-tech` | `mesh-run: {"phase":"verify",...,"childHosts":["zabz-tech"],"disagreements":["zabz-tech"],"ok":false}` then `location disagreement: zabz-tech not on zabz-tech-linux` |
| A | `zabz-tech-linux` | 1 | yes, correct content | 4802 | `zabz-tech` | same, `location disagreement: zabz-tech not on zabz-tech-linux` |

Both probes — with and without a double quote — failed identically, and failed for the
placement reason, not for the character. This is the dispatcher's own honesty working: the
run is scored failed rather than recorded as a success.

The real remote path (the provider's transport, `sh -s` with the generated script on stdin,
18:30Z and 18:35:23Z):

| What ran | Target | Bound | Result |
| --- | --- | --- | --- |
| provider transport, probe A (`PING` brief, no quotes) | linux-pc-ts | 180 s | `ok=false, timedOut=true, markerSettled=false, stdout=""` — killed at 180 036 ms |
| provider transport, minimal no-dsh script that only writes the frame | linux-pc-ts | 45 s | `ok=false, timedOut=true, stdout=""` — killed at 45 029 ms |
| hand-rolled copy of the transport's spawn shape | linux-pc-ts | 25 s | `event: close, code: null, signal: SIGKILL`, stdout `""`, stderr `""` |
| the same shape with a plain remote command, `ssh linux-pc-ts "hostname; echo DONE"`, file fds | linux-pc-ts | 25 s | **exit 0 in 309 ms**, stdout `"zabz-tech-linux\nDONE\n"` |

So the remote path to this POSIX node is blocked *below the prompt*: the client connects and
runs a plain command, but the `sh -s` + script-on-stdin shape never returns a byte, with a
trivial script and with a real one, at every bound tried. No double quote is needed to make
it fail, and adding one changes nothing. (`laptop-ts` was tested with the POSIX-only minimal
script, which is a test defect of mine — PowerShell rejected `printf`; the Windows transport
shapes are therefore only partly probed. `mac-mini-ts` failed differently and honestly:
`ssh: connect to host lakewooechsmini.tail93e6e6.ts.net port 22: Connection timed out`.)

## 3. Experiment 2 — batch reliability

Three batches, all through `mesh-run.mjs -Children N -TimeoutMs 180000`, each settling
before the next started. The child brief was a file; batch 1 used a one-line brief that did
not name the fan-out, batches 1b and 2 used a brief that told the parent to dispatch the
children and report them. Children were told, in their own brief, to run one command, not to
modify any file, not to install anything and not to write outside their own scratch directory.

| Batch | Started | Children asked | Wall ms | Exit | Broker node | MESH-HOST lines in the parent's report | Parent's own final output |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 18:40:20Z | 6 | 8738 | 1 | zabz-tech, tier `fits`, position 0 | 1 | `MESH-HOST: zabz-tech / TOKEN: (no token was provided in my brief) / CMD: zabz-tech` |
| 1b | 18:41:14Z | 6 | 21405 | 1 | zabz-tech, tier `fits`, position 0 | 0 | `Waiting for the remaining child to finish.` |
| 2 | 18:42:08Z | 12 | 19508 | 1 | zabz-tech, tier `fits`, position 0 | 1 | 9-line report naming **6** children, all `HOST=zabz-tech`, `TOKEN=CHILD-TOKEN` |

Success arithmetic: **0 of 3 batches passed**, 0 of 6 children verified in batch 1, 0 of 6 in
batch 1b, and 1 of 12 in batch 2 by the dispatcher's own count (the parent itself reported 6).

Failure texts, verbatim and with counts:

| Failure text (verbatim) | Count |
| --- | --- |
| `only 1 MESH-HOST lines for 6 children (1 literal, 0 summarised)` | 1 |
| `only 0 MESH-HOST lines for 6 children (0 literal, 0 summarised)` | 1 |
| `only 1 MESH-HOST lines for 12 children (1 literal, 0 summarised)` | 1 |

Two distinct failures sit behind those three lines, and they are not the children:

1. **The children ran; the parent did not report them in time.** In batch 1b the parent was
   still waiting on child 3 of 6 (`Five children have reported. Child 3 (9aeae22c) was
   running.`) when the headless process settled with the holding message
   `Waiting for the remaining child to finish.` — and `mesh-run` treats the parent's final
   message as the run's output, so the run scored 0 lines while children were demonstrably
   still being dispatched.
2. **The dispatcher's gate counts the parent's lines, not the children's.** Batch 2's parent
   did produce a complete report with one `MESH-HOST:` line plus six `CHILD=n HOST=...`
   lines, and the run still failed: `reportedHosts.length (1) < options.children (12)`. The
   `-Children N` number is used in the broker's placement arithmetic (batch 2's rationale
   says `0.5 GiB/child x 12 child(ren)` and `17 free slot(s) - 12 child(ren) = 5 >= 0`) but
   nothing makes the model spawn N children or makes the gate read N child reports.

Children were observed to run locally: the batch sessions landed on this node under
`C:\Users\ezabz\.dsh\sessions\--C-Users-ezabz-_fleet_p1scratch--\` (6 directories at
14:41:30 local = 18:41:30Z; 6 more at 14:42:23-24 local = 18:42:23-24Z), which is consistent
with a dispatcher that runs its parent here (`transportHostLines: 0` in every verify record).

## 4. Experiment 3 — what the batches did to the mesh

Roster read before and after each batch with
`ssh -o BatchMode=yes secratary-ts "curl -s --max-time 12 http://127.0.0.1:3091/nodes"`.
The ssh client is the known Win32-OpenSSH case (whole body delivered, client never exits), so
the reader reports `spawnSync ssh ETIMEDOUT` while `rawBytes` is complete and `parseError` is
null; every reading below is one of those complete bodies.

Broker-wide counters:

| Reading | Minute | `brokerAt` | `reads` | `readFailures` | live leases |
| --- | --- | --- | --- | --- | --- |
| baseline | 18:26Z | 18:26:33Z | 6194 | 2355 | 6 running, all zabz-tech |
| before batch 1 | 18:39Z | 18:40:05Z | 6254 | 2361 | 3 running, all zabz-tech |
| after batch 1 | 18:40Z | 18:40:41Z | 6268 | 2361 | 3 running, all zabz-tech |
| before batch 1b | 18:41Z | 18:41:52Z | 6278 | 2363 | 2 running, all zabz-tech |
| after batch 2 | 18:42Z | 18:42:53Z | 6288 | 2365 | 1 running, all zabz-tech |

The three batches added `reads 6254 → 6288` (+34) and `readFailures 2361 → 2365` (+4) across
their own window, 18:39Z–18:42Z. The standing ratio is much larger than the batch effect:
2365/6288 = **37.6 %** of all roster reads have failed since the counter started.

Per node, `state` / `freeSlots` / `latencyMs` / `warning`, with the minute read:

| Node | 18:26Z (baseline) | 18:39Z (pre-b1) | 18:40Z (post-b1) | 18:41Z (pre-b1b) | 18:42Z (post-b2) |
| --- | --- | --- | --- | --- | --- |
| zabz-tech | ok / 12 / 8 ms / null | ok / 15 / 66 ms / null | ok / 15 / 75 ms / null | ok / 16 / 46 ms / null | ok / 17 / 58 ms / null |
| zabz-yoga-1 | ok / 12 / 67 ms / null | ok / 12 / 179 ms / null | ok / 12 / 185 ms / null | ok / 12 / 164 ms / null | ok / 12 / 261 ms / null |
| zabz-tech-linux | ok / 4 / 6 ms / null | ok / 4 / 41 ms / null | ok / 4 / 50 ms / null | ok / 4 / 34 ms / null | ok / 4 / 38 ms / null |
| secratary | ok / 1 / 3 ms / null | ok / 1 / 18 ms / null | ok / 1 / 16 ms / null | ok / 1 / 26 ms / null | ok / 1 / 17 ms / null |
| lakewooechsmini | ok / 7 / 28 ms / null | **unreachable / 0 / 4003 ms** | ok / 7 / 62 ms / null | **unreachable / 0 / 4003 ms** | **unreachable / 0 / 4003 ms** |

No node ever carried a non-null `warning`, and no node changed state because of a batch: the
only bad node is `lakewooechsmini`, and it was bad both before a batch and after one, with
the raw reason string, verbatim and identical every time:

```
"reason": "timed out after 4000 ms (hard wall-clock deadline)"
```

Its `elapsedMs` after two retries read 5504 ms, and the batch 1 placement rationale called it
`SLOW (4658 ms door-to-door, first attempt missed the deadline): still slow on the second attempt, accepts.fleet=false`.
The two `unreachable` readings preceding a batch and the one after batch 2 are the same node
this whole audit ran on (`zabz-tech`) failing to reach one peer; `zabz-tech` itself read
`ok / 12–17 free slots / 8–75 ms` throughout.

## 5. Experiment 4 — the local cost

`Get-Counter "\\Memory\\Committed Bytes"`, `Win32_OperatingSystem.FreePhysicalMemory`, and
`Get-Process -Name node`, all in one PowerShell instant per reading.

| Reading | Minute | Committed GiB | Free physical MiB | node processes | node working set MiB | all processes |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | 18:25Z | 48.25 | 20925.6 | 37 | 4273.6 | 404 |
| before batch 1 | 18:39Z | 46.02 | 22360.6 | 28 | 3046.7 | 372 |
| after batch 1 | 18:40Z | 45.96 | 22651.7 | 29 | 3102.9 | 371 |
| before batch 1b | 18:41Z | 45.35 | 23134.7 | 26 | 2705.6 | 360 |
| after batch 2 | 18:42Z | 45.43 | 22978.5 | 27 | 2756.9 | 362 |

Delta across the three batches (18:39Z → 18:42Z, 2 min 49 s wall):

* committed bytes: 46.02 → 45.43 GiB = **−0.59 GiB**
* free physical: 22360.6 → 22978.5 MiB = **+617.9 MiB**
* node processes: 28 → 27 = **−1**
* node working set: 3046.7 → 2756.9 MiB = **−289.8 MiB**
* all processes: 372 → 362 = **−10**

On this laptop-flatness claim as measured here: the three batches did not raise any of these
numbers at all — every one of them is lower after the batches than before the first. The
caveat is that the batches were small (6, 6 and 12 requested, with 6, 6 and 6 children
actually reporting) and short (8.7 s, 21.4 s, 19.5 s), so this is a measurement of *these*
batches, not of a 12-child batch that completes.

## WHAT THESE NUMBERS DO NOT SHOW

* **They do not show remote dispatch working or failing for a real child turn.** `mesh-run`
  runs its child locally, and the provider's remote path never returned a byte for the one
  node I could reach, so no experiment here contains a remote child turn whose report I
  verified. `transportHost: null` in every remote attempt is the honest state: not "ran wrong",
  not "ran right" — no framed output at all.
* **They do not falsify the 2026-09-29 measurement in general.** Six probes, one dispatcher,
  one node, both quotes present in the *local* path only. A double quote may still break some
  other layer (the POSIX single-quote escaping in `remote-script.js:51`, a different shell, a
  future transport); nothing here exercised that layer far enough to see it return.
* **They do not show where the `sh -s` hang lives.** I can show that `ssh <target> "hostname"`
  with file fds exits 0 in 309 ms while the same client with `sh -s` and a stdin script never
  returns. I cannot show whether that is the local OpenSSH 10.0p2 client, the POSIX
  `sshd`'s stdin handling, the pipe shape, or something in the sandbox this run executes
  under.
* **They do not measure the broker under load.** The roster is a 15 s cache read over ssh;
  the batch window moved `reads` by 34 and `readFailures` by 4, which is smaller than one
  cache period's noise (readFailures moved by 8 in the 13 minutes before the batches started).
* **They do not show the 37.6 % read-failure rate is caused by anything.** It is a
  counter-derived ratio across the broker's whole lifetime, not a per-batch quantity.
* **They do not show what a 12-child batch costs.** `-Children 12` produced 6 children in
  both batches where the brief asked for 6, and the parent's report is the only per-child
  evidence there is; the per-child exit code, wall clock and node for batch 2's children
  were never delivered to any surface I can read.

## WHAT I COULD NOT VERIFY

* **Any completed remote child turn.** `-Node zabz-tech-linux` failed on placement
  disagreement with no double quote involved, and the provider transport timed out on a
  script containing no child at all.
* **Which node a batch child ran on.** The parent reported `HOST=zabz-tech` for all six
  children of batch 2, and the dispatcher's verify found no `transport host =` line, so I have
  no model-independent record of where those children ran. I did not treat the parent's word
  for it as proof.
* **The per-child exit code, wall clock and failure text** that Experiment 2 asks for. The
  dispatcher emits one `run-end` and one `verify` per *dispatch*, not per child, and no other
  surface carried them for these runs. The batch numbers above are the dispatch's, plus the
  parent's own child count.
* **Whether `secratary` can dispatch.** Its roster row still reads
  `"transport": {"v1": null}` with the evidence string "UNMEASURED"; nothing here attempted it.
* **`laptop-ts` (zabz-yoga-1) and `mac-mini-ts` as remote targets.** The yoga probe used a
  POSIX-only minimal script against a PowerShell target (my test defect), and the mac mini
  refused the ssh connection itself (`port 22: Connection timed out`) — neither is a result
  about the transport.
* **The double-quote behaviour on the exact path the prior measurement used.** I could not
  reproduce that path; the closest reproductions (probes C and A, same file, same command,
  differing only in the quote) both succeeded, which is evidence about this path only.
