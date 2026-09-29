# 121 — Dispatch failure taxonomy: every way a mesh child dies, and the minimal fix for each

Lane: `agent/p1taxonomy`, four-lane audit fleet. Base commit `f97626b`.
Host the audit ran on: **zabz-tech** (`hostname` → `zabz-tech`, `$env:COMPUTERNAME` → `ZABZ-TECH`).
Worktree: `C:/Users/ezabz/code/_fleet_p1taxonomy` (worktree of `C:/Users/ezabz/code/harness-config`).

Everything below is read from the code at `f97626b` on this branch. Line numbers are that
commit's. Where a hypothesis could not be settled from the code, it is in §5 rather than
asserted here.

The two live pain entries this exists to explain: `journal/entries/pain/P2667.md` (MESH-HOST
marker rejects the run *and discards the answer*) and `P2668.md` (a transient broker timeout
reported as an outage, no retry). Lessons `L3059.md` and `L3060.md` are the same two events
written as rules. §1 finds P2667 and P2668 confirmed, and finds the `L3060` double-quote
attribution refuted (§2, H1).

---

## SECTION 1 — THE DEFECT TABLE

Severity classes, worst first:

* **A — discards work AND is retryable.** The child's answer (or the whole turn) is thrown away,
  and a second attempt would very likely succeed. This is the class the owner feels.
* **B — discards work, not retryable.** Right to stop, wrong to delete.
* **C — strands a reservation.** No output lost, but a mesh slot is held to its 900 s TTL.
* **D — keeps the work, drops a fact about it.** Silent truncation / a dropped flag.
* **E — refuses before anything ran.** Discards nothing; listed for completeness.

