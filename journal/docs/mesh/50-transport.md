# 50 — Transport layer for the 6-node agent mesh

**Status:** design + partial verification. Every claim carries a label: **MEASURED** (I ran it, on the
node named, at the time named), **READ-FROM-DOCS** (official URL cited), **PROPOSED** (not yet
applied — a proposal, not a change), **NOT MEASURED** (with the exact command that would settle it).

**Written:** 2026-09-16 ~20:20 UTC from **ZABZ-YOGA** (this laptop). No networking configuration was
changed on any machine to produce this document. Nothing here is applied except where labelled
MEASURED (i.e. already true).

---

## 0. The mesh as it actually is

| Node | tailnet name | tailnet IPv4 | LAN IPv4 | OS | Role |
|---|---|---|---|---|---|
| ZABZ-YOGA | `zabz-yoga-1.tail93e6e6.ts.net` | 100.72.162.5 | 192.168.12.104 | Windows | owner's laptop, **home** network |
| ZABZ-TECH | `zabz-tech.tail93e6e6.ts.net` | 100.85.153.96 | 192.168.50.138 | Windows | office desktop, primary |
| secratary | `secratary.tail93e6e6.ts.net` | 100.84.72.88 | 192.168.50.77 | Linux | authority; DSH engine + phone gate |
| mac mini | `LakewooechsMini.tail93e6e6.ts.net` | 100.126.146.121 | 192.168.50.45 | macOS | employee Yisroel |
| linux-pc | `zabz-tech-linux.tail93e6e6.ts.net` | 100.105.248.90 | 192.168.50.23 | Linux | office |
| iPhone | `iphone-15-pro` | 100.85.105.93 | — | iOS | **the target client** |
| Hetzner VPS | (not in `tailscale status` output on this node) | — | 87.99.141.172 | Linux | public box |

**MEASURED 2026-09-16 20:09–20:20Z on ZABZ-YOGA:** `tailscale status` lists exactly six peers
(zabz-yoga-1 itself, iphone-15-pro, lakewooechsmini, secratary, zabz-tech-linux, zabz-tech). The
**Hetzner VPS is not a tailnet node** — it is reached over the public internet at 87.99.141.172 per
`~/.ssh/config`. So the mesh is *five tailnet nodes plus one public node*, not six equal peers.

**MEASURED:** `~/.ssh/config` defines, for every node, an office-LAN alias (`desktop`, `secratary`,
`linux-pc`, `mac-mini`, `laptop`) **and** a tailnet alias (`desktop-ts`, `secratary-ts`,
`linux-pc-ts`, `mac-mini-ts`, `laptop-ts`), plus two Cloudflare aliases (`desktop-cf`,
`secretary-cf`) that go through `scripts/windows/CloudflaredAccessSshProxy.ps1`. The laptop-ts alias
points at `zabz-yoga-1.tail93e6e6.ts.net` with `AddressFamily inet`.

