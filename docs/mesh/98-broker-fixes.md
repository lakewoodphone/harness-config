# 98 — The broker's two defects: a slow node is ranked, not removed; and a roster flag that was not true

**Program:** `docs/mesh/` (the placement broker, stream S5 of `71-mesh-program.md` §3; the seam
`92-provider-placement.md` wired to the provider on 2026-09-17). **Date:** 2026-09-17 (13:40–14:20Z).
**Author:** a delegated session, not the owner. **Reads with:** `92-provider-placement.md` §5.2–§6
(the measurement this fixes), `76-broker.md` §10.8 and §10.4 (the paragraphs the code disagreed
with), `71-mesh-program.md` §2.2 (the frozen contract), `86-authority.md` §1 (the service).

**Provenance convention.** **MEASURED** = taken live in this session by running the thing, with the
command given. **READ** = read out of source, with `path`. **REFUSED** = asked for and not obtained,
stated as a refusal rather than as a silence. Every number carries the run that produced it.

**What was NOT done.** No engine was started, stopped or restarted on the owner's laptop — engine
**pid 4880** was alive with the same start time (08:51:07) before the first command and after the
last, and no process this session did not start was killed. The broker was **not** restarted before
its new code was deployed and proven on disk (`§5`); the live service was restarted only by
`deploy/install-authority.sh`, which is the deployed copy's own installer. The broker listens on
`127.0.0.1:3091` and nothing was published: `tailscale serve` still carries only the `:3086` proxy,
and a request to the authority's LAN and tailnet addresses gets `curl exit 7` (`§5.3`). No
`personal-secretary-mvp` file, no allow-list and no other repo was touched. `git commit` was not
run (the tree keeps its uncommitted state, which is how it arrived).

---

## 1. The two defects, in one line each

1. **A `slow` node was removed from placement entirely, not ranked last.** `broker.js:607-610` (the
   shipped version) narrowed the candidate pool with `preferred = dispatchable.filter(c => !c.slow)`
   and used it whenever it was non-empty, so a node whose capacity read missed the 1500 ms deadline
   once and answered on the longer retry received **no work at all** while any other node answered
   quickly — *even when it had more free slots than the winner*. The node that alternates
   `ok`/`slow`/`ok` on consecutive reads is **the owner's own laptop**, which is also the machine
   running his engine. That is the exact opposite of his goal, which is to move work *off* it.
2. **The roster claimed `zabz-tech-linux` could take v1 dispatch, and the invocation the dispatcher
   actually runs cannot.** The node itself is fine and takes a real headless turn over `ssh` — but
   the dispatcher does not call `dsh`; it calls an explicit `nodeExe` + `bin.js` pair
   (`plugin-remote-fanout/lib/remote-script.js:101`), and that pair (a) names a Node path that does
   not exist and (b) therefore never sources the credential file the machine's `dsh` wrapper sources.
   A child placed there would be dispatched and die before it ran. The flag is now `false` with
   every command and result in its `evidence` string (`§4`).

The two are the same class of failure in different layers: a fact that was true of a *reading* was
being treated as a fact about the *machine*.

---

## 2. Defect 1 — a slow node is ranked, not removed

### 2.1 What the shipped code did

```js
// broker.js, as deployed from 2026-09-17 03:54 until this session (HEAD of the tree at 13:40Z)
const eligible = withDisk;
const dispatchable = eligible.filter((candidate) => candidate.dispatchOk);
const preferred = dispatchable.filter((candidate) => !candidate.slow);   // <-- the defect
const usable = preferred.length > 0 ? preferred : dispatchable;
const withSlow = eligible.filter((candidate) => candidate.dispatchOk || candidate.slow);
if (usable.some((candidate) => candidate.fits)) {
  tier = 'fits';
  pool = usable.filter((candidate) => candidate.fits);                    // <-- a slow node is not here
}
```

`dispatchable` keeps every node that can take v1 work; `preferred` drops the slow ones; and because
`preferred` is non-empty whenever **any** node answered first time, `usable` is `preferred` on every
healthy mesh. So `slow` was not a ranking penalty at all — it was a disqualification, and the two
`withSlow` branches below it existed only to rescue a node when *nothing* was fast.

**The contract said the opposite, in two places, before this session:**

* `docs/mesh/76-broker.md` §10.8: *"It is ranked **below every node that answered first time** and
  **never refused** (if every candidate is slow, `tier=slow` places on the best of them and says
  so)."*
* `docs/mesh/71-mesh-program.md` §2.2: *"if that second attempt succeeds the node is `slow` with its
  elapsed time, **ranked below every node that answered first time and never refused**."*

The code and the paragraph disagreed; the paragraph was right.

### 2.2 The measured consequence (the stream's own numbers, `92` §5.2–§5.3)