| # | ID | file:line | exact message (as it appears in the code) | retryable | discards |
|---|----|-----------|-------------------------------------------|-----------|----------|
| 1 | A1 MESH-HOST unproven | `packages/plugin-remote-fanout/lib/provider.js:580` | `the child did not begin its report with "${MESH_HOST_LINE} <hostname>" — its location is unproven, so the run is not reported as complete` | yes | **the child's entire answer** (P2667) |
| 2 | A2 child-turn timeout | `packages/plugin-remote-fanout/lib/provider.js:559` | `the remote turn did not finish within ${this.timeoutMs ?? 'the configured'} ms and the ssh client was killed` | yes | the whole turn (child keeps running orphaned on the target) |
| 3 | A3 child exit ≠ 0 | `packages/plugin-remote-fanout/lib/provider.js:564` | `the remote one-shot exited ${outcome.exitCode ?? 'without a code'}${parsed.answer ? '' : ' and produced no final message'}; stderr tail: …` | yes | the turn (this is the L3060 symptom string) |
| 4 | A4 no completion frame | `packages/plugin-remote-fanout/lib/provider.js:568` | `the remote process exited 0 but printed no completion frame — the target profile did not run (stderr tail: …)` | yes | the turn |
| 5 | A5 ssh client failed to spawn | `packages/plugin-remote-fanout/lib/provider.js:555` | `could not launch the ssh transport (${transport.describe()}): ${outcome.spawnError}` | yes | the turn |
| 6 | A6 broker did not answer | `packages/plugin-remote-fanout/lib/broker-client.js:190` | `the placement broker could not be reached at ${where} — ${why}` (why = `no answer within ${timeout} ms` or `ssh exited N…`) | yes | the whole child — nothing is dispatched (P2668) |
| 7 | A7 transport host ≠ placed node | `packages/plugin-remote-fanout/lib/provider.js:575` | `the transport reported host "${parsed.host ?? 'unknown'}", which is not one of the hostnames the placement named ("${placement.node}" may be …) — refusing to report work from a node the broker did not name` | yes | the turn (correct refusal, still a discard) |
| 8 | A8 location disagreement | `packages/plugin-remote-fanout/lib/provider.js:584` | `location disagreement: the child claims MESH-HOST ${meshHost} but the target shell recorded ${parsed.host}` | yes | the turn |
| 9 | B1 broker named an unknown node | `packages/plugin-remote-fanout/lib/placement.js:459` | `the broker named node "${placement.node}", which is not in this package's node table (${nodeNames().join(', ')}) — refusing to dispatch into a lookup miss` | no | the turn **and the lease** (see C1) |
| 10 | B2 no invocation resolves | `packages/plugin-remote-fanout/lib/remote-script.js:166` (re-thrown as `provider.js:501`) | `remote-fanout: no invocation for this node — it needs either an executor (\`command\`, e.g. the mesh \`dsh\` wrapper) or both a \`driver\` and a \`bin\` (the interpreter fallback)` | no | the turn (no lease yet) |
| 11 | B3 broker body contains `'` | `packages/plugin-remote-fanout/lib/broker-client.js:180` | `refusing to send a broker body containing a single quote (it is passed through a shell): ${json.slice(0, 200)}` | no | the placement |
| 12 | B4 broker answered without a node | `packages/plugin-remote-fanout/lib/broker-client.js:118` | `the broker answered without naming a node` | no | the placement |
| 13 | B5 broker issued no lease | `packages/plugin-remote-fanout/lib/broker-client.js:121` | `the broker named node "${node}" without issuing a lease, so the reservation could never be released` | no | the placement |
| 14 | B6 bad position | `packages/plugin-remote-fanout/lib/broker-client.js:125` | `the broker named node "${node}" with a position of "${body.position}", which is not a queue position` | no | the placement |
| 15 | B7 no rationale | `packages/plugin-remote-fanout/lib/broker-client.js:128` | `the broker named node "${node}" without a rationale — that is a bug in the decision, not a warning` | no | the placement |
| 16 | B8 broker answer not JSON | `packages/plugin-remote-fanout/lib/broker-client.js:196` | `the broker at ${where} answered something that is not JSON (${…}); body was ${…}` | no | the placement |
| 17 | B9 /nodes has no list | `packages/plugin-remote-fanout/lib/broker-client.js:227` | `the broker's /nodes answer carries no node list (keys: ${…})` | no | the queue-wait poll only |
| 18 | C1 **LEASE LEAK on lookup miss** | `packages/plugin-remote-fanout/lib/placement.js:457-461` | throws `placement-node-unknown` **after** `broker.place()` at `:372`/`:446` — no `broker.done()` on any path out of `acquire()` | no | **the lease** (held to TTL, 900 s) |
| 19 | C2 **LEASE LEAK on transport construction** | `packages/plugin-remote-fanout/lib/provider.js:467` | `transport = this.placer.transportFor(placement)` runs **outside** the `result` IIFE whose `release()` is at `:612`; `createSshTransport` throws (`ssh-transport.js:100`) when the placed row has no `ssh` | no | **the lease** |
| 20 | C3 lease release failed | `packages/plugin-remote-fanout/lib/placement.js:650` | `remote-fanout: the lease ${placement.lease} on "${placement.node}" could not be released (${error?.code ?? 'broker-error'}: ${…}); the broker reclaims it at its TTL` | yes | the lease (reported, not silent) |
| 21 | C4 prefer-remote release failed | `packages/plugin-remote-fanout/lib/placement.js:443` | `remote-fanout: the prefer-remote policy could not release the local reservation ${placement.lease} (${…}); the broker reclaims it at its TTL` | yes | the superseded lease |
| 22 | C5 broker says lease unknown/expired | `packages/mesh-broker/lib/broker.js:900` | `unknown or already-expired lease (a lease is reclaimed by the broker at its TTL, so this is not an error)` | n/a | nothing — honest fact |
| 23 | D1 **ssh stdout truncation is dropped** | `packages/plugin-remote-fanout/lib/ssh-transport.js:185` sets `truncated`, and `provider.js` never reads it | (no message exists) | n/a | the *fact* that the answer was cut at `DEFAULT_MAX_OUTPUT_BYTES` (200 000). `readCapped` (`:155`) also slices UTF-16 code units, not bytes |
| 24 | D2 **`truncated` is dropped by the CLI** | `packages/plugin-mesh-http/bin/mesh-dispatch.mjs:575-596` | `handler.js:159` sends `truncated: true`; the `answered` object records `stdoutBytes` but not `truncated` | n/a | the *fact* of truncation on transport v2 |
| 25 | D3 queue-wait poll errors swallowed | `packages/plugin-remote-fanout/lib/placement.js:593-598` | recorded as `lastError` / `polls[].error`, then `continue` | n/a | nothing; kept in the ledger only |
| 26 | E1 pressure refusal (local saturated) | `packages/plugin-remote-fanout/lib/placement.js:362-365` | `${refused.reason}; nothing was dispatched and no reservation was taken. Retry when this machine is under its high line (42 % of physical committed, docs/mesh/109-pressure-routing.md)` | yes | nothing |
| 27 | E2 mesh unreachable + saturated | `packages/plugin-remote-fanout/lib/placement.js:393` | `${refused.reason}; retry when the mesh answers again, or when this machine is under its high line again` | yes | nothing |
| 28 | E3 abort mid-queue-wait | `packages/plugin-remote-fanout/lib/placement.js:633` | `no free slot appeared within ${wait} ms; dispatching anyway (queue, never amputate)` | n/a | nothing |
| 29 | E4 empty child answer | `packages/plugin-remote-fanout/lib/provider.js:589` | `the remote child finished with an empty final message` — and `stopReason` is still `'completed'` (`:590`) | n/a | nothing (there is nothing) |
| 30 | E5 provider catch-all | `packages/plugin-remote-fanout/lib/provider.js:609` | `limitDiagnostic(error?.message ?? error)` | depends | blocks only if empty |
| 31 | E6 no lease on a fixed target | `packages/plugin-remote-fanout/lib/placement.js:642` | `the placement carried no lease` (skipped, not an error) | n/a | nothing |
| 32 | E7 runner: node full, no queueing | `packages/plugin-mesh-http/lib/runner.js:306` | `${this.active} of ${this.maxConcurrent} runs are in flight and this node answers 429 instead of queueing (refuseWhenFull)` → `reason: 'node-busy'` | yes | nothing |
| 33 | E8 queue budget exceeded | `packages/plugin-mesh-http/lib/runner.js:307` | `waited ${Math.round(admission.waitedMs / 1000)}s for a slot (limit ${this.maxConcurrent}); the queue did not drain within the ${…}s queue budget` → `reason: 'node-queue-wait-exceeded'` | yes | nothing (caller's budget) |
| 34 | E9 route refusals | `packages/plugin-mesh-http/lib/handler.js:71,74,90,92,100,105,107,118,121,126` | `method-not-allowed`, `content-type-must-be-application-json`, HMAC verdicts (`bad-signature`/`outside-window`/`replayed`/`node-has-no-secret`), `body verified but not a JSON object`, `prompt-required`, `prompt-too-large`, `workdir-not-allowed`, `workdir-unusable`, `node-workdir-unusable` | `prompt-required`/`workdir-*` yes; HMAC no | nothing |
| 35 | E10 route 500 | `packages/plugin-mesh-http/lib/handler.js:199` | `node-error` | yes | nothing |
| 36 | E11 CLI arg/boot refusals | `packages/plugin-mesh-http/bin/mesh-dispatch.mjs:155,181,186,190,212,216,457,621` | `-Transport must be v1, v2 or auto (got "…")`, `unknown argument "…"`, `-Node <name> is required (this script does not choose a node)`, `-Prompt "<task>" is required`, `… has no usable MESH_HTTP_SECRET (a secret is at least 16 bytes)`, `cannot read …`, `unknown node "…" (known: …)`, `transport v2 was required and is unavailable: …` (exit 3) | `-Node`/`-Prompt` yes | nothing |
| 37 | E12 no invocation for the v1 CLI | `packages/plugin-mesh-http/bin/mesh-dispatch.mjs:339,387` | `${facts?.label ?? 'this node'}'s row resolves to NO invocation (it needs an executor \`command\`, or both halves of a driver + bin pair) — refusing to spawn` | no | nothing |
| 38 | E13 broker boot/config refusals | `packages/mesh-broker/lib/config.js:75,78,82,86` | `node "…" appears twice` / `… needs an absolute http(s) baseUrl …` / `… needs its fqdn …` / `… does not match the first label of its own fqdn …` | no | nothing (boot) |
| 39 | E14 capacity read failures (never refuse) | `packages/mesh-broker/lib/capacity.js:155,170,186,190,202,205,303` | `invalid url …`, `response body exceeded ${MAX_BODY_BYTES} bytes`, `HTTP ${status}`, `invalid JSON: …`, `timed out after ${timeoutMs} ms`, `timed out after ${timeoutMs} ms (hard wall-clock deadline)`, `capacity document rejected: ${check.reason}` | **only `timeout`** (`isRetryableRead`, `:105`) | nothing — becomes `slow`/`unreachable` on `/nodes` |
| 40 | E15 capacity reader threw | `packages/mesh-broker/lib/broker.js:215` | `the capacity reader threw: ${messageOf(error)}` | n/a | nothing |
| 41 | E16 broker internal fault | `packages/mesh-broker/lib/broker.js:844` | `internal fault while scoring (${messageOf(error)}); placed on ${node.node} with position 1 rather than returning an error — the broker never refuses a placement` | yes | nothing (still returns a lease) |

Notes on the table:

* `packages/plugin-remote-fanout/lib/nodes.js`, `packages/mesh-broker/lib/scoring.js` and
  `lib/leases.js` contain **no failure exit path**: `nodes.js` returns `undefined` rather than
  throwing (`:211-213`), `scoring.js` has no `throw` at all, and `leases.js:104` returns
  `{ released: false, node: null, state: null, heldMs: null }` for an unknown lease.
* `packages/plugin-mesh-http/lib/concurrency.js` propagates no failure either: it *derives* a
  number and fails soft (`readAvailableMemoryMiB:199`, `createDeclaredCapacityReader:281-284`).
* `packages/plugin-mesh-http/lib/node-identity.js` deliberately does **not** refuse on a
  degraded identity (`:183-186`); see H5.

**The worst class, in three lines** — rows 1, 2 and 6: A1 `provider.js:580` (the answer is
deleted though only its provenance is in doubt), A2 `provider.js:559` (a transient timeout
deletes a real turn), A6 `broker-client.js:190` (a 30 s silence is reported with the wording of
an outage and is never retried).

---

## SECTION 2 — THE SEVEN HYPOTHESES

### H1 — "a double-quote in the prompt kills the remote one-shot" — **REFUTED, with the line quoted**

The claim is that "the task text is interpolated into a double-quoted shell string". There is
no such line anywhere on the dispatch path. The task is placed into the remote command at
exactly two places, and both quote it:

* **POSIX** — `packages/plugin-remote-fanout/lib/remote-script.js:257-261`, the last word of the
  generated program:

  ```js
  ...[resolved.command, ...(resolved.argvPrefix ?? [])].map(shellWord),
  '--profile',
  shellWord(profileWord),
  taskWord(singleLine(task)),
  ```

  and `taskWord` (`:71-73`) is unconditional:

  ```js
  function taskWord(text) {
    return shQuote(text ?? '');
  }
  ```

  with `shQuote` (`:50-52`) = `` `'${String(value).replace(/'/g, `'\\''`)}'` ``. That program is
  then delivered on **stdin** to `sh -s` (`ssh-transport.js:64`, `:216-219`), so it is not even
  a remote *command line*.

* **PowerShell** — `remote-script.js:189` puts the single-lined task into `argv`, and `:202`
  quotes every word of it:

  ```js
  const argv = [resolved.command, ...(resolved.argvPrefix ?? []), '--profile', profileWord, singleLine(task)];
  ...
  `& ${psCommandLine(argv)}`,
  ```

  `psCommandLine` (`:122-124`) maps `psQuote`, which doubles `'` and never introduces `"`. The
  whole program is then base64/UTF-16LE encoded — `remote-script.js:54-56` +
  `ssh-transport.js:63-66` — and passed as `-EncodedCommand`, so **no shell layer ever re-parses
  the task**.

I did not take this from the comments; I ran the builders. Command:

```
node $env:TEMP\qcheck.mjs        # imports remote-script.js and builds both programs
                                 # for task = 'The standing rule of this system is "a flag is raised only by the owner" and it is not optional.'
```

Result lines:

```
PWSH-LINE:  & 'C:/Program Files/nodejs/node.exe' 'C:/x/lib/bin.js' '--profile' 'headless' 'The standing rule of this system is "a flag is raised only by the owner" and it is not optional.'
POSIX-LINE: 'C:/Program Files/nodejs/node.exe' C:/x/lib/bin.js --profile headless 'The standing rule of this system is "a flag is raised only by the owner" and it is not optional.'
B64-BYTES: 1936 SCRIPT-CHARS: 726
```

The `"` survives as a literal inside a single-quoted word in both shells, and the PowerShell
program is 1 936 base64 characters of `-EncodedCommand`, not a double-quoted command line. The
`journal/packages/plugin-remote-fanout/lib/ssh-transport.js` snapshot is byte-identical to the
live one (`git diff --no-index` is empty) and also uses `-EncodedCommand:65`, so this is not a
"fixed already" artefact of the checkout.

**What `L3060` therefore is not is a code fact.** The writer inferred the mechanism from the
symptom ("stderr tail was the tail of my own prompt, cut at the first double-quote") and named
a cause the code does not have. What the symptom *is* consistent with, and what I could not
settle (§5): the Windows remote **command-line length ceiling**, because the base64 form grows
at ~2.67× the generated program (measured above: 726 script chars → 1 936 base64 chars). The
audit briefs in `L3060` were long; the PowerShell boilerplate is ~610 chars, so base64 passes
`cmd.exe`'s 8 191-character limit at roughly **2 450 characters of task text**. That is a real
defect class with the same symptom shape — live, unmapped, and *not* about double quotes.

**The correct fix, and which form is cheapest.** The hypothesis's three candidates are stdin, a
temporary file on the target, and a real escaping function. Two of the three already exist and
the third is the wrong shape for the remaining risk:

1. **POSIX already uses stdin** (`sh -s`, `ssh-transport.js:64`) — nothing to do.
2. **The escaping functions already exist and are correct** (`shQuote`, `psQuote`, `taskWord`,
   `psCommandLine`) — adding another would be duplicate code, and there is no unquoted
   interpolation left to fix.
3. **The cheapest fix for the real remaining risk is the temporary file on the target**, applied
   uniformly to *both* shells. Concretely: have `runOnce` (`provider.js:479-496`) write
   `childTask` into a file under the node's `cwd` (the script already knows `cwd` —
   `remote-script.js:197`, `:250`), and have the generated program read its task from that path
   instead of carrying it as the last word. Length stops mattering, `-EncodedCommand` stops
   being a length cliff, and the change is confined to `remote-script.js` (`buildPwshScript`
   argv, `buildPosixScript` argv) plus one write in `ssh-transport.js`. A single helper —
   `taskFileFor(cwd, nonce)` — replaces `taskWord(singleLine(task))` and the argv tail in both
   builders; nothing else moves.

