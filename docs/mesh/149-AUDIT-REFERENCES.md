# 149 — REFERENCES TO A DEAD MACHINE

**The audit class.** Not "is the office box off?" but "what still *points* at the office box, or at a
laptop, and what breaks the moment it is gone?" This document exists because a real miss was already
found: the owner's phone route redirected to the old office box, which no longer runs the phone
software it needed, and nobody noticed for hours while every health check was green.

**Scope.** The office box `secratary` (tailnet `secratary.tail93e6e6.ts.net`, tailnet IP
`100.84.72.88`, LAN `192.168.50.77`) is FROZEN as the rollback anchor and intended to be RETIRED.
`secratary-cloud` (`100.73.176.126`, public `178.156.194.1`) is the authority. `zabz-yoga-1`
(`100.72.162.5`) is the owner's laptop and is **not always on**. `zabz-tech` (`100.85.153.96`),
`zabz-tech-linux` (`100.105.248.90`), `lakewooechsmini` (`100.126.146.121`) are the other nodes.

**How this was produced.** Six independent workstreams were dispatched over the durable mesh — measured
placement: Cloudflare → `zabz-tech`; code grep → `zabz-tech`; per-machine config → `zabz-tech`
(reaching the laptop over ssh); shutdown forecast → `zabz-tech`; `ps_*`/MCP → `lakewooechsmini` (mac
mini); authority sweep → `lakewooechsmini`. **Zero of the six ran locally.** The Cloudflare read and the
phone-route finding were then **re-verified by me directly** from this laptop, and that re-verification
**corrected** the workstream's own reading (§1.3). Office-box commands were read-only and bounded
throughout; measured load during every office pass was 0.02–0.43.

**Measurement window.** 2026-10-11 15:48Z – 16:06Z. Everything below is timestamped; a later reader
should treat the cloud-box configuration, which was being actively edited during this window, as the
only part likely to have moved.

---

## §1 — CLOUDFLARE: every tunnel, every hostname, and where each one lands

### 1.1 Account and zone (provenance: `secratary-cloud`, `GET /client/v4/...` with `CF_API_TOKEN` from `/opt/company/.env`; values never printed)

| | value |
|---|---|
| account | `3fe00f424ec43810af16b55df54200a3` ("Abletelsolutions@gmail.com's Account") |
| zones | exactly one: `abletelsolutions.com` (`9cbca1d10b6a627ecc7593ce775ea82b`), NS `aron.ns.cloudflare.com`, `patryk.ns.cloudflare.com` |
| token | `GET /user/tokens/verify` → 200, `status: active` |
| zone DNS records | 30, complete (`count=30 total_count=30`) |

`lakewoodphoneandtech.com` is **not** in this account (`GET /zones?name=` → 0) — a webhook that points
there is therefore unmeasured, not verified (§5.3).

### 1.2 Every tunnel on the account (`GET /accounts/{acct}/cfd_tunnel?is_deleted=false` → count **7**)

`origin_ip` is Cloudflare's own view of which box the connector is running on.

| tunnel (id 8) | name | running on | status | conns | config source |
|---|---|---|---|---|---|
| `ef0b79cb` | home-services | — nothing | **down** | 0 | local |
| `2d0d8178` | homeassistant | `71.104.140.242` (office WAN, not the office box) | healthy | 4 | local |
| `829bc0fb` | **personal-secretary-ai** | `71.104.140.242` = **the frozen office box** | healthy | 4 | local |
| `3e62916c` | **personal-secretary-cloud** | `2a01:4ff:f0:c193::1` = secratary-cloud | healthy | 4 | local |
| `ad86d2a9` | personal-secretary-desktop-ssh | — nothing | **down** | 0 | local |
| `b69e2492` | secretary-standby | `2a01:4f8:c016:891a::1` (a second Hetzner host, no PTR) | healthy | 4 | cloudflare (remote) |
| `9fcb6858` | yocheved-ssh | — nothing | **down** | 0 | cloudflare (remote) |

**`829bc0fb` — the office tunnel — was never stopped at the cutover.** Its connections opened
`2026-10-11T02:42:12Z` and were still up at measurement. Nothing in the freeze touched it.

### 1.3 The hostname table

Binding is by `CNAME → <tunnel-uuid>.cfargotunnel.com`; every tunnelled record is proxied, so `dig`
from outside shows Cloudflare anycast only. "Exists today" was answered by asking **the machine the
tunnel runs on, right now**, not by reading a config.

| # | hostname | tunnel | ingress target | does that target exist TODAY (evidence) | lands where | verdict |
|---|---|---|---|---|---|---|
| C1 | `ai.abletelsolutions.com` | `3e62916c` personal-secretary-cloud | `http://127.0.0.1:3000` | YES — `ss -ltnp` → `*:3000 next-server pid=1089`, `secretary-dashboard` active; public `curl` → **307** | secratary-cloud | **OK** |
| C2 | `ai.abletelsolutions.com/phone` | `3e62916c` | `http://127.0.0.1:3087` | YES — `127.0.0.1:3087 python3 pid=137711`; `curl -i :3087/phone` → **302 `Location: https://secratary-cloud.tail93e6e6.ts.net/`** | secratary-cloud → **now self-contained** | **OK (was POINTS AT OFFICE BOX until 15:33:49Z, then POINTS AT LAPTOP, fixed 15:53:55Z — see §1.4)** |
| C3 | `api.abletelsolutions.com` | `3e62916c` | `http://127.0.0.1:8002` | YES — `127.0.0.1:8002 python pid=105362`, `company-api` active, `/health` **200**, public **200** | secratary-cloud | **OK** |
| C4 | `secretary-ssh.abletelsolutions.com` | `829bc0fb` **personal-secretary-ai (office)** | `ssh://localhost:22` | YES — office `ss` shows `0.0.0.0:22` + `[::]:22` | **THE FROZEN OFFICE BOX** | **POINTS AT OFFICE BOX** |
| C5 | `dialer.abletelsolutions.com` | `829bc0fb` (office) | `http://127.0.0.1:8899` | **NO** — office has no `:8899` listener; `curl :8899` → `000`; public `curl` → **502** (connector up, origin refuses) | office box, dead service | **POINTS AT DEAD SERVICE** |
| C6 | `desktop-ssh.abletelsolutions.com` | `ad86d2a9` | `ssh://localhost:22` | sshd YES on the desktop (`Test-NetConnection 127.0.0.1:22` → True); **connector NO** — tunnel 0 conns, scheduled tasks `PersonalSecretaryDesktopSshCloudflareTunnel`/`…Logon` `LastTaskResult=1`, no `NextRunTime`, last run 2026-10-09 | nobody | **POINTS AT DEAD TUNNEL (down since 2026-10-09)** |
| C7 | `ha.abletelsolutions.com` | `2d0d8178` | `http://homeassistant:8123` | tunnel healthy, 4 conns from `71.104.140.242`; the office box is **not** the origin (no `:8123`, no `:36500`, no docker); backend behind Access | not the office box | **tunnel OK; backend UNMEASURED end-to-end** |
| C8 | `printer.abletelsolutions.com` | `ef0b79cb` home-services | `http://localhost:8000` | **NO** — tunnel 0 conns, status down; public `curl` → **530** | nowhere | **POINTS AT DEAD TUNNEL** |
| C9–11 | `yocheved-ssh` (`ssh://localhost:2222`), `yocheved-shell` (`:7681`), `yocheved-cmd` (`:7682`) | `9fcb6858` | as listed | **NO** — tunnel 0 conns, status down | nowhere | **POINTS AT DEAD TUNNEL (×3)** |

**Access masks the dead ones.** `secretary-ssh.`, `desktop-ssh.`, `ha.`, `yocheved-*`, `printer.` all
answer **302 to `dawn-cell-26a7.cloudflareaccess.com`** rather than an error, so from outside they look
identical whether the backend is alive or not. `printer.` and the `yocheved-*` trio are the exceptions
that leak through as 530/502. This is exactly the "every health check was green" mechanism.

### 1.4 The phone route — re-measured, and the workstream's own reading was stale

The phone-route workstream read `/etc/cloudflared/phone-redirector.env` and found
`PHONE_TAILNET=zabz-yoga-1.tail93e6e6.ts.net` (the laptop), with a `.before-target-fix-20261011T153349Z`
backup beside it, and concluded the owner's phone route **depends on the laptop**. That was true when
read. **It is not true now**, and the correction matters because "points at the laptop" would have been
recorded as a standing risk:

```
secratary-cloud# cat /etc/cloudflared/phone-redirector.env
PHONE_TAILNET=secratary-cloud.tail93e6e6.ts.net
PHONE_STATE=<set>
secratary-cloud# ls -la --time-style=full-iso /etc/cloudflared/phone-redirector.env*
-rw-r--r-- 1 root root 86 2026-10-11 15:53:55.589288761 +0000 phone-redirector.env
-rw-r--r-- 1 root root 86 2026-10-11 15:53:55.589288761 +0000 phone-redirector.env.before-authority-target-20261011T155355Z
-rw-r--r-- 1 root root 80 2026-10-11 00:26:53.101065096 +0000 phone-redirector.env.before-target-fix-20261011T153349Z
secratary-cloud# curl -sS -i http://127.0.0.1:3087/phone | head -4
HTTP/1.0 302 Found
Location: https://secratary-cloud.tail93e6e6.ts.net/
secratary-cloud# systemctl show phone-redirector.service -p ActiveEnterTimestamp
ActiveEnterTimestamp=Sun 2026-10-11 15:53:55 UTC
```

**The sequence, reconstructed from three backup filenames and two `ActiveEnterTimestamp`s — this is
the owner-visible incident and its two repairs:**

