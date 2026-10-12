# 187 ΓÇö TRANSPORT ROBUSTNESS AND FALLBACK: the measured state, and the fallback that was missing

**Written 2026-10-12 from `zabz-tech`** (hostname `ZABZ-TECH`, Windows NT 10.0.26200.0, office LAN
`192.168.50.138`), `harness-config` on `main`.
**Governing policy:** `docs/mesh/143-TRANSPORT-POLICY.md` ΓÇö LAN, then Tailscale, then Cloudflare,
**measured and never assumed**. `docs/mesh/000-SYSTEMS-REGISTER.md` ┬º1 and ┬º2.3.
**Provenance:** **MEASURED** = the command was run in this session and its output is quoted.
**READ** = read from a file or a git object, with the path. Nothing is asserted.

**Every claim carries the command that produced it and the machine it ran on.**
**No service was started, stopped, enabled, disabled, masked, unmasked or restarted.** `secratary`
was touched with read-only commands only (`ssh ΓÇª 'echo ΓÇª'`). No DNS record was changed. No promotion
or failover was performed.

> ### A note on the third document the task named
> `docs/mesh/159-MESH-POST-MIGRATION.md` **does not exist** in this checkout (measured:
> `ls docs/mesh/159-*` ΓåÆ only `159-DIALPAD-GAP-FINAL-STATE.md`). **It is cited by name in two
> files that are deployed**, `scripts/phone-gate-allow.txt` and
> `journal/scripts/phone-gate-allow.txt`, both of which say *"Recorded in
> docs/mesh/159-MESH-POST-MIGRATION.md"* while explaining the most load-bearing line in the
> gate's allow-list. A document that governs the mesh and is cited from the mesh's own security
> file, but is absent from the repository, is **SPOF 9** below. This audit used `143`, `000`
> ┬º1/┬º2.3, `126` and `127` as instructed, and `159-DIALPAD-GAP-FINAL-STATE.md` as the nearest
> real neighbour.

---

## 1. Transport in use, per pair ΓÇö MEASURED

Command: `tailscale status --json` and `tailscale ping --c 5 <peer>` on `zabz-tech`; `ping -n 4`
for ICMP; `ssh -o BatchMode=yes ΓÇª 'true'` wrapped in a stopwatch for the ssh round trip (5
successful attempts each); `curl -m 8 -w '%{http_code} %{time_total}'` for the API paths.

### 1.1 Path and latency matrix

`ssh RTT` is a full connect + auth + exit, so it is dominated by key exchange, not by the wire ΓÇö
that is why it is 200ΓÇô380 ms even to a box 1 ms away. **`RTT` is the right column for "how fast is
this path"; `ssh RTT` is the right column for "how long does a dispatch handshake cost".**

| source | target | path | RTT | tailscale ping | ssh RTT |
|---|---|---|---|---|---|
| `zabz-tech` | `secratary` | **LAN** `192.168.50.77` | 0 ms | 1 ms (direct) | **217 ms** |
| `zabz-tech` | `secratary` | **Tailscale** `100.84.72.88` | 1 ms | 1 ms (direct) | **220 ms** |
| `zabz-tech` | `zabz-tech-linux` | **LAN** `192.168.50.23` | 0 ms | 2 ms (direct) | **266 ms** *(measured via `linux-pc-lan`)* |
| `zabz-tech` | `zabz-tech-linux` | **Tailscale** `100.105.248.90` | 1 ms | 2 ms (direct) | **269 ms** |
| `zabz-tech` | `lakewooechsmini` | **Tailscale** `100.126.146.121` | **40 ms** (min 3, max 104) | 70 ms (direct) | **250 ms** |
| `zabz-tech` | `lakewooechsmini` | **LAN** `192.168.50.73` | **64 ms** (min 3, max 87) | ΓÇö | **326 ms** |
| `zabz-tech` | `secratary-cloud` | **Tailscale** `178.156.194.1:41641` | **11 ms** | 12 ms (direct) | **350 ms** |
| `zabz-tech` | `secratary-cloud` | **Tailscale name** `secratary-cloud` | 11 ms | 12 ms | **375 ms** |
| `zabz-tech` | `secratary-cloud` | **public** `178.156.194.1:22` | 13 ms | ΓÇö | **OK** (`ssh -v`: *Server accepts key: id_ed25519_hetzner*) |
| `zabz-tech` | `zabz-yoga-1` | **Tailscale** `172.59.214.144:14823` | 52 ms | 52 ms (direct) | **1833 ms** |
| `zabz-tech` | `zabz-yoga-1` | **LAN** | **no path** ΓÇö home vs office | ΓÇö | `192.168.50.244` is the OFFICE value |
| `zabz-tech` | `mac-mini` alias | `192.168.50.45` | **100 % loss** | ΓÇö | **SPOF 7** |

