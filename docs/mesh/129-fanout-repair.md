# 129 — The mesh fan-out repair: what was broken, what is fixed, what was verified, what is not

Written 2026-09-29 from ZABZ-YOGA, at the end of the audit-and-fix session the owner asked for
(*"it seems to be constantly failing and crashing and also it looks like that loses the ability to
talk to subagents and for them to talk to you mid flight … audit and analyze this fully and fix it
way more robustly and better"*).

Every number below is a measurement with a source. Where something is not established, the text says
so instead of filling it in.

---

## 1. The diagnosis, in one table

From the provider's own placement ledger (`~/.dsh/mesh/placements/*.json`, one file per child, written
by `plugin-remote-fanout` itself), the **70 placements in the 48 hours to 2026-09-29 18:30Z**:

| outcome | count | share |
|---|---|---|
| **completed** | **16** | **23 %** |
| error | 33 | 47 % |
| never placed at all | 11 | 16 % |
| aborted | 2 | 3 % |
| no outcome recorded | 8 | 11 % |

By node: `zabz-tech` **16 completed / 12 error**; `secratary` **0 completed / 19 attempted**;
the owner's laptop `zabz-yoga-1` **0 completed / 4 attempted**; `zabz-tech-linux` and
`lakewooechsmini` **never chosen once**.

Independently corroborated from a second instrument — the wrapper's own run logs under
`~/.dsh/mesh/logs/` — in a 2026-09-18 window: **19 of 22 runs failed, 3 completed**, and the dominant
"failure" was a child that exited 0 with its text intact, scored failed as
`only 0 MESH-HOST lines for 1 children` (`docs/mesh/122-crash-and-loss-evidence.md`).

So: three attempts in four produced nothing, and most of them had already done the work.

---

## 2. The six root causes, each verified

**R1 — A bashism in the POSIX child script.** `remote-script.js` captured the target hostname with
`printf -v`, which does not exist in `dash` — and `sh -s` over ssh **is** `dash` on both Linux nodes.
The variable stayed empty, the transport recorded host `""`, and the provider refused the run at the
location check *after the child had done its work*. Measured live with a raw diagnostic on both nodes
(`sh: 1: printf: Illegal option -v`). This is the whole of the `secratary` 0-of-19 result.
**Fixed**: `fanout_host=$(hostname 2>/dev/null || uname -n)`, with a guard that fails on the old line.
Journal `L3061`.

**R2 — The model's formatting line was treated as proof of location.** A mesh child that did not open
with `MESH-HOST: <host>` had its *entire answer discarded*, although the transport already records the
target's hostname — written by the target shell **before** the child ran, and already checked against
the node the broker named. The model's line was the weak evidence and was being used as the strong one.
**Fixed**: the transport's recorded host is authoritative; a missing model line is now a recorded note
and the run completes with its answer preserved; a *disagreeing* line is still a hard failure, because
that is real self-inconsistency. Journal `L3059`, pain `P2667`.

**R3 — Eleven placements never got a node, and there was no retry.** `broker-unreachable`, with wording
identical to a real outage. **Fixed, and the interesting part is why it was not a one-liner**: `POST
/place` issues a lease and the broker accepted no request identity, so a naive retry after a timeout
would issue a **second** lease and leak the first for its 900 s TTL. The fix is an idempotency key
(`requestId`, TTL 300 s, bounded at 256 entries) so a replayed request returns the **same** lease, plus
a bounded client retry (3 attempts, jittered 250–4000 ms) and distinct error classes — reached-but-silent
is not the same fact as could-not-be-reached. Journal `P2668`, `docs/mesh/126`.

**R4 — The ranking demoted healthy nodes and promoted one that could not work.** A cold-start read
missed the broker's 1500 ms deadline while the same node answered on its second attempt at 1738–1887 ms,
and the node was then branded `SLOW` and ranked below `secratary` — one free slot, swap 100 % used, and
its own transport recorded as **UNMEASURED**. Live reading: roster reads 6194, `readFailures` 2355 =
**38.0 %**. This is the same mis-placement class as `docs/mesh/111` §6. **Fixed**: a cold-start miss no
longer demotes (only a still-slow *second* attempt does); an unmeasured transport can no longer outrank
a measured-working one; a node already at its fleet cap is queued rather than chosen
(`min(4, accepts.maxChildren)`), which is the `P2538b` shape where four install-heavy children starved
one desktop's sshd.