1. until **15:33:49Z** — `PHONE_TAILNET=secratary.tail93e6e6.ts.net` → **the frozen office box**.
   This is the incident: the owner's home-screen link landed on a box whose phone engine was
   `inactive`+`disabled` and whose `:3089` had no listener.
2. **15:33:49Z–15:53:55Z** — repointed to `zabz-yoga-1.tail93e6e6.ts.net` → **the owner's laptop**.
   Repaired one time bomb by creating another: the route would die every time he closed the lid.
3. **15:53:55Z →** — repointed to `secratary-cloud.tail93e6e6.ts.net` → **the authority itself. No
   third party in the path.** Correct.

**The office box still fights for this hostname.** The frozen box has its own `/phone` redirector
(`python3 /home/zabz/harness-config/scripts/phone-redirector.py --port 3087`, `/proc/<pid>/cgroup` →
`cron.service`) which 302s to `https://secratary.tail93e6e6.ts.net/` — back into itself — and it is kept
alive by **crontab lines `@reboot … serve-phone` and `*/2 * * * * … serve-phone-2`**. DNS no longer
sends `/phone` there, so it is inert — but it is a competing implementation of a live public route
running on a box scheduled to be powered off, and it will vanish without a trace.

### 1.5 The telephony path, traced end to end (why nothing alarmed)

| hop | where it points | measured |
|---|---|---|
| Twilio number `+17324447361` `voice_url` | `https://api.abletelsolutions.com/webhook/twilio/voice` (+ `sms_url`, `status_callback`) | Twilio API 200 → `api.` → `3e62916c` → cloud `:8002` — **LIVE** (public GET 405 = POST-only route) |
| Dialpad webhooks | `https://ai.abletelsolutions.com/webhook/dialpad/{call,sms}` | Dialpad API 200 → `ai.` → cloud `:3000` — **LIVE** (public GET 405) |
| Dialpad webhook #3 | `https://api.lakewoodphoneandtech.com/webhooks/dialpad/sms` | resolves to `2.28.33.58`, not Cloudflare-proxied, GET 404; the zone is not in this account → **UNMEASURED** |
| the owner's phone home-screen link | `https://ai.abletelsolutions.com/phone` | **302 → secratary-cloud** (§1.4) |

**The health-probe blind spot, stated precisely:** the authority's own telephony probes are
`TELEPHONY_HEALTH_HTTP_PROBE_BASE_URL=https://api.abletelsolutions.com` and
`VOICE_REALTIME_WS_BASE_URL=wss://api.abletelsolutions.com` (both read from `/opt/company/.env`).
`api.` is the healthy new box. **Nothing in the estate probes `ai./phone` or `dialer.`** — the two
hostnames that were broken. That is the whole explanation of "every health check was green".

### 1.6 `/etc/cloudflared/config.yml` on both boxes

**secratary-cloud** (mode 644, mtime 2026-10-11 05:43; `cloudflared.service` enabled+active since 08:25:06Z,
`tunnel run --token-file`, no `credentials-file:` deliberately):

```
tunnel: 3e62916c-04ac-421b-b4a4-9af0852d8024
ingress:
  - hostname: ai.abletelsolutions.com   path: ^/phone(/.*)?$   service: http://127.0.0.1:3087
  - hostname: ai.abletelsolutions.com                          service: http://127.0.0.1:3000
  - hostname: api.abletelsolutions.com                         service: http://127.0.0.1:8002
  - service: http_status:404
```
Its own comment: *"The dialer (:8899) and the ssh escape hatch (:22) deliberately have NO rule here:
their backends stay on the office box until they are moved, and a hostname pointed at this tunnel with
no rule answers 403 rather than the service."* **Serves `ai.` and `api.` only.**

**secratary (office, frozen)** (mtime Sep 18; `cloudflared.service` enabled+**active**, MainPID 1356,
`ActiveEnterTimestamp=2026-10-11 02:42:13Z` — it came back after the cutover and was never stopped):

```
tunnel: 829bc0fb-30f9-4244-b2ea-14fbb61a2753
credentials-file: /home/zabz/.cloudflared/829bc0fb-….json
ingress:
  - hostname: ai.abletelsolutions.com   path: ^/phone(/.*)?$   service: http://127.0.0.1:3087
  - hostname: ai.abletelsolutions.com                          service: http://localhost:3000
  - hostname: api.abletelsolutions.com                         service: http://localhost:8002
  - hostname: secretary-ssh.abletelsolutions.com               service: ssh://localhost:22
  - hostname: dialer.abletelsolutions.com                      service: http://127.0.0.1:8899
  - service: http_status:404
```
**Serves (by DNS): `secretary-ssh.` and `dialer.`** — and nothing at all on `:3000`, `:8002` or `:8899`.
Its `ai.` and `api.` rules are **shadowed**: those hostnames' DNS points at `3e62916c`, proved
empirically (public `api./health` = 200 while the office box has no `:8002` listener). They are no-ops
that will mislead the next reader; delete them at retirement.

`b69e2492` (secretary-standby) declares `ai.`, `api.`, `dialer.` and `secretary-ssh.` but **no DNS
record in the zone references it** — the whole tunnel is inert.

### 1.7 §1 verdict list

**Points somewhere dead or dying, in priority order:**

1. `dialer.abletelsolutions.com` — `829bc0fb` (office) → `:8899`, no listener, public **502**.
2. `secretary-ssh.abletelsolutions.com` — `829bc0fb` (office) → `sshd:22`, live. The off-LAN SSH
   escape hatch, which every Windows `~/.ssh/config` carries as `secretary-cf`, lands on the box
   marked RETIRE.
3. `desktop-ssh.abletelsolutions.com` — `ad86d2a9`, **0 connections since 2026-10-09**, masked by Access.
4. `printer.abletelsolutions.com` — `ef0b79cb`, 0 connections, public **530**.
5. `yocheved-ssh` / `yocheved-shell` / `yocheved-cmd` — `9fcb6858`, 0 connections, masked by Access.
6. `ai.abletelsolutions.com/phone` — **fixed to secratary-cloud at 15:53:55Z**, having passed through
   the office box and the laptop the same afternoon. Listed because it is the incident, and because a
   competing office-side implementation of the same route (`serve-phone-2`, `*/2`) is still running.
7. the office tunnel `829bc0fb` itself — healthy, still connected, never stopped. **This is the
   connector that keeps 1 and 2 alive.**

---

## §2 — HARD-CODED REFERENCES THAT WILL BREAK

Ranked. `[VERIFIED]` = I read the line myself from this laptop at 16:00–16:06Z; `[WORKSTREAM]` = reported
by a mesh child with file+line, not re-read by me.

### SEV 1 — routes traffic to a dying box

**2.1 The ops repo's `origin` is the office box — every node's convergence dies with it.** `[VERIFIED]`

```
C:\Users\ezabz\code\harness-config\.git\config   (laptop; read via `git -C … remote -v`)
  origin   secretary-ts:/home/zabz/harness-config.git   (fetch)
  origin   https://github.com/lakewoodphone/harness-config.git  (push)
  origin   secretary-ts:/home/zabz/harness-config.git   (push)
  offsite  https://github.com/lakewoodphone/harness-config.git
```

Note the shape: **fetch and push point at different hosts** — fetch at the office box, push at GitHub.
`scripts/autosync.sh` (Linux), `scripts/autosync.ps1` (Windows) and `scripts/harness-autosync.sh`
(macOS) each run *on the local node* and `git fetch origin` first. Office box off ⇒ **every node stops
converging**: settings, presets, plugins and the journal freeze at the last-fetched commit. There is a
designed failover — `scripts/autosync.sh:63` `MIRROR_REMOTE="${HARNESS_MIRROR_REMOTE:-mirror}"` used at
`:112-125`, and `autosync.ps1:87` — but **the mirror is `linux-pc:/home/zabz/harness-config-mirror.git`
(`zabz-tech-linux`, 192.168.50.23), also an office-LAN machine.** The fallback covers "secratary is
down"; it does not cover "the office is dark".

The workstream measured **13 remotes across 2 machines** pointing at office bare repos, all resolving
today (`git ls-remote` rc=0 at 15:56Z) and all failing on power-off: on `zabz-tech` — `harness-config`,
`harness-config-mesh`, `hc-342`, `hc-origin-fix`, `_fleet_p1evidence`, `_fleet_p1experiment`,
`_fleet_p1taxonomy`, `_fleet_p2broker`, `_fleet_p2children` (all `secretary-ts:/home/zabz/harness-config.git`),
`home` (`…/home.git`), `mesh-security` (`secratary-ip:`/`secratary-lan:`), `personal-secretary-mvp`
(`ssh://secretary/…`); plus `zabz-tech-linux:/home/zabz/code/harness-config` → `secretary:…`.
`[VERIFIED for the laptop; WORKSTREAM for the other machine]` The mac mini's remotes are unmeasured
(it was asleep — §5.5).

**2.2 The mesh placement broker: every default says `secratary-ts`, and the broker IS the office box.**

```
[VERIFIED] C:\Users\ezabz\code\harness-config\profiles\web\cordis.patch.yml:145
   brokerSsh: !!js "process.env.MESH_BROKER_SSH ?? 'secratary-cloud'"      <-- repo: ALREADY FIXED
[VERIFIED] C:\Users\ezabz\.dsh\profiles\web\cordis.patch.yml:137  (DEPLOYED on this laptop)
   brokerSsh: !!js "process.env.MESH_BROKER_SSH ?? 'secratary-ts'"        <-- deployed: STILL OLD
[VERIFIED] C:\Users\ezabz\.dsh\profiles\web\cordis.patch.yml:138
   brokerUrl: !!js "process.env.MESH_BROKER_URL ?? 'http://localhost:3091'"
[VERIFIED] C:\Users\ezabz\code\harness-config\packages\plugin-remote-fanout\lib\broker-client.js:163
   const sshTarget = config.sshTarget ?? 'secratary-ts';
[VERIFIED] …\plugin-remote-fanout\lib\broker-client.js:164  const url = (config.url ?? 'http://localhost:3091')…
[WORKSTREAM] …\plugin-remote-fanout\lib\nodes.js:133  ssh: 'secratary-ts',
[VERIFIED] …\plugin-remote-fanout\bin\mesh-run.mjs:52  const BROKER_SSH = process.env.MESH_BROKER_SSH ?? 'secratary-ts';
```

