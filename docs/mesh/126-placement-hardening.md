# 126 — Placement hardening (idempotency, retry, honest errors, ranking)

Lane: **PLACEMENT** (`agent/p2broker`), base `87bd0e7`. Owner of the files listed in the brief
and nothing else. Everything below was measured or run on `zabz-tech`.

The measured defect (provider placement ledger, `~/.dsh/mesh/placements`, 70 placements in the
48 h to 2026-09-29: 16 completed, 33 error, 11 never placed, 2 aborted — 23 %) has two halves
owned here: **11 `broker-unreachable` with no retry anywhere**, and a **ranking that demoted a
healthy cold-start-missed node below a nearly-full one**. This document records what changed.

## I1 — requestId idempotency (`packages/mesh-broker/lib/broker.js`)

Wire shape (documented, tested):

```json
POST /place
{ "task": { "kind": "oneShot"|"fleet", "children": 6, "worktreeGiB": 2,
            "prefer": "home"|"office"|null, "exclude": ["node"] },
  "requestId": "<optional opaque string, <= 200 chars>" }
```

* The response echoes `requestId`. A **repeat of the same requestId** returns the identical
  `node` and `lease` and adds `"idempotentReplay": true`, `"replayedAt"`, and one rationale line
  (`... NO second lease was issued ...`). No lease is issued on a replay.
* Two **different** requestIds still produce two leases (tested).
* Two concurrent calls with one requestId share one in-flight promise, so a race cannot issue
  two leases either.
* `requestId` is optional: a body without one behaves exactly as before.
* **TTL: `REQUEST_ID_TTL_MS = 300_000` (5 min)**, a named export. Why: the client bounds one
  place call at 3 attempts × a 30 s ssh timeout + a few seconds of backoff (~95 s worst case),
  so 300 s is >3× that; and 300 s is exactly ⅓ of the 900 s lease TTL, so a replay always names
  a lease still ≥⅔ of its TTL from expiry — a replay can never hand back a lease that was
  already reclaimed. The map is bounded at `MAX_REQUEST_ID_ENTRIES = 256` (oldest evicted).
* `GET /healthz` and `GET /nodes` expose `requestIds: { cached, ttlSec, maxEntries, replayed }`.
* `config.js` now carries `requestIdTtlMs` (default `300000`).

## I2/I3 — bounded retry and honest error classes (`packages/plugin-remote-fanout/lib/broker-client.js`)

Four codes replace the one blur. `broker-unreachable` is kept **only** for "could not be
reached at all":

| code | meaning | retried? |
| --- | --- | --- |
| `broker-unreachable` | ssh refused / DNS / route failure / client would not launch — the request did NOT land | yes |
| `broker-timeout` | reached, no answer in the bound — **the request MAY have landed (a lease may exist)** | yes |
| `broker-unparsable` | answered, body is not JSON or not a placement | yes (except a local single-quote refusal, which can never succeed) |
| `broker-error` | answered HTTP 4xx/5xx | 5xx yes, 4xx no |

**Every message ends with the accounting**: `[retried with a short jittered backoff: N of M
attempt(s) were made]` or `[not retried: 1 attempt was made ...]`. A 4xx and a well-formed
local refusal are never retried. `place()` and `nodes()` are retried; `done()` and `healthz()`
are single-attempt. Defaults: `attempts=3`, `retryBaseMs=250`, `retryCapMs=4000`, jitter 0.5–1.0×,
backoff doubling. **One `place()` call reuses ONE `requestId` across all attempts**, so a retry
after a lost answer cannot issue a second lease. `curl -w "\n%{http_code}"` gave the status;
a body with no status suffix still parses.

`placement.js` now keys the first ask on the child id itself (`requestId: id`) and the
prefer-remote re-ask on `id:prefer-remote`, so a caller-level retry of one child is idempotent
while the policy's genuinely different second ask is a different request. The ledger records
`requestId`.

## I4 — a cold-start latency miss is not a demotion

Read what already existed first: `capacity.js` already retries a timed-out read exactly once at
`retryTimeoutMs`, and `broker.js` already carried `retried` / `retryWasFast`. The defect was not
a missing retry — it was that **any** retried read was ranked below a fast one, including the
measured 1732–1887 ms cold first read of a healthy Windows node against the 1500 ms deadline,
which the retry fixes in ~120 ms. So: `coldMiss = state==='slow' && retryWasFast` keeps **full
rank**; only a read **still slow on the second attempt** (`rankSlow`) is a ranking penalty.
`state` stays `slow` and the miss is still printed (the miss is not hidden, it stops being a
demotion). This fixes the recorded rationale where `zabz-tech` (10 free slots, transport
measured working) lost to `secratary` (1 free slot, swap 100 %, transport unmeasured).

## I5 — unmeasured transport loses to measured-working

`compareFallback` now ranks the three transport facts `true (2) > null (1) > false (0)` instead
of collapsing `true` and `null` into one `dispatchOk`. An unmeasured node is not refused, but it
loses on transport unless capacity makes it the only option (the tier ladder already removes a
node that cannot take the work). The rationale states the rule in the transport line.

