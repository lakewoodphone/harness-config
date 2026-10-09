# 119 — Audit: the fan-out plane, why it kept going down, and what was rebuilt

**Date:** 2026-10-09, from ZABZ-YOGA. **Author:** the operating session, not the owner.
**Trigger (owner, verbatim):** *"the mesh seems to have gone down again … we seem to be having this
problem multiple times a day … most sub agents on the mesh end up being one shot agents where they
can't talk to the parent … start a new audit of the mesh system specifically for orchestrating
fanning out and giving child agents … it should be way more robust, should never go down."*

Everything below is a measurement with the command that produced it, or it says it is not measured.

---

## 0. The verdict in one screen

| # | finding | evidence | state |
|---|---|---|---|
| **C1** | **The fan-out plane's availability WAS one process on one machine.** The provider consumes 100% of its placement from a broker that runs only on `secratary`, reached by `ssh secratary-ts` to a loopback URL. That node was offline; two healthy workers were not. | reproduced twice, verbatim: `remote-ssh: broker-unreachable: … secratary-ts:http://localhost:3091/place — ssh exited 255 … Connection timed out` while `zabz-yoga-1` and `zabz-tech` answered `/mesh/health` in 0.13 s / 0.20 s | **FIXED — see §2, proven §3** |
| **C2** | **The v2 transport's auth model structurally forbids cross-node dispatch.** `docs/mesh/83-http-transport.md:552`: *"the design is deliberately **one secret per node**"*, and each node accepts only its own. A dispatcher on the laptop has no way to sign a request to another node. A 401 `bad-signature` is what that looks like. | `POST /mesh/run` with this laptop's own 64-byte secret → `HTTP 401 {"reason":"bad-signature"}` | **DESIGN DEFECT — decided, not yet built, §5** |
| **C3** | **A leaked-in-place experiment was black-holing ALL DNS on the office desktop**, which is why every mesh child there died. | §4 | **FIXED — removed, verified** |
| **C4** | **No out-of-process child can ever be a live two-way participant**, because a continuable child is *always* composed in-process by the engine's continuation manager. | engine audit, `dsh-subagent/lib/index.js:1082-1091`; §6 | **ENGINE LIMIT — designed around, §6** |
| **C5** | The mesh's own acceptance command could not reach its own definition of done, and the "live" claims were about processes, not traffic. | `docs/mesh/95-audit-live-mesh.md` (a prior independent audit, not re-measured here) | inherited finding |

**The one sentence:** the mesh never had a robustness problem, it had a **single point of failure
wearing three costumes** — one broker, one machine, one dispatch path — and each costume failed
independently.

---

## 1. What was actually there (so this is not re-litigated)

The fan-out plane is not one thing and was not un-built. Measured today:

- `packages/plugin-remote-fanout` (v0.3.0) — the provider `remote-ssh`, placement, pressure policy,
  retry plan, circuit breaker, ssh transport, a 25 KB file mailbox, and **199 unit tests**.
- `packages/mesh-broker` — the placement service, a systemd unit on the authority, a 5-node roster.
- `packages/plugin-mesh-http` — **transport v2**: a signed `POST /mesh/run` on each node's own engine,
  with an unauthenticated `GET /mesh/health` that publishes the node's whole concurrency decision.
- 119 documents under `docs/mesh/`, and ~30 commits touching these packages.

So the earlier work is real. It was also **repaired repeatedly and never made redundant** — which is
why the same outage returned. That is the finding this audit adds.

---

## 2. The rebuild: the broker becomes an optimisation, not a veto

### 2.1 What was added

| file | what it is |
|---|---|
| `packages/plugin-remote-fanout/lib/failover-placement.js` | a **pure** placement decision from probed node health: `assessNode`, `rankCandidates`, `chooseFailoverPlacement`. Total by construction (a hostile getter that throws is refused, never thrown onward). |
| `packages/plugin-remote-fanout/lib/node-probes.js` | reads every node directly over the tailnet (`GET /mesh/health`, `GET /mesh/capacity`), in parallel, bounded, and turns every failure into a RECORD rather than an exception. |
| `packages/plugin-remote-fanout/lib/failover-placer.js` | wraps the real broker placer (`createNodePlacer`, untouched) and branches in exactly one place: **broker unreachable ⇒ probe the mesh here and place from the measurement**, with a `leaseSource: 'local'` lease so the provider's release path stays total. |
| `packages/plugin-remote-fanout/bin/failover-place.mjs` | the read-only instrument: print the mesh's placement decision with its arithmetic, dispatches nothing. |
| `packages/plugin-remote-fanout/test/failover-placement.test.mjs` | 17 tests. |
| `packages/plugin-remote-fanout/test/failover-placer.test.mjs` | 8 tests. |