**The `localhost` here means the OFFICE BOX, not the local machine.** `broker-client.js:163-164`
builds `[...sshArgs, sshTarget, curl]` where the curl is `curl -sS -XPOST http://localhost:3091/place …`
— executed **on the far side of `ssh secratary-ts`**.

Measured end state: the broker runs **only** on the office box
(`node /home/zabz/mesh-broker/bin/mesh-broker.mjs --host 127.0.0.1 --port 3091`, `curl 127.0.0.1:3091/healthz`
→ **200**), and on the authority `systemctl is-enabled mesh-broker` → **disabled**, `is-active` → **inactive**.
So this is not a stale literal: **power off the office box and every broker-mode child dispatch on the
estate fails** with `broker-unreachable`. The repo's `profiles/web` default has been corrected to
`secratary-cloud` but the **deployed** files, `broker-client.js`, `nodes.js` and `mesh-run.mjs` have not —
and `brokerSsh` is an env-overridable default, so a corrected profile with a stale `broker-client.js`
still fails when `MESH_BROKER_SSH` is unset.

**2.3 The owner's `ps_*` toolbelt is an ssh to the office box — and fails silently.** `[VERIFIED]`

```
C:\Users\ezabz\.dsh\.agent-presets\zabz\agent.cordis.yml:595   - 'secretary-ts'
C:\Users\ezabz\.dsh\.agent-presets\zabz\agent.cordis.yml:597   - '/home/zabz/personal-secretary-mvp/scripts/ps_mcp_server.py'
C:\Users\ezabz\.dsh\.agent-presets\zabz\rows\mcp.rows.yml:69   - 'secretary-ts'
C:\Users\ezabz\.dsh\.agent-presets\zabz\rows\mcp.rows.yml:71   - '/home/zabz/personal-secretary-mvp/scripts/ps_mcp_server.py'
C:\Users\ezabz\.dsh\.agent-presets\yocheved\agent.cordis.yml:481  - 'secratary-ts'
repo: C:\Users\ezabz\code\harness-config\presets\zabz\agent.cordis.yml:595, :597
repo: C:\Users\ezabz\code\harness-config\presets\yocheved\agent.cordis.yml:481, :483
```

`secretary-ts`/`secratary-ts` both resolve to `secratary.tail93e6e6.ts.net`. This is the `ps_company_status`,
`ps_db_query`, `ps_action`, `ps_ceo_chat`, `ps_log_tail`, `ps_circuit_breakers` surface — the owner's
whole company interface. `failOnStartupError: false` (preset `:599`) means **it dies quietly**. It is
live today: three `ps_mcp_server.py` processes were measured running on the office box at 15:48–15:53Z.
The fix pattern already exists in the same file — `presets/zabz/agent.cordis.yml:610-620`
(`mcp-secretary-linux`) is a **local** row gated on `process.platform === 'linux'`. It moves with the
authority and is correct. The Windows rows need the same treatment.

**2.4 `lpt-ops` — the new authority's hostname is not in the authority set.** `[VERIFIED line] → [WORKSTREAM consequence]`

```
C:\Users\ezabz\code\lpt-ops\lpt_ops\transport.py:64   AUTHORITY_SSH = os.environ.get("LPT_AUTHORITY_SSH", "secratary")
C:\Users\ezabz\code\lpt-ops\lpt_ops\writes.py:84      AUTHORITY_NAMES = {"secratary", "secretary"}
C:\Users\ezabz\code\lpt-ops\lpt_ops\writes.py:104     return name in AUTHORITY_NAMES and Path(...HELPER_REMOTE).is_file()
```

`writes.py` decides whether to run the write helper **locally** (`:91-96`) or over ssh, by matching
`socket.gethostname()`. On the office box the name matched, so the ssh hop was skipped. I verified the
authority's hostname is `secratary-cloud` — **not in `AUTHORITY_NAMES`** — so `on_authority()` returns
False and `writes.py:138,168,203` fall through to `run_ssh(AUTHORITY_SSH, …)` with
`AUTHORITY_SSH="secratary"`, the retired box's alias. **Every customer write through `lpt-write` on the
new authority tries to ssh to the dead box.** `lpt_ops/dialpad.py:957-970` has the identical shape, so
the Dialpad event actor breaks the same way. Installers default the same: `install.sh:133`,
`install.ps1:192`, `install-label.sh:8,11`.

**2.5 The `mesh` profile dispatches children to the laptop.** `[VERIFIED]`

```
C:\Users\ezabz\code\harness-config\profiles\mesh\cordis.patch.yml:56  # MESH_TARGET_NODE … (default laptop-ts)
C:\Users\ezabz\code\harness-config\profiles\mesh\cordis.patch.yml:100 target: !!js "process.env.MESH_TARGET_NODE ?? 'laptop-ts'"
```
Same literal in the deployed `~/.dsh/profiles/mesh/cordis.patch.yml:100` on both Windows boxes.
Any `mesh`-profile session with no explicit `MESH_TARGET_NODE` sends its children to a machine that is
**not always on**. Overnight work dies when the lid closes.

**2.6 `journal.py` blocks on the office box.** `[VERIFIED]`

```
C:\Users\ezabz\code\harness-config\journal\tools\journal.py:2282
   tries.append(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "secratary-ts", …
```
The journal CLI's owner-queue read. 8 s connect timeout, 45 s overall (`:935`, `:2251`). Every
`journal.py questions` / `status` on a machine that can't reach the office box pays that and then
reports unreachable. A fallback exists (`journal/state/owner-questions.md`, `scripts/owner-queue.py:75`),
so this degrades rather than breaks — but the company's memory tool periodically hangs on a dead box.

**2.7 The authority still calls the office box by name in its environment.** `[VERIFIED — read from secratary-cloud]`

```
/opt/company/.env
  MACHINE_NAME=secratary                                       <-- the cloud box names itself the OLD box
  CLOUDFLARE_TUNNEL_NAME=personal-secretary-ai                 <-- the OFFICE tunnel's name
  AI_GATEWAY_MESH_PEERS_JSON=["http://192.168.50.138:8002"]    <-- an office-LAN desktop, unroutable from Hetzner
  LINUX_PC_HOST=192.168.50.23
  SHELLY_PLUG_HOST=192.168.50.103
```
`MACHINE_NAME=secratary` is why `lpt-ops`'s hostname matching (§2.4) would *pass* if it read this
instead of the real hostname — and it is what any identity check, metric label or report writes into
its own output. `AI_GATEWAY_MESH_PEERS_JSON` names the **office desktop** on the office LAN: from Ashburn
it cannot route, and the desktop listens on `:8002` only when the app is running locally. This is a live
gateway-peers value with no valid peer in it.

**2.8 The authority resolves the frozen box and archives it hourly.** `[VERIFIED]`

```
secratary-cloud# getent hosts secratary      → 100.84.72.88
secratary-cloud# getent hosts secratary.tail93e6e6.ts.net → 100.84.72.88
secratary-cloud# getent hosts secretary      → NO RESOLVE
secratary-cloud# /etc/transcript-archive.env → TRANSCRIPT_ALIAS_SECRATARY=secratary-ts
secratary-cloud# transcript-archive-pull.timer  LAST 15:23:27Z  NEXT 16:23:00Z  (enabled, active)
```
The authority **pulls the frozen office box as if it were a live machine**, hourly. Today that is
harmless and even useful (it proved the archive is complete — §4.3). On power-off it becomes a job that
logs a failure every hour against a host that will never answer, and **nobody will read it because the
pull's own success is the only signal.** `/root/.ssh/config` also still maps `secratary`/`secratary-ts`
to the office box. `AI_GATEWAY_MESH_PEERS_JSON` (§2.7) and this are the two places the *authority itself*
still treats the office box as alive.

### SEV 2 — breaks a job (targeted)

**2.9 `app/services/company_outcome_monitor.py:395` — a residual hardcode that `137` did not fix, reporting a false zero with a lying provenance.** `[VERIFIED — read and executed on secratary-cloud]`

```
/opt/company/app/services/company_outcome_monitor.py
  391   cmd = journal_lock_command(days, unit)          # builds the CORRECT command string
  395   "journalctl", "-u", "secretary-api",            # <-- and then runs the WRONG unit anyway
```
Runtime proof, executed 16:01Z:
```
journal_lock_unit()        -> ('company-api', 'resolved by `systemctl cat company-api`')
_journal_lock_events(7)    -> (0, "`journalctl -u company-api --since '7 days ago' --no-pager -o cat` -> 0 matching lines (resolved by `systemctl cat company-api`)")
```
`journalctl -u secretary-api …` returns **rc=0 with 0 lines** (the unit does not exist, so journalctl
succeeds silently). So the monitor's `lock_contention_7d` section reads a nonexistent unit, gets 0, and
**prints a provenance string naming `company-api` for an argv that ran `secretary-api`.** That is a
fabricated zero wearing a true-looking source — the estate's single worst recorded failure mode, inside
the instrument built to catch it. Workstream 137 patched the resolver (`:332`) and the declared env
(`company-outcome-monitor.service:23`) and **missed this literal**. Cosmetic leftovers of the same
literal at `:365` (default arg) and `:892` (`or "secretary-api"`).