**R5 — Two lease leaks.** The broker's node lookup miss threw *after* the lease was issued, and
`transportFor()` in the provider ran outside the only `release()` path — both stranded a node's slot for
its full 900 s TTL. `docs/mesh/121` found them; **fixed** in this session, both releasing before they
throw and recording that the lease was given back.

**R6 — A brief too long to send.** The Windows path base64-encodes the generated program (≈2.67× the
input) into an argv word, and a Windows command line is capped at 32 767 characters. **Measured**: a
12 000-character task produces an argv of 33 859 and fails with `spawn ENAMETOOLONG` — the child never
starts. The ceiling is about **11 400 characters of task**, and the fleet's own 8-part brief standard
routinely exceeds it, so a manager who briefs properly is the one who loses the run. It was reproduced
by accident in this very session, on the dispatch of the brief written to fix it. Journal `L3063`.
**Fixed**: the task keeps its newlines, large tasks are delivered without a giant argv word, and an
over-limit task is refused with a legible diagnostic rather than a mystery exit.

---

## 3. The mid-flight requirement, answered honestly

The owner asked to be able to talk to children mid-flight and for them to talk back. The audit
established, from the engine's own source, that **this cannot be done natively on the pinned engine**:
a continuable child requires a durable Session *this* engine owns plus process-local execution
ownership, and a remote child has neither. Three independent blockers were traced, each with file and
line, and the engine change that would lift them is written up with exact functions in
`docs/mesh/120-continuable-mesh-children.md`. The smallest honest note of scale: the engine's own
limitation list says the missing pieces are a **durable mailbox and a cross-process lease protocol**.

What this session delivered instead is the capability, at our layer, without an engine change and
without a restart:

- a **durable child record** per child (`lib/child-registry.js`): id, parent session, node, ssh
  destination, lease, invocation, state, and the exact remote inbox and outbox paths;
- **`mesh_children`** — see every mesh child and where its answer will land;
- **`mesh_message`** — send a message to a running child by appending to its inbox on the target node
  over ssh;
- **`mesh_interrupt`** — write a stop request to the same inbox;
- **`mesh_collect`** — read a child's outbox from the target node, **including after the transport that
  ran the child has died**, which is how a severed connection stops meaning lost work (`P2538b`,
  `P2313`);
- and the child's own task preamble now carries the contract: check the inbox before each major step,
  obey a stop, append progress to the outbox, and always write the final answer there before finishing.

**The honest limitation, stated because a claim nobody can see is the failure this whole programme
exists to prevent:** this is a **mailbox read at the child's checkpoints**, not engine-native adjacency.
A one-shot child reads its inbox only when it actually reaches a checkpoint. It restores the capability
the owner asked for; it does not make a mesh child a first-class `send_message` target in the engine's
own registry, and it must not be described as if it did. The child can also raise a wake flag through
the existing flag store to push a decision request asynchronously.

---

## 4. What was verified, and how

**Tests, run by me on the merged tree, not taken from a report:**

| suite | result |
|---|---|
| `plugin-remote-fanout` (9 files) | **152 tests, 151 pass, 0 fail**, 1 skip (the POSIX-`sh` guard, which only runs where the defect lives) |
| `mesh-broker` (4 files) | **67 tests, 67 pass, 0 fail** |

**The live proof — one real child turn per node, over real ssh, through the fixed code**
(`_scratch/mesh-fix-20260929/transport-proof.mjs`, executed 2026-09-29 18:4xZ):

| node | shell | invocation | framed | recorded host | exit | ms |
|---|---|---|---|---|---|---|
| `zabz-tech` | powershell | interpreter | true | `ZABZ-TECH` | 0 | 4160 |
| `zabz-tech-linux` | posix | executor | true | `zabz-tech-linux` | 0 | 5176 |
| `secratary` | posix | interpreter | true | `secratary` | 0 | 5080 |

`zabz-tech-linux` and `secratary` are the two nodes whose children were **always** refused for an empty
host. Both now report a real hostname and complete. The node with 0 completions in 19 attempts now
works.

**One correction to the record, because the record had it wrong.** `docs/mesh/122` states that the
wrapper "discarded" a child's intact text. On reading the code, `mesh-run.mjs` writes that text to a
`.out` file and prints it before exiting — nothing was discarded, the *failure record* simply did not
name the file, which is why a reader concluded it had been thrown away. The record now names it.

