# 88 — The elastic tier, designed against the real API

**Stream:** O7 of the overnight program (`docs/mesh/81-overnight-program.md` §1 row O7).
**Implements:** `docs/mesh/79-elastic-cloud.md` (the study), against `docs/mesh/76-broker.md` (the live API)
and `docs/mesh/71-mesh-program.md` §2.2/§2.3.
**Written:** 2026-09-17, 03:30–04:05Z from `ZABZ-YOGA`.
**Author:** stream O7, a delegated session — not the owner.
**Status:** a design that is runnable and exact, plus a **written refusal** (§6).
**This session owns exactly one file: this one.** Nothing was built on any cloud provider. Nothing was
bought, created, started, paused or resized anywhere. No credential was read into this session's context;
the one credential check below reports **names and lengths only** (`§1.5`). No commit was made.

**Provenance convention.** **SAW-LIVE** = I read it today, with the URL or command and the time.
**READ** = read out of source, with `path:line`. **ARITHMETIC** = derived here from named SAW-LIVE inputs.
**UNVERIFIED** = I looked and failed, or did not look — stated as a refusal, never as health.
A confidently wrong number is the failure this whole program exists to prevent.

---

## 0. The answer in one paragraph

**Everything below is buildable and I would build every mechanical part of it. I refuse to make it
*fire automatically* today, and the reason is a measurement, not an opinion: across every placement this
mesh has ever recorded — 6 `POST /place` calls, both days, at 03:45Z on 2026-09-17 — `tier` was **`fits`
six times out of six**, at `position 0`, on a mesh with two transport-capable nodes and **30 effective
slots free**. The trigger the study specifies (`tier != "fits"` twice, ≥60 s apart) **has never once been
satisfied, so it has never once fired, so its false-positive rate is unknown and its cadence is zero.**
Meanwhile the number that decides the economics is not subtle: **one forgotten CPX41 costs $141.49 in a
month against $163.12 to buy the machine outright** — 86.7 % of a permanent machine for a month of one
that then does not exist. An auto-firing provisioner whose trigger has never fired is a mechanism for
converting an occasional slowdown into a recurring bill, and the machine that would answer the same
demand today costs $163.12 once, lives in the mesh 24/7, and needs no credential path at all.
**The one measurement that changes my mind is in §6.3: two or more *unplaceable* fleets in a rolling
seven days.** That counter starts at zero and is cheap to start collecting tonight. Everything in §1–§4
is what to build the day it reaches two.

---

## 1. The provisioner, exactly

### 1.1 What it creates, from what image, in what order

Provider: **Hetzner Cloud**. It is the only option on the study's board that (a) the fleet has any
relationship with, (b) bills **per hour with the monthly price as a hard cap** — tested live by this
program in `79` §2.1 at 23:32Z on 2026-09-16 — and (c) does not depend on a spot market that can take
the machine away mid-fleet. The study's rows 17–23 are cheaper per vCPU and worse per *predictability*:
`71` §2.2 makes the broker's whole design "never refuse, always queue", and a node that can vanish with
GCP's **0-second** preemption notice (`79` §2.4) is the opposite of that.

**The image is Hetzner's stock Ubuntu 24.04 (`ubuntu-24.04`). It is never a snapshot and never a custom
image.** That is a credential rule, not a preference: a snapshot taken before teardown carries whatever
was on the disk, and `79` §3.2 measured that cloud user-data is readable from inside the VM and retained
provider-side. A stock image carries neither.

**What is created, in order.** Everything in this table is executed from **the operator's own machine**
(`ZABZ-YOGA` or `ZABZ-TECH` — the node that runs the dispatcher), never from a service that has to be
alive later:

| # | step | what runs | why in this position |
|---|---|---|---|
| 1 | **single-flight lock** | atomic `O_EXCL` create of `~/.dsh/mesh/elastic/lock.json` holding `{node, startedAt, pidHost, serial}` | two callers detecting the same burst must not boot two nodes. `79` §5.2(b)(1) — the governor's lesson applied to money |
| 2 | **create the instance** | `POST https://api.hetzner.cloud/v1/servers`, `type = cpx31`, `image = ubuntu-24.04`, `location = ash`, `name = mesh-el-1-<serial>`, `labels = {project: mesh-elastic, node: mesh-el-1, serial: <serial>}`, `ssh_keys = [<operator key name>]`, `user_data = <the config below>` | the **labels** are the only durable record the provider keeps that this program can query for free — §3.4 makes them load-bearing |
| 3 | **record the node** | append one JSON object to `~/.dsh/mesh/elastic/nodes.jsonl` **and** one line to the authority's journal via `journal.py append handoff` (over ssh) | two records, in two places, written **before** the VM can do anything. §3.4 |
| 4 | **wait for ssh** | poll `ssh -o BatchMode=yes -o ConnectTimeout=5 root@<public-ipv4> true` for ≤180 s | the operator's public key is the only credential in the instance request, and it is not a secret |
| 5 | **join the tailnet — FIRST** | `ssh root@<ip> "tailscale up --authkey=$TS_AUTHKEY --hostname=mesh-el-1 --accept-dns=false --advertise-tags=tag:mesh-node"` | `79` §1.3's ordering change, and the whole of §1.5 below |
| 6 | **verify the DNS label, and fail if it is wrong** | `ssh root@<ip> "tailscale status --json"` → `Self.DNSName` must be **exactly** `mesh-el-1.tail93e6e6.ts.net.` | a reused hostname whose previous device record still exists gets suffixed (`mesh-el-1-1`), and §2.1's invariant is `node == fqdn.split('.')[0]`. A suffixed label means the broker reads a node that will never answer, silently. **This check is a hard abort, and it is the single most valuable line in the provisioner** |
| 7 | **the runtime + the gate + the engine** | `scripts/provision-mesh-node.sh -H root@mesh-el-1 --authority secratary-ts --node-version v22.23.2 --expect-reply "NODE OK"` — run **from the operator's machine**, which means its local half `ssh`es into the node and its remote half does everything on the node | `79` §1.3 step: the runtime, `npm ci` from the authority's lockfile, `/etc/dsh-worker.env`, `/usr/local/bin/dsh`, `dsh-engine.service`, `phone-gate.service`, `tailscale serve --bg 3086`. **The existing script is not reinvented** |
| 8 | **the credential, over the tailnet, AFTER the join** | happens inside step 7, and this is the point of step 5: the script reads `secratary:$HOME/.dsh/.credentials.yaml` **from the node over WireGuard** and installs it as `/etc/dsh-worker.env` at `0640 root:zabz` (`provision-mesh-node.sh:428-455`) | §1.5 |
| 9 | **readiness, as the broker measures it** | poll `GET https://mesh-el-1.tail93e6e6.ts.net/mesh/capacity` until it returns a schema-1 document with `node == "mesh-el-1"` | "ready" means ready *to the broker*. A process that started is not a node |
| 10 | **the proof** | `ssh root@mesh-el-1 'cd ~/code && /usr/local/bin/dsh --profile headless "Reply with exactly: NODE OK"'` → stdout contains `NODE OK`, **exit 0** | the single command in §1.3 |
| 11 | **the allow-list entry** | write the `volatile` roster row (§2.1) into `packages/mesh-broker/nodes.json` and restart the broker | §2.1. Note this is a **file on the authority**, i.e. one `ssh` write, not a node action |
| 12 | **the boot deadline** | record `bootDeadline = provisionedAt + maxLifetimeSec` into `~/.dsh/mesh/elastic/nodes.jsonl` and into the journal line | §3 |