### H2 — "the provider fails the run AND discards the child's entire answer when the marker is missing" — **CONFIRMED**

`packages/plugin-remote-fanout/lib/provider.js:578-582`:

```js
if (this.verifyMeshHost) {
  if (meshHost === undefined) {
    diagnostic = `the child did not begin its report with "${MESH_HOST_LINE} <hostname>" — its location is unproven, so the run is not reported as complete`;
    return { output: blocks, diagnostic, stopReason: 'error' };
  }
```

`stopReason: 'error'` is what makes the seam treat the run as failed, and everything the child
wrote is discarded by the caller. The text is *not* discarded by `renderReport` — `blocks` is
returned and `renderReport` (`:268-271`) puts `parsed.answer` in the body when `parsed.framed`.
The discard happens **downstream of the provider**: the seam sees `stopReason: 'error'`, so
`job_output` returns `(no new output)`, which is exactly what `P2667.md:4` and `L3059.md:4`
record. Note also `:579` uses `MESH_HOST_LINE`, a constant exported at `:111`, and `:588-591`
already demonstrates the *right* shape for an inconclusive run: `stopReason: 'completed'` with a
diagnostic and no `output` change.

**Fix (preserves the output, marks it unproven).** Keep the diagnostic and the evidence, stop
calling it an error. At `provider.js:579-582`, return
`{ output: blocks, diagnostic, stopReason: 'completed', provenance: 'unproven' }`, and put the
provenance into the report so it cannot be read as proof of location: add one line to the header
in `renderReport` (`:265`), e.g.
`` `location check = UNPROVEN — the child did not begin with "${MESH_HOST_LINE} <hostname>"; the answer below is preserved and its location is NOT proven` ``.
The asymmetry with A7/A8 (host mismatch) is deliberate and must stay: a *wrong* node is a
security refusal, a *missing* marker is missing metadata. The same change is needed in
`packages/plugin-mesh-http/bin/mesh-dispatch.mjs`, which records `disagreements` (`:556`,
`:639`) but never refuses — consistent, nothing to change there.