## I6 — per-node fleet concurrency cap

`FLEET_CONCURRENT_LEASE_CAP = 4` (`scoring.js`), the measured P2538b pain threshold. Effective
cap per node is `fleetLeaseCap(accepts.maxChildren, cap)` = `min(cap, declared max)` — a node
that declares a smaller `maxChildren` is obeyed, one that declares a larger one cannot raise the
cap, because `maxChildren` is a memory budget, not a measure of what an sshd survives. The
broker counts its own live `kind==='fleet'` leases on the node; over the cap the node leaves the
*fleet-eligible* pool but stays in the arena, so the placement is **queued, never refused**, with
`blockedBy: ['fleet-cap']` and a `fleet concurrency cap: ...` rationale line. `config.js` carries
`fleetConcurrentLeaseCap` (default `4`).

## I7 — the local machine

The caller's preference is expressed as `task.exclude` (`placement.js` sends the local node when
pressure says to route away, and the prefer-remote policy re-asks with it). The broker honoured
it in the eligible pools but **not in the `queued` arena fallback**, where `exclude` was never a
ranking term — so an excluded local node with more slots could win over an allowed remote node.
`compareFallback` now ranks a caller-excluded node below a non-excluded one (after `fits`, so
capacity still wins when the allowed node cannot take the work). When the local node is the only
eligible one, `placement.js` records precisely why the preference was not honoured
(`preferRemoteNote`), and when the broker names it anyway the `pressureConflict` /
`supersededLease` lines say so.

## Findings outside this lane's file scope (not edited)

* `packages/mesh-broker/bin/mesh-broker.mjs` builds `createBroker({ nodes, cacheTtlMs,
  readTimeoutMs, leaseTtlMs })` explicitly and does **not** spread the roster, so the new
  `retryTimeoutMs` / `requestIdTtlMs` / `fleetConcurrentLeaseCap` roster keys are reported and
  testable but the deployed binary applies the code defaults. Threading them is a one-line
  change in a file this lane does not own.
* `packages/plugin-remote-fanout/lib/provider.js` / `lib/index.js` own whether `preferRemote` is
  turned on and how the placer is constructed; not touched.
* `docs/mesh/71-mesh-program.md` §2.2 and `docs/mesh/76-broker.md` still describe the old
  one-code client and the slow-node demotion; they are not in this lane's scope and should be
  reconciled by the docs owner.

## Tests, and the before/after evidence

Required suites (all pass):
`node --test test/broker-client.test.mjs test/placement.test.mjs` → 31 pass / 0 fail;
`node --test test/scoring.test.mjs test/config.test.mjs` → 33 pass / 0 fail;
`node --test test/leases.test.mjs test/acceptance.test.mjs` → 34 pass / 0 fail (unchanged).

Every new guard was run against the **unmodified** lib files (only the five lib files stashed;
tests kept) and then with the fix:

```
BEFORE  ✖ I1 the same requestId twice returns the SAME lease ...          AFTER  ✔
BEFORE  ✖ I2 a transient transport failure is retried ...                 AFTER  ✔
BEFORE  ✖ I3 a timeout and a refusal produce DIFFERENT codes ...          AFTER  ✔
BEFORE  ✖ I4 a node that missed the read deadline ...                     AFTER  ✔
BEFORE  ✖ I5 an unmeasured-transport node loses to a measured-working ... AFTER  ✔
BEFORE  ✖ I6 the per-node fleet cap blocks another fleet ...              AFTER  ✔
BEFORE  ✖ I7 a caller-excluded node ranks below ...                       AFTER  ✔
BEFORE  ✖ I1 acquire() keys the broker request on the child id ...        AFTER  ✔
BEFORE  ✖ I2 a 5xx is retried ... / ✖ I2 nodes() is retried ...          AFTER  ✔
```
The config guard (`I1/I6 the roster carries ...`) could not fail as an assertion before, because
it imports exports that do not exist on the unfixed tree — it fails as a module-load error there
and passes with the fix. `config.test.mjs`'s stale "names four nodes" assertion (the roster has
five since `lakewooechsmini` was added) was repaired, not worked around.

## Deliberately NOT done / not verified

* No live mesh, no broker over the network, no port bound by any new test (injected readers and
  spawn doubles only). The pre-existing acceptance suite does bind `127.0.0.1:0`, as it always did.
* `packages/plugin-remote-fanout/lib/provider.js`, `lib/index.js`, `lib/remote-script.js`,
  `lib/ssh-transport.js`, `presets/`, `profiles/` and the broker's `bin/` were not edited.
* The `curl -w` status suffix was not exercised against the real authority curl; it is covered by
  spawn doubles. A real end-to-end run against `secratary` remains unverified here.
* Whether 4 is the right fleet cap on every node is a P2538b-derived first cut, not a calibration.