### 1.2 The user-data, verbatim — and what is deliberately NOT in it

```yaml
#cloud-config
# NO SECRETS. This file is readable from inside the VM at
# http://169.254.169.254/hetzner/v1/metadata (measured by 79 §3.2 on both existing
# VPSs, 2026-09-16) and is retained on Hetzner's side. A serial number is not a
# credential; an API key, a tailnet auth key and a model key all are.
package_update: false
write_files:
  - path: /etc/apt/apt.conf.d/20auto-upgrades
    content: |
      APT::Periodic::Update-Package-Lists "1";
      APT::Periodic::Unattended-Upgrade "1";
  - path: /etc/apt/apt.conf.d/51unattended-upgrades-security-only
    content: |
      Unattended-Upgrade::Allowed-Origins { "${distro_id}:${distro_codename}-security"; };
      Unattended-Upgrade::DevRelease "false";
runcmd:
  - [ systemctl, enable, --now, unattended-upgrades ]
  - [ sh, -c, 'echo "mesh-elastic serial $(cat /etc/mesh-elastic-serial 2>/dev/null || echo unknown) booted $(date -u +%FT%TZ)" >> /var/log/mesh-elastic-boot.log' ]
```

**Not in the user-data, and each for a measured reason:**

* **no model API key** — `79` §3.2(1): user-data is readable from inside the VM *and* retained by the
  provider. The key goes over the tailnet after the join (§1.5).
* **no tailnet auth key** — same channel, same reason. It is passed as an environment variable to
  `tailscale up` over the ssh session the operator already holds.
* **no ssh private key** — the instance request carries a **public** key only. The private half never
  exists on a rented box, and it does not need to: every later step is executed *from the operator*
  over ssh, and the credential transfer is a *pull* by the node from the authority, not a push.
* **no repository checkout** — `73` §1.2: the node's gate and the provisioner arrive over ssh from the
  operator's machine. A fresh VM has no `harness-config` checkout and needs none.

### 1.3 The single command that proves the node is ready

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 root@mesh-el-1 \
  'cd ~/code && /usr/local/bin/dsh --profile headless "Reply with exactly: NODE OK"; echo "exit=$?"'
```

**Ready** is: `NODE OK` on stdout **and** `exit=0`. The **string** is the discriminating part, not the
exit code: `62` §1.1 measured that a Node below 22.18 makes `bin.js` exit **0 having printed nothing**,
so an exit-code-only check passes on a node that does nothing. In one shot this proves the interpreter
floor, that the credentials resolved, that `api.deepseek.com` is reachable from that machine, that the
base toolbelt mounts, and that the session store is writable.

This command is **already inside the provisioner**: `provision-mesh-node.sh` step 8b runs exactly it with
`--expect-reply` (default `NODE OK`), captures stdout/stderr to `$HOME/.dsh-mesh/`, and returns **exit 4**
with `failures+=("the headless turn did not print 'NODE OK'")` if the string is absent
(`provision-mesh-node.sh:772-797`). The elastic provisioner does not reimplement it — it reads the exit
code.

### 1.4 The runtime install, the engine, the gate, the allow-list entry

All four are `scripts/provision-mesh-node.sh`'s existing work, invoked once with the arguments that make
it correct for a rented box. Nothing new is installed and no second script is invented — `79` §5.2(b)
requires wrapping it, and the wrapper is thin enough to be a shell function.

| what | how, exactly | where it lands |
|---|---|---|
| **runtime** | nodejs.org tarball, version **pinned by `--node-version`**, sha256 against `SHASUMS256.txt` | `~/.local/node-v22.23.2-linux-x64/`, with `~/.local/node` as the stable symlink |
| **DSH** | `npm ci --omit=dev` from **the authority's own `package-lock.json`** (pinned by integrity hash, not by the `^0.1.5-rc.1` range) | `~/dsh-engine/` |
| **launcher** | `/usr/local/bin/dsh` — resolves the interpreter, never names a version | — |
| **credentials** | `/etc/dsh-worker.env`, **`0640 root:zabz`** | — |
| **engine** | `dsh-engine.service` — `web --port 3099 --no-open --trusted-host mesh-el-1.tail93e6e6.ts.net`, with `HOME` and `DSH_HOME` set explicitly (systemd sets neither, and without `HOME` the engine's `~/.dsh` resolves to `/`) | loopback only |
| **gate** | `phone-gate.service` — `phone-gate.py --listen-port 3086 --engine-port 3099`. **The gate needs no change at all for an elastic node** — `79` §5.3 is right that this is the payoff of putting the capacity surface in the gate | `127.0.0.1:3086` |
| **the door** | `tailscale serve --bg 3086` → `https://mesh-el-1.tail93e6e6.ts.net/` | the path the broker reads |
| **allow-list entry** | the roster row of §2.1, written into `packages/mesh-broker/nodes.json` **on the authority**, then the broker restarted | §2.1 |

**The pinned-version trap, and a real hole in the wrapper as it stands.** `provision-mesh-node.sh:317-323`
resolves the runtime version by asking the authority *from the node*:

```bash
node_version="$(ssh "${ssh_opts[@]}" "$authority" '"$HOME"/node/bin/node -v')"
…
warn "could not read node -v from $authority; falling back to $node_version"
```

Measured today: `ssh secratary-ts 'command -v node'` is **empty** — the authority's interpreter is *not*
on the non-interactive `PATH`, only at `$HOME/node/bin/node`, which the line above does use. So the happy
path works. But the **fallback is silent in its consequence** (it warns and continues): a failure to read
the authority silently pins **v22.23.2** — a version that is *correct today* (`62` §1.1 measured it as the
runtime the live engine runs) and would be **wrong the day the authority moves**. The elastic wrapper must
therefore pass `--node-version` **explicitly** and treat the script's output line `pinned to the
authority's own version:` as a **required** line: if it is absent, the run aborts before `npm ci`. That is
a development decision (`rule 3`), recorded here and implemented by the wrapper, not a question for the
owner.

**Two constraints from `71` §0/§5 that a rented node must not break:**

1. **One engine per `DSH_HOME`, one `DSH_HOME` per node.** The node gets a *fresh* `~/.dsh`,
   self-initialised on first boot (`62` §1.3: a fresh `DSH_HOME` needs nothing). It must never be handed a
   copy of another node's home — two engines on one home corrupt session logs.
2. **Sessions are node-local and do not move.** A rented node is a **job runner**, never a place a session
   lives. That is not a limitation to work around; it is what makes teardown free.

### 1.5 How the model key reaches the node without being baked into the image

**The channel.** `/etc/dsh-worker.env` is written on the node by `provision-mesh-node.sh:419-460`, whose
source is the authority's own credential file, read **from the node, over the tailnet**:

```bash
# provision-mesh-node.sh:428 — runs ON the node, as the node's user
ssh "${ssh_opts[@]}" "$authority" 'cat "$HOME"/.dsh/.credentials.yaml' > "$tmp"
```

**Verified today, without reading a value** (2026-09-17 03:40Z, `ssh secratary-ts`,
`~/.dsh/.credentials.yaml` mode `0600 zabz:zabz`): the file's `refs:` section holds exactly
`DEEPSEEK_API_KEY` (35 characters) and `DEEPINFRA_API_KEY` (32 characters). The transport is a
`ssh + cat` pipe, never `scp` (the script's own header says why: `scp` is the one non-portable command in
it, and it needs the remote sftp subsystem).

**Why the ordering change is the whole of the credential control**, in `79` §3.2's three failure modes:

1. **cloud-init user-data** is readable from inside the VM and retained provider-side →
   *nothing secret is ever in it* (§1.2).
2. **snapshots outlive the VM** → *there is no snapshot*; the image is stock, and teardown is
   **destroy**, never stop (§3.2).
3. **there is no un-provision** → **the key's lifetime equals the VM's lifetime**, the VM's lifetime is
   capped by a hard timer (§3), and the key is delivered over the already-authenticated tailnet rather
   than through the provider's metadata channel.

**The property that makes the key non-extractable from inside the agent process.** `62` §1.5(a): the
environment layer **wins** over `~/.dsh/.credentials.yaml`, and the provider *refuses* a write the
environment would shadow. So an agent running on that node cannot rewrite its own model credential, and
the key never touches disk inside `~/.dsh`. `73`'s "credentials decision" section verified this on
`zabz-tech-linux` by grepping the live file for `sk-` and finding zero.

**The check that makes the claim falsifiable, and I have NOT run it** (it needs a live rented node):
after boot and after the env file lands, read the node's own metadata channel and assert the key is not
in it —

```bash
ssh root@mesh-el-1 'curl -s http://169.254.169.254/hetzner/v1/userdata' \
  | grep -c -E 'sk-|DEEPSEEK_API_KEY'   # MUST be 0
```

`79` §3.2 proved the channel exists on the two existing VPSs; **that it is empty of secrets on *this*
node is unverified until the first real boot.** It belongs in the runbook as a required step, not as a
claim.

**UNVERIFIED, and it decides whether this is a rotation problem or a bookkeeping problem** (`79` §7(7)):
whether the gateway can issue **per-node, revocable, scoped** keys. Until it can, every burst uses the
same long-lived key and the teardown *is* the revocation. That is acceptable for a single-tenant tailnet
and it is one more reason the first burst should be hand-run with the invoice in hand (`79` §6).

---

## 2. The roster entry and the trigger, against the real API

### 2.1 The roster entry

`packages/mesh-broker/nodes.json`, two rows added — and a measurement that changes what can honestly be
put in them:

```json
{
  "node": "mesh-el-1",
  "fqdn": "mesh-el-1.tail93e6e6.ts.net",
  "location": "office",
  "baseUrl": "https://mesh-el-1.tail93e6e6.ts.net",
  "volatile": true,
  "dispatch": {
    "v1": null,
    "measuredAt": null,
    "evidence": "UNMEASURED. Set to true by the provisioner only after `dsh --profile headless \"Reply with exactly: NODE OK\"` returns NODE OK with exit 0 on this node (§1.3)."
  },
  "note": "ELASTIC, volatile. Not provisioned unless the dispatcher's trigger fires (§2.3 of docs/mesh/88-elastic-build.md). Cost, TTL and provider constants live in ~/.dsh/mesh/elastic/config.json, NOT here - see the note below."
}
```

**READ, and it corrects `79` §5.2(a):** `packages/mesh-broker/lib/config.js:88-103` is the roster
normalizer, and it returns exactly
`{node, baseUrl, fqdn, location, note, excluded, dispatch, volatile, index}`. **`hourlyUsd` and
`maxLifetimeSec` — the two keys the study proposed putting in the roster row — are silently dropped by
the loader and are read by nothing** (`grep -rn 'hourlyUsd|maxLifetimeSec' packages/mesh-broker/` returns
zero hits outside this document). Putting them in `nodes.json` would look authoritative and be decorative,
which is exactly the class of error `70` §4.4 and `76` §8 exist to catch. **They belong in the elastic
tier's own config, where something reads them** (`~/.dsh/mesh/elastic/config.json`, §2.4).

Also **READ**: `config.js:81-87` makes `fqdn` **required** and refuses to boot the broker if
`node !== fqdn.split('.')[0]`. The naming invariant is enforced at startup, with both spellings in the
message.

What `volatile: true` buys, **READ** from `lib/broker.js:194-196`: `isAbsent(node)` is
`node.volatile === true && everAnswered === false`, and an absent node is excluded from `eligible`, from
the ranking and from the candidate count, gets `unreachable: false` (the two states are mutually
exclusive) and an `ageSec` measured from configuration. That is amendment 5, already built and tested
(`76` §10.6); the live roster sets the marker nowhere.

**One honesty limit worth stating, because it is a real behaviour and not a bug:** `everAnswered` is
**in-memory and per-process** (`lib/broker.js:169-184`), and the baseline resets when a row's
`baseUrl|fqdn` signature changes. So a torn-down node that was once provisioned is reported
**`unreachable`**, not `absent`, until the broker restarts — and it is **counted in the latency cache and
charged one read timeout per 15 s** until then (`76` §5 item 9). The operational rule that follows: **a
broker restart is part of teardown**, alongside removing the row. `79` §2.4's mitigation for
`ipv6.forwarding=0` is not relevant here; this one is.

### 2.2 The `absent` state, as the broker already implements it

Live evidence that the state exists and is correct — `GET /nodes` **SAW-LIVE** on the authority at
03:40Z on 2026-09-17, a live node row carrying the full schema:

| field | `zabz-tech-linux`, live | a `volatile` node before its first answer |
|---|---|---|
| `state` | `ok` | `absent` |
| `unreachable` | `false` | **`false`** — mutually exclusive, which is the point |
| `absent` | `false` | `true` |
| `absentSince` | `null` | the moment it was configured |
| `effectiveSlots` | `4` | — (not ranked) |
| `slots` / `memorySlots` / `coreSlots` | `4` / `24` / `4` (basis `physical`) | — (not ranked) |
| `swapUsedPct` / `swapApplied` | `15.3` / `false` | — |
| `transport` | `{v1:true, measuredAt:"2026-09-16", evidence:"…"}` | `{v1:null, …}` until measured |

And the placement response, **SAW-LIVE** 03:41Z — `POST /place {"task":{"kind":"fleet","children":6,
"worktreeGiB":2}}` returned `{node: "zabz-tech", position: 0, tier: "fits", score: 16, eligible: 4,
blockedBy: []}`, and `POST /place`'s response keys are
`[absent, at, blockedBy, children, considered, eligible, excluded, expiresAt, kind, lease, leaseTtlSec,
node, position, queue, rationale, score, tier, unreachable]`. **`tier` is on the wire** — that is what a
trigger reads.

*(One honest note on method: my first attempt at this probe died on remote-shell quoting — a
`python3 -c` one-liner mangled inside a PowerShell→ssh→bash→python chain. The retry piped the script to
`cat > /tmp/x.py` and ran it from the file, which is what `81` §2's "a remote command needing quoting
goes in a file you scp, never inline" is for. The numbers above are from the retry.)*

### 2.3 The firing condition, exactly — and where the code lives

**The rule, as the study recommends it and as I would implement it:**

| fire | do not fire |
|---|---|
| `POST /place` for a job that is wanted **now** returns **`tier != "fits"`**, **and** the same answer holds on a **second reading ≥ 60 s later** in the same busy window | on a percentage of free slots, on a wall-clock schedule, or on `governor.inUse` |
| **`kind = "fleet"` with `children ≥ 2` only** | **never for `kind = "oneShot"`**: a headless turn is 3–5 s (`73` §1.3) against a 2–4 minute boot, a guaranteed 30–50× loss |
| when the highest `slots` on the mesh is genuinely too small for the job | when the only "blocking" node is `secratary`, whose `accepts.fleet` state is its **designed** state (`76` §7.2) |
| under a spend cap: ≤ N nodes, ≤ $X/hour, and an alarm if any node outlives `maxLifetimeSec` | ever, for a job `tier == "fits"` can place at `position 0` today |

**READ, and it settles the `?fresh=1` question precisely:** `?fresh=1` exists **only on
`GET /nodes`** (`lib/server.js:107-108`; `POST /place` is `lib/server.js:68-84` and takes no query
parameter at all — `lib/server.js:2-6` names the three frozen verbs and only `/nodes` carries the flag).
`POST /place` therefore reads the **≤15 s cache** (`cacheTtlMs: 15000` in the live roster, SAW-LIVE in
`GET /healthz`). The honest reading of "the second reading is fresh" is therefore:

```
reading 1:  POST /place {kind:"fleet", children:N}          -> tier, position, rationale
            (if tier == "fits" or position == 0 -> STOP. nothing to do.)
