# 120 — The office three went off the tailnet; `secratary` was OFF, and I read the wrong machine

**Date:** 2026-10-09 16:2x–17:4x UTC. **From:** ZABZ-YOGA, with ZABZ-TECH as a bridge into the office.

## 0. CORRECTION, added 17:40Z — the first version of this document was WRONG

The owner arrived at the office, found `secratary` **powered off**, and turned it on. Measured immediately
after, over ssh:

```
secratary  up 0 min  |  boot 2026-10-09 17:37:39  |  secretary-api started 17:38:06 UTC
```

**He was right and this document's first version was wrong.** It claimed `secratary` "was never off" and
that Wake-on-LAN "cannot apply". Both statements are false.

**Why I got it wrong, stated precisely, because the method is the lesson.**
`api.lakewoodphoneandtech.com` resolves to **`2.28.33.58` — the Hetzner `lpt-apps-01` box, not
`secratary`** (`Resolve-DnsName`, and `Via: 1.1 Caddy` in the response headers). The `uptime: 33264 →
34106 → 38301` seconds I read and reported as proof that "`secratary` has been up for 9.5 hours" was **the
Hetzner VPS's uptime**. `secratary`'s own API answers a *different* shape on loopback
(`{"ok":true,"time":…,"database":{…}}`, no `uptime` field at all) — a five-second check that would have
caught it, and I did not run it before asserting.

This is pain **P3** exactly — *"reading the wrong data and believing it"* — and it is the same class as the
stale-database crisis that this estate already paid for once. **A number without its provenance is not a
reading.** The rule was re-earned here, not newly learned.

**What it cost:** the owner made a trip to the office. **What it would have cost if he had not gone:** nothing
would have recovered itself, because no watchdog outside the office noticed a node going off the tailnet.

**The instrument that would have prevented it** — and must exist before this can happen again — is a probe
that reports **which host answered**, and a wake system that fires on "the node is not answering **on its
own address**", not on "some service in the estate answers".

## 1. The trigger, and the tool that was right all along

The owner: *"is the secretary still down? why don't you fix that also… if it's off you are supposed to be
able to lan wake it, we set up systems for this."*

**The Wake-on-LAN system was correct and is the right tool.** It is fully built:
`_fleet/co2026/*/scripts/wake-secretary.ps1`, MAC `34:17:eb:9f:f5:e0`, target `192.168.50.77`, BIOS WoL
enabled 2026-09-02, `/etc/systemd/network/10-eno1.link WakeOnLan=magic`. The machine was off; WoL was the
answer; it was never attempted, because of the mis-reading in §0.

**Still to establish (NOT measured):** whether the WoL packet would in fact have been delivered and
honoured — i.e. whether the office router forwards a directed broadcast to `.77`, and whether the NIC keeps
its standby power. That is the test to run from inside the office, and it is the first thing to fix, because
a wake path that has never been fired is not a wake path.

## 2. What is actually wrong

Every office machine is **off the tailnet**, and `secratary`'s own `tailscaled` is not connected:

| node | tailnet | last seen (UTC) |
|---|---|---|
| `lakewooechsmini` | offline | 15:29:39 |
| `zabz-tech-linux` | offline | 15:36:32 |
| `secratary` | offline | 15:37:04 |
| `zabz-tech` (desktop) | **online** | — |
| `zabz-yoga-1` (laptop) | **online** | — |

Three machines went dark inside eight minutes, and `secratary` was **off** — which means **its Tailscale
being down was a symptom, not the fault.** The office box had stopped; the tailnet simply recorded it.

## 3. The office LAN is not a way in either

Measured from **inside** the office (the desktop, over its own LAN), so this is not a home-network or
Tailscale-routing artefact:

```
from zabz-tech:  secratary 192.168.50.77   icmp no reply   tcp 22/80/443/3091/8002/3089 ALL timeout
                 linux-pc  192.168.50.23   icmp no reply
                 mac-mini  192.168.50.45   icmp no reply
                 router    192.168.50.1    icmp REPLY, tcp 53 OPEN
full /24 ARP sweep from the desktop -> 11 neighbours, and .77 / .23 / .45 are NOT among them
tailscale ping secratary / zabz-tech-linux / lakewooechsmini  -> "no reply" from inside the office
```

So the three are not merely unreachable from home; **the desktop cannot reach them over the office LAN
either**, while the router itself answers. The desktop's L2 neighbours are `.1 .24 .34 .42 .84 .89 .103
.138 .170 .204 .231 .243 .247`.

**Not established, and not guessed at:** whether the three are powered, whether their NICs are up,
whether a switch port or VLAN changed, or whether the desktop's own recent history is implicated.

## 4. The correlation, and what it actually suggests

The desktop booted at **11:37:12 local = 15:37:12 UTC**; `secratary`'s last tailnet sighting is
**15:37:04 UTC** — eight seconds earlier. `linux-pc` went at 15:36:32 and `mac-mini` at 15:29:39. Three
machines leaving the tailnet and a fourth rebooting inside eight minutes is not coincidence, and the
simplest reading is a **single site event around 15:29–15:37Z** — a power interruption on the circuit
these machines share, or a switch.

**`secratary` was then off for roughly two hours** (15:37Z → 17:37Z) until the owner powered it on. So the
event took the machines down and **only the one a human attended came back** — which is the whole argument
for the migration in `121-always-on-server.md`.

**And the desktop's own state is a separate, independent fault of its own:** its only DNS resolver was
broken all morning (`119` §4, the filter), and it runs `Ethernet`, `Wi-Fi` and `Tailscale` all up with
**two default routes** (`default via 192.168.50.1 if=Wi-Fi` metric 45 and `… if=Ethernet` metric 25). That
is a second thing to fix on that machine and nobody has measured which one it uses.

## 5. What was built in response

- `_scratch/mesh-audit/watch-nodes.mjs` — a witness. Polls this machine's own `tailscale status` and
  the API over the tunnel, and logs the moment any node returns **with the state it returned in**.
  Started 2026-10-09 16:1xZ for 180 minutes, logging to `_scratch/mesh-audit/watch-nodes.log`.
  This exists because the failure was discovered by the owner noticing, not by the estate.

## 6. What cannot be done from here, said plainly

Nothing outside the office can re-attach a node whose own `tailscaled` is down. There is no in-band
path left: ssh is gone with the tailnet, the office LAN does not reach them, and the Cloudflare
`secretary-ssh` tunnel needs an interactive `cloudflared access` login
(`A browser window should have opened at https://secretary-ssh.abletelsolutions.com/cdn-cgi/access/cli?aud=43af6675…`).
`desktop-ssh` differs usefully: it has a **cached session token** in `~/.cloudflared/`
(`desktop-ssh…-token`, 1042 bytes) while `secretary-ssh` has only a `.url` and a `.lock` — which is why
the same tunnel that can reach the desktop cannot be used for `secratary` without one browser login.

## 7. The durable fixes this demands

1. **A second way into the authority that does not depend on the tailnet.** A cached Cloudflare access
   token for `secretary-ssh` on every control machine, or an ssh listener on the office LAN reachable
   from a machine that is always up. One node being off the tailnet must not remove the only door.
2. **A watchdog outside the office** that notices a node leaving the tailnet and says so within a
   minute (see §5) rather than a human noticing hours later.
3. **`secratary` must not be the only control plane.** Already built in docs/mesh/119 §2: the broker is
   now an optimisation and a dispatcher can place from its own measurement. That keeps fan-out alive
   through this exact outage; it does not restore ssh.