**2.10 `server/access-watchdog.sh` — a self-heal path permanently disabled by an office-LAN probe.** `[WORKSTREAM, file+line]`
```
personal-secretary-mvp/scripts/server/access-watchdog.sh:4   APP_ROOT="${APP_ROOT:-/home/zabz/personal-secretary-mvp}"
personal-secretary-mvp/scripts/server/access-watchdog.sh:11  DESKTOP_ORIGIN_HEALTH_URL="${DESKTOP_ORIGIN_HEALTH_URL:-http://192.168.50.138:8002/health}"
personal-secretary-mvp/scripts/server/access-watchdog.sh:164 log "public API health failed but desktop origin $DESKTOP_ORIGIN_HEALTH_URL is unhealthy; skipping cloudflared restart"
```
The watchdog's `restart cloudflared` branch only fires when the **desktop** answers on the office LAN.
Run from Ashburn that probe never answers, so the watchdog permanently refuses its one remedy and logs a
false "desktop origin unhealthy". Already half-dead; fully dead on power-off, when the office LAN behind
it is gone too.

**2.11 The node-agent hub is the office box on four machines.** `[VERIFIED lines] → [WORKSTREAM deployment]`
```
personal-secretary-mvp/scripts/mesh/node-agent.py:60  LOCAL_HUB     = "http://192.168.50.77:8002"
personal-secretary-mvp/scripts/mesh/node-agent.py:61  TAILSCALE_HUB = "http://secratary.tail93e6e6.ts.net:8002"
```
The hub-probe ladder tries LAN → tailnet → `DEFAULT_HUB` (`https://api.abletelsolutions.com`, correct).
So this degrades rather than breaks — but it spends two failed probes on every report and logs "hub
unreachable" while reporting successfully. Deployed as: `zabz-tech` scheduled task
`PersonalSecretary-NodeAgent` (`--peers linux-pc,mac-mini,secretary`, `node-report.json` last written
**2026-10-07**, 4 days stale); `lakewooechsmini` LaunchAgent `com.personalsecretary.nodeagent`;
`zabz-tech-linux` crontab `*/30 node-agent-standalone-cron.sh` (authority copy `:24,28`
`--hub http://192.168.50.77:8002`); and the authority's own `/opt/company` copy.

**2.12 Wake-on-LAN and AI-platform parity probes aimed at the office box.** `[VERIFIED lines]`
```
personal-secretary-mvp/scripts/wake-secretary.py:26,28  SECRETARY_IP = "192.168.50.77"; HEALTH_URL = f"http://{SECRETARY_IP}:8002/health"
personal-secretary-mvp/scripts/ai_platform/mesh_status.py:24,270-272,275-277  SECRETARY_LAN_IP="192.168.50.77"; three probes at secratary.tail93e6e6.ts.net:8002
personal-secretary-mvp/scripts/ai_platform/mesh_status.py:367  violations.append("secretary API not reachable on LAN 192.168.50.77:8002 (production unreachable)")
```
`wake-secretary.py` cannot wake a retired box — dead by definition. `mesh_status.py`'s parity report
will declare the retired box the unreachable "production" and the live authority invisible; its own
comment at `:301` still states *"Canonical production is the SECRETARY server (192.168.50.77)"*, now false.

**2.13 Fleet gates with a permanent FAIL row.** `[WORKSTREAM, file+line]`
`scripts/mesh-hygiene.sh:801`, `scripts/mesh-hygiene.ps1:966-968`, `scripts/fleet-profile-gate.ps1:49`,
`scripts/mesh-e2e.ps1:154-158` all carry a node table headed by `secratary`/`secratary-ts`.
`scripts/mesh-restart-when-idle.ps1:1102-1104` probes `http://localhost:3091` **inside a remote shell on
`secratary-ts`** — the same "localhost means the office box" trap as §2.2 — and will warn on every run
about a placement it cannot see. A gate that always fails stops being read; that is the cost.

**2.14 `harness-config`'s sync/provision/inspector scripts.** `[WORKSTREAM, file+line]`
`scripts/provision-mesh-node.sh:58` `authority=secratary` (`:383-385`, `:428-430` pull the pinned
lockfile and `.credentials.yaml` **from the office box**) — new mesh nodes cannot be provisioned at all.
`scripts/push-dsh-sessions.mjs:98` `SSH_HOST = … || 'secretary-ts'` (legacy branch only; the live default
is `--transport http` to `https://api.abletelsolutions.com`, measured 200 — stale, not breaking).
`packages/attention-badge/lib/client.js:59` `BADGE_AUTHORITY = 'https://secratary.tail93e6e6.ts.net'`
— **live client code fetched by a browser/phone**; the badge stops loading. `packages/mesh-broker/nodes.json`
still lists `secratary` and `zabz-yoga-1` as placement candidates (the authority's own deployed copy at
`/opt/mesh-broker/nodes.json:22,46` does the same and has **no `secratary-cloud` row**) — a broker that
ranks an unreachable node it can never dispatch to.

**2.15 `phone-and-tech-full` shop-closure generator.** `[WORKSTREAM, file+line]`
`scripts/generate-shop-closures.mjs:221` `const host = arg('host', 'secratary-ts')` and `:251` a
provenance string `secratary:~/personal-secretary-mvp/app/services/shalom_zmanim.py:is_chag_yom_tov` that
is **written into `frontend/src/data/shop-closures.json:3`** and ships to the website. The refresh stops
and the stale provenance ships.

### SEV 3 — stale, no live effect today (recorded so nobody re-litigates them)

`harness-config` matches for `secratary.tail93e6e6.ts.net` (202), `secratary-ts`/`secretary-ts` (556),
`192.168.50.` (254), `zabz-yoga|laptop-ts|zabz-yoga-1` (41 in `*.ps1`), the Hetzner IPs (60) are
**overwhelmingly in `docs/` and `journal/`** — documentation of a state that has passed, not breakage.
Zero live-code hits for the three Hetzner IPs in `harness-config`. `ZABZ-YOGA.yaml` (the laptop's machine
settings file) does not match `os.hostname()` if the host is `ZABZ-YOGA-1` — unconfirmed, §5.6.
`lpt-ops` and `phone-and-tech-full` deliberately avoid MagicDNS names (`lpt-ops/tests/test_install_contract.py:269,272`
*asserts* `secratary-ts` and `tail93e6e6` must not appear). `2.31.18.142` has **zero** matches in any repo.

---

## §3 — PER-MACHINE CONFIG FINDINGS

Full detail is in the workstream reports; this is the consolidated registry. Every machine was
enumerated for scheduled tasks / cron / timers / scripts / MCP configs / `.env` / ssh config.

### 3.1 This machine — ZABZ-YOGA (owner's laptop, Win11)

| surface | finding |
|---|---|
| `~/.dsh/profiles/web/cordis.patch.yml:137` | `brokerSsh` default `'secratary-ts'` — **ROUTES**. Repo copy `:145` is already `'secratary-cloud'`; the deployed copy is not. |
| `~/.dsh/profiles/web/cordis.patch.yml:136` | `target` default `'desktop-ts'` (a fixed fallback, not a broker route). |
| `~/.dsh/profiles/mesh/cordis.patch.yml:100` | `target` default `'laptop-ts'` — **ROUTES to itself**. |
| `~/.dsh/.agent-presets/zabz/agent.cordis.yml:595,597`; `…/zabz/rows/mcp.rows.yml:69,71`; `…/yocheved/agent.cordis.yml:481,483` | `ps_*` over `ssh secretary-ts`/`secratary-ts` → the office box — **ROUTES**, silent. |
| `~/.dsh/settings.yaml` | **no host references.** Explicit no-match. |
| `~/.dsh/.credentials.yaml` | key names only: `version`, `records`, `records.client-connection/browser-session{kind,payload{version,secret}}`, `refs{DEEPSEEK_API_KEY,DEEPINFRA_API_KEY,LPT_VERIFICATION_EMAIL,LPT_VERIFICATION_PASSWORD}`. **No values read.** |
| `~/.dsh/profiles/headless/cordis.patch.yml` | **no host references** on this machine (explicit no-match). |
| scheduled tasks | **zero task command lines contain an office-box or laptop literal.** Enumerated. |
| MCP discovery | no `.cursor/mcp.json`, no `claude_desktop_config.json`, no VS Code user `mcp.json`, no `~/.dsh/mcp.json`, no `~/.codex`, no `~/.gemini` — all explicit no-matches. |
| repo `.vscode/mcp.json` × 12 | all local stdio. |
| listeners | **3099 (this DSH engine) and 3086 only.** Nothing on 3000/8002 — a locally-spawned `ps_mcp_server.py` here would talk to nothing. |
| `~/.ssh/config` | office box at `:13-22` (`secratary` → 192.168.50.77), `:57-67` (`secratary-ts` → tailnet), `:186` (`secretary-cf`). Migration additions present: `:244 secratary-cloud`, `:255 lpt-survivor-01`, `:264 secratary-rescue`, `:271 secratary-cloud-recovery`. |
| `harness-config` git remotes | `[VERIFIED]` `origin` fetch+push → `secretary-ts:/home/zabz/harness-config.git` (push also listed against GitHub); `offsite` → GitHub. |
| `.cloudflared` | desktop-ssh + secretary-ssh tokens; **no `.yml` ingress configs**. |

### 3.2 ZABZ-TECH (office desktop, Win11) — reached over ssh