sleep >= 60 s
reading 2:  GET  /nodes?fresh=1                              -> force every node to re-answer
            POST /place {kind:"fleet", children:N}          -> tier, position, rationale
            (fire only if the SECOND call is also tier != "fits")
```

The second `POST /place` cannot be *guaranteed* fresh — nothing in the frozen interface offers that —
so the `GET /nodes?fresh=1` immediately before it is what bounds the staleness to one round-trip,
measured at `latencyMs` 3–103 ms per node (SAW-LIVE, §2.2). **If the frozen interface is ever amended
again, `?fresh=1` on `POST /place` is a one-line, additive change and I would ask for it before automating
this** — until then the ordering above is the strongest available reading, and the design must not pretend
it is stronger.

**Where the code lives — the dispatcher, never the broker, and the exact file:**

> **`packages/plugin-remote-fanout/bin/mesh-run.mjs`** — the dispatcher, between step **1. PLACE**
> (`:302-339`) and step **2b. CAPABILITY** (`:354-367`), plus one entry in the `NODES` node table
> (`:66-114`) for `mesh-el-1`.

That is the right file and not merely the convenient one, for three reasons that are all in the code
already:

1. `mesh-run.mjs:317-328` **already records `tier`** from every placement into the run log
   (`~/.dsh/mesh/logs/<runId>.jsonl`, phase `place`). The trigger needs no new data — it needs a
   *counter*, and the counter is the stored state §2.2 forbids the broker from keeping
   (`71` §2.2: "nothing it can go stale on"; `76` §5 item 1: no heartbeat table, no PUBLISH verb).
2. `mesh-run.mjs:341-351` is the single place that maps a broker node name to a transport — and it
   **fails the run loudly on a lookup miss**. An elastic node the broker can name but the dispatcher
   cannot reach is worse than a queued one; that check is where the elastic node's `ssh`, `hosts`,
   `shell:'posix'`, `nodeExe` and `dshBin` have to be declared, so it is where the node must appear.
3. The exit contract is **0 / 10 / 1** (`71` §2.3) and is unchanged by an elastic retry: a run that
   provisions a node and then places is still `0`, and a run that waits is still `10`.

**Where the counter lives** (dispatcher-side, disposable, and never the broker's):

```
~/.dsh/mesh/elastic/
  config.json     every constant, with provenance - §2.4
  lock.json       the single-flight lock (§1.1 step 1)
  nodes.jsonl     one JSON object per provisioning run - §3.3
  attempts.jsonl  append-only: {at, kind, children, tier, position, node, score, freshRead}
```

`attempts.jsonl` is a log, not a state machine: the trigger reads the last two entries inside a 15-minute
window. That keeps it **derivable from evidence** rather than itself becoming a thing that can be stale —
the same reasoning the lease TTL uses.

### 2.4 The constants, and making a changed constant need no code change

`79` §1.4 and `76` §10.2/§10.3 both end by saying the same thing about the two numbers that decide
capacity: `0.75 × physical cores` and the `90 % swap` half are **first cuts, not measurements**. Stream O3
is taking the real load measurement tonight. A trigger whose thresholds are literals in JavaScript would
have to be edited the day that measurement lands, and — worse — could go on being *wrong* silently.

So **every constant lives in exactly one file, and nothing in the code is a literal**:

```json
{
  "schema": 1,
  "_comment": "Every number the elastic tier fires or spends on. A constant change must be a FILE change; if a number appears in code as well, that is a bug. `provenance` is mandatory per entry.",
  "trigger": {
    "minChildren": 2,
    "requiredConsecutiveMisses": 2,
    "minSecondsBetween": 60,
    "maxWindowSec": 900,
    "freshReadBeforeSecond": true,
    "enabled": false
  },
  "spend": {
    "maxNodes": 2,
    "maxUsdPerHour": 0.50,
    "provider": "hetzner",
    "serverType": "cpx31",
    "location": "ash",
    "hourlyUsd": 0.1178,
    "monthlyCapUsd": 73.49
  },
  "lifetime": {
    "maxLifetimeSec": 3600,
    "idleSec": 600,
    "readyTimeoutSec": 420,
    "orphanGraceSec": 900
  },
  "constants": {
    "coreSlotsPerVcpu": 0.75,
    "requiredGiB": "20 + worktreeGiB + 0.5 * children"
  },
  "provenance": {
    "spend.hourlyUsd":     "SAW-LIVE 2026-09-17T03:36:12Z, hetzner.com cloud_data.json ASH1/CPX31/USD",
    "spend.serverType":    "chosen by this stream: 4 vCPU = 3 child seats under the broker's own core term (floor(4 x 0.75))",
    "trigger.minSecondsBetween": "79 §5.2(d), the study's recommendation - UNMEASURED, see §6.3",
    "lifetime.maxLifetimeSec":   "79 §5.2(c) default - UNMEASURED; see the break-even table §4.3",
    "constants.coreSlotsPerVcpu": "76 §10.3: calibrated on a 16-core laptop (pages at 13-14 turns). Stream O3 owns the real measurement; change this line, not the code"
  }
}
```

**`"enabled": false` is the shipped default and it is deliberate.** A trigger that has never fired has
no measured false-positive rate (`§6.2`), so it ships off, and turning it on is a one-character,
journal-recorded act.

**And the honesty mechanism:** if any entry named in a required list is missing from `provenance`,
the trigger refuses to fire and says which number is undocumented. A constant whose date is unknown is
not a measurement — the same rule `76` §5 item 15 ends on.

---

## 3. The teardown rule — the number that decides the economics

### 3.1 Destroy on the FIRST of four conditions

**Destroy, never stop.** A stopped Hetzner VM still bills storage and still holds the key on a disk that
still exists (`79` §5.2(c)). The four conditions, in the order they are most likely to be reached:

| # | condition | default | who owns it | how it is enforced |
|---|---|---|---|---|
| 1 | **no broker lease has named the node for `idleSec`** | 600 s | the reaper | `GET /nodes` on the broker reports `brokerLeases` per node (READ: `lib/broker.js`, `brokerLeases` is on every `/nodes` row) — the reaper reads it, not a local guess |
| 2 | **`maxLifetimeSec` elapsed since the capacity route first answered** | 3600 s | the reaper **and** the node itself | the reaper always; and the node's own systemd timer as a second, independent killer (§3.2) |
| 3 | **the lease was released and no queued work remains** | immediately | the dispatcher | `mesh-run.mjs:420-424` already `POST /done`s on every path. The elastic run's `done` handler also asks the reaper for an immediate teardown |
| 4 | **a failure to become ready** | `readyTimeoutSec` 420 s | the provisioner | if step 7 or step 9 of §1.1 fails, the provisioner destroys the instance **itself**, before it ever writes a roster row |

**Why the wall-clock cap is not optional and does not belong to the broker.** `71` §2.2's 900 s TTL
governs *leases*, and it is deliberately reclaimed by whoever reads it, so a dead dispatcher cannot wedge
the mesh. But a lease TTL is not a **node** TTL, and §2.2 explicitly forbids the broker storing node
state (`76` §5 item 1). So the hard ceiling belongs to the provisioner's own record, and — critically —
it must be enforced by something that **does not depend on the placing caller still being alive**
(`76` §10.7 says exactly this). Hence a reaper, and hence the node's own timer.

### 3.2 The reaper, and why it is safe to run from anywhere

```
~/.dsh/mesh/elastic/reap.sh   (idempotent, no arguments)
  1. read nodes.jsonl; for each record: destroyedAt present? -> skip
  2. ask the broker GET /nodes (over ssh) -> brokerLeases, state for that node
  3. destroy if: idle > idleSec  OR  now > maxLifetimeSec  OR  no record of the node in
     /servers?label_selector=project=mesh-elastic,node=<n>   (it was already destroyed -> mark it)
  4. destroy = DELETE /servers/<id>  (204 or 404 both mean "gone"; 404 is a SUCCESS here)
     then: remove the roster row, restart the broker, append the journal handoff line,
     and only then write destroyedAt
  5. any node found by label that is NOT in nodes.jsonl -> destroy it, and journal a PAIN