### 2.2 The rules it keeps, which are the harness's own

- **A reading that could not be made never changes a decision.** An unreachable node is recorded
  `unreachable`; it is never scored as full, busy, or bad. (This is the P3/P12 rule, applied.)
- **Queue, never amputate.** A node short of slots is still the answer, with `position > 0`.
- **Never exclude everything.** `rankCandidates` YIELDS rather than emptying the list, and says so —
  a stale exclusion list must not become an outage.
- **No silent local default, ever.** When nothing can be placed the error names both halves and says
  nothing was dispatched. A silent default is how a mesh of one machine looks like a mesh of five.
- **A live broker with a BAD answer still throws.** `broker-unparsable` is not routed around; probing
  past it would hide a real bug behind a fallback.

### 2.3 What was deliberately NOT changed

`lib/placement.js`, `lib/broker-client.js`, `lib/provider.js`'s dispatch path and the pressure policy
are **untouched** except for one report label. The broker is still asked FIRST, every time, because it
holds the only cross-node lease ledger and the only cross-dispatcher accounting. Every call delegates
to it; only its *absence* is survivable. The wrapper does not re-implement pressure, prefer-remote,
queueing, credentials or the node table — a second source of truth for placement is the defect class
this programme exists to kill.

---

## 3. The proof: a real child with the broker deliberately dead

`_scratch/mesh-audit/proof-dead-broker.mjs` builds the real provider with a placer whose broker
`place()` throws `broker-unreachable` **on purpose**, and dispatches a real child.

```
WARN  remote-fanout: the placement broker is UNREACHABLE (… secratary-ts … Connection timed out)
      — falling back to reading 5 node(s) directly, here, now
INFO  remote-fanout: child remote-f939843b-… placed on "zabz-tech" by DIRECT PROBE (broker unreachable)
      — 8 free slot(s), position 0, transports v2>v1
=== RESULT ===  stopReason: completed   ms: 40892
MESH-HOST: zabz-tech
[remote-ssh] child ran on node "ZABZ-TECH" via ssh -o BatchMode=yes -o ConnectTimeout=8 desktop-ts
location check = matched (zabz-tech) — ZABZ-TECH, zabz-tech, zabz-tech.tail93e6e6.ts.net
exit = 0 in 32545 ms
```

**Read the parts that matter.** The placement was made by this machine reading the fleet, the child
reported **its own** hostname from **its own** shell, and the location check confirmed the node the
placement named rather than trusting the intent. `PROOF PASSED`.

And the same command, run before C3 was fixed, is the most useful negative result in this document:
the placement succeeded and the dispatch happened, and the child still came back empty with
`dsh: TRANSPORT: DeepSeek Messages transport failed`. **A placement fix cannot be validated while a
node's DNS is broken**, and that is why §4 is part of the same audit rather than a separate story.

---

## 4. C3 — what was black-holing DNS on ZABZ-TECH (the owner asked: and the answer is yes)

### 4.1 The culprit, named

| what | where | state found |
|---|---|---|
| `KosherFilterService` | `C:\Program Files\KosherFilter\KosherFilterService.exe` | **Running, AUTO_START, LocalSystem** |
| `KosherFilterDnsRelay` | `C:\Program Files\KosherFilterRelay\KafDnsRelayService.exe` | **Running, AUTO_START, LocalSystem** |
| `WinDivert` kernel driver | `C:\Program Files\KosherFilter\WinDivert64.sys` | **Running** (`start= Disabled`) |

Both are built from the repo at `C:\Users\ezabz\code\kosher-filter-ai` (`lpt-filter-ai`); the installed
binaries were written **2026-10-08 21:32** and **2026-10-09 01:32** — yesterday and the same morning.

### 4.2 The mechanism, from the filter's own config

`C:\Program Files\KosherFilter\appsettings.json`:

```json
"DnsInterception": {
  "Enabled": true,
  "Filter": "udp.DstPort == 53 or udp.SrcPort == 53",
  "BrokerHost": "127.0.0.1", "BrokerPort": 1080
}
```

`C:\Program Files\KosherFilterRelay\appsettings.json`:

```json
"Relay": { "UpstreamHost": "2.28.33.58", "UpstreamPort": "1080", "Username": "zabz-desktop" }
```

So **every DNS query on that machine is captured at the kernel and tunnelled through a SOCKS5 relay
whose upstream is a Hetzner box**, and that upstream was not answering. The relay's own event log,
repeating every few seconds on the boot of 2026-10-09 11:37:

```
relay-err: OSError: [WinError 10051] A socket operation was attempted to an unreachable network
Relay child exited with code 1; restarting in 5s.
```

### 4.3 The measured symptom