**What this says.** Every reachable peer resolved to a **direct** path, and none is relayed (┬º2).
The LAN column is *not* meaningfully faster than the tailnet column for the wired boxes: both are
0ΓÇô2 ms, so the WireGuard hop costs nothing measurable at this distance. **The LAN's real value is
that it does not depend on the Tailscale control plane** ΓÇö the same reason `143` ranks it first.
The wifi Mac mini is 40ΓÇô64 ms with 87ΓÇô104 ms spikes and is the only jittery peer on the estate.

### 1.2 The two API paths for the authority (the `143` precedence, re-measured)

| path | URL | result |
|---|---|---|
| **tailnet (private)** | `https://secratary-cloud.tail93e6e6.ts.net:8443/health` | **200**, `0.073` / `0.085` / `0.095` / `0.084` s ΓÇö 4/4 |
| **public (Cloudflare)** | `https://api.abletelsolutions.com/health` | **200**, `0.146` / `0.092` / `0.090` / `0.072` s ΓÇö 4/4 |

**`143`'s "RESOLVED 2026-10-11" block still holds**: the authority **does** have a private path, and
it answers. As `143` itself predicted, the tailnet door is *not faster* ΓÇö the gain is that it does
not traverse Cloudflare, public DNS or the tunnel process.

---

## 2. Is Tailscale healthy, and how is every node connected? ΓÇö MEASURED

Command: `tailscale status`, `tailscale status --json`, `tailscale ping --c 5 <peer>` on `zabz-tech`.

| node | tailnet address | online | connection type | endpoint | best DERP (home region) |
|---|---|---|---|---|---|
| `zabz-tech` (self) | `100.85.153.96` | yes | ΓÇö | ΓÇö | `nyc` |
| `secratary-cloud` | `100.73.176.126` | yes | **direct** | `178.156.194.1:41641` | `iad` |
| `secratary` | `100.84.72.88` | yes | **direct** | `192.168.50.77:41641` | `nyc` |
| `zabz-tech-linux` | `100.105.248.90` | yes | **direct** | `192.168.50.23:41641` | `nyc` |
| `zabz-yoga-1` | `100.72.162.5` | yes | **direct** | `172.59.214.144:14823` | `nyc` |
| `lakewooechsmini` | `100.126.146.121` | yes | **direct** | `192.168.50.73:51184` | `nyc` |
| `iphone-15-pro` | `100.85.105.93` | yes | idle, not exercised | ΓÇö | `nyc` |
| `ipad-air-5th-gen-wifi` | `100.76.204.64` | no (1 min) | ΓÇö | ΓÇö | `nyc` |
| `iphone-11` | `100.118.10.22` | no (2 d) | ΓÇö | ΓÇö | `nyc` |
| `iphone-11-1` | `100.119.73.69` | no (18 h) | ΓÇö | ΓÇö | `nyc` |
| `iphone-se-gen-2` | `100.73.102.5` | no (5 d) | ΓÇö | ΓÇö | `nyc` |

**Answer to "which peers are relayed?": NONE.** `tailscale ping --c 5` answered **every** peer on a
**direct** endpoint ΓÇö `pong from secratary-cloud ΓÇª via 178.156.194.1:41641 in 12ms`, and the same
shape for all five. Relaying is the slow path and the estate has none of it today.