### H3 — "a transient broker timeout is reported as broker-unreachable with outage wording, and there is no retry" — **CONFIRMED**

`packages/plugin-remote-fanout/lib/broker-client.js:186-191`:

```js
if (!result.ok) {
  const why = result.spawnError
    ?? (result.timedOut ? `no answer within ${timeout} ms` : `ssh exited ${result.exitCode ?? 'without a code'}`)
    + (result.stderr.trim() === '' ? '' : `: ${result.stderr.trim().slice(0, 300)}`);
  throw new BrokerError(BROKER_UNREACHABLE, `the placement broker could not be reached at ${where} — ${why}`, { route, argv, exitCode: result.exitCode, stderr: result.stderr.slice(0, 600), ms: result.ms });
}
```

`BROKER_UNREACHABLE` is the *only* code for every failure shape — a 30 s silence, a refused
connection, a DNS failure, a non-zero ssh exit. The `sshRun` timeout at `:105-108` sets
`timedOut = true` and kills the client, so the distinction is *measured* and then thrown away.
`P2668.md:7` quotes the exact string that came out, and `:11` records that `GET /place` answered
405 minutes later — the broker was up the whole time.

**No retry exists anywhere on the path.** The provider's placement try/catch
(`provider.js:421-435`) counts and re-throws; `placement.js:371-400` re-throws. The only retry in
the package is `shouldRetryWithFallback` (`remote-script.js:139-147`), which retries the
*invocation*, not the broker. The mesh already contains the correct model in the other
direction: `capacity.js:105-107` retries exactly one thing —

```js
export function isRetryableRead(result) {
  return result?.ok !== true && result?.errorKind === 'timeout';
}
```

— with a longer second budget (`retryTimeoutMs`, `:275-277`).

**Where the bounded retry belongs, and how the two cases must read.** In `broker-client.js`
`request()` (`:174-199`), not in `placement.js`: the retry needs the transport-level evidence
(`result.timedOut` vs `result.spawnError` vs `exitCode`), which only exists there. One retry,
only when `result.timedOut === true`, at `timeout/2` for the second attempt, with the attempt
count carried on the thrown error. The two readings must then be *different strings with
different codes*:

* timeout, retried: code `broker-timeout` —
  `the placement broker at ${where} did not answer within ${timeout} ms (retried once, still no answer after ${total} ms) — the broker's own POST /place was never executed`
* never answered: keep `broker-unreachable` —
  `the placement broker at ${where} could not be reached — refused/DNS/exit ${…}`

`placement.js:393` (E2) and `provider.js:434` (A6) then stop needing to guess.