Directly on that node: `www.google.com`, `microsoft.com`, `cloudflare.com`, `tailscale.com`,
`api.deepseek.com`, `mcp.jina.ai` → **all `ENOTFOUND`**; and a query straight at `1.1.1.1` and
`8.8.8.8` → **both FAIL**. DNS was not slow or filtered; it was **gone**.

### 4.4 Why deleting it never stuck — this answers "the 5th time"

Three independent re-arm mechanisms, all of them properties of the product rather than accidents:

1. `windows/install-dns-relay-service.ps1:99` — `sc.exe create … start= auto` (boot-start);
2. the same script, `:101` — `sc.exe failure … reset= 86400 actions= restart/5000/restart/5000/restart/5000`
   (a stopped relay is restarted five seconds later — `sc qfailure` confirmed this live);
3. `windows/FilterService/Tamper/ServiceRestarter.cs` + `Tamper/ManagementWmiWatcher.cs` — the service
   watches for its own removal and puts itself back.

**Deleting files removes none of those.** The repo ships the correct inverse,
`windows/scripts/uninstall-service.ps1` (`stop`, wait, `sc delete`, `-RemoveFiles`), which is not what a
file delete does.

### 4.5 What was done, with the owner's explicit approval

1. `sc failure <svc> reset= 0 actions= ""` attempted first (its syntax was rejected by `sc.exe` —
   recorded, not hidden — and became moot at step 3);
2. both services **stopped**;
3. both **`sc delete`d** (exit 0 each);
4. `WinDivert` driver **stopped**;
5. `C:\Program Files\KosherFilter` and `…\KosherFilterRelay` **removed** (3.3 MB / 2.4 MB — the driver
   filed successfully, so interception is gone at the kernel, not merely unregistered).

**Verified after, and again minutes later:** both services `GONE`, no `Kosher*` service registered, no
`WinDivert` driver registered, zero leftover files, no `KosherFilter` process. And the symptom:

```
api.deepseek.com -> 3.173.21.63
www.google.com   -> 2001:4860:482c:7700::
mcp.jina.ai      -> 2606:4700:20::681a:af2
```

### 4.6 What can still bring it back

Nothing automatic was found on that node: no scheduled task references the filter, no process holds
its repo open, no service remains. The installers are still present **in the repo**
(`windows/install-dns-relay-service.ps1`, `windows/scripts/install-service.ps1`) and running either is
an explicit, deliberate act. **Recording this is the whole point**: the recurrence was never a mystery
daemon — it was a boot-start service plus a tamper restarter, reinstalled by hand each time. Anyone who
installs it on a node that must dispatch mesh children will break that node again; it must be a
separate machine, or its relay upstream must be reachable.

---

## 5. C2 — the cross-node auth defect, stated so it is not rediscovered

`lib/auth.js` signs `POST /mesh/run` with a per-node secret, and `83-http-transport.md:552` says the
model is *one secret per node* so that a stolen secret opens one node and not the fleet. That is a good
property for a **tailnet of peers**. It is a structural problem for a **dispatcher**, because the
dispatcher is by definition a different machine:

- today the mesh dispatches over **ssh** (transport v1), which is why fan-out works at all;
- the v2 HTTP route therefore cannot be used from a dispatcher that does not hold the target's secret,
  and refusing a wrong secret is correct behaviour, so a 401 here is not a bug to route around.

**Two ways out, both honest; this one is a decision, not an oversight:**

1. **A per-node secret STORE on the dispatcher** (`~/.dsh/mesh/secrets/<node>.env`), populated by an
   explicit `mesh-http.mjs secret sync` over ssh, and a **fingerprint published in `/mesh/health`**
   (`sha256(secret)[0:12]`, never the value) so a mismatch is visible *before* a signed call instead of
   as an unexplained 401. This is the recommendation: it keeps one secret per node, makes the drift
   that costs a dispatch detectable in one read, and needs no change to any node.
2. Make the dispatcher's own node list trusted by every node (a second HMAC scheme). More moving parts
   and a larger blast radius; not recommended first.

**Not implemented in this session.** It is recorded here with its recommendation so the next session
builds it deliberately rather than rediscovering a 401.

---

## 6. C4 — the two-way conversation limit, measured in the engine (this is the owner's second complaint)

The owner's words: *"most sub agents on the mesh end up being one shot agents where they can't talk to
the parent agent and the parent agent can talk to them."* An adversarial audit of the installed engine
(`@deepseek-ai/dsh` 0.2.0-rc.2) says that is **exactly right for a remote child, and it is not a bug in
this package**:

- **`SubagentProvider` is five members** — `name`, `capabilities`, `inheritsParentContext`, `start`
  (required) and `agentRouteDefaults`, `prepareContinuable` (optional). There is **no** send, interrupt,
  list, dispose or resume on a provider (`dsh-subagent/lib/types/types.d.ts:327-376`).