- **343 scheduled tasks enumerated, ZERO containing an office-box or laptop literal.** One task,
  `\PersonalSecretary-NodeAgent`, targets `node-agent.py` whose *script* routes to the office box (§2.11);
  `node-report.json` last written 2026-10-07 (4 days stale). `\DSH Metrics Sampler` runs from
  `C:\Users\ezabz\AppData\Local\Temp\harness-config-snap-20261010-233208\` — it breaks when temp is cleaned,
  unrelated to the migration but the same class.
- Same DSH findings as §3.1 (`~/.dsh` is synced): `profiles/web/cordis.patch.yml:137`,
  `profiles/mesh/cordis.patch.yml:100`, `profiles/headless/cordis.patch.yml:30,63` (the `ps_*` row that
  **every mesh-spawned child boots with**), `.agent-presets/zabz/agent.cordis.yml:595`,
  `.agent-presets/yocheved/agent.cordis.yml:481`. `.dsh/settings.yaml` — no host refs. `.credentials.yaml`
  — key names only (`refs{DEEPSEEK_API_KEY}`).
- `~/.dsh/gateway-route.patch.yml:18` `baseURL: http://secratary:8002/v1` — the file's own header says
  "OPT-IN, NOT ENABLED". **ROUTES (dormant)**, and `C:\Windows\System32\drivers\etc\hosts` pins
  `100.84.72.88 … secratary`, so it resolves rather than failing fast.
- `.cloudflared/config.yml` declares `ai.`→localhost:3000 and `api.`→localhost:8002, but **nothing listens
  on 3000/8002 here** — stale; the authority's tunnel owns those hostnames.
- **There is NO `secratary-cloud` ssh alias on this machine** — the runbook's alias exists on the laptop
  and the authority, not here. Anything following the runbook from the desktop fails.
- `~/.ssh/config` `secretary-ssh`/`secretary-cf` (off-LAN escape hatch) → §1.7 item 2.
- `code\personal-secretary-mvp\.env` (key names + host values only): `LINUX_PC_HOST=192.168.12.9` —
  **stale/wrong** (the node-identity file itself says the router reservation is `192.168.50.23`);
  `HA_URL=http://homeassistant.local:8123`; `SHELLY_PLUG_HOST=192.168.50.103`; `HETZNER_MDM_IP=87.99.141.172`;
  `PUBLIC_BASE_URL=https://ai.abletelsolutions.com`; `CLOUDFLARE_TUNNEL_NAME=personal-secretary-ai`.
  **Zero** `SECRETARY_API_BASE`/`*_BASE_URL` naming the office box.
- `~/.personal-secretary/node-identity.json` still registers `admin-laptop` @192.168.50.244 and
  `secratary` @192.168.50.77.

### 3.3 ZABZ-TECH-LINUX (Linux worker, 192.168.50.23)

- crontab `*/30 node-agent-standalone-cron.sh` → `--hub http://192.168.50.77:8002` (**BREAKS**);
  `*/30 push-dsh-sessions.mjs --transport http` → authority (OK). Root crontab, `/etc/cron.d`, `/etc/crontab`:
  stock only.
- systemd: only `dsh-engine.service` + `phone-gate.service`. **No broker, no cloudflared, no app.**
- **No DSH host config at all**: no `settings.yaml`, no `.agent-presets`; `profiles/{headless,web}/cordis.patch.yml`
  are empty. `mcp-secretary-linux` mounting here is **UNMEASURED** (the repo has `ps_mcp_server.py` but no
  `.venv/bin/python` and no `data/secretary.db`).
- `~/bin/find-anything:189` — the documented business-data fallback is `ssh secratary-ts 'fa data …'` → **BREAKS**.
- `~/.ssh/config` has the office box and **no `secratary-cloud`**. `/etc/hosts` → `87.99.141.172 mdm.abletelsolutions.com` only.
- `~/personal-secretary-mvp/.env` — FLEET_API_URL/TOKEN + search keys only; **no office-box host**.

### 3.4 SECRATARY-CLOUD (the authority) — `[VERIFIED myself]`

- **The mesh broker is not here.** `systemctl is-enabled mesh-broker` → `disabled`; `is-active` → `inactive`.
  The running broker is on the office box (§2.2).
- `/opt/mesh-broker/nodes.json` — the deployed roster still lists `secratary` (`:46-56`) and `zabz-yoga-1`
  (`:22-31`) and has **no `secratary-cloud` row**.
- `/root/.dsh/profiles/web/cordis.patch.yml` — `brokerSsh 'secratary-ts'` (`:135`), `target 'desktop-ts'` (`:136`),
  and the **yocheved `ps_*` row is gated `disabled: process.platform === 'win32'`, i.e. ENABLED on Linux** —
  so it spawns `ssh … secratary-ts /home/zabz/…/ps_mcp_server.py` from the authority. `[WORKSTREAM, file+line]`
  (this file was rewritten at 15:53Z mid-audit; line numbers as of then).
- `/root/.ssh/config` — `secratary`/`secratary-ts` → the office box, plus a **temporary catch-up relay block**
  (`catch-*` → `127.0.0.1:2201-2205`, comment "the authority is not on the tailnet") that is **stale**:
  tailscale is logged in and `100.73.176.126` is live. `[WORKSTREAM]`
- `/opt/company/.env` — `MACHINE_NAME=secratary`, `CLOUDFLARE_TUNNEL_NAME=personal-secretary-ai`,
  `AI_GATEWAY_MESH_PEERS_JSON=["http://192.168.50.138:8002"]` — **`[VERIFIED]`**; §2.7.
- **`/home/zabz` on the authority is a symlink farm**, created 06:31–06:37 on cutover day:
  `bin→/root/bin`, `code→/root/code`, `.dsh→/root/.dsh`, `.sms-inbox→/root/.sms-inbox`,
  `personal-secretary-mvp→/opt/company`, `.lpt-ops`, `.cfo`, `.cron-status`, `accounting-data`, … —
  **`[VERIFIED]`**. `/home/zabz/repos` and `/home/zabz/lpt-hub` are **MISSING** — **`[VERIFIED]`**.
  Three live cron payloads depend on the farm (`sms-inbox`, `mirror-owner-sms`, `reconcile-sent-status`,
  all `rc=0` through 15:40Z), and `app/company_blueprint.py:74-152` has nine `local_path` defaults under
  `/home/zabz/repos/*`. **The farm is a cutover crutch with a deletion date nobody has set** — §5.2.
- `app/services/company_outcome_monitor.py:395` — §2.9, `[VERIFIED]` by execution.
- `app/main.py:1638` `ssh secretary cat /home/zabz/.personal-secretary/mesh-health.json` — `secretary`
  does not resolve on the authority (`[VERIFIED]`: `NO RESOLVE`), so this fallback is dead code that
  silently returns "SSH failed".
- `scripts/windows/seat-ssh-run.py:51,59-73`, `scripts/mesh/node-agent.py:27,60-61`, `scripts/self-audit.ps1:47-48`,
  `scripts/write-session-handoff.ps1:38-39`, `scripts/wake-secretary.ps1:3,27`, `scripts/linux-pc-recovery.sh:14`,
  `app/services/presence.py:15` (`OFFICE_LAN=192.168.50.0/24`) — office literals, most reached at runtime.
- **`systemctl --failed` → "0 loaded units listed."** No failed unit; nothing that looks like a second writer.
- `/etc/cloudflared/config.yml` — §1.6.

### 3.5 SECRATARY-TS (the office box) — read-only, bounded; load 0.02–0.43

- **`systemctl is-enabled cron` → `masked`; `is-active` → `inactive`.** The crontab file still lists **87**
  `cron-wrap.sh` jobs; all inert. `sudo crontab -l` → "no crontab for root". `/etc/cron.d` = stock.
- **What is still running** (`systemctl list-units --state=running` + `ps`, measured 15:54Z):
  `mesh-broker.service` (:3091, healthz 200), `phone-gate.service` (:3086), `phone-redirector.py` (:3087),
  `vscode-tunnel.service`, **`cloudflared.service` (active since 02:42:13Z — never stopped at cutover)**,
  `actions.runner.lakewoodphone-phone-and-tech-full.secratary-lpt.service` (self-hosted GitHub runner),
  `xvfb-login.service`, **3× `ps_mcp_server.py`** (the ssh-spawned `ps_*` servers the desk/laptop open),
  tailscaled, fail2ban, rsyslog.
  `secretary-api.service` → **inactive + disabled**; `phone-engine.service` → **inactive + disabled**;
  `secretary-backup.service` → **failed**.
- Listeners: `127.0.0.1:{3086,3087,3091,20241}`, `100.84.72.88:{443,50101}` (tailscale serve). **Nothing on
  3000, 8002, 8899, 3089.**
- `/home/zabz/.dsh/settings.yaml` **absent** (only `.bak`s). `.ssh/config` has the Hetzner block **duplicated
  three times**, and **no `secratary-cloud` alias**. `~/.lpt-r2.env` present. `~/scripts` = one file, zero
  host literals.

### 3.6 LAKEWOOECHSMINI (mac mini, macOS)

- LaunchAgent `com.personalsecretary.nodeagent` → `~/.personal-secretary/node-agent-cron.sh:17-18`
  `--hub http://192.168.50.77:8002 --peers desktop,secretary,linux-pc` → **the office box (BREAKS)**;
  its error log is empty.
- `dsh-session-sync`, `harness-autosync`, `journal-daily`, `repo-sync` — no host literals (the http default
  is the authority). `yocheved-harness.plist.disabled-by-mesh-20260916` disabled.
- No crontab, no `/etc/cron.d`. `~/.ssh/config` has the office box and **no `secratary-cloud`**.
- Listeners: 3086, 8128, 7000, 5000 — no 8002/3000.
- `~/.dsh/logs/engine.err.log:311-321` is historical proof of this exact class:
  *"Read from remote host secratary.tail93e6e6.ts.net: Operation timed out"*.

### 3.7 §5 — the `ps_*` / MCP path