**The measurement trap, recorded so nobody repeats it.** A *cold* `tailscale status --json`
reports **no `CurAddr`** for a peer that is idle (it prints `Relay: nyc`), and it is easy to read
that as "on a DERP relay". It is **demand-driven**: `zabz-tech-linux` and `lakewooechsmini` showed
an empty `CurAddr` before they were pinged and a direct one immediately after, with no relay in
either reading. **A cold status is not evidence of a relay.** Corroborating evidence:
`tailscale netcheck` on `zabz-tech` reports `UDP: true`, `MappingVariesByDestIP: false`,
`PortMapping: UPnP, NAT-PMP, PCP`, and DERP latency `nyc 7.3ms`, `iad 16.8ms`.

---

## 3. The Cloudflare fallback: what it carries, and whether it works ΓÇö MEASURED

### 3.1 What Cloudflare carries today

`cloudflared` is present on the authority, and the estate has **two kinds** of Cloudflare path:

| path | mechanism | what it carries |
|---|---|---|
| **`api.abletelsolutions.com`** | cloudflared tunnel, `localhost:8002` | the company **public API** ΓÇö **200**, 4/4 |
| **`ai.abletelsolutions.com`** | cloudflared tunnel, `localhost:3000` | the **dashboard** |
| **`secretary-ssh.abletelsolutions.com`** | cloudflared **Access** + ssh | was the **office box** ΓÇö **DOWN today** (┬º3.3) |
| **`desktop-ssh.abletelsolutions.com`** | cloudflared **Access** + ssh | **`zabz-tech` itself** (┬º3.2) |

**It carries the company's public API/dashboard. It does NOT carry the mesh.** See ┬º3.4.

### 3.2 The Cloudflare path WORKS ΓÇö proven, read-only

I did **not** run the estate's `desktop-cf`/`secretary-cf` aliases, because the wrapper they invoke
is **not inert** (┬º3.5). I exercised `cloudflared` directly instead. The credentials came from
`personal-secretary-mvp/.env` **by name only** (`CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET`,
values never printed) and were passed through the **environment**, never argv:

```
cloudflared access tcp --hostname desktop-ssh.abletelsolutions.com --url 127.0.0.1:34541
ssh -p 34541 -i ~/.ssh/zabz-tech-ed25519 ezabz@127.0.0.1 'echo CF_PATH_WORKS=yes host=$(hostname)'
```

**Result: `CF_PATH_WORKS=yes host=zabz-tech`, exit 0.** The origin banner read over the tunnel was
`SSH-2.0-OpenSSH_for_Windows_9.5`, and `desktop-ssh.abletelsolutions.com` resolves to Cloudflare
edge (`172.67.172.153`, `104.21.71.247`). **The Cloudflare Access + ssh transport is real and it
works end to end ΓÇö to `ZABZ-TECH`, the machine that runs the connector.** It proves the mechanism;
it is **not** a route to any other node.

### 3.3 `secretary-ssh` ΓÇö the documented office fallback is DEAD

```
cloudflared access tcp --hostname secretary-ssh.abletelsolutions.com --url 127.0.0.1:34522
ΓåÆ ERR failed to connect to origin error="websocket: bad handshake"
   originURL=https://secretary-ssh.abletelsolutions.com
```

The edge is reached and the **tunnel has no healthy connector** (the office `cloudflared` was
stopped by the cutover and the box is frozen, per `126` Stage 8 / `131` Rule 1 ΓÇö correctly so). But
the hostname still resolves, and `~/.ssh/config` still offers `secretary-cf`. **The estate believes
it has a Cloudflare fallback to the office box; it does not have one.** A fallback that has never
been fired is not a fallback (`000` ┬º4 trap 6, in spirit).

### 3.4 Is there a transport fallback for the MESH specifically? ΓÇö **NO, and here is the proof**

This is the central finding of the audit.

**READ, `scripts/mesh/route.sh` lines 79ΓÇô94** ΓÇö the mesh role has no Cloudflare row, deliberately:

```bash
MESH_ROWS=(
  "loopback|secratary-cloud|http://127.0.0.1:3089"
  "tail|secratary-cloud|https://secratary-cloud.tail93e6e6.ts.net"
  # no flare row: the mesh gate is deliberately not public (docs/mesh/143)
)
```

**READ, `packages/plugin-remote-fanout/lib/nodes.js`** ΓÇö the mesh's **supply** of children names
exactly **one** ssh destination per node, and **every one is a tailnet MagicDNS name**:

| broker node | `ssh` destination | transport | second path? |
|---|---|---|---|
| `zabz-tech` | `desktop-ts` | Tailscale MagicDNS | **none** |
| `zabz-yoga-1` | `laptop-ts` | Tailscale MagicDNS | **none** |
| `zabz-tech-linux` | `linux-pc-ts` | Tailscale MagicDNS | **none** |
| `secratary` | `secratary-ts` | Tailscale MagicDNS | **none** |
| `lakewooechsmini` | `mac-mini-ts` | Tailscale MagicDNS | **none** |

**READ, `packages/plugin-remote-fanout/lib/ssh-transport.js`** ΓÇö `createSshTransport()` is the only
transport in the file and it spawns `ssh` against that single `config.target`.

**Therefore: if Tailscale is down ΓÇö or MagicDNS alone stops resolving ΓÇö a mesh dispatch simply
fails.** There is no second attempt, no address spelling, no HTTP path, and no fallback. The whole
fleet leaves at once, which is exactly the failure shape `143` exists to prevent.

**And it has already happened once on this estate.** `~/.ssh/config` carries a standing note
measured on `zabz-tech`: on **2026-09-28 between 18:18Z and 18:32Z MagicDNS resolution of
`secratary.tail93e6e6.ts.net` failed four times while the Tailscale service was up and the peer was
`active; relay nyc`.** The fix applied that night was `Host secratary-ip` ΓåÆ the bare `100.84.72.88`.
**The reasoning was correct and it was applied to one node by hand; it was never generalised.** That
is the gap this audit closes (┬º4).

### 3.5 A defect in the documented fallback, found and NOT run

`~/.ssh/config` aliases `desktop-cf` and `secretary-cf` invoke
`personal-secretary-mvp/scripts/windows/CloudflaredAccessSshProxy.ps1`. **READ, lines 89ΓÇô117**: before
connecting, that script calls `Remove-StaleTunnelConnectors`, which issues
`DELETE https://api.cloudflare.com/client/v4/accounts/<id>/cfd_tunnel/<tunnel>/connections?client_id=<id>`
ΓÇö it **deletes live connectors on a production tunnel** when it finds more than one, keeping only
the highest `client_version`.

**So using the estate's documented Cloudflare ssh fallback can tear down a live tunnel connector.**
It is not inert, so I did not run it; ┬º3.2 tested the transport with `cloudflared` directly instead.
This is **SPOF 8**. The `CF_API_TOKEN` in `.env` is valid and active (verified read-only against
`/user/tokens/verify`), so the DELETE would be attempted for real.

### 3.6 Read-only tests deliberately SKIPPED, and why

| test | why skipped |
|---|---|
| `company-promote.py --dry-run` on `lpt-survivor-01` | it is a **failover driver**; the task forbids promotion and the register's ┬º2.1 already records it as **PROVEN 2026-10-06** with five pre-flight refusals. Re-running it risks touching public DNS for a fact already established. |
| `desktop-cf` / `secretary-cf` as configured | ┬º3.5 ΓÇö the wrapper issues a **DELETE** against the Cloudflare API. |
| Cloudflare API tunnel/DNS enumeration | `CF_API_TOKEN` returned **`{"code":1001,"message":"Not authorized"}`** for `GET /accounts/<id>/cfd_tunnel`. The token is scoped below tunnel-read. Reported as a measurement gap, not worked around. |
| Any `systemctl` verb on `secratary` | the box is **FROZEN**; `scripts/mesh/guard-service-state.sh --host secratary --op <op>` refuses, and that refusal is correct. Only `ssh ΓÇª 'echo'` was used. |

---

## 4. The fallback: proposed, implemented where safe, and verified

### 4.1 The gap, stated in one sentence

**The mesh's supply of children has exactly one transport ΓÇö `ssh` over Tailscale, addressed by
MagicDNS ΓÇö and no second path is configured anywhere in the dispatch code, so a Tailscale or
MagicDNS failure removes the entire fleet at once.**

### 4.2 What I implemented ΓÇö no service state touched, both reversible

**Implementation 1 ΓÇö `scripts/mesh/install-mesh-ip-aliases.ps1`** *(new)*