---

## 5. What is NOT fixed, and is not claimed to be

1. **Engine-native continuable mesh children.** Needs the engine change named in `docs/mesh/120`. Not
   attempted; the mailbox above is the interim.
2. **Cross-process mailbox and lease protocol.** A child registry that two harness processes share
   safely is the gap `docs/mesh/120` names. Not attempted. A registry read and written by two engines at
   once is not safe today, and the current design has each parent own its own records.
3. **`powershell -Command -` stdin delivery was not measured against a real Windows `ssh.exe`.** The
   transport proof above exercised the *fixed* path and it worked, but the specific stdin variant was
   not isolated as its own measurement. Flagged by the lane that wrote it; repeated here so it is not
   mistaken for verified.
4. **The authority's own broker is still running the old code.** The broker package changes (R3, R4)
   take effect on the broker process, which runs on `secratary`; that process must be redeployed and
   restarted. Not done while a live measurement was in flight.
5. **The running engine on this laptop has the old provider loaded.** These packages are junctions into
   this repo, so the *files* are already fixed, but Node caches modules per process: the provider
   changes take effect at the next engine start.
6. **`lakewooechsmini` is unproven as a worker** — reachable by the broker's own HTTP route (28 ms
   reading) but never chosen, and direct ssh to it timed out.
7. **`secratary` is still 4× oversubscribed with swap 100 % full** (`P2606`, `P2553`). R4 stops it being
   *chosen* for work it cannot do; it does not make the machine healthy.

---

## 6. Files that carry the repair

- `packages/plugin-remote-fanout/lib/remote-script.js` — the portable host capture, and task delivery
  that is not a giant argv word and does not flatten a brief.
- `packages/plugin-remote-fanout/lib/provider.js` — the location policy, no answer discarded, the
  truncation flag surfaced, no lease leaked on a pre-publish failure, the child contract.
- `packages/plugin-remote-fanout/lib/child-registry.js` (new) and `lib/mesh-tools.js` (new) — the
  durable child record and the four parent tools.
- `packages/plugin-remote-fanout/lib/placement.js` — the lease released on the lookup-miss path.
- `packages/plugin-remote-fanout/lib/broker-client.js` — bounded retry, honest error classes, the
  idempotency key.
- `packages/mesh-broker/lib/{broker,scoring,config}.js` — request-id memoization, cold-start and
  unmeasured-transport ranking, the per-node fleet cap.
- `packages/mesh-broker/bin/mesh-broker.mjs` — every config key `loadConfig` parses is now threaded and
  logged, instead of being silently ignored.
- `packages/plugin-remote-fanout/bin/mesh-run.mjs` — failure records name where the child's text is.

The audits behind all of it: `docs/mesh/120` (the seam), `121` (41 exit paths, severity-classed),
`122` (the evidence, with its one corrected claim), `123` (the load experiment), `126` (placement
hardening), `127` (child identity and mailbox).

**Two things the load experiment (`docs/mesh/123`) changed, both recorded rather than folded in.**

1. **`L3060` is refuted, twice.** That lesson said a double-quote in a prompt kills the remote one-shot;
   the taxonomy lane refuted it from source and the load lane refuted it by running a controlled probe —
   a prompt with two double-quotes exited 0 and came back verbatim. The mechanism the symptom really
   belongs to is the command-line ceiling in R6. `L3060` is superseded by `L3064`, and it is **not**
   edited: the record of having been wrong is worth more than a tidy log.
2. **A new open hazard, filed as pain `P2670`.** From `zabz-tech`, every attempt at a **remote** child
   turn returned nothing at 180 s, 45 s and 25 s bounds, while a plain ssh over the same descriptor shape
   exited 0 in 309 ms — and the identical `sh -s` stdin shape completed real turns from ZABZ-YOGA to
   `zabz-tech-linux` (5176 ms) and `secratary` (5080 ms) on the same day and the same code. So the defect
   is a property of the *dispatching client*, not of the target, the generated program, or any quote
   character. The cause is **not established** and the experiment says so itself; the next step is to
   reproduce it from `zabz-tech` with the package's own `createSshTransport` rather than a hand-rolled
   probe, and if it reproduces, deliver the POSIX program from a file on the target so stdin leaves the
   path entirely. Three of five nodes are POSIX, so this is half the mesh as seen from the desktop.