**What `ps_*` is.** `personal-secretary-mvp/scripts/ps_mcp_server.py` — a Python **FastMCP server on stdio**.
`[WORKSTREAM, file+line]`: `:51` `from mcp.server.fastmcp import FastMCP`; `:53-63`
`FastMCP(name="personal-secretary", …)`; `:66` `API_BASE = "http://localhost:8002"`; `:798`
`mcp.run(transport="stdio")`. **It binds nothing and owns no host:port.** It is a stdio child that opens a
*local* SQLite file and calls a *local-host* API. Its 12 tools are `ps_ceo_chat, ps_task_list, ps_task_update,
ps_memory_search, ps_health, ps_db_query, ps_log_tail, ps_standing_work_orders, ps_action, ps_open_loops,
ps_company_status, ps_circuit_breakers`. Its intended home is the authority, reached **over ssh** from
Windows, or run locally on Linux.

**What every owner session loads** (`agent-presets.default: zabz` on all three measured machines;
children boot `headless`; the manager uses `yocheved`):

| preset / profile | row | target | verdict |
|---|---|---|---|
| `zabz` on Windows (laptop + desktop) | `mcp-secretary`, stdio, `command: ssh` | **`secretary-ts`** → office box | **POINTS AT OFFICE BOX**, silent (`failOnStartupError:false`) |
| `headless` (every mesh child) | same ssh row | **office box** | **POINTS AT OFFICE BOX** |
| `yocheved` on Linux/macOS | same ssh row, gated `disabled: platform==='win32'` → **enabled** | **`secratary-ts`** → office box | **POINTS AT OFFICE BOX** |
| `yocheved` on Windows | ssh row to `secretary-ts` | office box | **POINTS AT OFFICE BOX** |
| `mcp-secretary-linux` | stdio, local `/home/zabz/…` (→ `/opt/company` on the authority) | the local box | **LIVE — correct**. On `zabz-tech-linux`: UNMEASURED |
| `remote-fanout` (the mesh provider) | `placement=broker`, `brokerSsh` default `secratary-ts` | **office box** decides where children run | **POINTS AT OFFICE BOX** |
| `mesh` profile | `target` default `laptop-ts` | laptop | **POINTS AT LAPTOP** |
| firecrawl / jina / context7 / fetch / playwright | local npx / `.venv` / URLs | — | **LIVE** (jina `mcp.jina.ai/v1` → 406 in 0.06 s; github → 401 in 0.10 s) |

**The office box mounts `ps_*` at itself** (`profiles/headless/cordis.patch.yml:30`,
`.agent-presets/yocheved/…:462`) and three `ps_mcp_server.py` processes were running there — but its own
`:8002` is dead (`curl` → `000`), so those children talk to a stopped API and to the frozen DB
(`data/secretary.db`, 23,622,823,936 B, mtime 2026-10-11 04:28). A `ps_db_query` issued from the owner's
desk today reads **the frozen office database**, not the authority. That is the `ps_*`-shaped version of
the incident.

**No machine binds an MCP port** (authority `ss -ltnp`; both Windows listener enumerations) — so there is
no network MCP surface to repoint. The whole path is `ssh` + stdio, and its breakage is a *silent child
startup failure*.

---

## §4 — THE OFFICE-BOX SHUTDOWN FORECAST

Measured state at 16:03:50Z: load `1.62 1.16 0.54`, uptime 13:10 (booted 02:41Z). **All five timers
`enabled` AND `active`**, all last runs `Result=success ExecMainStatus=0`. This is the frozen box still
doing work.

### 4.1 The five timers, and the question that matters

The question is not "does the timer stop" — it does. It is **"does anything consume its output?"** For
three of the five the answer is **no**, and that converts them from "breakage" into **silent waste**,
which is a materially different verdict and worth stating as one.

