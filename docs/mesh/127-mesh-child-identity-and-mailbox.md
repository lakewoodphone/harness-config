# 127 — Mesh child identity and the durable mailbox

Written 2026-09-29 by the **child-identity lane** of the two-lane p2children fix
fleet, on branch `agent/p2children` (base `87bd0e7`). This is the child half of
the mesh fan-out repair: how a child's task is delivered, whether its answer
survives, and whether a parent can see, message, interrupt and collect it.

Companion reading: `docs/mesh/120-continuable-mesh-children.md` (the engine
Activation-ownership contract that would make a mesh child natively addressable).
That document is the *native* answer to D2 and is **not** redone here; this lane
builds the plugin-level durable identity that works on today's pinned engine.

## 1. THE FOUR MEASURED DEFECTS AND WHAT CHANGED

### D1 — the model's `MESH-HOST:` line was treated as the PRIMARY proof
`provider.js` failed a run with `stopReason: error` when the child did not open
with `MESH-HOST:`, and discarded the entire answer (pains P2667, P269; lesson
L3059). The transport ALREADY recorded the target host — the target's own shell
writes it before the child runs, and `parseFanout` puts it in `parsed.host`.
**Fix (R1):** the transport's recorded host is authoritative; the model's line is
corroboration.

* A **missing** `MESH-HOST:` line no longer fails. The run returns `completed` and
  the report says exactly what carried the proof:
  `location check = transport recorded X, matched the node the broker named; the
  child's own MESH-HOST line was absent, so provenance rests on the transport,
  not the model.`
* A **disagreeing** line is still a hard failure. Corroboration that contradicts
  is not corroboration.
* A recorded host that is not among the placement's allowed names is still a hard
  failure (unchanged).

### D2 — a mesh child has no durable identity
`provider.js` returns `localAgent: undefined` and declares no continuable
capability, so `list_agents` shows nothing, `send_message`/`interrupt_agent`
cannot address the child, and the Subagents UI is empty. The engine change that
would fix this natively is `120`. **Fix (R3/R4/R5):** a plugin-owned durable child
registry plus four parent tools.

* `lib/child-registry.js` — one JSON file per child under
  `$DSH_HOME/mesh/children/`, atomic writes, never throws, holding `id`,
  `parentSessionId`, `node`, `ssh`, `lease`, `invocation`, the exact remote
  `inbox`/`outbox` paths, `state`, `createdAt`, `updatedAt` and the last host the
  transport proved.
* The provider takes an optional `childRegistry` and forwards EVERY patch its own
  `#record(id, patch)` already writes to `childRegistry.patch(id, patch)` inside a
  try/catch. There is no second event model: the registry is a durable projection
  of the one record the provider already keeps.
* `lib/index.js` constructs the registry under the engine's `DSH_HOME` and passes
  it to the provider (both `broker` and `fixed` modes) and to the four tools.

### D3 — a severed transport lost the answer
ssh stdout is buffered to a temp file and read when the client settles, so a
`Connection reset` lost the in-flight answer (P2538b: two of four children died
with nothing surviving; P2313). **Fix:** the child's outbox on the target, named
in the task preamble before the child starts and readable with `mesh_collect`
after the transport has died. The transport itself is unchanged in this respect:
it already reads its temp files on every settle (close, error, timeout), so bytes
that arrived before the cut are returned; a regression guard pins that.

### D4 — the task was one argv word and flattened to one line
PowerShell delivered the whole program with `-EncodedCommand` (base64 UTF-16LE,
~2.67 argv characters per task character). MEASURED: a 12000-character task
produced an argv of 33859 and `spawn` failed with `ENAMETOOLONG` — the child never
started. The real ceiling was ~11400 characters of task, below the fleet's own
8-part brief standard. Lesson L3060 (a double quote kills the run) was REFUTED by
another lane and is **not** acted on here; the live cause is length.
**Fix (R7):**

* The generated program now travels on **stdin for both shells**
  (`ssh <target> sh -s`, `ssh <target> powershell -NoProfile -NonInteractive
  -Command -`). argv is a constant five words and no longer grows with the brief.
* The task is **no longer flattened**: `singleLine()` is kept for old callers but
  the builders carry the task verbatim. A multi-line brief reaches the child as
  one quoted string literal, newlines intact.