| run | what happened | why |
|---|---|---|
| `--children 8`, 13:17Z | 8 of 8 children on `zabz-tech`; the laptop at 12 free slots never named | at 7 in, the desktop was at 11 free and the laptop at 12; the eighth *should* have gone to the laptop |
| three consecutive fresh reads of the laptop, same window | `ok`, `slow`, `ok` | its gate is a Python route on a machine running the owner's engine; it alternates across the 1500 ms deadline |
| `--hold 6 --children 2`, 13:24Z | both children on the desktop at `score 12` and `score 11`, against a laptop reading 12 | the laptop read `slow` in that moment's reading, so it was not in the pool |

So on this mesh, *the node whose gate is slowest is never asked to work* — and the "may be a reading
problem, not a capacity problem" suspicion was correct, exactly.

### 2.3 The fix, and why the shape is this one

```js
const eligible = withDisk;
const dispatchable = eligible.filter((candidate) => candidate.dispatchOk);
const canStart = (candidate) => candidate.fits;
if (dispatchable.some(canStart)) {
  tier = 'fits';
  pool = dispatchable.filter(canStart);
} else if (dispatchable.length > 0) {
  tier = 'highest-slots';
  const highest = Math.max(...dispatchable.map((candidate) => candidate.slots));
  pool = dispatchable.filter((candidate) => candidate.slots === highest);
} else if (eligible.some(canStart)) { … tier = 'transport' … }
```

Three changes, and each one is a sentence a reader can check:

1. **`preferred` and `usable` are gone.** The pool is every node that can take v1 work. A slow node
   is in it, in the tier its numbers put it in, and it wins when the fast nodes cannot take the job.
2. **`compareFallback` now decides `fits` too**, and puts room for *this job* above raw slot count:
   `reachable` → `can take v1 work` → **`NOT slow`** → **`fits now`** → effective slots → load →
   roster order. The old code sorted the `fits` tier by `rankingKey` (score, preference, load, order)
   only.
3. **The `withSlow` rescue branches are gone, and `tier=slow` is no longer produced.** A slow node
   is a candidate in the tier it belongs to; the fact that it is slow is printed
   (`classification=slow`, and the `SLOW - …` line) instead of being encoded as a different tier.
   `tierLine`'s `slow` case is kept so a `tier` value persisted by an older caller still reads.

**What deliberately did NOT change.** A node whose roster row says it cannot take v1 work is still
kept out of the ladder above while a node that can is in play (AMENDMENT 4, §10.4) — that is a
measured *capability*, not a stopwatch, and it is what stops a placed child from dying on the node.
`slow` still ranks below `ok` whenever both can take the job, so the §10.8 measurement that created
the state is still honoured: a node that answered first time wins.

### 2.4 The new test, and proof that it fails on the shipped code

`test/acceptance.test.mjs`:

```
REQUIREMENT 3b a SLOW node with more free slots is still a candidate: an ok node with fewer wins only if it can take the job
```

The mesh is the measured §5.3 shape: `zabz-tech` **ok with 4 free slots** against a 6-child fleet,
`zabz-yoga-1` **slow with 12** (its first read is accepted and never answered, its retry answers
after a real 700 ms delay). It asserts `node === 'zabz-yoga-1'`, `position === 0`, `score === 12`,
`tier === 'fits'`, that the rationale carries the `classification=slow` line and the
`never removed from the pool and never refused` wording, and that the losing fast node is still
explained. Raw output of the test alone:

```
$ node --test --test-name-pattern "REQUIREMENT 3b" test/acceptance.test.mjs
✔ REQUIREMENT 3b a SLOW node with more free slots is still a candidate: an ok node with fewer wins only if it can take
the job (1113.9023ms)
ℹ tests 1
ℹ suites 0
ℹ pass 1
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 1409.9038
```

**And the test is not vacuous — it was run against the defect**, by restoring the two shipped lines
in place and re-running it:

```
$ # lib/broker.js with `preferred = dispatchable.filter((candidate) => !candidate.slow)` put back
$ node --test --test-name-pattern "REQUIREMENT 3b" test/acceptance.test.mjs
ℹ tests 1
ℹ pass 0
ℹ fail 1
  AssertionError [ERR_ASSERTION]: the slow node is still eligible: it is the only candidate that can take the job
  + actual - expected
    actual: 'zabz-tech',
    expected: 'zabz-yoga-1',
```

### 2.5 The strongest evidence: the shipped broker and the fixed broker, same nodes, same request

The live mesh cannot show this defect on any ordinary request, and the reason is worth stating
rather than hiding: the desktop's 18 slots exceed the laptop's 12, so **every job that fits the
laptop also fits the desktop**, and a job they both fit correctly goes to the desktop. The defect
needs a *fast node that cannot take the job*, which is the case `92` §5.2 measured at 8 children.

So the comparison was run deliberately, with the shipped code materialised byte-for-byte from git
into a temp directory and both brokers pointed at the **same two stubs**
(`_scratch/mesh-98-side-by-side.mjs`, a scratch driver, not part of the package):