Installs **11 address-spelling ssh aliases** into `~/.ssh/config`. This is the generalisation of the
2026-09-28 `secratary-ip` fix that was applied to one node by hand. Every address was **read from
`tailscale status --json` on `zabz-tech` on 2026-10-12**; every user was **confirmed by the
connection that succeeded**; no address or user is guessed.

```powershell
.\scripts\mesh\install-mesh-ip-aliases.ps1 -DryRun   # show, change nothing
.\scripts\mesh\install-mesh-ip-aliases.ps1           # install (idempotent; backs up first)
.\scripts\mesh\install-mesh-ip-aliases.ps1 -Remove   # remove the managed block
```

**ALL 11 VERIFIED with a live read-only `echo hostname`** (2026-10-12, from `zabz-tech`):

```
OK  desktop-ts-ip            exit=0  host=zabz-tech
OK  desktop-lan              exit=0  host=zabz-tech
OK  secratary-ip             exit=0  host=secratary
OK  secratary-lan            exit=0  host=secratary
OK  linux-pc-lan             exit=0  host=zabz-tech-linux
OK  linux-pc-ts-ip           exit=0  host=zabz-tech-linux
OK  laptop-ts-ip             exit=0  host=zabz-yoga
OK  mac-mini-lan             exit=0  host=LakewooechsMini
OK  mac-mini-ts-ip           exit=0  host=LakewooechsMini
OK  secratary-cloud-ip       exit=0  host=secratary-cloud      <- NEW out-of-band path: survives a MagicDNS failure
OK  secratary-cloud-public   exit=0  host=secratary-cloud      <- NEW out-of-band path: public IPv4, no tailnet at all
```

Backup written before the first change: `~/.ssh/config.bak-before-187-20261012-120948`.
**The two authority rows are the substantive win**: `secratary-cloud-ip` removes the MagicDNS
dependency for the box that runs `mesh-broker`, and `secratary-cloud-public` gives the authority a
path that needs **neither the tailnet nor MagicDNS nor Cloudflare**.

**Implementation 2 ΓÇö `scripts/mesh/route-mesh.ps1`** *(new)*

The **mesh-node counterpart to `route.sh` / `Resolve-MeshPath.ps1`**. Those two answer "which base
URL for the **authority**"; neither answers "how do I reach a **worker node**", which is the question
a dispatch actually asks. This script measures every transport spelling per node and reports **the
one that answered, with the evidence and what the others did** ΓÇö `143` ┬º5 requirements 1, 2 and 3.
It is **read-only** (`ssh ΓÇª exit 0`, an HTTP GET, a single posture read) and starts nothing.

Measured run, 2026-10-12 16:09:58Z from `zabz-tech`:

```
zabz-tech          lan       -> desktop-lan      (402ms)   [tail-name ok 385ms, tail-ip ok 378ms]
secratary          lan       -> secratary-lan    (216ms)   [tail-name ok 271ms, tail-ip ok 231ms]
zabz-tech-linux    lan       -> linux-pc-lan     (266ms)   [tail-name ok 277ms, tail-ip ok 269ms]
zabz-yoga-1        tail      -> laptop-ts       (1833ms)   [tail-ip ok 1830ms, NO LAN PATH]
lakewooechsmini    lan       -> mac-mini-lan     (326ms)   [tail-name ok 216ms, tail-ip ok 250ms]

AUTHORITY  tail-name secratary-cloud ok 350ms | tail-ip secratary-cloud-ip ok 336ms | public secratary-cloud-public ok 354ms
```

**Every node now has at least two measured paths, and four of five have three.** Exit contract
verified: `0` every node answered ┬╖ `3` a node answered on no transport ┬╖ `4` nothing was probed.
`-Node nonexistent` returned **4**; `-Node zabz-tech` returned **0**.

**A real bug this script found in its own first draft, kept because it is the same class of error as
SPOF 5.** The first draft probed **bare addresses**. `ssh 192.168.50.77` carries no account, so it
tried the local user `ezabz` and was **refused** on a box whose account is `zabz` ΓÇö and the script
duly reported **three healthy LAN paths as dead**. A transport test that gets the credential wrong
libels a working path. Every candidate is now an **alias** that carries the user and the key.