```

**Running on two independent hosts is a feature, not a bug:** a reaper that finds the instance already
gone must treat **404 as success** so a second reaper racing the first is harmless. The only destructive
verb in the whole design is `DELETE /servers/<id>` (plus the tailnet device cleanup), and it is
**idempotent by construction**.

**The authorization model, stated because it is the one place a design like this goes wrong:** the reaper
holds a Hetzner API token that can create *and destroy* servers. That token exists in exactly one place,
`/etc/mesh-elastic.env` (mode `0600`), on **one** machine — the dispatcher host — never on the node, never
on the authority's web surface, and never in `harness-config`. The node holds a **tailnet auth key** and
a **model key**; it holds **no provider credential**, so a rented node cannot create or destroy anything,
including itself.

### 3.3 The expensive failure — the provisioner dies mid-create — and how it is made visible

This is the failure the brief calls the expensive one, and it is worth naming exactly how expensive: the
provisioner dies between `POST /servers` returning 201 and the local `nodes.jsonl` append. **A server now
exists that nothing knows about.** It boots, joins the tailnet, installs itself, answers the broker's
capacity read — and bills until someone notices. `79` §3.4's number: **$141.49 for a CPX41 in a month.**

**Four independent mechanisms, in increasing order of how much they depend on good behaviour.** The
design intends the first two to be *impossible to circumvent*, and the last two to be *impossible to
miss*:

1. **The provider's `created` timestamp is the authority, not our record.**
   `GET /servers?label_selector=project=mesh-elastic` returns every elastic node with its `created` field
   — **including a node whose serial appears in no local file**. Nothing this program writes can make a
   node invisible to that query, because the labels are set **in the same API call that creates the
   server** (§1.1 step 2). This is the single most important line in the design: **the durable record is
   the provider's label, not our JSON.**
2. **The node kills itself.** The cloud-init unit list includes a `mesh-elastic-deadman.timer` that
   `systemctl poweroff`s the node at `serial_created + maxLifetimeSec + 300 s`. The value is baked into
   the machine at boot out of data that is **not a secret** (the serial and the create time), so it costs
   nothing in §1.5 terms. A node whose controller never existed still dies. *(A powered-off Hetzner VM
   still bills — `79` §5.2(c) — so this is a **bill limiter, not a bill stopper**; it removes the
   runaway-work cost and the credential exposure, and the reaper still has to delete it.)*
3. **A timed sweep that does not need any of the above.** A `systemd` timer on the authority every
   60 s: list by label, compare `created` against `maxLifetimeSec + orphanGraceSec`, destroy anything
   over. It needs no lock, no state, and no cooperation from the dispatcher — the only thing it can get
   wrong is being switched off, which is why it is a systemd unit and not a script someone remembers to
   run.
4. **A journal record written before the VM can do anything.** `§1.1` step 3 appends the journal handoff
   line **immediately after** the 201 and **before** waiting for ssh. If the provisioner dies after that
   point, the authority's own record — not a laptop's local file — names the server id and the deadline.
   The journal is the fleet's most durable store and it is already synced between machines; this is what
   that is for. **And if it dies *before* that point, the provider label still catches it** — which is why
   mechanism 1 is the one that makes the failure "impossible" rather than "unlikely".

**What is deliberately not claimed:** there is no way to make the window *zero*. The claim is narrower and
checkable: **there is no window in which a created server is untracked by the provider**, and a
node-created one is swept within `maxLifetimeSec + orphanGraceSec` (default 75 minutes) regardless of
what the controller did. The check that this is true is mechanism 1's query, and the runbook's first step
after any failed burst is:

```bash
curl -s -H "Authorization: Bearer $HCLOUD_TOKEN" \
  'https://api.hetzner.cloud/v1/servers?label_selector=project=mesh-elastic' | jq '.servers[] | {id,name,created,status}'
```

**UNVERIFIED:** the Hetzner Cloud API paths above (`POST /v1/servers`, `GET /v1/servers?label_selector=`,
`DELETE /v1/servers/<id>`, the `labels` field, `location: "ash"`) are stated from the provider's public
API shape and were **not** exercised — exercising them means creating a server, which this stream is
forbidden to do. The one thing I would verify before the first real burst is exactly this query, on a
throwaway instance, with the invoice open.

### 3.4 The tailnet side, which costs nothing and is the one *manual* step

Tailscale does not know about the provider's teardown. When a node is destroyed, its device record
lingers in the tailnet, and **the next burst that reuses the hostname can be suffixed** — `mesh-el-1-1`
instead of `mesh-el-1`. That breaks §2.1's invariant, and the failure is not loud: the broker would simply
read a node that never answers.

**Measured, and it is the reason this is a manual step rather than an automated one:** the tailnet has
**six devices** today (SAW-LIVE 03:48Z, `tailscale status` from the authority) —
`secratary`, `iphone-15-pro`, `lakewooechsmini`, `zabz-tech-linux`, `zabz-tech`, `zabz-yoga-1` — and
**there is no API token anywhere this fleet can reach**: `~/.tailscale*` does not exist on the authority
and a targeted grep of `~/bin` and `~/code/harness-config/journal` for `tskey-`/`TS_API`/`TAILSCALE_API`
found nothing. So device deletion cannot be automated today.

**The design's answer is not to soften the problem but to make it impossible to miss:**
`§1.1` step 6 asserts the DNS label is **exactly** the expected one and aborts otherwise.
That is a fail-fast on the one symptom that matters, and it converts a silent mislabel into a loud stop
before any money is spent on a node the broker can never reach.

---

## 4. The cost table for one night's burst

### 4.1 Provenance of the prices

**SAW-LIVE, 2026-09-17T03:36:12Z**, from Hetzner's own calculator dataset —
`https://www.hetzner.com/_resources/app/data/bench/cloud_data.json`, `HTTP 200, 12 920 bytes`, read with
`-NoProxy` from `ZABZ-YOGA`. The ASH1/USD rows, verbatim from the JSON:

| SKU | cores | **USD/hr** | **USD/mo (cap)** | traffic map |
|---|---|---|---|---|
| CPX11 | 2 | **0.032800** | **20.49** | `{"0":0,"1":"1.200000"}` |
| CPX21 | 3 | 0.060100 | 37.49 | `{"0":0,"2":"1.200000"}` |
| **CPX31** | **4** | **0.117800** | **73.49** | `{"0":0,"3":"1.200000"}` |
| **CPX41** | **8** | **0.226700** | **141.49** | `{"0":0,"4":"1.200000"}` |
| CPX51 | 16 | 0.447900 | 279.49 | `{"0":0,"5":"1.200000"}` |

IPv4 add-on, same file, `USD`: **`$0.60/mo`, `$0.001/hr`**.

**Specs re-read live, same minute**, from `https://www.hetzner.com/cloud/regular-performance/`
(`HTTP 200, 324 361 bytes`, 03:36:36Z): **CPX31 = 4 vCPU AMD / 8 GB / 160 GB**,
**CPX41 = 8 vCPU AMD / 16 GB / 240 GB**, **CPX11 = 2 vCPU AMD / 2 GB / 40 GB**. This closes the
`REMEMBERED` cells in `79` §2.2 rows 1–5 (the study could not pin RAM and disk for the 1-series CPX plans).

**These prices are unchanged from the study's 2026-09-16 23:31Z reading, to the cent** — four hours and
five minutes earlier. So the study's numbers are sound as of now, and this document does not need to
correct them (it corrects its *recommendation*, in §4.2, for a different reason).

**One price I did NOT re-verify, and it is the sentence the whole elastic model rests on:**
Hetzner's *"your server's bill will never exceed its monthly price cap … we will only bill you for the
hourly rate"* (`79` §2.1, read live at 23:32Z on 2026-09-16 on `hetzner.com/cloud/regular-performance/`).
I did not re-render that page tonight. **The hourly rates and the caps are SAW-LIVE as of 03:36Z; the
billing *term* is the study's live reading from four hours earlier, dated, and labelled as such.** If
that term is ever wrong, every number in §4.3 is wrong in the same direction and the burst becomes
strictly more expensive.

### 4.2 What one elastic node is worth, in the broker's own arithmetic (ARITHMETIC)

The broker's score is `min(memorySlots, floor(physical × 0.75))`, then halved at ≥90 % swap
(`71` §2.2 as amended). Applying it to the two candidate SKUs with the **same** memory formula the broker
uses, `min(floor((freeMiB − 3885) / 160), 24)`, and `free ≈ total × 0.92` (a fresh boot; `freeMiB` is the
OS's own free number and a bare VM has no page cache):

| SKU | vCPU | RAM | `coreSlots = floor(0.75 × vCPU)` | `memorySlots` | **effective `slots`** | children it can seat |
|---|---|---|---|---|---|---|
| CPX11 | 2 | 2 GB | **1** | 0 | **0** | **0** |
| **CPX31** | **4** | **8 GB** | **3** | 26 | **3** | **3** |
| CPX41 | 8 | 16 GB | **6** | 72 | **6** | **6** |

**Read the CPX11 row again.** `2048 × 0.92 = 1884 MiB free`, and `(1884 − 3885) / 160` is **negative**,
floored at 0 by `76` §3's rule — and `floor(2 × 0.75) = 1` anyway. So the study's recommended single-node
pick (`79` §6: "if he rents exactly one thing, the pick is Hetzner CPX11 in Ashburn at $0.0328/hr") **scores
1 slot: it cannot absorb even a 2-child fleet**, which is the smallest job the trigger is allowed to fire
for. The CPX11 recommendation is right for *cost-per-hour* and wrong for *this use*, and the reason is a
constant that did not exist when `79` was written: the core term landed the same night, in `76` §10.3. This
is the single most useful correction in this document — the cheapest plan on the board is not eligible for
the only job that pays for it.

**And the honest caveat on the CPX31 row.** `0.75 × vCPU` is `76` §10.3's constant, calibrated on a
**16-core laptop**; the same document says in terms that it has never been measured on a rented box and
that ~1 generating turn ≈ 1 core is the measured shape. So "3 children per CPX31" is **an arithmetic
consequence of an unmeasured constant**, and it is the number that decides how many nodes a burst buys.
Stream O3's measurement replaces it. **It is in `config.json` for exactly that reason (§2.4)** — if the
real number is 1 slot per vCPU, a 6-child fleet needs 6 CPX31s rather than 2, and the burst costs triple.
The design does not change; the table does.

**And the cost-per-child framing that actually matters:** a 6-child fleet costs **2 × CPX31 × 1 h =
$0.2356**, i.e. **$0.0393 per child-hour**, against a headless one-shot turn's 3–5 s (`73` §1.3) which
provisioning cannot help at all. That gap — 2–4 minutes of boot against 3–5 seconds of work — is why the
study's "fleets of 2+ children only, never a one-shot" rule is not a preference. It is arithmetic.

### 4.3 One night's burst, three ways (ARITHMETIC on §4.1's SAW-LIVE prices)

The brief's scenario is **a 2-hour burst of 3 nodes**, and the study's flagship comparison is
**CPX41 × 3** (24 vCPU). Both are below. All figures exclude the $0.60/mo IPv4 (each row is per-hour and
the IP is per-month; at ≤16 h/month it adds $0.016/hr, under 14 % at CPX31 and under 1.5 % at CPX41 × 3 —
stated rather than folded in, so the numbers are reproducible).

| scenario | shape | arithmetic | **cost** |
|---|---|---|---|
| **A. one night's burst, as briefed** | 3 × CPX41, 2 h | `3 × 0.2267 × 2` | **$1.36** |
| **A′. one night's burst, as recommended** | 2 × CPX31, 2 h — enough for a 6-child fleet | `2 × 0.1178 × 2` | **$0.47** |
| **A″. the cheap reading** | 2 × CPX31, 2 h + 3 h of boot and teardown | `2 × 0.1178 × 5` | **$1.18** |
| **B. the same 3 nodes, forgotten overnight** | 3 × CPX41, 12 h | `3 × 0.2267 × 12` | **$8.16** |
| B′. the same 3 nodes, forgotten a full day | 3 × CPX41, 24 h | `3 × 0.2267 × 24` | **$16.32** |
| B″. as recommended, forgotten overnight | 2 × CPX31, 12 h | `2 × 0.1178 × 12` | **$2.83** |
| **C. forgotten for a month**, per node | 1 × CPX41 to the cap | `monthly cap` | **$141.49** |
| C′. forgotten for a month, all three | 3 × CPX41 to the cap | `3 × 141.49` | **$424.47** |
| C″. as recommended, forgotten for a month | 2 × CPX31 to the cap | `2 × 73.49` | **$146.98** |
| **D. the legitimate month** — a node that is *supposed* to be resident | 1 × CPX41, 24/7 | `monthly cap` | **$141.49** |

**The cap is real, not a marketing ratio.** `0.2267 × 744 = $168.66 > $141.49`, so the hourly rate stops
mattering after `141.49 ÷ 0.2267 = **624.7 h/month**` — and the same arithmetic for CPX31 is
`73.49 ÷ 0.1178 = 623.8 h`. Beyond 26 days, the month costs the cap and the extra hours are free; below
it, you pay the hours. **That is the whole mechanism the owner described, and it is why "delete before the
end of the billing month" costs only the hours used** (`79` §2.1, SAW 2026-09-16 23:32Z).

**The three rows to read twice, side by side:**

* **A′ → C″: $0.47 becomes $146.98 by forgetting to run one command.** A 313× multiple, and it buys
  nothing, because the fleet it was provisioned for finished in two hours.
* **C vs the machine: $141.49 for one forgotten CPX41 against $163.12 to own the machine outright.** That
  is **86.7 % of the purchase price, gone at the end of the month, for a machine that no longer exists.**
  `76` §10.7 already records this sentence as the reason the teardown rule matters more than the price;
  this document is the arithmetic behind it.
* **C′ vs the machine: $424.47 = 2.60× the price of the machine.** Three forgotten nodes cost more than
  two and a half permanent machines — and a permanent machine's cost is *recurring*, which is precisely
  what makes it cheap per hour (§4.4).

### 4.4 The break-even against the $152.98 machine, with the arithmetic shown

**What owning costs** (`79` §4.1, VERIFIED inputs, restated so the arithmetic is self-contained):

| input | value | source |
|---|---|---|
| purchase price | $152.98 | live listing, 2026-09-16, `61` §4.2 |
| NJ sales tax 6.625 % → taxed | **$163.12** | `61` §4.2 (`$489.35` for three ✓) |
| amortisation | 36 months | `40` §4 |
| **upfront per month** | **$4.531** | `163.12 ÷ 36` |
| idle draw | 12.7 W *(the sibling 5090's measured value; the 3090's is unmeasured)* | `61` §4.2 |
| electricity | `12.7 W × 8.766 kWh/W·yr × $0.2495/kWh = $27.78/yr` = **$2.315/mo** | EIA 5.6.A Jun-2026, NJ 24.95 ¢/kWh, `40` §0 |
| **cost of owning, per month** | **$6.846** | ARITHMETIC |

**The break-even hours for one node** — the machine is on 24/7 (it must be, to be in the mesh), so the
machine's cost is incurred whether it works or not; the rental is billed only while it exists. Break-even
is therefore a number of **hours**, and nothing else:

```
h* = $6.846 / hourly price

CPX31:  6.846 / 0.1178 = 58.1 h/month   ≈ 1.9 h/day
CPX41:  6.846 / 0.2267 = 30.2 h/month   ≈ 1.0 h/day
```

**Read plainly: if one rented node runs more than 1–2 hours a day, every day, the $163.12 machine is
cheaper and it is permanent.** Below that, renting wins — and the owner's own sentence ("we only need
them once in a while") is exactly the case where renting wins.

**And at fleet scale, which is the right comparison for a burst** — because the constraint `40` §4
measured to bind is **cores**, not machines. 24 vCPU needs `4 × OptiPlex 3090 Micro = $652.47 taxed`:

```
3 × CPX41:  3 × 0.2267 = $0.6801/hr      fleet-hours to break even = 652.47 / 0.6801 = 959 h
4 × CPX31:  4 × 0.1178 = $0.4712/hr      fleet-hours to break even = 652.47 / 0.4712 = 1385 h
2 × CPX31:  2 × 0.1178 = $0.2356/hr      (a 6-child fleet)        = 652.47 / 0.2356 = 2769 h
```

**At one fleet-hour a week (52 h/yr), 959 h is 18.4 years and 1385 h is 26.6 years.** So renting a peak
instead of buying cores pays back in **decades as hardware** and pays back **immediately as peak** — which
is `79` §4.3's conclusion, reproduced here from the live prices and unchanged. **The elastic tier is
therefore not a way to save money. It is a way to avoid buying a machine you would run at 3 % most of the
time.** That framing matters for the decision in §6: if the demand is real, rent it; if the demand is
occasional *and* the machine would be useful the rest of the time, the machine wins outright — and that is
the comparison the trigger has to earn its way past.

---

## 5. What this design does NOT do, deliberately

* **It does not make a rented node a place a session lives.** `71` §0/§5: sessions are node-local and
  cannot move; session *placement* is v2. The node is a job runner.
* **It does not give the node a provider credential.** The node can hold a tailnet key and a model key and
  nothing else (§3.2).
* **It does not change the broker.** `76` §10.6 and §10.7 already landed the broker's half (`absent`, the
  `volatile` marker, the printed score terms). §2.1 above found one thing the study proposed that the
  broker's loader silently drops (`hourlyUsd`, `maxLifetimeSec`) and moved it to where something reads it.