### H4 — "the ssh transport can be severed mid-turn, leaving nothing pushed and no resumption" — **CONFIRMED, with one real mitigation that lives in config, not in the package**

What the code does today, `packages/plugin-remote-fanout/lib/ssh-transport.js`:

* stdout/stderr go to **temp files**, read after the client exits (`:191-192`, `:169-170`), and
  the files are unlinked in `settle` (`:171-173`). Nothing is streamed anywhere — deliberately,
  because of the measured Win32-OpenSSH pipe hang (`:22-39`).
* the run settles on the client's `close` (`:209-214`) or on the completion frame
  (`:231-265`). If the TCP flow is severed, `close` fires, `ok: false`, and `settle` runs. The
  provider turns that into a diagnostic (`provider.js:554-570`) and `stopReason: 'error'`.
* `killTree` is called only on **timeout** (`:222-225`), on `kill(reason)` (`:269-273`), and from
  `dispose()` (`provider.js:645`). **A severed transport does not kill the child.** The `dsh
  --profile headless` process on the target keeps generating and keeps its toolbelt, and nobody
  will ever collect its answer.

**Would a child's work survive?** The answer text: no. The bytes are in `outPath` on the
*dispatcher's* temp dir only if the ssh client wrote them before dying; on a hard severance they
were never delivered, and `settle` cannot distinguish "the child never answered" from "the
answer was in flight". There is **no resumption**: the provider has no `prepareContinuable`
(documented at `provider.js:48-52`), the child is a fresh one-shot process
(`remote-script.js:230-266`), the frame nonce is per-run (`provider.js:399`) so a later reader
cannot re-find the frame, and nothing on the target writes the child's answer to a durable path
the dispatcher could re-fetch. `runner.js:452-454` is the only place a child's streams are
persisted — and that is transport **v2**, the other transport, not this one. The child's *side
effects* (files written) survive; its *turn* does not.

The lease is not lost: `provider.js:612` releases with `ok:false` once the attempt settles, so
the broker's arithmetic stays right (`placement.js:645`) — but the model turn is paid for and
thrown away, which is A2/A3 in the table.

**Keepalive: exists, but as a deployment fact.** `ssh-transport.js:97` defaults `sshArgs` to
`[]` and `createSshTransport` adds nothing. The keepalive the config comments call
"not optional" lives in `profiles/web/cordis.patch.yml:179`:
`['-o','BatchMode=yes','-o','StrictHostKeyChecking=accept-new','-o','ConnectTimeout=25','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=4']`.
The broker client — the *other* ssh consumer — defaults to `['-o','BatchMode=yes','-o','ConnectTimeout=8']`
(`broker-client.js:162`) and therefore has **no keepalive at all**. So H4 is confirmed for any
caller that does not restate that list, and the fix is to make the keepalive the package default
in `ssh-transport.js:97` and `broker-client.js:162` rather than a profile fact.

### H5 — "a transport that reports an empty host identity is refused" — **REFUTED as a refusal; the *message* is the defect**

Two different things are being conflated, and they behave oppositely.

**(a) The mesh-http route does not refuse.** `packages/plugin-mesh-http/lib/node-identity.js:200-205`
sets `identityDegraded` and `identityReason`, and `:183-186` states the policy in words:

```
* `identityDegraded` is the honest half of the fix: a node whose tailnet name could not be read
* still SERVES (refusing would take a node with no tailscale CLI out of the mesh entirely), but
* it says so, and says why, so the dispatcher can decline to place work on a name it cannot
* corroborate.
```

The route answers 200 with `identityDegraded: true` (`handler.js:233-273`, no branch on it), and
`mesh-dispatch.mjs:528` **records** `identityDegraded: probe.json.identityDegraded === true` and
then proceeds. An empty `MESH_NODE_NAME`/`DNSName` is `normalizeTailnet` → `fqdn: null`,
`node: null` (`node-identity.js:76-88`), and `node()` falls back to `os.hostname()`
(`:167`) — a name, never an empty one. There is nothing to refuse.

**(b) The fan-out provider *does* refuse an unreadable host, and the message is not truthful.**
`packages/plugin-remote-fanout/lib/provider.js:574-577`:

```js
if (placementHosts.length > 0 && !placementHosts.some((host) => sameNode(host, parsed.host))) {
  diagnostic = `the transport reported host "${parsed.host ?? 'unknown'}", which is not one of the hostnames the placement named ("${placement.node}" may be ${placementHosts.join(', ')}) — refusing to report work from a node the broker did not name`;
```

When the target shell's `FANOUT_TRANSPORT_HOST` line never arrived, `parsed.host` is `undefined`
(`remote-script.js:282`, `:300`), and the message says the transport **"reported host `unknown`"**.
That is false: the transport reported *nothing*. The refusal itself is correct — an unproven
location must not be reported as a proven one — but it is reported as a *wrong* node when the
truth is a *missing* reading, which sends a reader hunting for an ssh alias bug that does not
exist. The mirror of the same untruth is `provider.js:254`, where
`` `transport host = ${parsed.host ?? '(not reported)'}` `` gets this right; :575 should use the
same wording. Fix: branch on `parsed.host === undefined` and emit
`the target shell recorded no FANOUT_TRANSPORT_HOST line at all (no host identity was reported), so the placement on "${placement.node}" cannot be corroborated — refusing to report work whose node is unproven`.

### H6 — Lease hygiene, every path from placement to settle — **TWO LEAKS**

Every path, with the release verdict:

| path | lease released? |
|------|-----------------|
| fixed target (no lease at all) | n/a — `placement.js:641-643` returns `skipped: 'the placement carried no lease'` |
| pressure refusal *before* `POST /place` (`placement.js:334-368`) | n/a — no lease was issued, and the message says so (`:364`) |
| `POST /place` throws (`placement.js:371-400`) | n/a — no lease |
| **`facts === undefined` for the placed node (`placement.js:455-462`)** | **NO — LEASE LEAK (C1)** |
| `prefer-remote` releases the local lease (`placement.js:438-440`) | released unspent; a failure is recorded in `supersededLease` and warned (`:443`) but the lease stands to TTL (C4) |
| second `POST /place` in `prefer-remote` throws (`placement.js:446`) | n/a — the first lease was already released |
| `waitForSlot` runs (`placement.js:577-637`) | held throughout; released at settle |
| **`transportFor(placement)` throws (`provider.js:467`)** | **NO — LEASE LEAK (C2)** |
| `buildPosixScript`/`buildPwshScript` throws inside `runOnce` (`remote-script.js:166`) | yes — thrown inside `attempt()`, caught at `provider.js:604-611`, released at `:612` |
| every outcome of `attempt()` — abort, spawnError, timeout, exit≠0, no frame, host mismatch, no marker, empty answer, success | yes — `provider.js:612` runs unconditionally after the try/catch |
| `release()` itself fails (`placement.js:648-651`) | no, but **reported**: `provider.js:285` puts `lease … COULD NOT be released` in the report and `:624` records `leaseReleaseError` |
| `dispose()` called mid-turn (`provider.js:641-651`) | yes — it kills the client; the attempt settles from `started.done`, then `:612` releases with `ok:false` |
| broker restart / lease TTL | reclaimed by the broker (`leases.js:58-67`, reaped on every read) |
| transport v2 (`runner.js`) | no leases exist; the slot is returned in the `finally` (`:435-439`) |

**The two leaks, named.**

* **C1 — `placement.js:455-462`.** `facts === undefined` throws `placement-node-unknown`
  *after* `broker.place()` succeeded at `:372` (or `:446`). The comment at `:464-471` argues
  correctly that a refusal here "would strand the lease the broker just issued (its TTL is
  900 s)" — and then the code does exactly that on the lookup-miss branch. The message is
  about not dispatching; it is silent about the reservation it is holding.
* **C2 — `provider.js:466-467`.** These two statements run in `start()`'s synchronous prefix,
  *outside* the `result` IIFE that owns the `release()` call at `:612`:

  ```js
  const shell = remoteFacts.shell === 'posix' ? 'posix' : 'powershell';
  const transport = this.placer.transportFor(placement);
  ```

  `transportFor` (`placement.js:271-282`) calls `createSshTransport`, which throws
  `remote-fanout: transport \`target\` is required …` (`ssh-transport.js:100`) whenever the
  placed row carries no `ssh`. No `try/finally` covers this, so `start()` rejects and the lease
  from `:422` is never given back. The same hole covers anything thrown by the queue-wait
  `onWait` callback (`:441-453`) that is not already swallowed by `#record` (`:374-381`).

**Minimal fix, and it removes the whole class: make the release unconditional the moment the
lease exists.** In `provider.js`, move the `result` IIFE up so it opens immediately after
`:436` (`this.counters.placed += 1;`), wrapping lines 437-593, with a `finally` that performs
`await this.placer.release(placement, settled?.stopReason === 'completed')` and the `withLeaseNote`
patch — one release site instead of one. In `placement.js:455-462`, release before throwing:
`await broker.done(placement.lease, false)` in a `try/catch` that only warns, exactly as the
prefer-remote branch at `:438-444` already does — the precedent is in the same file.

### H7 — Output and timeout: does a timed-out or over-cap child keep partial output? — **CONFIRMED (kept), with the flag dropped on both transports**

**Killed by the child-turn timeout — partial output IS kept, on both transports.**

* transport v1: `ssh-transport.js:222-225` sets `killed = 'timeout'` and calls `killTree`; `settle`
  (`:163-188`) then reads the temp files through `readCapped` and returns `stdout: out.text`
  with `timedOut: true`. Everything the target wrote before the kill is in the answer.
* transport v2: `runner.js:428-432` kills the child; `finish` (`:400-421`) returns
  `stdout: captured(outChunks, outPath)` — the chunks collected up to the kill. `handler.js:192`
  answers 504 **with the stdout attached**, and `mesh-dispatch.mjs:579-599` treats `504` as an
  answered run, not a fallback.
* the provider does not throw the partial answer away either: `renderReport`
  (`provider.js:268-271`) prints `parsed.answer` when framed and the raw stdout when not.

**Output over `maxOutputBytes` — partial output is kept, but the *fact of truncation* is lost.**

* transport v1, `packages/plugin-remote-fanout/lib/ssh-transport.js:152-161`:

  ```js
  const readCapped = (file) => {
    try {
      const text = readFileSync(file, 'utf8');
      return text.length > maxOutputBytes
        ? { text: text.slice(0, maxOutputBytes), truncated: true }
        : { text, truncated: false };
  ```

  The cap is real and reported to the provider as `truncated: out.truncated || err.truncated`
  (`:185`) — **and `provider.js` never reads `outcome.truncated`.** Grep it: `provider.js` uses
  `outcome.exitCode`, `outcome.timedOut`, `outcome.spawnError`, `outcome.stderr`, `outcome.ms`,
  `outcome.markerSettled`, `outcome.stdout`. Not `truncated`. So a child whose answer was cut at
  `DEFAULT_MAX_OUTPUT_BYTES = 200_000` returns a report that says nothing about it. Two further
  details: the slicing is by **UTF-16 code unit**, not byte, so on non-ASCII output the retained
  text can be up to ~3× the stated byte budget; and `outPath`/`errPath` are deleted in `settle`
  (`:171-173`), so the cut remainder is unrecoverable — unlike v2, which keeps
  `stdout.txt`/`stderr.txt` on the node forever (`runner.js:450-454`).

* transport v2 reports it correctly and then loses it one layer up: `runner.js:382-399` caps by
  bytes and sets `stdoutTruncated`/`stderrTruncated`; `handler.js:159` forwards
  `truncated: result.stdoutTruncated === true || result.stderrTruncated === true`; and
  `mesh-dispatch.mjs:575-578` and `:582-596` build the `answered`/`record` objects with
  `stdoutBytes` and `stderr` but **no `truncated` field at all**. The operator reading the JSONL
  record or the final `result` line cannot tell an answer that ended from one that was cut.