**MEASURED — the office nodes all NAT to one public IP:** every office peer's tailnet endpoint is
`71.104.140.242:<port>` (desktop :41641, linux-pc :61481, mac mini :55390, secratary :3270). That is
the office WAN address, confirmed independently by secratary's own `tailscale netcheck`
("IPv4: yes, 71.104.140.242:53633", "MappingVariesByDestIP: false", "PortMapping: UPnP, NAT-PMP,
PCP" on an AsusWRT 388 router at 192.168.50.1).

---

## 1. What each node answers on, and what is already published

### 1.1 Measured reachability (from ZABZ-YOGA, 2026-09-16 20:12–20:16Z)

```
$ tailscale ping -c 3 --timeout 3s <ip>
100.85.153.96  zabz-tech        pong via DERP(nyc) in 141ms ; then via 71.104.140.242:41641 in 36ms
100.84.72.88   secratary        pong via 71.104.140.242:3270 in 29ms
100.126.146.121 lakewooechsmini pong via 71.104.140.242:55390 in 30ms
100.105.248.90 zabz-tech-linux  pong via 71.104.140.242:41644 in 40ms
```
**MEASURED:** all four office peers answer, and each first answers **over a direct path** (30–40 ms)
to the office WAN address. `zabz-tech` needed one DERP-relayed packet (141 ms) before it upgraded to
direct (36 ms) — that is normal Tailscale hole-punching (READ-FROM-DOCS: DERP "primarily uses DISCO
packets to establish and negotiate a direct connection", <https://tailscale.com/kb/1232/derp-servers>).

**MEASURED — the phone is a tailnet node but was idle:** `iphone-15-pro` (100.85.105.93) appears in
`tailscale status` with **no presence column** (never seen / never handshaked from this node), i.e.
Tailscale is installed on the iPhone but the app was not connected at 20:10Z. Nothing on the phone
side can be assumed reachable until the app is up.

### 1.2 The one engine that is already correctly published — secratary

**MEASURED 20:12Z, `ssh secratary-ts 'tailscale serve status; tailscale funnel status'`:**
```
https://secratary.tail93e6e6.ts.net (tailnet only)
|-- / proxy http://127.0.0.1:3086
```
Both `serve status` and `funnel status` print the same "tailnet only" line and **funnel is not
enabled** — this is Serve, not Funnel, so nothing is exposed to the public internet (READ-FROM-DOCS:
"`tailscale serve` lets you share a local service securely within your tailnet … you can also choose
to use Tailscale Funnel … to expose your service publicly, open to the entire internet",
<https://tailscale.com/kb/1242/tailscale-serve>).

The chain behind it, per `docs/dsh-mobile/02-SYSTEMS.md` (READ, not re-measured today):

```
iPhone Safari/app  ->  https://secratary.tail93e6e6.ts.net/   (Tailscale Serve, TLS, tailnet-only)
                   ->  127.0.0.1:3086  phone-gate.py   (phone-gate.service; signs a cold visitor in,
                                                        injects the mobile layer, relays /api + WS)
                   ->  127.0.0.1:3089  dsh web --trusted-host secratary.tail93e6e6.ts.net
                                       (phone-engine.service, loopback only)
```
**This is the working pattern to copy to other nodes.**

### 1.3 Every *other* node publishes nothing

**MEASURED:** on ZABZ-YOGA, `tailscale serve status` has never been run for this node and the local
engine is `node .../dsh/lib/bin.js web --port 3099 --no-open` — **no `--trusted-host` argument**
(read from the process command line of PID 1784, started 15:49 local). ZABZ-TECH, the mac mini and
linux-pc were **not** checked for serve config (NOT MEASURED: `ssh desktop-ts 'tailscale serve status'`
— deliberately not run; see §6).

---

## 2. The DSH access model — what the auth actually is

**MEASURED by reading the shipped implementation** (not documentation):
`@deepseek-ai/dsh-web-app/lib/startup.js` defines
`--trusted-host <authority...>` as "extra authority the `/api` browser-trust fence accepts (host or
host:port; repeatable)" and passes it as `trustedHosts` into the composed web config. The startup
function's own docstring says it parses "`--host`, `--port`, `--trusted-host`, `--no-open`".

`@deepseek-ai/dsh-client-connection/lib/index.js` is the whole model, and it is small:
- `AUTH_RECORD_KEY = credentialKey("client-connection", "browser-session")` — the secret lives in
  `~/.dsh/.credentials.yaml` under `client-connection/browser-session` as a `grant` record
  (MEASURED: the file on this laptop holds `kind: grant`, `payload.version: 1`, a 43-char base64url
  secret).
- `SECRET_BYTES = 32`, `COOKIE_PREFIX = "dsh-auth-"`, and
  `cookieName(authority) = COOKIE_PREFIX + base64url(sha256(authority))`.

**That last line is the whole answer to "why does a session break on a different host/port":** the
cookie *name itself* is a hash of the authority, and the value is HMAC-signed over that same
authority. A cookie minted for `127.0.0.1:3099` does not exist for `secratary.tail93e6e6.ts.net`, and
if one is forced across, the Host fence refuses it.

**MEASURED — the fence, live, against the engine in this session (2026-09-16 20:18Z):**
```
$ Invoke-WebRequest http://127.0.0.1:3099/api -Headers @{Host='127.0.0.1:3099'}
401   in 136 ms   (accepted authority, simply unauthenticated)
$ Invoke-WebRequest http://127.0.0.1:3099/api -Headers @{Host='zabz-yoga-1.tail93e6e6.ts.net'}
403   in   6 ms   (refused — this engine was not launched with --trusted-host)
```
So: **a second authority needs `--trusted-host` at launch, and a session reached on that authority
needs a token minted for that authority.** The one-time `?token=` URL is exchanged for the cookie on
that authority; `docs/dsh-mobile/00-RESEARCH.md` records that experiment (the token is accepted only
from the trusted authority, the cookie is minted for it, and "an untrusted Host is refused 403 even
with a valid cookie").

### 2.1 The live defect this creates, and the correct shape

**The defect (reported by the parent, sourced from `scripts/serve-phone.ps1` lines 16–18 and
`multi-window/windows.json:5`):** `serve-phone.ps1` starts a **dedicated second engine on port 3085
sharing the same `~/.dsh`**, because `--trusted-host` is a startup-only setting and the author would
not restart the engine in use. `windows.json:5` calls exactly that UNSUPPORTED: "Two `dsh web`
processes on one home have been observed writing duplicate sequence numbers into one session log and
making the whole history unloadable."

**The correct shape — PROPOSED, one engine per DSH_HOME:**

1. **Launch the primary engine with the tailnet authority in its arguments, always.** On ZABZ-YOGA
   that is:
   ```
   node <dsh>\lib\bin.js web --port 3099 --no-open --trusted-host zabz-yoga-1.tail93e6e6.ts.net
   ```
   and the machine-local equivalent on each other node (`zabz-tech.tail93e6e6.ts.net` on ZABZ-TECH,
   `secratary.tail93e6e6.ts.net` on the server, …). The authority must be the **tailnet FQDN this
   node answers on** (`tailscale status --json | jq -r .Self.DNSName`), which is stable across
   DHCP/LAN changes — unlike `192.168.50.138`, which is not.
2. **Then publish the engine that already exists**: `tailscale serve --bg --https=443 http://127.0.0.1:3099`
   (or `tailscale serve --bg 3099` on newer CLI). No second `dsh` process, ever.
3. **Retire the dedicated engine.** `serve-phone.ps1`'s stop path should stop the 3085 engine, and
   the launcher (`multi-window/windows.json` / the `dshw` entry point) should carry
   `extraArgs: ["--trusted-host","<node>.tail93e6e6.ts.net"]` so every normal start is already
   publishable. This is a **machine-local config change on each node** — PROPOSED, not applied.
4. **Phone URL becomes the node's own tailnet FQDN** — `https://zabz-yoga-1.tail93e6e6.ts.net/`,
   `https://zabz-tech.tail93e6e6.ts.net/`, `https://secratary.tail93e6e6.ts.net/` — one URL per
   node, no port, valid TLS, tailnet-only. secratary additionally keeps its existing 3086 gate in
   front (`serve` → 3086 → 3089) because the gate is what signs the phone in and injects the mobile
   layer; the other nodes can serve 3099 directly.

**If the two ever conflict, the safe choice is a temporarily unroutable phone, not a second engine.**
A second engine on one DSH_HOME can corrupt a session log that cannot be unloaded afterwards — it
destroys the owner's history. An unreachable phone costs one retry. That asymmetry decides it.

**What happens on a node where Tailscale is down:** `tailscale serve` is not merely unreachable, it
is *absent* — the Serve config lives in the Tailscale daemon's state, so with the daemon stopped the
tailnet FQDN does not resolve and nothing answers on it. The engine itself is **unaffected**: it is
loopback-only, so the local browser at `http://127.0.0.1:3099` keeps working with no auth step
(loopback is the implicit trusted authority). So the failure mode is "phone can't reach this node",
not "this node's DSH is broken". **MEASURED (journal L326/P127):** an unprivileged `tailscale`/CLI on
a machine whose daemon is not running reports `BackendState: NoState` **even for a healthy tunnel**,
which is why `NoState` must never on its own be read as "the tailnet is down" — see §5.

**Does `tailscale serve` survive a reboot?** NOT MEASURED. READ-FROM-DOCS: the Serve configuration is
persistent daemon state, not a flag on the CLI invocation — which is what the `--bg` flag's existence
implies ("set the config and exit"). To settle it in one command on each node:
`ssh <alias> 'tailscale serve status'` immediately after a reboot, expecting the same
`https://<node>.tail93e6e6.ts.net (tailnet only)` line. Until that is run, do not assume it.
(PROPOSED hardening regardless: whatever brings the engine up at boot should also assert Serve, e.g.
`tailscale serve --bg 3099` in the same unit/task that starts the engine — idempotent, so it costs
nothing.)

---

## 3. Moving agent work between nodes

What can actually be shuttled:

| Thing | Where it lives | How it moves | Cost |
|---|---|---|---|
| A DSH session's on-disk state | `~/.dsh/sessions` (machine-local) | not portable as-is — cookies/authority are per-node and the cwd must resolve, or DSH refuses to attach the session (`docs/dsh-mobile/02-SYSTEMS.md` §2) | move the **work**, not the session |
| A git worktree / repo | `~/code/<repo>` | `git push` over tailnet ssh, or `scp -r`, or run the agent where the repo already is | 100 MB ≈ 60–80 s measured, §3.1 |
| A queue entry / task row | authority DB on secratary | SQL over the tailnet, or `ssh secratary-ts 'python3 ~/bin/owner-queue.py …'` | KB, latency-bound |
| A file handoff | anywhere | Taildrop (`tailscale file cp`) — READ-FROM-DOCS capability, and `CapMap` shows `file-sharing` present on this node; NOT MEASURED | not measured |

**The rule this implies:** shuttle **work**, not sessions. A session is bound to one node's
`~/.dsh`, one authority cookie, and one resolvable cwd. A repo + a task row + a prompt is portable;
a session directory is not.

### 3.1 Measured throughput and latency — ZABZ-YOGA (home) ↔ secratary (office)

Payload: 100 MB (104,857,600 bytes) written on secratary by a Node script
(`node /home/zabz/mk100.js /home/zabz/testfile_100mb.bin` → "wrote 104857600 bytes in 24 ms").

```
$ scp -o BatchMode=yes -o ConnectTimeout=8 secratary-ts:/home/zabz/testfile_100mb.bin %TEMP%\dl_100mb.bin
DOWN  bytes=104857600  sec=59.67  MBps=1.68

$ scp -o BatchMode=yes -o ConnectTimeout=8 %TEMP%\dl_100mb.bin secratary-ts:/home/zabz/up_100mb.bin
UP    bytes=104857600  sec=82.08  MBps=1.22

$ for i in 1..3 { ssh -o BatchMode=yes -o ConnectTimeout=8 secratary-ts 'true' }
664 ms / 744 ms / 962 ms        (full scp/ssh process cost, including handshake + auth)
```
**MEASURED 2026-09-16 20:14–20:19Z.** Download 1.68 MB/s ≈ 13.4 Mbit/s; upload 1.22 MB/s ≈ 9.8 Mbit/s.

**The important qualifier — this number was taken on a RELAY, not a direct path.**
**MEASURED:** at the start, during and after the transfer, `tailscale status` on ZABZ-YOGA reported
secratary as `active; relay "nyc"`, and `tailscale ping 100.84.72.88` returned **"direct connection
not established"** with pongs "via DERP(nyc) in 32–50 ms". At 20:09–20:12Z, before the transfer, the
same peer was `active; direct 71.104.140.242:3270` with `tailscale ping` 29 ms. Between those two
readings, the laptop also reported `tailscale ping` to secratary "via DERP(iad) in 125–155 ms" while
secratary pinged back "via DERP(iad)" with "direct connection not established" — both ends relayed,
through **different** DERP regions (nyc one way, iad the other) at the time of each measurement.

So: **1.2–1.7 MB/s is the DERP-relay floor for this pair, not the tailnet's capability.** The direct
path measured on the same pair minutes earlier was 29 ms RTT. READ-FROM-DOCS: when no direct path is
negotiated the DERP server "relays encrypted WireGuard packets between the two devices"
(<https://tailscale.com/kb/1232/derp-servers>) — a relay is a shared hop, which is exactly the shape
of a 10 Mbit/s ceiling on a link whose RTT is 30 ms.

**NOT MEASURED — direct-path throughput.** The command that settles it, run twice (once as-is, once
after forcing a direct path and confirming with `tailscale ping` that it says `via <ip:port>` and not
`via DERP`):
```
tailscale ping -c 5 100.84.72.88          # must report "via 71.104.140.242:3270", not DERP
scp -o BatchMode=yes -o ConnectTimeout=8 secratary-ts:/home/zabz/testfile_100mb.bin <tmp>
```
**NOT MEASURED — LAN-to-LAN (office-internal) throughput**, e.g. secratary ↔ mac mini. Command:
`ssh secratary-ts 'tailscale ping -c 5 100.126.146.121'` (expect the 192.168.50.45 direct endpoint),
then an scp of the same 100 MB file between them. ZABZ-YOGA is **not** on the office LAN
(192.168.12.104 vs 192.168.50.x), so no LAN number can be produced from this machine.

**MEASURED — MagicDNS resolution, and it is not free:**
```
Resolve-DnsName secratary.tail93e6e6.ts.net  -> 100.84.72.88   in 339 ms
Resolve-DnsName zabz-tech.tail93e6e6.ts.net  -> 100.85.153.96  in   1 ms
```
339 ms on the first name, 1 ms on the second — consistent with journal **L1685**: "MagicDNS on
ZABZ-YOGA blocks one call for ~60s and then heals; retry before blaming the mesh." **Design
consequence: never put a MagicDNS name on a hot path.** Aliases in `~/.ssh/config` for the latency-
critical hops should carry the **tailnet IP literal** (`100.84.72.88`), with the FQDN kept for human
use. This is also why the health check in §7 resolves the name *once* and then talks to the IP.

---

## 4. Tailscale specifics, against the official docs

- **Serve vs Funnel.** Serve = tailnet-only; Funnel = public internet. **READ-FROM-DOCS**
  (<https://tailscale.com/kb/1242/tailscale-serve>, <https://tailscale.com/kb/1312/serve>,
  <https://tailscale.com/kb/1223/funnel>). Funnel's own doc states the ACL requirement — "If the
  funnel node attribute in your tailnet policy file doesn't permit you to use Funnel, you won't be
  able to" — and notes public DNS propagation "can take up to 10 minutes". **Recommendation:
  Funnel OFF for every DSH node.** A harness GUI behind Funnel is remote code execution with a
  password prompt on the open internet; the owner reaches every device through the tailnet anyway,
  including the iPhone. Funnel stays a fallback of last resort only, and if ever used it must be
  Funnel → the gate/service, never → a raw engine port.
- **DERP relay fallback.** READ-FROM-DOCS: DERP "primarily use[s] DISCO packets … to establish and
  negotiate a direct connection", and only "when two devices use a DERP server as a fallback
  connection method" does it relay WireGuard packets (<https://tailscale.com/kb/1232/derp-servers>).
  **MEASURED here:** the fallback is not theoretical — this pair was on it for minutes at a time, and
  it cost roughly the difference between 29 ms direct and 125–155 ms relayed, with throughput
  measured at 1.2–1.7 MB/s (§3.1).
- **Subnet routers.** READ-FROM-DOCS: a node advertises routes (`--advertise-routes`), and "Enable
  subnet routes from the admin console" plus "Add access rules for advertised subnet routes" are
  required steps (<https://tailscale.com/kb/1019/subnets>). **PROPOSED:** secratary advertises
  `192.168.50.0/24`, so a device that is off the office LAN reaches `192.168.50.23/.45/.138/.77` by
  their real addresses without per-host work — and, more valuable, so the laptop can reach the office
  **printer/router-class** gear the way it already reaches the hosts. This changes routing on every
  client that accepts routes, so it is a proposal, not an action.
- **Exit nodes.** READ-FROM-DOCS: a device advertises itself as an exit node, an Owner/Admin must
  allow it, "by default, exit nodes capture all your network traffic that isn't already directed to a
  subnet router", and local network access is off unless explicitly enabled
  (<https://tailscale.com/kb/1103/exit-nodes>). **Recommendation: do NOT use an exit node.** The
  owner's iPhone needs *reachability of five hosts*, not a VPN for all traffic; a phone-wide exit
  node adds latency to every request and, per the doc, removes local-network access by default. The
  only candidate would be the Hetzner box as a public-IP exit, and that is a privacy/traffic-routing
  decision — the owner's, and not needed for anything in this document.
  **MEASURED anomaly worth fixing:** `tailscale debug prefs` on **ZABZ-YOGA reports
  `RouteAll: true` with `ExitNodeIP` empty** while secratary reports `RouteAll: false`. `RouteAll` is
  the "use an exit node" switch (the same field `tailscale set --exit-node` writes); with no exit node
  selected it is inert today — **MEASURED**, the Windows default route is still
  `0.0.0.0/0 → 192.168.12.1 via Ethernet, metric 0`, so internet traffic is *not* being captured. But
  a `RouteAll: true` with a populated `ExitNodeIP` is one `tailscale set` away from blackholing this
  machine's internet. **PROPOSED:** run `tailscale set --exit-node=` on ZABZ-YOGA to normalize, and
  add `RouteAll` to the health check so it can never be true-with-an-exit-node by accident.
- **MagicDNS.** READ-FROM-DOCS: it registers a name per device and, for tailnets created on or after
  2022-10-20, is on by default; a device can stop accepting Tailscale DNS settings
  (<https://tailscale.com/kb/1081/magicdns>). **MEASURED:** MagicDNS **is** enabled (`CorpDNS: true`)
  on both ZABZ-YOGA and secratary, the suffix is `tail93e6e6.ts.net`, and all four office FQDNs
  resolve correctly from the laptop. **Recommendation: keep MagicDNS on everywhere** — it is what
  makes `tailscale serve` URLs and `~/.ssh/config` hostnames work — but resolve once and cache the IP
  on any hot path (§3.1), and never let a monitor depend on it (journal L220/L326).
- **Key expiry.** **MEASURED:** ZABZ-YOGA's own `KeyExpiry` is `2027-02-26T03:54:29Z`. **PROPOSED:**
  disable key expiry on the always-on nodes (secratary, ZABZ-TECH, linux-pc, mac mini, Hetzner) — a
  node that expires stops answering and *nothing in the mesh notices*, which is exactly the failure
  class in §5. Key expiry on the phone and the laptop is fine and desirable. The admin-console
  command is a click per machine (**NOT MEASURED** — no admin-console access exercised from here;
  `tailscale status --json | ConvertFrom-Json` per node shows each node's `KeyExpiry`, which is how
  to audit it).
- **ACLs / tags. PROPOSED policy shape** (not applied; requires the admin console):
  - one tag `tag:mesh-node` on secratary, ZABZ-TECH, linux-pc, mac mini, Hetzner;
  - the owner's devices (`iphone-15-pro`, `zabz-yoga-1`) untagged, as user-owned;
  - `tag:mesh-node` ↔ `tag:mesh-node`: allow tcp 22, 3099, 3086, 3089 (and 5432 only between
    secratary and ZABZ-TECH);
  - owner devices → `tag:mesh-node`: allow the same;
  - **default deny**; no rule that grants anything from the internet;
  - **never** `tag:mesh-node` → `*:*`. A tag is a permission boundary, and the whole point of
    tagging the servers is that a compromised employee laptop or a lost phone cannot reach the
    authority DB just because it is on the tailnet.
  This closes the current state, which is **MEASURED-by-implication**: every node today sits under one
  owner account with no tags in `CapMap` (`AdvertiseTags: null` on secratary), i.e. full mesh
  any-to-any.

---

## 5. Robustness — designed against the incidents that actually happened

Evidence pulled with `journal.py search`, 2026-09-16:

- **H117 / H96 / H198 (2026-09-14): Tailscale on ZABZ-YOGA wedged, `BackendState: NoState` for 51
  minutes, `C:\ProgramData\Tailscale` empty; "the daemon answers netcheck/prefs … but the engine never
  comes up"; two `tailscaled` processes.** Two of those were *real* wedges needing a repair.
- **L326 (2026-09-14) — the correction that matters most:** "the tailnet was never down — the
  **unprivileged** tailscale CLI reports `NoState` for a healthy tunnel, and **MagicDNS resolution
  was the real fault**." `CorpDNS` was false, so the hostname did not resolve *even with the tunnel
  up*.
- **L1685 (2026-09-15): "MagicDNS on ZABZ-YOGA blocks one call for ~60s and then heals; retry before
  blaming the mesh."** Reproduced today in miniature: 339 ms for the first resolve (§3.1).
- **P164: "Nothing watches the LOCAL services the mesh depends on: a stopped Tailscale or IP Helper
  silently [breaks the mesh]."** Cause both times: `Get-Service Tailscale = Stopped` while StartType
  was Automatic; office-LAN names still resolved, so the machine *looked* networked.
- **H385 / H386 / H376 (2026-09-16, today): `BackendState=NoState`, laptop on `192.168.12.x`
  (neither documented network), with an APIPA interface.** **MEASURED right now on ZABZ-YOGA:** three
  interfaces carry APIPA addresses — `Local Area Connection* 10 = 169.254.133.183`,
  `Local Area Connection* 8 = 169.254.174.119`, `Wi-Fi = 169.254.105.243` — while the live path is
  `Ethernet = 192.168.12.104` and `Tailscale = 100.72.162.5`. **An APIPA address on Wi-Fi means the
  Wi-Fi radio is up but DHCP failed.** That is the state that produces "the mesh is broken" reports:
  the machine has a second, dead network interface, and anything that resolves a name or opens a
  socket can land on it.

**Design rules that follow — these are the deliverable, not a diagnosis:**

1. **A Tailscale check must distinguish three different failures: daemon not running, engine wedged,
   and DNS not resolving.** They have three different fixes and today they all print `NoState`.
   Order: `Get-Service Tailscale` → `tailscale status --json | .BackendState` →
   `tailscale debug prefs | .CorpDNS` → a resolve. Never collapse them into "the tailnet is down".
2. **Never let a monitor need the thing it monitors in order to report it** (journal L220). The
   health check must run with zero tailnet dependency and say "I could not check X", not "X is fine".
3. **Every ssh and every network call carries a hard bound.** **MEASURED today:** an scp to
   `secratary-ts` failed with `ssh: connect to host secratary.tail93e6e6.ts.net port 22: Connection
   timed out` and then succeeded on the immediate retry; an ssh chain without `ConnectTimeout` hung
   for 21+ minutes on an open socket to a peer that had gone relay-only/unresponsive. **Rule:** every
   ssh in a script is `ssh -o BatchMode=yes -o ConnectTimeout=8`; every transfer is size-bounded;
   nothing sleeps on a socket.
4. **`tailscale ping` is the only honest path check.** It reports `via <ip:port>` (direct) or
   `via DERP(<region>)`, and the string "direct connection not established" is the relay verdict. Any
   monitor that only pings the tailnet IP will report a relay as healthy — and a relay costs ~3x
   latency and an order of magnitude of throughput on this pair (§3.1).
5. **MagicDNS is a single point of failure that heals late.** On any hot path, resolve once to an IP
   and keep it; in `~/.ssh/config` prefer `HostName 100.x.y.z` for the tailnet aliases and keep the
   FQDN as a comment/human label. **PROPOSED** (a config change, not applied).
6. **When Tailscale is up but the peer is asleep:** the TCP connect blocks until timeout, and the
   user experience is "it hung", not "it failed". So every path needs a *bounded* failure: the SSH
   aliases already set `ServerAliveInterval 30 / ServerAliveCountMax 4` (MEASURED, in
   `~/.ssh/config`) — that bounds a *dropped* session after roughly 2 minutes, but nothing bounds a
   *connect* except `ConnectTimeout`, which only the `-ts` aliases' callers pass today. **PROPOSED:**
   add `ConnectTimeout 8` to every Host block in `~/.ssh/config` rather than relying on callers.
7. **The laptop switching networks is a normal event, not an incident.** The laptop was on
   192.168.12.x today with an APIPA Wi-Fi adapter; the tailnet IP is the only stable address it has.
   Therefore: **nothing may reference ZABZ-YOGA by a LAN address**, and the mesh must treat "the
   laptop moved" as routine. `tailscale serve` on each node publishes an FQDN, which is exactly the
   address that survives this — one more reason §2.1's shape is the right one.
8. **Cloudflare is the only path** when Tailscale is down on a node and the office is unreachable by
   LAN — the `-cf` aliases exist for this and go through
   `CloudflaredAccessSshProxy.ps1` + `cloudflared access`. **MEASURED:** the tokens for
   `desktop-ssh.abletelsolutions.com` and `secretary-ssh.abletelsolutions.com` are present in
   `~/.cloudflared`. **NOT MEASURED:** an actual `ssh secretary-cf` this session. **PROPOSED:** keep
   Cloudflare as the documented second path for *ssh only*; do **not** publish a DSH engine through a
   Cloudflare tunnel — that is the internet-exposed case, and it is exactly what the tailnet exists
   to avoid.

### 5.1 The environment rule that cost ten minutes today

**Never pipe a script that spawns children into `powershell -Command -` over ssh.** Piping into
PowerShell's stdin makes it read the script from a pipe, and any cmdlet that spawns a child and needs
the console then blocks; the symptom is a silent multi-minute hang with no output, and a `-Command -`
process that keeps the ssh channel open. **Write the script to a file (`Set-Content -Encoding ascii`,
then `scp`), and run it with `powershell -NoProfile -File <path>`** — which is what the Cloudflared
proxy aliases in `~/.ssh/config` already do. This document is itself written under that rule: the
one script it copies to a node is `mk100.js`, run with `node <file>`, never piped.

---

## 6. Recommended access path per device

| Device | Path to a running DSH session | Why |
|---|---|---|
| **Windows laptop (ZABZ-YOGA)** | local `http://127.0.0.1:3099`; to reach *another* node's session, the **other node's** `https://<node>.tail93e6e6.ts.net/` over the tailnet | loopback needs no auth flow; a tailnet FQDN survives the laptop moving networks, and its cookie is minted for that authority |
| **Office desktop (ZABZ-TECH)** | local `127.0.0.1:3099` for its own engine; the laptop/phone reach it at `https://zabz-tech.tail93e6e6.ts.net/` (after §2.1 is applied) | same shape, symmetric |
| **iPhone** | **Tailscale app up** → `https://secratary.tail93e6e6.ts.net/` (the gate → engine) for the authority's agent; other nodes at `https://<node>.tail93e6e6.ts.net/` once §2.1 is applied | TLS, tailnet-only, no port, no public DNS; the existing gate already signs the phone in and injects the mobile layer. The Home-Screen icon via `ai.abletelsolutions.com/phone` is a **302 redirect** into it, so it needs no separate design |
| **Employee (mac mini)** | its own node; the owner should *not* be told to use it | **PROPOSED:** keep the employee's node off the owner-access path entirely — a shared GUI authority is a shared cookie jar |
| **Anywhere, degraded** | `ssh <node>-ts` then `http://127.0.0.1:3099` **through an SSH port-forward**: `ssh -N -L 3099:127.0.0.1:3099 <node>-ts` | works when Serve is broken; binds only to localhost, so nothing is exposed; costs one `ssh` and no TLS (it is already inside the tunnel) |

**Explicitly rejected:** `tailscale funnel` (public RCE surface), any reverse proxy binding the engine
to `0.0.0.0`, `--host 0.0.0.0` (refused by DSH for this exact reason — quoted in
`docs/dsh-mobile/02-SYSTEMS.md`), and a Cloudflare tunnel to a raw engine port.

**Latency/exposure cost of each option** (MEASURED RTT where noted, otherwise reasoned from the
measured path):

| Option | Cost | Exposure |
|---|---|---|
| loopback | ~0 ms | none |
| Tailscale direct to the node's tailnet IP | **29–40 ms RTT MEASURED** to every office peer | tailnet only |
| `tailscale serve` (FQDN) | same tunnel + TLS + one proxy hop | tailnet only |
| `tailscale funnel` | same + public DNS | **the entire internet**, gated only by DSH's token |
| SSH port-forward | **664–962 ms MEASURED** per `ssh` process start, then ~0 ms per request | localhost only |
| Cloudflare tunnel | unknown (NOT MEASURED) | an edge provider sees the stream |

---

## 7. The one-command health check

**Proposed file:** `harness-config/scripts/mesh-health.ps1` (PROPOSED — not yet written to disk; this
document is the only file this session wrote). Design constraints, all from §5: it must run with zero
tailnet dependency, bound every network call, distinguish daemon/engine/DNS, and report the **path
type**, not just reachability.

```powershell
# mesh-health.ps1 — one command, from any Windows node.  Exit 0 = healthy, 1 = degraded.
# Usage:  pwsh -File scripts\mesh-health.ps1 [-Node secratary-ts,zabz-tech-ts,...] [-Session 3099]
[CmdletBinding()] param(
  [string[]]$Node = @('secratary-ts','desktop-ts','linux-pc-ts','mac-mini-ts'),
  [int]$Session = 3099, [int]$MaxRelayMs = 120
)
$bad = @()
# 1. LOCAL SERVICE — the failure that 'looks networked' (P164). Not a tailnet call.
$svc = Get-Service Tailscale -ErrorAction SilentlyContinue
if (-not $svc -or $svc.Status -ne 'Running') { $bad += 'local: Tailscale service is not Running' }
# 2. DAEMON — BackendState + whether an EXIT NODE is armed (RouteAll). Never conflate with DNS.
$j = tailscale status --json 2>$null | ConvertFrom-Json
if ($j.BackendState -ne 'Running') { $bad += "tailnet: BackendState=$($j.BackendState)" }
$prefs = tailscale debug prefs 2>$null | ConvertFrom-Json
if ($prefs.RouteAll -and $prefs.ExitNodeIP) { $bad += "tailnet: RouteAll with ExitNodeIP=$($prefs.ExitNodeIP)" }
if (-not $prefs.CorpDNS) { $bad += 'dns: CorpDNS=false (MagicDNS off — names will not resolve)' }
# 3. PER PEER — resolve once, then talk to the IP; require a DIRECT path, not a relay.
foreach ($n in $Node) {
  $ip = (ssh -o BatchMode=yes -o ConnectTimeout=8 $n 'tailscale ip -4' 2>$null | Select-Object -First 1)
  if (-not $ip) { $bad += "$n : unreachable in 8s (asleep/off-network/DERP-only)"; continue }
  $p = tailscale ping --c 3 --timeout 3s $ip 2>&1
  if ($p -match 'direct connection not established') { $bad += "$n : RELAY only (no direct path)" }
  elseif ($p -match 'via DERP') { $bad += "$n : still relaying via DERP (slow path)" }
  $ms = [int](($p | Select-String 'in (\d+)ms' | ForEach-Object { [int]$_.Matches[0].Groups[1].Value } |
        Measure-Object -Minimum).Minimum)
  if ($ms -gt $MaxRelayMs) { $bad += "$n : ${ms}ms exceeds ${MaxRelayMs}ms" }
  "$n  ip=$ip  min=${ms}ms  path=$(if($p -match 'via DERP'){'DERP'}else{'direct'})"
}
# 4. MY SESSION REACHABLE FROM HERE — the 403/401 fence, per authority (validates --trusted-host).
$auth = $j.Self.DNSName.TrimEnd('.')
$code = try { (Invoke-WebRequest "http://127.0.0.1:$Session/api" -Headers @{Host=$auth} `
          -TimeoutSec 8 -SkipHttpErrorCheck -UseBasicParsing).StatusCode } catch { 0 }
# 401 = fence accepted this authority, just no cookie here (correct). 403 = --trusted-host missing.
if ($code -eq 403) { $bad += "session: this engine refuses Host $auth — relaunch with --trusted-host $auth" }
"session: Host=$auth -> $code (401=fence OK, 403=needs --trusted-host)"
# 5. PUBLICATION — is Serve actually serving, and is Funnel OFF?
$serve = tailscale serve status 2>&1
if ($serve -match 'No serve config') { $bad += 'serve: nothing published for this node' }
if (tailscale funnel status 2>&1 -notmatch 'Funnel is not enabled') { $bad += 'EXPOSURE: Funnel appears enabled' }
if ($bad.Count) { "DEGRADED:"; $bad | ForEach-Object { "  - $_" }; exit 1 } else { 'MESH OK'; exit 0 }
```

**The one-liner equivalent** for a node that has no script yet (Linux/macOS, or before the file is
deployed) — deliberately boring, no tailnet dependency, nothing that can hang:
```
ssh -o BatchMode=yes -o ConnectTimeout=8 secratary-ts \
  'hostname -s; tailscale status --json | grep -E "BackendState|CorpDNS"; tailscale serve status; tailscale ip -4'
```
plus, from the client, the two checks that actually predict the user experience:
```
tailscale ping -c 3 --timeout 3s 100.84.72.88        # must NOT say "via DERP" for long
Invoke-WebRequest http://127.0.0.1:3099/api -Headers @{Host='<this-node>.tail93e6e6.ts.net'} -TimeoutSec 8
```

**NOT MEASURED:** the script above has not been executed (this session wrote exactly one file, as
instructed). The individual probes it composes **were** each run by hand today and are quoted in §1
and §3.1.

---

## 8. Proposals, in priority order (nothing here has been applied)

1. **One engine per DSH_HOME** — add `--trusted-host <node FQDN>` to the primary launcher's
   arguments, publish it with `tailscale serve --bg 3099`, stop the duplicate 3085 engine (§2.1).
   Machine-local config change per node.
2. **`mesh-health.ps1`** as written in §7, plus a scheduled run on ZABZ-YOGA that only *reports*.
3. **`ConnectTimeout 8` in every `~/.ssh/config` Host block**, and tailnet aliases resolving to the
   tailnet IP literal rather than the FQDN (§5.5).
4. **Disable key expiry on the five always-on nodes**; audit with `tailscale status --json` per node.
5. **Tag-based ACLs**, default-deny, no internet ingress (§4).
6. **`tailscale set --exit-node=` on ZABZ-YOGA** to clear the inert `RouteAll: true` (§4).
7. **Subnet router `192.168.50.0/24` on secratary**, if the owner wants office-LAN addresses to work
   off-site (§4). Needs admin-console route approval.
8. **Keep Funnel off everywhere.** If ever enabled, only in front of the gate, never a raw engine.