* The legacy `delivery: 'encoded'` form is still available and now **refuses** an
  over-long command line by name (`MAX_WINDOWS_COMMAND_LINE = 32767`) instead of
  letting the OS fail obscurely.
* A `MAX_TASK_BYTES = 2 MiB` backstop in `remote-script.js` refuses an absurd
  payload with a legible diagnostic. **Nothing is ever truncated silently.**
* The frame markers, the per-run nonce and the POSIX host-capture line are all
  kept (`fanout_host=$(hostname 2>/dev/null || uname -n)`).

## 2. R2 — NOTHING IS DISCARDED

Every failure path in `attempt()` now returns through one helper that appends the
child's own text (`parsed.answer`, or the raw stdout when unframed) inline to the
diagnostic as `--- child final message ---`, in addition to the output blocks.
The diagnostic is what survives a job store that drops the blocks of an errored
run. The seam's 4096-byte diagnostic cap still applies (`limitDiagnostic`), so a
very large answer is truncated in the diagnostic while the blocks keep it whole.

## 3. R5/R6 — THE FOUR TOOLS AND THE CHILD CONTRACT

`lib/mesh-tools.js` registers four tools through the shipped `ctx.tools`, the same
service `plugin-health` uses:

| tool | what it does |
| --- | --- |
| `mesh_children` | lists the registry: node, state, age, lease, last proven host, and where the answer lands (outbox) |
| `mesh_message` | appends a message to the child's inbox ON THE TARGET over ssh |
| `mesh_interrupt` | writes a stop request to the same inbox and marks the record `stopping` |
| `mesh_collect` | reads the child's outbox from the target over ssh — works after the transport died |

`mesh_message` and `mesh_interrupt` say plainly that delivery is **not instant**:
a one-shot child reads its inbox only at the checkpoints it actually reaches, and
a child already past its last checkpoint will never read it. That honesty is in
the tool result text on every call.

`DEFAULT_TASK_PREAMBLE` (`provider.js`) now carries `{{inbox}}`/`{{outbox}}`,
substituted per run by `renderTaskPreamble`, and the contract: check the inbox
before each major step and obey a stop request; append short progress lines to the
outbox; ALWAYS write the final answer to the outbox before finishing; and raise a
wake flag through the flag store under `scripts/wake` (`scripts/wake-flag.py` on
the authority) if a mid-flight decision is needed.

## 4. PATHS, AND WHERE THE PARENT MUST NOT GUESS

`meshChildPaths({ dshHome, id, shell })` (in `remote-script.js`) builds the target
paths. When the placement names a `dshHome` (the usual case) they are exact
absolute paths in the node's own shape. When it does not, the path stays a shell
expression (`$HOME/.dsh/mesh/children/<id>/...` for POSIX,
`$env:USERPROFILE\.dsh\...` for PowerShell) that the TARGET expands — the parent
must not invent another machine's home. `mesh_message`/`mesh_interrupt`/
`mesh_collect` build their ssh programs to match, leaving the expression
unquoted so it expands on the target.

## 5. WHAT THIS LANE DID NOT DO, AND WHAT IT COULD NOT VERIFY

* **No engine change.** `prepareContinuable`, `localAgent`, the catalogue and the
  Activation graph are untouched. A mesh child is still not a first-class
  engine-addressable agent; `docs/mesh/120` remains the native fix. These tools
  are the plugin's own control surface, not a substitute for that contract.
* **Stdin delivery was not run against a real Windows ssh client.** The change is
  unit-tested hermetically (argv size, stdin bytes, the encoded fallback and its
  refusal), but this lane was forbidden to dispatch a real mesh child, so the
  `powershell -Command -` path over `ssh.exe` is reasoned, not measured. The
  encoded form is preserved as an opt-in if the stdin form misbehaves on a node.
* **The POSIX `sh` end-to-end guard is skipped on Windows** (no `/bin/sh`), as
  before; on a Linux node it runs.
* **Concurrency between two harness processes sharing one registry is not
  addressed.** Writes are atomic per file, but there is no cross-process lease,
  which is exactly the gap `docs/mesh/120` names.
* **`lib/index.js` has no full-engine integration test.** The wiring guard drives
  `apply()` with a context double and asserts the registry is constructed, handed
  to the provider, and that all four tools register; it does not boot an engine.
* **`package.json` was left untouched** (not in this lane's ownership list), so
  the new modules are reached by relative import and `npm run verify` does not yet
  `--check` them.