**Fix.** v1: surface `outcome.truncated` as one more header line in `renderReport`
(`provider.js:242-267`) — `output = TRUNCATED at ${maxOutputBytes} chars; the remainder was not
collected` — and, because the temp files are deleted, either raise `maxOutputBytes` or keep the
files when `truncated === true`. v2: add `truncated: post.json?.truncated ?? null` to the
`record`/`answered` objects at `mesh-dispatch.mjs:575` and `:582`.

---

## SECTION 3 — THE FIXES

One row per confirmed defect; smallest change that removes the class, then the test that would
prove it. Every test is a `node --test` case in a suite that already exists.

| ID | file:line to change | minimal fix | test that proves it |
|----|--------------------|-------------|---------------------|
| A1 (H2) | `provider.js:579-582` | return `{ output: blocks, diagnostic, stopReason: 'completed', provenance: 'unproven' }`; add the `UNPROVEN` line to `renderReport`'s header (`:242-267`) | `node --test packages/plugin-remote-fanout/test/provider.test.mjs`, new case **`a child that omits MESH-HOST keeps its answer and is marked unproven`**: fake transport returns a framed answer with no marker → assert `result.stopReason === 'completed'`, `result.provenance === 'unproven'`, and `result.output[0].text.includes('the child said this')` |
| A2 | `provider.js:558-562` | do not delete the turn: keep `stopReason:'error'` (a timeout is not a success) but set `provenance:'timed-out'` and ensure the partial stdout reaches `renderReport` even when unframed (it already does, `:268-271`) — the real fix is H4's keepalive + a `resume`-less re-dispatch note | `provider.test.mjs`, new case **`a timeout reports the partial answer`**: transport resolves `{timedOut:true, stdout:'FANOUT_BEGIN\nhalf an answer'}` → assert the text contains `half an answer` |
| A6 (H3) | `broker-client.js:186-191` (+ `:162` keepalive) | one retry when `result.timedOut === true`, second budget `timeout/2`; throw `broker-timeout` for a timeout and keep `broker-unreachable` for spawn/refused/DNS; put the attempt count in `detail` | `node --test packages/plugin-remote-fanout/test/broker-client.test.mjs`, new case **`a first timeout is retried once and reported as broker-timeout`**: injected `spawnImpl` whose first child closes with `code 255` after the timeout fires and whose second succeeds → assert `spawnImpl` was called twice, `error.code === 'broker-timeout'`, and `error.message.includes('retried once')` |
| B1/C1 (H6) | `placement.js:455-462` | before `throw`, `try { await broker.done(placement.lease, false) } catch { logger?.warn?.(…) }` — the pattern already at `:438-444` | `node --test packages/plugin-remote-fanout/test/placement.test.mjs`, new case **`an unknown node releases the lease before refusing`**: broker returns `{node:'nope', lease:'L1', position:0, rationale:['x']}` → assert the thrown `code === 'placement-node-unknown'` **and** that `done` was called with `'L1'` |
| C2 (H6) | `provider.js:436-612` | open the `result` IIFE immediately after the placement counter and put `release()` in a `finally`, so exactly one release site covers `transportFor` too | `provider.test.mjs`, new case **`a placed row with no ssh destination still releases its lease`**: placer whose `transportFor` throws (row without `ssh`) → assert `start()` rejects **and** `placer.release` was called once with the lease |
| D1 (H7) | `ssh-transport.js:152-161`, `provider.js:242-267` | keep the byte cap but report it: add `output = TRUNCATED …` to the report header; slice by `Buffer` bytes, not code units; keep the temp files when `truncated === true` | `node --test packages/plugin-remote-fanout/test/ssh-transport.test.mjs`, new case **`a capped stream is flagged truncated`**: child writes `maxOutputBytes + 100` chars → assert `outcome.truncated === true` and `outcome.stdout.length === maxOutputBytes`; plus a `provider.test.mjs` case asserting `TRUNCATED` appears in the report |
| D2 (H7) | `mesh-dispatch.mjs:575-578`, `:582-596` | add `truncated: post.json?.truncated ?? null` to the `record` and `answered` objects | `node --test packages/plugin-mesh-http/test/mesh-http.test.mjs`, new case **`the dispatcher's result carries the node's truncated flag`** |
| A5/E14 keepalive (H4) | `ssh-transport.js:97`, `broker-client.js:162` | make the measured keepalive the package default: `['-o','BatchMode=yes','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=4']` | `ssh-transport.test.mjs`, new case **`the default argv carries a keepalive`**: assert `createSshTransport({target:'x'}).start(...)`'s `outcome.argv` contains `ServerAliveInterval=15` |
| H1 residual | `remote-script.js:189` and `:257-261` | replace the argv-tail task with a task file on the target (`taskFileFor(cwd, nonce)`), written by `ssh-transport` before the program runs — removes the `-EncodedCommand` length cliff for long briefs without touching the (already correct) quoting | `node --test packages/plugin-remote-fanout/test/remote-script.test.mjs`, new case **`the generated program does not embed the task`**: for a 4 000-character task, assert the PowerShell program is shorter than the task and that the task path appears instead; keep a case asserting a `"` and a `'` both survive in the file's contents |
| H5 | `provider.js:575` | branch on `parsed.host === undefined` and say *no host identity was reported* rather than `reported host "unknown"` | `provider.test.mjs`, new case **`a missing transport host is reported as missing, not as a wrong node`**: framed output with no `FANOUT_TRANSPORT_HOST` line → assert the diagnostic contains `no host identity was reported` and not `reported host "unknown"` |

Whole-suite check for the two packages touched:

```
node --test packages/plugin-remote-fanout/test/ packages/plugin-mesh-http/test/
```

---

## SECTION 4 — LIVE READINGS

Read on **2026-09-29 at 18:26 UTC** (14:26 local, America/New_York) from **zabz-tech**, over
`ssh secratary-ts`, against the broker on the authority's loopback.