* **It does not change the gate.** `79` §5.3 is right: `/mesh/capacity` reports measurements, and a rented
  node that is up reports them like any other. Nothing in the capacity surface needed changing, and it
  still doesn't.
* **It does not add `?fresh=1` to `POST /place`.** That would be an additive change to a frozen interface
  and this stream's job is to design against the API that exists. It is named in §2.3 as the one change I
  would ask for before automating.
* **It does not touch `scripts/provision-mesh-node.sh`, `packages/mesh-broker/**`, `mesh-run.mjs` or any
  other stream's file.** Every edit named here is named as *where the change goes*, for whoever owns that
  file.
* **It does not build anything, on any provider, and it spends nothing.** No `POST /servers` was issued.
  The prices are read from public files; the API shape in §3.3 is labelled UNVERIFIED because exercising
  it costs money.

---

## 6. THE REFUSAL

**I do not recommend building the automated elastic tier now. I recommend building the *trigger* — the
part that decides — and leaving it switched off.** The refusal is specific and falsifiable, and it is not
about money.

### 6.1 The hardware arithmetics all say "yes, rent the peak"

§4.3–4.4 reproduce `79`'s conclusion from tonight's live prices: 2-hour burst **$0.47–$1.36**; the same
three nodes forgotten overnight **$8.16**; forgotten a month **$141.49 each** against **$163.12** to own
the machine and **$652.47** for the 24 cores they replace; break-even at fleet scale **959–2769
fleet-hours**, i.e. **18–53 years at one fleet-hour a week**. As a *purchase decision about peak capacity*,
renting wins and it wins by decades. **I am not refusing that.**

### 6.2 What I am refusing is arming a trigger that has never fired, on evidence I measured tonight

**SAW-LIVE, 03:45Z 2026-09-17.** Every placement this mesh has ever recorded, out of the dispatcher's own
run logs (`~/.dsh/mesh/logs/*.jsonl`, phase `place`), which `mesh-run.mjs:317-328` has been writing since
the dispatcher landed last night:

| when | run | node | **tier** | position | score |
|---|---|---|---|---|---|
| 2026-09-16 23:24:38Z | `…T23-24-37-421Z` | `zabz-tech` | **fits** | 0 | 20 |
| 2026-09-16 23:26:03Z | `…T23-26-00-586Z` | `secratary` | **fits** | 0 | 22 |
| 2026-09-16 23:27:46Z | `…T23-27-44-800Z` | `zabz-tech` | **fits** | 0 | 20 |
| 2026-09-17 03:35:57Z | `…T03-35-56-769Z` | `zabz-tech` | **fits** | 0 | 18 |
| 2026-09-17 03:36:58Z | `…T03-36-56-368Z` | `zabz-tech` | **fits** | 0 | 18 |
| 2026-09-17 03:37:49Z | `…T03-37-48-965Z` | `zabz-tech` | **fits** | 0 | 18 |

**`tier != "fits"`: zero occurrences, ever.** The trigger requires two of them 60 s apart. At the moment
the last one was recorded, the live broker reported `eligible: 2` and `score: 18`, and `GET /nodes`
(03:35:55Z) showed `zabz-tech` at 18 effective slots and `zabz-yoga-1` at 12 — **30 effective slots across
two transport-capable nodes**, with the mesh at `reads: 24, readFailures: 0` and **`live: 0` leases**.