| timer | writes | who reads it | what breaks on power-off | cloud successor (verified) |
|---|---|---|---|---|
| `estate-monitor` (`*:0/2`) | `~/.estate-monitor/{state.json,monitor.log,alerts.jsonl,ESCALATED}` + journal | **NO READER FOUND** — `grep -rIl "\.estate-monitor"` over `/home/zabz`, `/etc/systemd/system`, `/usr/local/bin` → **zero**. (An earlier apparent hit in `mesh-hygiene.sh` was a false positive — it matches that script's own `ESCALATED_PIDS` variable.) | **A MONITOR STOPS ⇒ SILENT WASTE.** And it is not hypothetical: `alerts.jsonl` holds **19 rows 2026-10-07T18:34Z → 2026-10-11T05:34Z**, every one `"transport": "syslog-only, no outbound message"`, the last a real `public_health_status=1.0 crit`. **It escalated the company being unreachable from outside and nothing saw it.** | **YES, running** — `enabled`+`active`, LAST 16:02:07Z NEXT 16:04:02Z, `/root/.estate-monitor/` |
| `tmp-reaper` (`*:0/15`) | `~/logs/tmp-reaper.log` + syslog; effect = delete direct children of `/tmp` older than 3 d when `/tmp` ≥75 % | **NO READER** (only the script itself) | **NOTHING.** The effect is bounded to that box's `/tmp`. SILENT WASTE. | unit `not-found`; the **function** is covered by the authority's cron `*/20 cron-wrap.sh tmpfs-reaper` |
| `fa-index` (`OnBootSec=5min`+15 min) | `~/.faindex/{paths.txt,tags,built_at.txt}`; refreshes the journal index | **`fa`** (`/usr/local/bin/fa` exists there; `bin/find-anything` reads `$HOME/.faindex`) | **A REAL CAPABILITY IS LOST on that box** — but its consumers live there too. The material finding is the other side: **the authority has no `fa` at all** (`command -v fa` → nothing; `/root/.faindex` absent; no `/root/bin/find-anything`). `[VERIFIED]` | **none** — verified `not-found` |
| `trunk-check` (3 min +30 min) | `/home/zabz/.trunk-check.log` (1,380 lines: per-node `harness-config` branch/HEAD/dirty + `DRIFTED`) | **NO READER** (only the script and its own unit) | **NOTHING ⇒ SILENT WASTE** — with the caveat that *what it measured* (P2881's "which machines are on the trunk", after 87 divergent branches accumulated) is now measured by **nothing anywhere**. | **none** — verified `not-found` |
| `company-outcome-monitor` (`00/4:07`) | `~/company-reports/outcome-*.{txt,json}`, journal line, prunes >90 d | **NO READER for the office copies** (the cloud has its own producer, not a reader of this one) | **A MONITOR STOPS** — and it is worse than waste: **the office DB has been frozen since 04:28:35Z**, so its 12:07:16Z run journaled `CRITICAL: company work is failing: [CRITICAL] 69.4% of work sessions fail` — a live alarm about a dead database, into the void. Power-off removes a false-alarm source. | **YES, running** — `enabled`+`active`, LAST 12:07:01Z NEXT 16:07:00Z |
| `/home/zabz/heartbeat.sh` (PID 1673, `@reboot`, **not a unit**) | `~/heartbeat.log` every 60 s, content a **hardcoded `06/27/2026 22:20:25: Alive` literal** (mtime advances, content lies) | a **human runbook step** (`scripts/wake/README.md:355,760`: *"its absence is the signal"*, `tail -1 ~/heartbeat.log`) | **A DOCUMENTED RUNBOOK STEP LOSES ITS SUBJECT.** Already misleading, because the content never changes. | none needed — the authority has `authority-deadman.timer` (**enabled+active**, LAST 15:59:36Z), which pings an **external** check and is the only mechanism that can report the authority's own death |

**One unit nobody asked about: `secretary-backup.service` is `failed` on the office box.** Per 132 §4 it is
the **second writer** if anyone "fixes" it. It is correctly inert and must stay so.

### 4.2 Non-timer dependencies — the three that actually cost something

**A. The bare git remotes (§2.1).** Office bare repos measured on the box:
`bin.git`, `ceo-kernel.git`, `harness-config.git`, `home.git`, `mesh-security.git` (+ `repos/halacha.git`,
`repos/lpt-books.git`). **13 remotes across 2 machines** point at them and all resolve today.
136 §1 records **71 unpushed commits** in each of `/home/zabz/bin` and `/home/zabz/code/harness-config`
relative to their remotes — so some of what dies may be unpushed work. I did not enumerate refs (§5.7).

**B. The rollback anchor — REAL DATA LOSS.** The pristine frozen copy exists **only on the office box**:
`/home/zabz/cutover/office-frozen.db` = **23,622,823,936 B**, sibling `FROZEN` marker
`frozen 2026-10-11T04:46:27Z lsof=0 size=23622823936 snapshot=23622823936`, and `snapshot3.log` proving
the procedure (`CLEAN: zero holders`, `.backup` rc=0 in 1495 s, `SIZES EQUAL`, `integrity_check: ok`).
On the cloud, `find / -xdev -type f -size 23622823936c` → **no file**; `/root/authority.db` has **grown**
to 23,764,770,816 B (+142 MB, live WAL) — **it is not a pristine copy**. In R2 the office-era object
(7,234,886,331 B) was **overwritten in place**; only the 6,278,791,492 B (06:46:57Z) cloud object remains.
Also office-only: `/home/zabz/secretary-backups/` = **199 GB, "only copy: yes"** (136 §1 item 16), which
includes a **02:56Z snapshot taken before the 04:28:35Z freeze**. Power-off ⇒ the estate has no byte-exact
pristine copy of the rollback anchor anywhere reachable. That is the single largest irreversible
consequence in this forecast.

**C. The raw transcript archive — PROVED SAFE. The worst case does not exist.** This was the one to test
before switching anything off, and it is discharged:

| | office `/home/zabz/lpt-transcripts` | authority `/opt/company/archive/lpt-transcripts` |
|---|---|---|
| objects on disk | 256 shards, **1,652** files | **16,028** files |
| manifest `object` | **1,652** | **16,028** |
| manifest `arrival` / `machine_contact` / `quarantine` | 1,654 / 2 / 0 | 16,941 / 17 / 0 |

**Decisive test, run locally at 15:56Z:** dumped `select sha256 from object order by sha256` from **both**
manifests and diffed as sets ⇒ **office objects missing from the cloud = 0. The cloud is a strict
superset.** Corroborated by the cloud manifest's own `machine_contact` for `secratary`:
`2026-10-11T15:29:50Z files_seen=2390 files_new=0 newest_source_mtime=1791687728.78`
(= 2026-10-11T04:22:08Z, the last write before the freeze) — and `files_new=0` at 14:23:05Z, 15:23:30Z
and 15:27:29Z too. 136 §1 item 6 ("only copy? yes") is **superseded**: the pull completed the office box
at 06:39:25Z. **Powering the office box off does not destroy the training data.**

### 4.3 Office-only cron families with no successor

`/home/zabz/cutover/crontab.before` = 176 lines carrying **87 `cron-wrap.sh` payloads**. The authority's
root crontab carries **21–22**. **66 office jobs have no same-named cloud successor.** All 87 are
**ALREADY DEAD** — `cron.service` is masked and inactive, recorded by `snapshot3.log` at 04:03:33Z
(`cron=inactive cron.socket=inactive … masked=masked`). **The power-off neither causes nor cures this.**
Grouped, with the ones that have a differently-named successor marked:

- **Money/CFO, no successor:** `auto-categorize`, `nightly-plaid-sync`, `daily-finance-sync-cron`, `cfo-ask`,
  `cfo-scoreboard`, `cfo-shift`, `pain-check`, `lpt-daily-track`, `lpt-business-report`, `lpt-report-freshness`.
  (141 records the ledger as moved to `/root/accounting-data/live/accounting.db`; **I did not verify a cloud
  runner for any of these jobs** — §5.8.)
- **Owner channel / wake, no successor:** `owner-ask`, `owner-attention-digest`, `serve-phone`, `serve-phone-2`,
  `wake-fanout`, `wake-balance`, `wake-cost`, `run-wake-sources`, `chip-resume`. (The authority runs
  `phone-gate`/`phone-redirector`/`phone-engine` as **services** instead of `serve-phone` cron.)
- **Core / sentinel / HA, no successor:** `run-sentinel`, `run-ha-truth`, `run-ha-behaviour`,
  `converge-authority`, `profile-gate`, `engine-watch`, `model-failover-watch`.
- **Comms / store freshness, no successor:** `reconcile-sms-status`, `store-write-check`, `text-channel-check`,
  `text-line-check`, `dialpad-call-fresh`, `comms-refresh`, `comms-refresh-2`, `website-comms-push-cron`,
  `push-dsh-sessions`. (`lpt-freshness-watchdog` and `lpt-deploy-drift` **do** exist on the authority.)
- **Mesh / estate, no successor:** `mesh-health`, `mesh-placement-monitor`, `node-agent-cron`, `git-health-check`.
- **Shop / ops, no successor:** `lpt-hub-refresh`, `lpt-recon-check`, `lpt-retranscribe`, `audit`,
  `work-integrator`, `tree-integrity-check`, `hours-drift`, `order-feed-refresh`, `supplier-order-ingest`,
  `supplier-delivery-watch`, `stripe-key-watch`, `backup-phoenix-evidence`, `check-phoenix-evidence`,
  `check-phone-ui`, `monitor-hetzner-backups`, `sync`.
- **Superseded under a different name (not gaps):** `deadman` → `authority-deadman.timer`; `push-db-offsite`
  + `company-offsite-push` → `authority-offsite-backup.timer`; `transcript-archive` →
  `transcript-archive-pull.timer`; `report-offsite-age` → `authority-report-offsite-age.timer`;
  `box-health-check` → folded into the authority's `estate-monitor`; plus `db-integrity-check`, `disk-guard`,
  `cron-target-guard`, `cron-script-guard`, `guard-registry`, `journal-commit`, `prune-backups`, `sms-inbox`,
  `mirror-owner-sms`, `reconcile-sent-status`, `dialpad-*-harvest/-gap`, `ai-gateway-health`,
  `site-uptime-check-cron`, `tmpfs-reaper` — same name on the authority.
- **LAN-bound, cannot move to Ashburn:** `check-security-absence`, `run-ha-truth`, `run-ha-behaviour`
  address `192.168.50.34` / `192.168.50.23` / `HA_URL=http://homeassistant.local:8123`. Home Assistant is
  physically at the office: powering off the office box does not kill HA, but it removes the only on-LAN
  host that could ever watch it.

### 4.4 THE FORECAST — what breaks the day that box is switched off, in order

**Already broken by the freeze (not caused by power-off, and not repaired by it):** cron masked, all 87
jobs dead; `secretary-api`, `secretary-dashboard`, `phone-engine` disabled; the database frozen at
04:28:35Z; the office `estate-monitor` escalated 19 times into a file nobody reads; the office
`company-outcome-monitor` emitting CRITICAL about a dead database into a journal nobody reads; the
owner's phone route landing on a box with no phone engine (15:33:49Z–15:53:55Z).

**Breaks on power-off, most severe first:**

1. **The pristine rollback anchor is destroyed — REAL, IRREVERSIBLE DATA LOSS.** §4.2B. Nothing on the
   cloud, nothing in R2, no second copy. Lost with it: 199 GB of office-only `secretary-backups/`
   including the 02:56Z pre-freeze snapshot.
2. **The mesh broker dies — REAL CAPABILITY LOST, no successor.** The broker runs **only** on the office
   box (§2.2) and the authority's `mesh-broker.service` is `disabled`+`inactive`. Power-off ⇒ every
   broker-mode child dispatch on the estate fails `broker-unreachable`. Every default that points at it
   (`profiles/*/cordis.patch.yml`, `broker-client.js:163`, `nodes.js:133`, `mesh-run.mjs:52`) has to be
   repointed first, **and the broker itself has to exist somewhere.** This is the highest-value
   *repairable* item in the forecast.
3. **Git push/pull dies for 13 remotes across 2 machines.** §2.1/§4.2A. Every node's `harness-config`
   convergence stops; the `mirror` fallback points at `linux-pc`, another office-LAN box.
4. **The off-LAN SSH escape hatch and the dialer stop answering — REAL CAPABILITY LOST until repointed.**
   `secretary-ssh.abletelsolutions.com` (ssh → office `:22`, the `secretary-cf` alias in every Windows
   ssh config) and `dialer.abletelsolutions.com` (`:8899`, already dead — public 502 today). The
   authority's own tunnel config says these backends *"stay on the office box until they are moved"*.
5. **`lpt-write` keeps failing on the authority — already broken, gets no worse.** `AUTHORITY_SSH="secratary"`
   plus a hostname not in `AUTHORITY_NAMES` (§2.4). Today it ssh's to a live box that no longer holds the
   role; on power-off it ssh's to nothing. Either way customer writes do not land where they should.
6. **The phone/runner surfaces stop — impact UNKNOWN.** `vscode-tunnel.service`, `phone-gate` (:3086),
   `phone-redirector` (:3087), `xvfb-login.service` and the self-hosted GitHub runner all stop. The
   authority already runs `phone-engine`, `phone-gate`, `phone-redirector`, `secretary-dashboard` and its
   own `cloudflared`, so the phone trio is **probably** superseded — but the office-side `serve-phone-2`
   (`*/2`) competing for `/phone` (§1.4) means the retirement should be checked against the live route,
   not assumed. For the runner: **no workflow in `phone-and-tech-full`, `personal-secretary-mvp` or
   `kosher-filter-ai` requests `self-hosted`** (0 matches; every `runs-on:` is `ubuntu-latest`), so no
   *measured* CI depends on it — a remote-only workflow could.
7. **Monitoring stops, and none of it is consumed — SILENT WASTE, not breakage.** Office `estate-monitor`
   (no reader), `trunk-check` (no reader), `company-outcome-monitor` (no reader). Two consequences that
   are **not** silent waste and must be stated: **trunk-drift measurement now exists nowhere**, and the
   office monitor's own doc-level claim that the box "stays its own monitor of record" becomes false the
   moment it is off.
8. **`fa-index` effect stops; `fa` has no successor anywhere** (§4.1). The authority has no fast-search
   index and no `fa` tool. This is a *desk* tool by 137's own reasoning, so the question is for the
   machines you type on, not the server.
9. **`tmp-reaper` stops — nothing lost** (the authority's `tmpfs-reaper` cron covers `/tmp`).
10. **The orphan heartbeat stops — trivial**, and the human runbook step that reads it loses its subject.

**The one thing the forecast clears:** powering the office box off **does not destroy the transcript
archive** — §4.2C, proven by set difference. That was the highest-consequence hypothesis and it is now
evidence, not hope.

---

## §5 — WHAT I COULD NOT DETERMINE

1. **Cloudflare Access applications and policies — UNMEASURED.** `GET /zones/{zone}/access/apps` → **403**
   (`Authentication error`); `GET /accounts/{acct}/access/apps` → 200 with **`result: []`, count 0** —
   while Access login redirects are demonstrably live for `secretary-ssh.`, `desktop-ssh.`, `ha.`,
   `yocheved-*`, `printer.`. Six `aud` claims were observed but not resolved. **The empty list is a token
   visibility artefact, not truth.** I cannot say which identities can reach the two office-hosted
   hostnames — i.e. **exactly who can still ssh to the box being retired via `secretary-ssh.`**.
2. **Whether the `/home/zabz` symlink farm on the authority is permanent or a cutover crutch.** This
   decides whether three live cron payloads (`sms-inbox`, `mirror-owner-sms`, `reconcile-sent-status`)
   and nine `company_blueprint.py` `local_path` defaults are "stale literals that can wait" or "about to
   break". **It has no recorded owner or deletion date.** It is the largest un-decided item found.
3. **The third Dialpad webhook**, `https://api.lakewoodphoneandtech.com/webhooks/dialpad/sms` → resolves to
   `2.28.33.58`, not proxied, public GET 404. `lakewoodphoneandtech.com` is **not in this Cloudflare
   account** (0 zones). Whether it still delivers is unmeasured — outside this token's reach.
4. **The backend behind `ha.abletelsolutions.com`.** The tunnel is healthy (4 conns from the office WAN)
   but `http://homeassistant:8123` is a container/DNS name on a host that is **not** the office box
   (no `:8123`, no `:36500`, no docker), and Access blocks an end-to-end probe. The tunnel is fine; the
   backend is unmeasured.
5. **The mac mini's git remotes and archive-pull state.** `ssh` from the office box → `No route to host`
   (asleep). Its LaunchAgent hub (§3.6) was read from the mac's own filesystem; its remotes were not.
6. **Whether the laptop's OS hostname is `ZABZ-YOGA` or `ZABZ-YOGA-1`.** `harness-sync.mjs` keys on
   `os.hostname()` to find `settings/machines/<HOST>.yaml`; there is a `ZABZ-YOGA.yaml` and no
   `ZABZ-YOGA-1.yaml`. If the host is suffixed, the laptop **silently loses** its `deepinfra` provider and
   `maxParallelToolCalls: 20`. Cheap to settle; not settled.
7. **The unpushed work inside the office bare repos.** I did not enumerate refs on `harness-config.git`,
   `bin.git`, `home.git`, `mesh-security.git`, `ceo-kernel.git`; the "71 unpushed commits" figure is
   carried from 136, not measured by me. The size of the git loss in §4.4 item 3 is therefore bounded only
   by that quote.
8. **Whether the 66 office-only cron families have cloud successors under *other* names.** I matched by
   name. 141 records the accounting ledger as moved, but I did not verify a cloud runner for
   `nightly-plaid-sync`, `daily-finance-sync-cron`, `cfo-*` or any of the money family. **The money family
   is the least verified and the most expensive to be wrong about.**
9. **Which preset the authority's phone/harness engine actually mounts.** `/root/.dsh` has no
   `.agent-presets`; presets are embedded in `profiles/web/cordis.patch.yml` and `settings.yaml` says
   `default: zabz`. The yocheved→office-box `ps_*` row on the authority is therefore reported as
   **LATENT**, not confirmed-active.
10. **`zabz-tech-linux`'s `mcp-secretary-linux` row** — the repo has `ps_mcp_server.py` there but no
    `.venv/bin/python` and no `data/secretary.db`; UNMEASURED.
11. **The `secretary-standby` tunnel's host** (`b69e2492`, origin `2a01:4f8:c016:891a::1`, no PTR) — its
    identity and software version are unknown. Impact today is nil (no DNS record references it), but it
    is a fourth healthy tunnel nobody has accounted for.
12. **Four documents the brief names were not where the brief said.** `137-PORT-SYSTEMD-TIMERS.md` was
    found **nowhere** on `zabz-tech`, on the office box, or anywhere on `secratary-cloud`
    (`find / -xdev`); only `137-patch-company-outcome-monitor.{py,diff}` exist. `131`, `132`, `136`, `141`,
    `145`, `146` exist **only** at `secratary-cloud:/root/out/migration-review/`. This document therefore
    leans on live measurement rather than citations, and **the two doc-artefact sets (repo `docs/mesh/`
    vs cloud `/root/out/migration-review/`) have drifted apart** — worth reconciling.
13. **Not measured at all:** the office box's own `~/harness-config` checkout; Tailscale ACLs (no shell
    surface); Windows profiles other than `ezabz` on either box; `lpt-survivor-01` (`2.31.18.142`, zero
    repo matches); Cloudflare Workers and the `emt`/`mdm`/`yocheved`/`personality` A-records.
14. **One deliberate deviation to disclose:** while proving reachability, the authority workstream
    executed the `sms-inbox` cron payload **once by hand**
    (`/usr/bin/python3 /home/zabz/bin/sms-inbox.py sync --pages 3`). It is read-only against Twilio per its
    own header; it returned real data and was not repeated. No other job was run by hand, nothing was
    restarted, and on the office box every command was `cat`/`head`/`grep`/`ls`/`wc`/`ps`/`stat`/
    `systemctl show|is-enabled|is-active|list-timers|cat`.

---

## §6 — PROVENANCE

| claim | machine | how it was produced |
|---|---|---|
| tunnels, hostnames, ingress, DNS bindings | `secratary-cloud` (API) + `zabz-tech` + this laptop | Cloudflare API v4 with `CF_API_TOKEN` from `/opt/company/.env`, values never printed; CNAME→UUID matched to the tunnel list |
| `dialer.` 502, `printer.` 530, `secretary-ssh.` 302, `api./health` 200, `ai./` 307 | **this laptop** | `curl -sS -k -o NUL -w "%{http_code}"` at 16:01Z |
| the phone route's current target and its two repairs | **this laptop → secratary-cloud** | `cat /etc/cloudflared/phone-redirector.env`, `curl -i :3087/phone`, `systemctl show -p ActiveEnterTimestamp`, three `ls -la --time-style=full-iso` backups |
| `company_outcome_monitor.py:395` runs the wrong unit | **this laptop → secratary-cloud** | `sed -n '388,400p'`; then `journal_lock_unit()` and `_journal_lock_events(7)` executed in `/opt/company/.venv` |
| the authority's hostname, `/home/zabz` symlink farm, `repos`/`lpt-hub` absence | **this laptop → secratary-cloud** | `hostname`; `ls -la /home/zabz`; `ls -d /home/zabz/repos /home/zabz/lpt-hub` |
| authority `.env` office literals, broker disabled, listeners, ported timers | **this laptop → secratary-cloud** | `grep -E` on named keys (values of secrets never printed); `systemctl is-enabled/is-active`; `ss -ltnp`; `systemctl list-timers` |
| this laptop's git remotes, DSH broker/MCP rows, listeners | **this laptop** | `git -C … remote -v`; `Select-String` on `~/.dsh/**`; `netstat -ano` |
| the 5 office timers enabled+active, load, listeners, heartbeat PID | **this laptop → secratary-ts** | `systemctl list-timers --all`, `is-enabled`, `is-active`, `ps -p 1673`, `cut -d' ' -f1-3 /proc/loadavg` |
| internal office state: 24 timers, 87 cron payloads, running units, bare repos, 199 GB backups | `zabz-tech` → `secratary-ts` | read-only, bounded; captured in `_mig149-shutdown/SECTION-4-REPORT.txt` |
| the transcript-archive set difference (=0) | `zabz-tech` | `select sha256 from object order by sha256` from both `manifest.sqlite` files, diffed as a HashSet; 1,652 vs 16,028 lines retained in `_mig149-shutdown/office-object-shas.txt` and `cloud-object-shas.txt` |
| repo file+line references | `zabz-tech` (grep workstream) | ripgrep over 4 repos, per-pattern counts recorded |
| per-machine config (tasks, cron, MCP, `.env`, ssh) | `zabz-tech` + `lakewooechsmini` | enumerated on each node and over ssh; scratch in `_mig149-config/SECTION3-REPORT.txt` |
| the authority unit/cron/`/opt/company` sweeps | `lakewooechsmini` | 510 unit names → 415 unit+drop-in files; **zero non-comment hits** |
| mesh placement of all six workstreams | the broker | each child self-reported its hostname; the provider's placement line named the node |

**Workstream scratch directories** (throwaway, safe to delete): `_mig149/`, `_mig149-code/`,
`_mig149-config/`, `_mig149-shutdown/`, `_mig149-mcp/`, `_mig149-auth/` under `C:\Users\ezabz\code\`.

---

## §7 — WHAT I WOULD FIX, IN ORDER

Not a question for the owner — recorded so the next session starts where this one stopped.

1. **Move the mesh broker off the office box, or accept the fleet stops dispatching.** §4.4 item 2.
   Everything else is repointing; this one needs a decision and an install.
2. **Make a pristine copy of the frozen anchor before the box is switched off.** §4.2B. It is 23.6 GB and
   the cloud's disk is the binding constraint — so this needs an answer (the VPS `lpt-survivor-01`, the
   vault `lpt-apps-01`, or R2 at a **new key** rather than the overwritten one) before the box dies.
3. **Re-point `origin` on every node's `harness-config`, and move the mirror off `linux-pc`.** §2.1.
4. **Fix `company_outcome_monitor.py:395`** — a one-line change that converts a fabricated zero into a
   measured one. §2.9.
5. **Repoint the `ps_*` rows at the authority** (or at the local Linux row pattern that already exists).
   §2.3, §3.7. Otherwise the owner's company interface dies quietly at retirement.
6. **Fix `lpt-ops` `AUTHORITY_NAMES` + `AUTHORITY_SSH`.** §2.4. Customer writes are misrouted today.
7. **Decide the `/home/zabz` symlink farm's fate** (§5.2) and `MACHINE_NAME=secratary` (§2.7).
8. **Repoint the four hostnames that land on the office box or nowhere** — `secretary-ssh.`, `dialer.`,
   `desktop-ssh.`, `printer.`, `yocheved-*` (§1.7) — and **delete `829bc0fb`'s shadowed `ai.`/`api.`
   rules** so the next reader is not fooled.
9. **Add a probe that would have caught the incident:** nothing in the estate probes `ai./phone` or
   `dialer.`. §1.5. This is the cheapest item on the list and the reason the audit exists.