```
the shipped code materialised from git into C:\Users\ezabz\AppData\Local\Temp\mesh-98-old-5j8lZt
  does it contain the defect (`preferred = dispatchable`)? YES

stub requests after the priming reads: zabz-tech 2 (fast), zabz-yoga-1 4 (1 unanswered + 1 answered = SLOW)

=== SHIPPED (HEAD, the defect) ===
  POST /place {fleet, 6 children} -> HTTP 200
  node=zabz-tech  position=1  score=4  tier=highest-slots  blockedBy=["no-free-slots"]
    chosen from 2 configured node(s): 0 unreachable, 0 excluded by the caller, 0 switched off in the roster; tier=highest-slots; chosen zabz-tech
    zabz-tech: 4 free slot(s) - 6 child(ren) = -2 < 0 -> does not fit now
    no node fits 6 child(ren) (every candidate's free slots - 6 < 0); zabz-tech has the highest measured slots on the mesh (4) -> placed there, QUEUED rather than refused
    position 1: 4 free slot(s) - 6 child(ren) = -2 (< 0, it does not fit), queued because no-free-slots; 0 accepted job(s) ahead on zabz-tech
    zabz-yoga-1: 12 free slot(s) of 24, 12 memory slot(s), 12 core slot(s) of 16 physical x 0.75 -> effective 12, 6 after 6 child(ren), SLOW (1017 ms door-to-door, first attempt missed the deadline): still slow on the second attempt

=== FIXED (this session) ===
  POST /place {fleet, 6 children} -> HTTP 200
  node=zabz-yoga-1  position=0  score=12  tier=fits  blockedBy=[]
    chosen from 2 configured node(s): 0 unreachable, 0 excluded by the caller, 0 switched off in the roster; tier=fits; chosen zabz-yoga-1
    zabz-yoga-1: 12 free slot(s) of 24 (slots 12 = 12 raw …)
    zabz-yoga-1: classification=slow - ranked below every node that answered first time and above nothing, placeable via its own tier - never removed from the pool and never refused
    zabz-yoga-1: SLOW - the first read missed the 300 ms deadline (313 ms), the second answered in 738 ms for 1052 ms door-to-door; the node was STILL slow on the second attempt -> ranked below every node that answered first time, never refused
    zabz-yoga-1: 12 free slot(s) - 6 child(ren) = 6 >= 0 -> fits now
    position 0: 12 free slot(s) - 6 child(ren) = 6 >= 0 on a reachable node -> start now
    zabz-tech: 4 free slot(s) of 24, 4 memory slot(s), 18 core slot(s) of 24 physical x 0.75 -> effective 4, -2 after 6 child(ren)

=== VERDICT ===
  shipped: node=zabz-tech position=1 tier=highest-slots
  fixed  : node=zabz-yoga-1 position=0 tier=fits
  PASS: the fixed broker places the job on the SLOW node that can take it; the shipped one queues it on the fast node that cannot.
```

**In the owner's terms:** the shipped broker took a 6-child job it could run *now* and parked it in a
queue on a node with four slots that could not run it, while a twelve-slot node that had answered
was left out for missing one deadline. The fixed broker runs it.

### 2.6 The rationale now prints the classification, always

`broker.js` gained `classificationLine()`, printed for the chosen node on **every** placement —
`ok` as well as `slow`, because a line that appears only when the state is unusual is a line nobody
looks for. It is the fact the caller can match on:

```
zabz-tech: classification=ok - a normal reading: it is ranked on capacity, and no faster node is preferred over it for answering faster than it did
zabz-yoga-1: classification=slow - ranked below every node that answered first time and above nothing, placeable via its own tier - never removed from the pool and never refused
```

---

## 3. Defect 1's fix, measured live through the real broker, over ssh