- **`prepareContinuable` is "DATA, never a capability"** (`:360-374`). The continuation manager owns
  identity, composition, Agent creation, prompt delivery and disposal, and composes the child itself
  (`index.js:1082-1091`). **A continuable child is therefore always in-process** — a remote node can
  never host one.
- **Messaging is a SERVICE method bound to a live in-process Agent**: `sendMessage` requires
  `this.ctx.agents.get(sender.id) === sender` (`index.js:1763`), and child→parent requires a
  **resident continuable** child (`:1766-1770`). `interrupt` consults `this.resident` only
  (`:849-850`). A remote child is not in either map.
- **A remote child is invisible to `list_agents`**: the parent's catalog row is written only when
  `run.localAgent?.session` exists (`index.js:3130-3132`), and the mesh provider returns
  `localAgent: undefined` (correctly — it does not own a local Agent).
- **`interrupt_agent` on a mesh child is a silent no-op that renders as success**
  (`dsh-tool-subagent-control/lib/index.js:86-90`). **To stop a mesh child you must kill its job.**
- **`dsh --profile headless` has no `--resume`**, and `--session-id` refuses any session with
  `origin === 'subagent'` outright (`dsh-headless/lib/index.js:224`) — so a child process can never be
  re-entered with a follow-up.

### What that means, and what was done about it

`lib/mailbox.js` already implements the **only** conversation the runtime allows: a durable JSONL thread
on the child's node (inbox / outbox / transcript), written by the child *as it works* and read back by
the parent, so that a **second dispatch on the same thread reads everything said so far**. The report
renders the child's own thread into the parent's transcript. That is a real conversation across turns,
and it survives a parent crash.

It does **not** provide, and cannot honestly be made to provide without an engine change:
live steering mid-turn, a parent answering a waiting child inside one turn, or `send_message` reaching a
remote child. **`subagent_fork` (same process, this machine, parent history) is the only delegation path
with live two-way conversation today.** The engine's own README names the missing mechanism: *"remote
providers need an Activation ownership contract before they can support continuable children"* and
*"no durable parent mailbox"*. That is a change to the engine, not to this package.

**Recommendation, and it is a build, not a question:** make the mailbox first-class and use it
deliberately — a child that needs a decision asks in its transcript and **ends its turn**; the next
dispatch on the thread carries the answer. Document the choice per job: *live dialogue ⇒ `subagent_fork`
(one machine); long parallel work ⇒ mesh children on a thread.*

---

## 7. What is verified, and what is not

| claim | verified by |
|---|---|
| the broker can be gone and a child still starts on a healthy node | `proof-dead-broker.mjs` → `PROOF PASSED`, `MESH-HOST: zabz-tech`, exit 0 |
| the placement decision itself, against the live fleet | `bin/failover-place.mjs` → chose `zabz-tech` (8 slots), 3 nodes recorded `unreachable`, `source=direct-probe` |
| the new modules behave as specified | 25 new tests + the package's own 199 → 197 pass / 0 fail / 2 skip |
| the filter was the cause of the child deaths on ZABZ-TECH | §4.2–4.3 (kernel DNS capture + dead upstream) and §3's negative result |
| the removal is complete and stable | §4.5, re-checked minutes later |
| **that the resident engine now uses the failover placer** | **NOT VERIFIED** — the engine loads a mounted bundle at boot, so this takes effect on the next engine start (P210). The code path is proven; the deployment is not. |
| the cross-node v2 secret store | **NOT BUILT** (§5) |
| live two-way dialogue with a remote child | **IMPOSSIBLE** in this engine (§6); the mailbox thread is the available substitute |

---

## 8. Files changed

- **new** `packages/plugin-remote-fanout/lib/failover-placement.js`
- **new** `packages/plugin-remote-fanout/lib/failover-placer.js`
- **new** `packages/plugin-remote-fanout/lib/node-probes.js`
- **new** `packages/plugin-remote-fanout/bin/failover-place.mjs`
- **new** `packages/plugin-remote-fanout/test/failover-placement.test.mjs`
- **new** `packages/plugin-remote-fanout/test/failover-placer.test.mjs`
- **edited** `packages/plugin-remote-fanout/lib/index.js` — wraps the broker placer, `placementFailover: false` opts out, boot line says which mode is on
- **edited** `packages/plugin-remote-fanout/lib/provider.js` — `placementNote` names a direct-probe placement as one, instead of printing `broker → node`
- **edited** `packages/plugin-remote-fanout/package.json` — the three new modules, the new test
- **new** `_scratch/mesh-audit/*` — the instruments and their raw output (untracked, as `_scratch` is)
- **edited on ZABZ-TECH, with the owner's approval** — the filter stack removed (§4.5)