### 4.3 What I did NOT implement, and whose decision it is

The **dispatch code itself still has one path per node.** `nodes.js` and `ssh-transport.js` were
**read, not modified**. Wiring the measured fallback into the dispatcher means either

1. adding a `sshFallbacks: []` array per row in `packages/plugin-remote-fanout/lib/nodes.js` and a
   retry loop in `ssh-transport.js` ΓÇö a **code** change, deployable by a normal commit, and the
   right next step; or
2. mounting `plugin-mesh-http` into the default dispatch path ΓÇö see ┬º5, where the capability is
   already built and merely unwired.

Both are development decisions, not the owner's (**AGENTS.md ┬º2**). The reason I stopped at the
transport layer is the task's own rule: I may add a fallback that needs **no service change**, and
these two are service/code deployments rather than read-only measurements. **The exact plan is in
┬º5.3.**

---

## 5. Every single point of failure, ranked

Ranked by **blast radius ├ù likelihood**, with the measured evidence for each.

| # | SPOF | blast radius | evidence (machine + command) |
|---|---|---|---|
| **1** | **The mesh's only transport is `ssh` over Tailscale, addressed by MagicDNS, one name per node.** | **the whole fleet, at once** | READ `nodes.js` (one `ssh:` per node, all `-ts`); READ `ssh-transport.js` (single `config.target`); READ `route.sh` `MESH_ROWS` (**no flare row**). Measured 2026-09-28: MagicDNS failed 4├ù in 14 min while Tailscale was up. |
| **2** | **The mesh's fallback capability `plugin-mesh-http` EXISTS and is UNWIRED.** Every node answers `GET /mesh/capacity` 200 over the tailnet, but the default dispatcher does not use it. | entire fleet | MEASURED 2026-10-12 from `zabz-tech`, 6/6 and 1/1: `zabz-tech` 200/0.056s, `secratary` 200/0.053s, `zabz-tech-linux` 200/0.031s, `zabz-yoga-1` 200/0.484s, `lakewooechsmini` 200/0.291s, `secratary-cloud` 200/0.059s. READ `plugin-mesh-http/package.json`: *"so dispatch stops depending on ssh."* |
| **3** | **`phone-gate.py` + `phone-gate-allow.txt` is a chokepoint on every node, and it has already caused total mesh blindness once.** | entire fleet | READ `phone-gate-allow.txt`: *"MEASURED, 2026-10-12 03:18Z, before this line existed: from the cloud every node answered HTTP/2 403 ΓÇª 5 of 5 nodes unreachable, 0 free slots"* ΓÇö the broker placed every child on one machine. A **missing or empty** allow-file **fails OPEN** and signs in every tailnet device (READ, the file's own header): a security failure, and the opposite of the availability one. |
| **4** | **`mesh-broker` is a single loopback instance on the FROZEN office box** (`127.0.0.1:3091` on `secratary`). | placement for the whole fleet | READ `000` ┬º2.3; READ `154-MESH-BROKER-MOVE.md`. Mitigated, not removed: `failover-placer.js` reads every node's `/mesh/health` directly when the broker is unreachable ΓÇö *"the broker is an optimisation, not a veto."* The fix needs the office copy stopped, i.e. **a state change on a frozen host ΓçÆ the owner's call.** |
| **5** | **Bare addresses and wrong users silently libel working paths** ΓÇö the same error class as SPOF 3. | misdiagnosis; dispatches rerouted or refused | MEASURED 2026-10-12: my first `route-mesh.ps1` draft probed `ssh 192.168.50.77`, which tried `ezabz@` and was **refused** on a box whose account is `zabz`, and reported **three healthy LAN paths as dead**. |
| **6** | **`secratary-cloud` is the sole authority and the broker's host; its tailnet path is single-spelled.** | authority, API, broker | MEASURED: it answers on the tailnet name (12 ms), direct via `178.156.194.1:41641` ΓÇö but `route.sh` `API_ROWS`/`MESH_ROWS` and `nodes.js` each name **one** spelling. Mitigated **today** by `secratary-cloud-ip` + `secratary-cloud-public` (┬º4.2). |
| **7** | **`mac-mini` in `~/.ssh/config` points at `192.168.50.45`, which does not answer.** The live peer is `192.168.50.73`, wifi, 40ΓÇô104 ms. | one node, plus the workspace's own documentation | MEASURED: `ping -n 4 192.168.50.45` ΓåÆ **100 % loss**; the tailnet peer's `CurAddr` is `192.168.50.73:51184`; ICMP to `.73` min 3 / max 87 / avg 64 ms while wired peers are 0ΓÇô1 ms. `personal-secretary-mvp/AGENTS.md` also records `.45`. Mitigated by `mac-mini-lan` ΓåÆ `.73` (┬º4.2). |
| **8** | **The documented Cloudflare ssh fallback can DELETE live tunnel connectors.** | **production public API/dashboard**, if ever used under stress | READ `CloudflaredAccessSshProxy.ps1` lines 89ΓÇô117: `DELETE ΓÇª/cfd_tunnel/<id>/connections?client_id=ΓÇª`. `CF_API_TOKEN` verified **active**. Not run. |
| **9** | **`docs/mesh/159-MESH-POST-MIGRATION.md` is cited by name from two deployed files and does not exist.** | the reasoning behind the gate's most load-bearing line is unrecoverable on the nodes | MEASURED: `ls docs/mesh/159-*` ΓåÆ only `159-DIALPAD-GAP-FINAL-STATE.md`. READ `scripts/phone-gate-allow.txt` and `journal/scripts/phone-gate-allow.txt`, both citing it. |
| **10** | **`secretary-ssh.abletelsolutions.com` resolves and is advertised but has no healthy connector.** | an office fallback the estate believes it has | MEASURED: `ERR failed to connect to origin error="websocket: bad handshake"`. |
| **11** | **Tailscale's control plane is a hard dependency with no estate-level watchdog.** | new connections fleet-wide | Behavioural, and consistent with `143`'s own table: *"fails when ΓÇª the control plane is down, a key expires, a node is not joined."* Keys are already `key expiry DISABLED` (`126` Stage 1a step 7). |
| **12** | **The wifi Mac mini is the only jittery peer** (87ΓÇô104 ms spikes vs 1 ms wired). | one node; placement quality | MEASURED `ping -n 4`: min 3 / max 87 / avg 64 ms; `tailscale ping` 70 ms. Not fatal; **its capacity readings are noisy and a placement that trusts them ranks it wrongly.** |

**The ranking's headline.** SPOF 1 is the one that matters: it is a **total, simultaneous** loss, it
has already fired once (2026-09-28), the code that carries it names one path per node, and the
fallback mechanism is **already built and answering** (SPOF 2) ΓÇö so the highest-value repair is not
new machinery, it is **wiring what exists**, which is AGENTS.md ┬º0 followed rather than violated.

### 5.3 The exact plan for the one thing I could not implement without a code change

**Whose decision:** a development decision (**AGENTS.md ┬º2**), not the owner's. Recorded here,
unimplemented, because it is a deployable code change rather than a read-only measurement.

1. In `packages/plugin-remote-fanout/lib/nodes.js`, add to each row an ordered
   `sshFallbacks: []` naming the address-spelling aliases verified in ┬º4.2 ΓÇö e.g. for `zabz-tech`
   `['desktop-ts-ip', 'desktop-lan']`, for `secratary` `['secratary-ip', 'secratary-lan']`.
   **Keep `ssh` first** so today's behaviour is unchanged when the tailnet is healthy.
2. In `packages/plugin-remote-fanout/lib/ssh-transport.js`, on a spawn error or a non-zero exit
   **before any output is written**, retry down the list; report the destination that worked in the
   result frame so `posture.js`'s wrong-machine check still sees the real target.
3. Add a `mesh-transport` probe to the existing node probe that runs `route-mesh.ps1 -Json` and
   files a journal `pain` entry when **any** node drops to a single path. A fallback nobody measures
   becomes an untested fallback, which is the bug `143` exists to prevent.
4. Consider mounting `plugin-mesh-http` into the default path for the **second** fallback, since
   `POST /mesh/run` already exists, is HMAC-authenticated, and is explicitly designed for this.
   That one needs a plugin mount, i.e. an engine restart ΓÇö **a service change, and therefore a
   separate, scheduled decision.**

---

## 6. What I could not verify ΓÇö stated plainly

1. **Cloudflare tunnel/DNS state via the API.** `CF_API_TOKEN` returned `{"code":1001,"message":"Not authorized"}` for `GET /accounts/<id>/cfd_tunnel`. ┬º3 conclusions rest on **direct connection tests** (┬º3.2, ┬º3.3) and on `README`/config reads, not on the API.
2. **The mac mini's cold-start behaviour is not characterised.** Two initial `GET /mesh/capacity` attempts returned `http=000` after **21.0 s**; minutes later the same probe returned **6/6 ├ù 200**, avg 0.080 s. **I am not calling it dead** ΓÇö the honest statement is *intermittent from cold, healthy once warm*, and the cause is unmeasured.
3. **Latency from any machine other than `zabz-tech`.** Every number in ┬º1 was measured on this host. `zabz-yoga-1`'s 1833 ms ssh RTT in particular may be dominated by *this* Windows client's key exchange, not by the laptop.
4. **Whether `ssh-transport.js` would actually recover on a fallback destination.** Its retry behaviour was **read**, not exercised, because exercising it means a real dispatch.
5. **`lpt-survivor-01` and the cutover tooling.** Not run at all (┬º3.6); the failover proof is READ from `000` ┬º2.1, dated 2026-10-06.
6. **The office box's service state.** Deliberately not inspected beyond the gate's HTTP answer ΓÇö `secratary` is FROZEN and read-only, and this audit had no business reading further.
7. **Why `159-MESH-POST-MIGRATION.md` is absent** ΓÇö whether it was never committed, was renamed, or exists only on another node. Its content is unrecoverable from this checkout.
8. **`mac-mini`'s `.45` vs `.73`** ΓÇö I measured that `.45` does not answer and `.73` does. I did not determine whether `.45` is a stale DHCP reservation or a second NIC.

---

## 7. Appendix ΓÇö the commands this document is built on

```powershell
# --- on zabz-tech (ZABZ-TECH), 2026-10-12 ---
tailscale status ; tailscale status --json ; tailscale ping --c 5 <peer> ; tailscale netcheck
ping -n 4 192.168.50.77        # and .23 .73 .45 .138
ssh -o BatchMode=yes -o ConnectTimeout=10 <alias> 'echo H=$(hostname)'     # 5x each, timed
ssh -v -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1 'echo RANON=OK'
curl.exe -s -m 8 -o NUL -w "%{http_code} %{time_total}" https://secratary-cloud.tail93e6e6.ts.net:8443/health
curl.exe -s -m 8 -o NUL -w "%{http_code} %{time_total}" https://api.abletelsolutions.com/health
curl.exe -s -m 20 https://<node>.tail93e6e6.ts.net/mesh/capacity          # every node; 6x for reliability

# --- the Cloudflare path, proven WITHOUT the connector-deleting wrapper ---
$env:TUNNEL_SERVICE_TOKEN_ID=<CF_ACCESS_CLIENT_ID>       # from personal-secretary-mvp/.env, names only
$env:TUNNEL_SERVICE_TOKEN_SECRET=<CF_ACCESS_CLIENT_SECRET>
cloudflared access tcp --hostname desktop-ssh.abletelsolutions.com --url 127.0.0.1:34541
ssh -p 34541 -i ~/.ssh/zabz-tech-ed25519 ezabz@127.0.0.1 'echo CF_PATH_WORKS=yes host=$(hostname)'
cloudflared access tcp --hostname secretary-ssh.abletelsolutions.com --url 127.0.0.1:34522
#   -> ERR failed to connect to origin error="websocket: bad handshake"

# --- the failover I added and verified ---
.\scripts\mesh\install-mesh-ip-aliases.ps1 -DryRun
.\scripts\mesh\install-mesh-ip-aliases.ps1
.\scripts\mesh\route-mesh.ps1 -Explain -TimeoutSec 8
.\scripts\mesh\route-mesh.ps1 -Node nonexistent       # exit 4, nothing probed
.\scripts\mesh\install-mesh-ip-aliases.ps1 -Remove    # the reversal
```