The live broker on the authority was restarted by the installer at **14:05:47Z** with the new code
(`MainPID 2304821`, then `2304920`, then `2304940` after the installer's own SIGKILL test, `active`).
A read-only Node probe piped over ssh, `POST`ing to `http://127.0.0.1:3091` (`§6`, run list):

```
MESH READ FRESH at 2026-09-17T14:08:02.041Z  (this process: pid 2305927)
  zabz-tech         state=ok                   slots= 18 free= 18 transport.v1=true
  zabz-yoga-1       state=ok                   slots= 12 free= 12 transport.v1=true
  zabz-tech-linux   state=ok                   slots=  4 free=  4 transport.v1=false
  secratary         state=ok                   slots=  3 free=  3 transport.v1=null

=== FRESH PLACEMENT 1 (whole mesh, fleet 2) ===
  POST /place {"kind":"fleet","children":2,"worktreeGiB":0} -> HTTP 200 at 2026-09-17T14:08:02.058Z
  node=zabz-tech position=0 score=18 tier=fits eligible=3 blockedBy=[]
    zabz-tech: classification=ok - a normal reading: it is ranked on capacity, and no faster node is preferred over it for answering faster than it did
    zabz-yoga-1: 12 free slot(s) of 24, 24 memory slot(s), 12 core slot(s) of 16 physical x 0.75 -> effective 12, 10 after 2 child(ren)
    secratary: 3 free slot(s) of 24, …, transport v1 unmeasured
    zabz-tech-linux: 4 free slot(s) of 24, …, transport v1 MEASURED BROKEN
  /done released=true node=zabz-tech  live leases now=0

=== THE LAPTOP AS THE ONLY ELIGIBLE NODE (the other three excluded) ===
  POST /place {"kind":"oneShot","children":1,"exclude":["zabz-tech","zabz-tech-linux","secratary"]} -> HTTP 200 at 2026-09-17T14:08:09.608Z
  node=zabz-yoga-1 position=0 score=12 tier=fits eligible=1 blockedBy=[]
    zabz-yoga-1: classification=ok - … (it read ok in this moment)
    zabz-yoga-1: 12 free slot(s) - 1 child(ren) = 11 >= 0 -> fits now
    position 0: 12 free slot(s) - 1 child(ren) = 11 >= 0 on a reachable node -> start now
    zabz-tech: 18 free slot(s) of 24, …, excluded by the caller
    zabz-tech-linux: 4 free slot(s) of 24, …, transport v1 MEASURED BROKEN, excluded by the caller
    secratary: 3 free slot(s) of 24, …, transport v1 unmeasured, excluded by the caller
  /done released=true node=zabz-yoga-1  live leases now=0

HEALTHZ: ok=true leases.live=0 reads=8 readFailures=0
```

**Read this honestly, because the live half is weaker than the stub half and saying so is the point.**
Run 1 and runs 2–3 (identical, omitted) show the new code serving the live mesh and printing
`classification=ok`; every one of the three landed on `zabz-tech`, and that is **correct** on this
mesh — the desktop has 18 slots against the laptop's 12, so every job that fits the laptop fits the
desktop, and the roomiest node wins. At 14:08Z the laptop read `ok` in all four readings, so the
`slow` half of the live demonstration could not be produced *on demand* in that window; the exact
condition the defect needs (a fast node that **cannot** take the job) does not arise while the
desktop is idle. The laptop-as-sole-candidate run shows it placeable and printing `fits`, `position
0`; the partial-eligibility case is `§2.5`'s side-by-side and `§2.4`'s test in the suite.

**And then the last placement of the session caught the state live.** On the build installed at
14:11:29Z, a `POST /place {fleet, 3 children}` at **14:11:55.791Z** — a fresh read taken inside the
placement — saw the laptop **`slow`** (`2922 ms door-to-door, first attempt missed the deadline`),
made by `zabz-yoga-1`'s own gate on the owner's laptop at the moment the decision was taken:

```
POST /place {"kind":"fleet","children":3,"worktreeGiB":0} -> HTTP 200 at 2026-09-17T14:11:55.791Z
node=zabz-tech position=0 score=18 tier=fits eligible=3 blockedBy=[]
  zabz-tech: classification=ok - a normal reading: it is ranked on capacity, and no faster node is preferred over it for answering faster than it did
  zabz-tech: 18 free slot(s) - 3 child(ren) = 15 >= 0 -> fits now
  position 0: 18 free slot(s) - 3 child(ren) = 15 >= 0 on a reachable node -> start now
  secratary: 3 free slot(s) of 24, …, transport v1 unmeasured
  zabz-yoga-1: 12 free slot(s) of 24, 24 memory slot(s), 12 core slot(s) of 16 physical x 0.75 -> effective 12, 9 after 3 child(ren), SLOW (2922 ms door-to-door, first attempt missed the deadline): still slow on the second attempt
  zabz-tech-linux: 4 free slot(s) of 24, …, transport v1 MEASURED BROKEN, disk 21 GiB < 21.5 GiB required
/done -> released=true node=zabz-tech live leases=0

/nodes?fresh=1 at 2026-09-17T14:11:57.076Z  reads=8 readFailures=0
  zabz-tech         state=ok                   slots= 18 free= 18 transport.v1=true 2026-09-16
  zabz-yoga-1       state=ok                   slots= 12 free= 12 transport.v1=true 2026-09-16
  zabz-tech-linux   state=ok                   slots=  4 free=  4 transport.v1=false 2026-09-17T14:00Z
  secratary         state=ok                   slots=  3 free=  3 transport.v1=null
```

Two facts in that block, and the second matters more than the first:

1. **The laptop was `SLOW` and the desktop was chosen anyway — and that is the fix working, not the
   defect.** Both nodes had room for a 3-child fleet (18 and 12 slots against 3), so `ok` correctly
   wins on `NOT slow`, and `slow` is named in the same rationale it lost in. Before the fix the same
   decision would have been made *without* the laptop ever having been in the pool — which is
   indistinguishable from correct on this request and is exactly why the stub comparison of `§2.5`
   exists.
2. **`slow` and `ok` in the same 1.3 seconds.** The placement's own read (14:11:55.791Z) saw `slow`
   while the `/nodes?fresh=1` two seconds later saw `ok`, and `92` §5.2's 13:17Z three-read sequence
   was `ok`, `slow`, `ok`. That alternation on the owner's laptop is the measured state the whole
   defect is about, and it is now reproducible on demand for the next session.

Every lease in this section was released and `healthz` ended at `leases.live=0`.

### 3.1 A separate finding, measured at 14:23Z: the LAPTOP'S TAILNET PATH, not the broker

While the final checks ran, `zabz-yoga-1` flipped from `slow` to `unreachable` — `timed out after
4000 ms (hard wall-clock deadline)`, i.e. **both** attempts failed, not one. That is a different
fact from anything this document fixes, and it is recorded here because a future session will meet
it and should not read it as the broker regressing:

```
# the laptop itself, at 14:24Z
127.0.0.1:3086/mesh/capacity            -> HTTP 200      (its own gate is UP)
# the authority, at 14:24Z
tailscale status                        -> zabz-yoga-1  active; relay "nyc"
tailscale ping --c 3 zabz-yoga-1        -> pong via DERP(nyc) 43-49 ms, then "direct connection not established"
curl https://zabz-yoga-1.tail93e6e6.ts.net/mesh/capacity -> HTTP 200 in 0.254 s
# the broker, three reads 20 s apart, 14:25:30-14:26:09Z
zabz-yoga-1 state=unreachable attempts=6 reason=timed out after 4000 ms (hard wall-clock deadline)
zabz-yoga-1 state=slow        attempts=7
zabz-yoga-1 state=slow        attempts=8
```

**So: home and office are on separate networks, the laptop's direct tailnet path had dropped to
DERP-relayed only, and that path is intermittently too slow for a 1500 + 4000 ms read budget.** The
gate responds in 254 ms when it is reached; the read sometimes is not reached in time. Before that
window (14:08Z and 14:11:55Z) every read of that node answered, and the placement evidence in `§3`
comes from those moments. **Nothing in this session touched networking, tailscale, or anything on
the owner's laptop** — this is reported as measured, not as something acted on, and it is the third
distinct cause of "the laptop gets no work" (`slow` was one, a slow tailnet path is another, and a
genuinely offline machine the third). The broker now reports all three as different facts, which is
the point of `ok`/`slow`/`unreachable` being three states.

### 3.2 Leases taken and given back

Every placement in `§3` was released by `POST /done` and every `/done` answered
`released: true`; `healthz` ended at `leases.live=0`. The four placements I first fired with a
malformed body (a quoting mistake of my own, which the broker correctly reported as
`note: the request body was not valid JSON … assumed kind=oneShot children=1`) left four `running`
leases on `zabz-tech`; all four were released explicitly at 14:07:44Z
(`heldMs` 63.8–73.4 s) and `healthz` then read `leases.live=0`. Nothing was left holding a slot.

---

## 4. Defect 2 — the linux node's measured transport truth

**The verdict: `dispatch.v1` is now `false` — but "measured broken" here means *the invocation the
dispatcher runs is broken*, not that the machine is.** Those are different facts and the roster
string carries both.

### 4.1 What was measured, with commands and results

All read-only, over `ssh linux-pc-ts`, 2026-09-17 13:55–14:06Z.

| # | command | result |
|---|---|---|
| 1 | `uname -a` | `Linux zabz-tech-linux 6.8.0-111-generic`, Ubuntu, x86_64 |
| 2 | `which node; node --version` | `/usr/local/bin/node` → symlink to `/home/zabz/.local/node/bin/node`, **v22.23.2** |
| 3 | `ls -l /home/zabz/.local/node-v24.12.0-linux-x64/bin/node` | **No such file or directory** (this is the path `plugin-remote-fanout/lib/nodes.js` records as `nodeExe`; `62-worker-runtime.md` §3.1 also describes the install that was never run in that exact form) |
| 4 | `ls -l /usr/local/bin/dsh` | the mesh-worker wrapper from `scripts/provision-mesh-node.sh` (**stream S2**): it resolves `$HOME/.local/node/bin/node` from a stable symlink, sources `/etc/dsh-worker.env` with `set -a`, then `exec "$node" "$bin" "$@"` |
| 5 | `dsh --version` | **0.1.5-rc.1** (exit 0) |
| 6 | `ls /home/zabz/.dsh/profiles/` | `headless`, `node_modules`, `web` — the profile tree exists, and `headless/package.json` lists `dsh-base` + `dsh-headless` |
| 7 | `dsh --profile headless "Reply with exactly: LINUX NODE OK"` | **`LINUX NODE OK`, exit 0, 3 s** (13:59:30Z→13:59:33Z) |
| 8 | the same via `/bin/sh -lc` and via `/bin/bash -c` | `SHLC OK` exit 0, `BASH OK` exit 0 |
| 9 | `/home/zabz/.local/node-v24.12.0-linux-x64/bin/node …/lib/bin.js --profile headless "<task>"` (the dispatcher's own shape) | **`timeout: failed to run command …: No such file or directory`, exit 127** |
| 10 | `/home/zabz/.local/node/bin/node …/lib/bin.js --profile headless "<task>"` (path corrected) | **`dsh: MISSING_CREDENTIAL: llm-deepseek: no API key for provider route "deepseek-official"`, exit 1** |
| 11 | `env \| grep -i deepseek`; `bash -lc`; `bash -c` | `DEEPSEEK_API_KEY` is **not** in the non-interactive ssh environment, not via a login shell and not via `bash -c` |
| 12 | `ls -l /etc/dsh-worker.env`; keys only, values redacted | `-rw-r----- 1 root zabz 108`; `DEEPSEEK_API_KEY`, `DEEPINFRA_API_KEY` |
| 13 | the same direct invocation with `/etc/dsh-worker.env` sourced | **`DIRECT WITH ENV OK`, exit 0** |
| 14 | `python3 -c` over `~/.dsh/.credentials.yaml` (keys only, values redacted) | `version`, `records`; the only record is `client-connection/browser-session`. **No model credential is stored there**, which is why row 10 fails when the wrapper is bypassed |
| 15 | `whoami; hostname` | `zabz` / `zabz-tech-linux` |

### 4.2 What that means, and what would change the flag

* **The machine is a working worker.** Rows 2, 5, 6, 7, 8, 13: it has a Node runtime, a DSH install,
  a `headless` profile, a populated credential file for the wrapper, and it **completes real
  headless child turns over its own sshd** — three different ways. The old roster note ("no Node
  runtime yet", inherited from `62-worker-runtime.md` §3.1) is **stale**, and so is the §10.4
  evidence string it was built on ("no Linux node has yet completed a child turn").
* **The dispatcher cannot use it as configured.** Rows 3, 9, 10, 11: `lib/nodes.js` → `nodeExe` does
  not exist, and its *shape* — an explicit `node` + `bin.js` pair, `remote-script.js:101` — is
  exactly what bypasses the wrapper that supplies `DEEPSEEK_API_KEY`. So `dispatch.v1: false` is not
  a claim that the box is weak; it is the answer to the question the flag asks, and a child the
  broker placed there today would fail.
* **What would have to change for `true`** — both of these, and neither is a file this session owns:
  1. `plugin-remote-fanout/lib/nodes.js` `zabz-tech-linux.nodeExe`: `/home/zabz/.local/node-v24.12.0-linux-x64/bin/node`
     → **`/home/zabz/.local/node/bin/node`** (the version-free symlink the machine's own wrapper uses,
     which is the point `62-worker-runtime.md` §3.2 makes: a version-stamped path is what rots);
  2. the credential must reach the dispatch process — either the dispatcher sources
     `/etc/dsh-worker.env` for a posix node, or that key is exported into the ssh session's
     environment. Row 13 shows the corrected path plus the env file is sufficient.
  The alternative that needs no dispatcher change is for the posix script to invoke the `dsh` wrapper
  **by name** (`dsh --profile headless <task>`) instead of an explicit interpreter+file pair — the
  wrapper is the machine's contract for "how a worker is launched here", and row 7 is that command.

**Reported, not fixed, and deliberately so:** `packages/plugin-remote-fanout/**` is outside this
session's ownership (`packages/mesh-broker/**` and this document only). Writing the fix here would
have been a change nobody authorised in a package with its own tests and its own deploy path.

### 4.3 The roster change, verbatim

`packages/mesh-broker/nodes.json`:

```json
"dispatch": {
  "v1": false,
  "measuredAt": "2026-09-17T14:00Z",
  "evidence": "MEASURED BROKEN FOR v1 AS THE DISPATCHER ACTUALLY DISPATCHES, … (1) The runtime is provisioned: node v22.23.2 … (2) `ssh linux-pc-ts dsh --profile headless \"Reply with exactly: LINUX NODE OK\"` COMPLETED exit 0 in 3 s at 13:59:33Z … (3) What FAILS is the invocation the dispatcher table records and actually runs … exit 127 … (4) AND EVEN WITH THE PATH CORRECTED … MISSING_CREDENTIAL … (5) … SET BACK TO true when the dispatcher table is corrected … and the credential is made to reach the dispatch process …"
}
```

The evidence string is long on purpose: `76-broker.md` §5 item 15's rule is that *a roster capability
is a dated measurement*, and `§10.4`'s lesson is that a stale `false` cost a whole node. The string
therefore names the commands, their results, the date, the stale note it corrects, and the two
conditions that restore `true`, so the next session re-measures instead of re-arguing.
`test/config.test.mjs` asserts the flag, the corrected-note marker and the restore condition, so the
roster and its own test cannot drift apart silently.

**Effect on placement:** with `zabz-tech-linux` at `v1: false`, the broker treats it as AMENDMENT 4
always did — ranked below every node that can take the work, chosen only when nothing else is
eligible, and then only as a `tier=transport` placement with `blockedBy: ["transport"]`, which the
provider sees as a queue rather than a start. Live proof that the broker now says so, from `§3`'s
run: `zabz-tech-linux: 4 free slot(s) of 24, …, transport v1 MEASURED BROKEN`.

---

## 5. The diffs

```
$ git diff --stat -- packages/mesh-broker
 packages/mesh-broker/lib/broker.js            | 122 +++++++++++++++++++-------
 packages/mesh-broker/nodes.json               |   6 +-
 packages/mesh-broker/test/acceptance.test.mjs |  94 ++++++++++++++++++++++
 packages/mesh-broker/test/config.test.mjs     |   8 +-
 4 files changed, 196 insertions(+), 34 deletions(-)
```

* **`lib/broker.js`** — the tier ladder: `preferred`/`usable`/`withSlow` removed, the pool is the
  dispatchable set, `highest-slots` uses the whole dispatchable set, the `fits` tier is ranked by
  `compareFallback` (which gained the `fits now` term and now orders `NOT slow` above it),
  `classificationLine()` added and printed for the chosen node on every placement, the
  `highest-slots` tier line names `SLOW` when it applies, the `slow` tier case is documented as a
  compatibility case, and the file header gains the one-paragraph record of the defect.
* **`test/acceptance.test.mjs`** — the new `REQUIREMENT 3b` test (`§2.4`), run against the defect as
  well as the fix.
* **`nodes.json`** — the `zabz-tech-linux` `dispatch` block (`§4.3`).
* **`test/config.test.mjs`** — the assertion that follows the roster flag, with the reason.

The complete diff is in the tree (`git diff -- packages/mesh-broker`); it is not reproduced line by
line here because the bullets above are the change and `§6` is the proof.

---

## 6. Verification: every claim, its command, its result

| claim | command | result (MEASURED, 2026-09-17) |
|---|---|---|
| every source file parses | `cd packages/mesh-broker && npm run verify` | exit 0 |
| the package's own suite passes, with the new test | `npm test` | **tests 61 · pass 61 · fail 0** (was 60 before this session; `duration_ms 5006`) |
| the new test fails on the shipped code | restore `preferred = dispatchable.filter(c => !c.slow)` and re-run it | **pass 0 · fail 1**, `actual: 'zabz-tech'`, `expected: 'zabz-yoga-1'` (`§2.4`) |
| the shipped and fixed brokers differ on the same nodes | `node _scratch/mesh-98-side-by-side.mjs` (shipped code from `git show HEAD:…`) | shipped `node=zabz-tech position=1 tier=highest-slots`; fixed `node=zabz-yoga-1 position=0 tier=fits`; **PASS** (`§2.5`) |
| the copy that was deployed is the code that was tested | local sha256 of all 22 files vs `sha256sum` on the staged tree | **22/22 identical**; and for the final build, `lib/broker.js` `7f8b6371…` on both sides |
| the deployed tree runs its own tests | `deploy/install-authority.sh` step 3 | `the deployed copy passes its own suite: # tests 61 # pass 61 # fail 0` |
| the service is installed, enabled, active and loopback-only | `deploy/install-authority.sh /tmp/mesh-broker-stage2` at 14:11Z (the final build) | **20 passed, 0 failed**; `bound to 127.0.0.1 only`; LAN `192.168.50.77` → `curl exit 7`; tailnet `100.84.72.88` → `curl exit 7`; `tailscale serve` publishes nothing on 3091 |
| the running process is the deployed copy and nothing else holds the port | `deploy/verify-deploy.sh /tmp/mesh-broker-stage2` | `NO DRIFT: the deployed tree, the installed unit and the running process all agree` |
| it survives a supervised restart and a SIGKILL | installer step 9, both installs | 14:05Z: `MainPID 2304821 → 2304920` (restart) → `2304940` (SIGKILL); 14:11Z: `2308723 → 2308860` → `2308879`; `service active`, answers after both |
| a real `POST /place` over ssh shows the new rationale and a correct placement | Node probe piped to `ssh secratary-ts node …` (`§3`) | HTTP 200 at 14:08:02.058Z, `node=zabz-tech position=0 score=18 tier=fits eligible=3`, `classification=ok` in the rationale, `/done released=true`, `leases.live=0`; and at 14:11:55.791Z the same shape with the laptop's `SLOW` line in the same rationale |
| every node reports its transport capability | `GET /nodes?fresh=1` on the authority | `zabz-tech ok 18 true(2026-09-16)`, `zabz-yoga-1 ok 12 true(2026-09-16)`, `zabz-tech-linux ok 4 **false**(2026-09-17T14:00Z)`, `secratary ok 3 null` — `reads=12 readFailures=0` |
| the linux node takes a real v1 child turn | `ssh linux-pc-ts dsh --profile headless "Reply with exactly: LINUX NODE OK"` | `LINUX NODE OK`, **exit 0**, 3 s (`§4.1` row 7) |
| the dispatcher's own invocation of that node fails | `/home/zabz/.local/node-v24.12.0-linux-x64/bin/node …/bin.js --profile headless '<task>'` | exit **127**; and with the path corrected, `MISSING_CREDENTIAL`, exit 1 (`§4.1` rows 9–10) |
| the owner's engine was never touched | `Get-Process -Id 4880` before and after | same pid, same start time `2026-09-17 08:51:07`, alive at the end of the session |
| nothing was left holding a slot | `GET /healthz` after the last placement | `leases.live=0` |
| nothing of mine was left on the authority | `rm -rf /tmp/mesh-broker-stage*`, `/tmp/mesh-98-live-probe.mjs` | both gone; `/home/zabz/mesh-broker/lib/broker.js` untouched by the cleanup, service `active` |

---

## 7. What could not be verified, stated as refusals

* **A live placement *onto* a `slow` node while a fast node was also in play.** The live half of `§3`
  does now include the laptop reading `SLOW` at 14:11:55.791Z inside a placement that correctly went
  to the desktop, and a laptop-as-sole-candidate `fits` placement. What was not observed live is the
  decisive case — a fast node with **no room** and a slow node with room — because on today's numbers
  that combination does not arise: the desktop's 18 slots exceed the laptop's 12, so every job the
  laptop can take, the desktop can take too, and the roomiest node wins on rank. That case is proven
  by `§2.4` (the suite, run against both code states) and `§2.5` (shipped vs fixed, same stubs), and
  `92` §5.2's 13:17Z eight-child measurement is the record that it occurs in the field.
* **A full dispatch through the new shipped provider config.** The provider's own config change from
  `92` §8 is *inert until the engine restarts* (`profiles/web/cordis.patch.yml` was installed, the
  running engine pid 4880 loads the previous layer). So a real child running end to end with the
  broker's answer **and** the new `nodes.js` delivery has not been observed on this laptop, and
  restarting the engine is the owner's decision to schedule. The provider-side facts are unchanged
  by this session: `92` §5.6's resident-engine proof stands, and nothing in this session touched
  `plugin-remote-fanout`.
* **The dispatcher-table fix itself** (`nodeExe` → `/home/zabz/.local/node/bin/node`, plus the
  credential reaching the dispatch process). Measured, designed and written down (`§4.2`), **not
  applied**: `packages/plugin-remote-fanout/**` is outside this session's ownership.
* **`secratary`'s v1 transport** stays `null`. It was not re-measured this session: the brief named
  the linux node, and the authority's `dispatch.v1: null` is a live, honest "never measured" that
  changing without a measurement would falsify.
* **Whether the `slow` state recurs often enough to matter after this fix.** `92` §5.2 measured
  `ok`/`slow`/`ok` at 13:17Z; this session caught `slow` inside one placement at 14:11:55.791Z and
  `ok` two seconds later, and four `ok` in a row at 14:08Z. One session cannot say how often a gate
  misses the 1500 ms deadline, and the two-readings-per-re-read cost of `slow` (1500 + 4000 ms worst
  case per node) is unchanged by this work.
* **The laptop's tailnet path degradation at 14:23Z** (`§3.1`). Measured, not diagnosed and not
  touched: `ssh`/`tailscale` reach the laptop from the authority, the gate answers 200 in 254 ms
  when reached, `tailscale ping` falls back to DERP with *"direct connection not established"*, and
  the broker's two-attempt read then fails the 1500 + 4000 ms budget while three `/nodes?fresh=1`
  reads 15 s apart flip `unreachable` → `slow` → `slow`. Whether that is the home link, the relay,
  or the laptop's own tailscaled is beyond this session's scope (`packages/mesh-broker/**`), and it
  is the third distinct cause of a node getting no work.

---

## 8. What the next session should know

1. **A `slow` node is a candidate now, and `tier=slow` is no longer produced.** Do not re-add a
   `!c.slow` filter to any pool: `76-broker.md` §10.8 and `71` §2.2 both say *ranked below*, and the
   ranking is `compareFallback` — `reachable` → `can take v1 work` → `NOT slow` → `fits now` →
   slots → load → roster order. The new test's name is the contract.
2. **`zabz-tech-linux` is `v1: false`, and THAT IS A DISPATCHER DEFECT, NOT A NODE DEFECT.** The
   machine completed `LINUX NODE OK` exit 0 over its sshd. Before re-flagging it `true`, fix
   `plugin-remote-fanout/lib/nodes.js` (`nodeExe` → `/home/zabz/.local/node/bin/node`) **and** make
   the credential reach the dispatch process (`/etc/dsh-worker.env`, or invoke the `dsh` wrapper by
   name). `§4` has every command and result.
3. **The live mesh cannot demonstrate defect 1 on an ordinary request**, because the desktop's 18
   slots exceed the laptop's 12 and every job the laptop fits, the desktop fits too. To reproduce
   the fault or its fix, use a job **bigger than the fast node** — `92` §5.2's eight-child wave or
   the stub shape in `test/acceptance.test.mjs`'s `REQUIREMENT 3b`.
4. **The `dispatch` flag is the only lever this roster has for "a child here would die".** With it
   `false`, a placement there is a `tier=transport` queue with `blockedBy: ["transport"]` and the
   provider does not start a child. That is the safe state until the dispatcher is fixed.
5. **The service is installed at `/home/zabz/mesh-broker`, unit `mesh-broker`, loopback
   `127.0.0.1:3091`; deploy with `deploy/install-authority.sh <staged-tree>` and check with
   `deploy/verify-deploy.sh <staged-tree>`.** Both are idempotent, and step 3 of the installer runs
   the deployed copy's own suite, which is what stops a stale copy from passing silently.