Commands (the ssh output had to be redirected to a **file**: the first two attempts hung
forever with stdout on a pipe, which is the exact failure the transport's own module header
records at `ssh-transport.js:22-39`):

```
ssh -n -o BatchMode=yes -o ConnectTimeout=10 secratary-ts \
  'curl -s -m 10 http://127.0.0.1:3091/nodes -o /tmp/n.json -w CODE:%{http_code}'
```

Result: `hostname` → `secratary`; `date -u` → `2026-09-29T18:26:38Z`; `CODE:200`; body 16 673 bytes.
Top-level fields read from that body:

```
"schema": 1, "at": "2026-09-29T18:26:38.865Z", "cacheTtlSec": 15,
"readTimeoutMs": 1500, "leaseTtlSec": 900,
"reads": 6199, "readFailures": 2355
```

**Reads vs readFailures, as a percentage**

| | value |
|---|---|
| `reads` | **6 199** |
| `readFailures` | **2 355** |
| readFailures as a share of reads | **2 355 / 6 199 = 37.99 %** (38.0 %) |
| reads that succeeded | 3 844 → **62.0 %** |

The broker is up and answering (`HTTP 200`, `schema 1`) and all four roster rows read
`state: "ok"` at 18:26:52Z, with `freeSlots` 12 / 12 / 4 / 1 and `leases.live: 6`. Ten live
`"node": "…"` values resolved to `zabz-tech` and `zabz-yoga-1`; `zabz-tech-linux` and
`secratary` are in the same body. `GET /status` is not a route (`404 no route for GET /status`),
so the counters above are the `/nodes` ones; there is no separate uptime reading.

**Have the failure counters changed since 2026-09-28?** Yes — both of them, and the failure
share has fallen.

| | 2026-09-28 (baseline) | 2026-09-29 18:26Z (this reading) | delta |
|---|---|---|---|
| `reads` | 1 653 | 6 199 | **+4 546** |
| `readFailures` | 995 | 2 355 | **+1 360** |
| failures as a share of reads | **60.19 %** | **37.99 %** | **−22.2 points** |
| marginal failure rate over the interval | — | — | **1 360 / 4 546 = 29.9 %** |

So: cumulative `readFailures` rose by 1 360, but ~4 546 new reads arrived in the same interval,
so the *rate* is 29.9 % on the recent interval against 60.2 % cumulatively — the mesh's capacity
reads are failing considerably less often than the cumulative average suggests, and roughly
three reads in ten still fail. This is a counter reading, not a diagnosis of why (see §5).

---

## SECTION 5 — WHAT I COULD NOT VERIFY

1. **The real cause of the `L3060` double-quote failures.** I refuted the stated *mechanism*
   from the code and by running both script builders (§2 H1). I could not reproduce the
   *symptom*, because reproducing it needs a live remote dispatch of a quote-bearing prompt to
   `zabz-tech` through the mounted engine, and this lane may not dispatch subagents. The
   command-line-length ceiling I propose as the alternative mechanism (~2 450 task characters
   before the base64 `-EncodedCommand` passes `cmd.exe`'s 8 191-character limit) is **arithmetic
   from a measured base64 ratio, not a measurement**: I did not confirm the target's default
   sshd shell, nor that the failing briefs were long enough. **Unproven.** What I can state as
   measured is narrower: the generated command keeps a `"` literal in both shells, and the
   PowerShell program is base64-encoded.
2. **Whether the deployed engine is running this code.** `L3060`/`P2667`/`P2668` were measured
   on ZABZ-YOGA on 2026-09-29; I audited base `f97626b`. I verified that
   `journal/packages/plugin-remote-fanout/{lib/ssh-transport.js,lib/remote-script.js}` are
   byte-identical to the live copies, but I did **not** inspect ZABZ-YOGA's
   `~/.dsh/profiles/<name>/node_modules` junction, so I cannot prove the engine that failed
   loaded these files rather than another checkout on that laptop. Until that is checked, H1's
   refutation is a statement about the repository, not about the process that produced the
   failure.
3. **Why `readFailures` is 38 %.** I did not read a per-node breakdown of failure kinds
   (`errorKind`) or the `unreachable`/`slow` rows, so I cannot say which node or which failure
   mode dominates — only that all four rows were `state: "ok"` at the moment of the read. My
   grep for `node`/`state` pairs also produced noise from prose fields, so the per-node
   `freeSlots` list (12/12/4/1) is one reading and the fifth `freeSlots` value (7) is
   unattributed.
4. **The broker's uptime and whether the 1 653-read baseline is the same process.** `GET /status`
   is a 404 on this build, so there is no `startedAt`/`uptimeSec` to compare against
   2026-09-28. If the broker was restarted between the two readings the counters would have
   reset, which would make the deltas above meaningless — nothing I read rules that out.
5. **Lease leaks in production.** C1 and C2 are read from the code and are unambiguous, but I
   did not observe a stranded lease: `GET /nodes` in §4 shows `leases.live: 6` with no age
   breakdown, and I did not read `<DSH_HOME>/mesh/placements/` on any node. So the *code paths*
   are proven; the *live impact* is not.
6. **H4 end-to-end.** I confirmed from the config that the keepalive pair is present for the
   provider's transport and absent from the broker client's, and confirmed from the code that no
   resume exists. I did not sever a connection to watch a child survive, and I have no reading of
   how long an orphaned `dsh --profile headless` process keeps running on a target after its ssh
   client dies.
7. **Time bounds actually achieved.** Every remote reading in §4 took under 70 s wall clock, but
   two earlier attempts at the same read never returned at all and had to be killed at 100 s and
   120 s. Both were the documented Win32-OpenSSH stdout-pipe hang. I did not isolate whether the
   hang is in this machine's ssh client alone or would also hit the provider's `Start-Process`
   path — the provider avoids it by writing to files (`ssh-transport.js:191-192`), which is
   consistent, but that is an argument, not a measurement.