**The one six-child fleet that was actually dispatched** — the largest job this mesh has ever attempted —
is in that table: `…T03-37-48-965Z`, 6 children, placed `fits` at `position 0` with `score 18`. It then
**failed for a reason that has nothing to do with capacity**: `verify` recorded `meshHostLines: 0` for 6
children and the run ended `result: failed, reason: "only 0 MESH-HOST lines for 6 children"`. Around it,
two one-child runs in the same three minutes produced `meshHostLines: 3` and `1` with a **location
disagreement** (`childHosts: ["zabz-yoga"]` on a run placed on `zabz-tech`).

That is the finding that decides this document. **Tonight's real problem is not that the mesh is full —
it is that the mesh cannot reliably prove where work ran.** An elastic node would add a seventh and eighth
machine to a mesh whose 6-child fleet produced zero child attestations, and every dollar spent on that
capacity would be spent on a symptom that does not exist. `79` §6 reached the same conclusion in one line:
*"Renting a machine the dispatcher cannot reach buys nothing"* — and the measurement has moved one step
past that: the dispatcher *can* reach the machines, and the fleet still did not land.

**And the trigger's own constants are unmeasured**, which is the second half of the refusal. The study's
`tier != "fits"` twice ≥60 s apart is a *recommendation*, not a measurement: **nothing in this program has
ever observed a `tier != "fits"` placement, so the rule's false-positive rate is unknown and its
specificity is unmeasured.** The one thing that *can* be said about it from tonight's data is reassuring
in the narrow sense — with `position 0` six times out of six and 30 slots free, the two-readings rule
would not have fired once, so it is not *obviously* trigger-happy. But "it didn't fire when it shouldn't"
is not the same as "it fires when it should", and only a real miss can measure that.

### 6.3 The measurement that changes my mind — and it is cheap

**The gate is a cadence counter, and it starts tonight.**

> **Automate the elastic tier only when, in a rolling seven-day window, at least TWO fleets of ≥2 children
> were genuinely unplaceable** — that is, `POST /place` returned `tier != "fits"` **or** `position > 0`,
> **twice, ≥60 s apart, ≥60 s after the job was actually wanted**, and **on a mesh where no node was
> unreachable, `capacity-unreadable` or `absent` for a reason other than being switched off.**
> Two in seven days is `79` §6's own number ("a measured cadence of ≥ 2 fleets a week").

**How the counter gets measured, without the elastic tier existing:**

1. `mesh-run.mjs` **already writes `tier` and `position`** into every run log (`:317-328`). Nothing new has
   to be instrumented for a *first* reading — the record is there and I counted it for §6.2 in one command.
2. Add, in the dispatcher (its own file, `packages/plugin-remote-fanout/bin/mesh-run.mjs`), one append to
   `~/.dsh/mesh/elastic/attempts.jsonl` per placement, and one `journal.py append handoff` line when a
   candidate miss is seen. That is ~15 lines and it costs nothing.
3. The counter is read at the start of any substantial session, exactly like `owner-queue.py next` — which
   is the fleet's existing mechanism for "a number that decides something, read when it matters".

**A second measurement, which is O3's and would sharpen the design rather than gate it:** how many
*children* a rented 4-vCPU/8 GB node actually sustains. §4.2 uses `floor(0.75 × 4) = 3` because
`76` §10.3's constant says so, and that constant has never been measured on a rented box. **One sustained
fleet on one rented node, watching `commit`, page-ins and loop lag, replaces the 3 with a measured number
and changes only `config.json`.** Until then, "3 children per CPX31" is arithmetic from an unmeasured
constant and it is labelled as such wherever it appears.

**And the one thing that would make me refuse *permanently*, stated because it is a real possibility:**
if the true cadence is **under 2 unplaceable fleets a week** AND the fleet is something the owner would
want running anyway (a nightly build, a standing work order, a resident agent), then **the $163.12 machine
wins outright**, because its cost is $6.846/mo whether it works or not and renting is $73.49+ the moment
you run it 58 hours a month. In that world the elastic tier is not "not yet" — it is **never**, and the
correct build is one more node in the roster. The number that distinguishes the two worlds is the same
cadence counter, and it is why §6.3 is the deliverable and the provisioner is not.

### 6.4 What I would build tonight if the answer were yes — the order, unchanged from the study

1. the `attempts.jsonl` counter and the two-reading trigger in `mesh-run.mjs`, **shipped `enabled: false`**;
2. `~/.dsh/mesh/elastic/config.json` (§2.4) with mandatory provenance;
3. the provisioner wrapper (§1) — **run by hand once, with the invoice open**, `79` §6's own instruction;
4. the deadman timer and the labeled reaper (§3.2–3.3), **before** the trigger is switched on, because the
   reaper is the thing that makes a mistake cost $1.36 instead of $141.49;
5. the tailnet device-deletion step, which needs a Tailscale API token that **does not exist in this fleet
   today** (§3.4) — until it does, hostname reuse carries the check of §1.1 step 6 and nothing more;
6. and only then, `"enabled": true`, in a session that records the switch in the journal.

---

## 7. What I could not verify

Stated as refusals, not as health.

1. **Any part of the Hetzner Cloud API in practice.** `POST /v1/servers`, `GET /v1/servers?label_selector=`,
   `DELETE /v1/servers/<id>`, the `labels` field, `location: "ash"`, the `ssh_keys` reference and the
   `user_data` field are stated from the provider's public API shape. **Exercising any of them creates a
   server, which this stream is forbidden to do.** The exact command that would verify the one that matters
   (§3.3's orphan sweep) is given there.
2. **The billing term for tonight's prices.** The **hourly rates and monthly caps are SAW-LIVE at
   03:36:12Z**; the *"bill never exceeds the monthly cap, hourly otherwise"* sentence is the study's live
   read from 2026-09-16 23:32Z, **not re-read tonight**. Every figure in §4.3 assumes it.
3. **Whether a reused Tailscale hostname gets suffixed.** Not tested (it needs a node to create). It is
   the one behavioural assumption that could make `mesh-el-1` unreachable, which is why `§1.1` step 6 is a
   hard abort rather than a warning.
4. **Whether the gateway can issue per-node, revocable, scoped model keys.** `79` §7(7) could not verify
   it and neither can I. It decides whether the credential story is a rotation problem or a bookkeeping
   problem. **Unchanged from the study.**
5. **The node's user-data being secret-free after a real boot.** The check is written in §1.5; there is no
   node to run it on.
6. **The true `slots` a rented 4-vCPU node contributes.** §4.2 derives 3 from `76` §10.3's `0.75 × vCPU`,
   a constant calibrated on a 16-core laptop and explicitly unmeasured elsewhere. **This is O3's
   measurement**, and it is the number that decides how many nodes a burst buys.
7. **A Tailscale API token, anywhere in this fleet.** Measured absent (§3.4), so device deletion cannot be
   automated and the design says so rather than assuming it.
8. **`hourlyUsd` and `maxLifetimeSec` reaching the broker in any form.** `lib/config.js:88-103` drops both.
   I did not change it (not my file); I designed around it and said so in §2.1.
9. **The cloud's own reported latency to the office.** `79` §3.1's 10–20 ms from Ashburn is an inference
   from geography, and it was not measured — neither VPS has Tailscale installed and no node was created.
   It is a reason to prefer US-East over Falkenstein, not a fact.
10. **The price of the machine in §4.4.** $152.98 / $163.12 taxed is `61` §4.2's live listing from
    2026-09-16. **I did not re-check the listing tonight**; the eBay item may be gone. Everything in §4.4
    scales with it linearly.
