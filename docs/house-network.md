# The house network — measured topology, what the router stack costs, and how to measure it

Updated: 2026-10-15 (ZABZ-YOGA, session 784c436d)

This is the one place that says what the owner's home internet actually is. Everything in it was
read off a machine, not inferred from a manual or a vendor page. Every number carries the time it
was taken.

Owner's question that produced it, 2026-10-15: *"the Verizon router after the T-Mobile one causes
problems and makes the Internet slow. Right now, the Internet slows. I want to know if it's related
to that."*

**Short answer: no.** Measured on 2026-10-15, the stack adds about 1 ms and zero loss; the slow
episodes are the cellular uplink's own single-flow throughput swinging 3x within minutes. The stack
does cause four separate *defects* — no IPv6, an unset WAN MTU, double NAT, and a still-on second
5 GHz radio fighting on channel 157 — but none of them is the thing that makes the internet feel
slow today. Details below.

---

## 1. Topology, read off the wire

```
laptop / iPhone
      |
  Verizon_ZYFY4N          Verizon CHR30A "Wi-Fi Access Point", 192.168.1.1
  (192.168.1.0/24)        Wi-Fi 7, tri-band, 6 GHz ch 37, 5 GHz ch 157, 2.4 GHz ch 1
      |
  192.168.12.1            T-Mobile 5G Gateway, Arcadyan TMO-G4AR, LAN 192.168.12.0/24
      |
  192.0.0.1               T-Mobile carrier NAT (CGNAT)
      |
  10.177.x.x -> internet  T-Mobile 5G core
```

`tracert 1.1.1.1` from ZABZ-YOGA, 2026-10-15 14:13 UTC: hop 1 `192.168.1.1`, hop 2
`192.168.12.1`, hop 3 `192.0.0.1`, then T-Mobile's `10.177.60.x`/`10.177.61.x` core.

**The tell, for a future session:** if hop 2 is `192.168.12.1`, the T-Mobile gateway is upstream and
the Verizon is a *second router* behind it. That is the current state and it is deliberate — the
Verizon is the house's Wi-Fi, the T-Mobile is the modem.

Measured on this machine (ZABZ-YOGA) at 2026-10-15 14:10 UTC: Wi-Fi `192.168.1.5` and Ethernet
`192.168.1.3`, both gateway `192.168.1.1`. Both of the laptop's legs terminate on the Verizon, not
the T-Mobile.

---

## 2. The T-Mobile gateway reports its own radio, unauthenticated

**This is the single most useful instrument in this document and almost nobody knows it exists.**
The gateway's web app is a React bundle; the read-only API behind it answers without any token:

```
curl http://192.168.12.1/TMI/v1/gateway?get=signal    # radio
curl http://192.168.12.1/TMI/v1/gateway?get=all       # radio + device + uptime
curl http://192.168.12.1/TMI/v1/version
```

Writes (`/TMI/v1/network/configuration?set=ap`) require a bearer token and return
`{"error":"AuthorizationError"}` without one.

Read 2026-10-15 14:18 UTC:

| Field | Value | Read |
|---|---|---|
| model / fw | TMO-G4AR (Arcadyan), 1.00.18, serial JT74032C0 | healthy |
| band | n41 (mid-band, the fast one) | healthy |
| bars | 4.0 / 5 | healthy |
| RSRP | -89 dBm | fair (good is -80 or better, usable to -100) |
| RSRQ | -10 dB | fair |
| RSSI | -78 dBm | fair |
| SINR | 28 dB | **excellent** (anything over 20 is clean) |
| antenna | Internal_omni | — |
| registration | registered, roaming false, APN FBB.HOME | healthy |
| hasIPv6 | **true** | see §4 |
| uptime | 389,506 s = 4.5 days | no reboot loop |

Signals of 4 bars with SINR 28 on n41 is a *good* cellular link. Nothing about the radio explains
slow internet, and nothing about it changes when the Verizon is or is not in the path.

---

## 3. What the internet measured, 2026-10-15 morning

All times UTC. Instruments: `ping`, `curl`, `netsh wlan`; full logs in the evidence section.

| Measurement | 2026-10-15 14:10-14:23 | 2026-10-14 20:50-22:50 (last night) |
|---|---|---|
| Packet loss, 8.8.8.8 | **0%** (30, 60, then 8x24 pings) | 0% (110 pings) |
| Packet loss, gateway and T-Mobile hop | 0% | 0% |
| Latency 8.8.8.8 | min 13 / avg 27-37 / max 216 ms | min 19 / avg 31 / max 71 ms |
| Latency 1.1.1.1 | min 14 / avg 28 / max 86 ms | — |
| Latency across the T-Mobile hop (192.168.12.1) | 0-1 ms | 1-2 ms |
| DNS, warm | 1-27 ms | 4-52 ms |
| DNS, first lookup after 11 h idle | 694 ms, then 2 ms | — |
| Single-flow download, Wi-Fi leg | **179 Mbps** (22.4 MB/s) | 219 Mbps |
| Single-flow download, Ethernet leg | **88 Mbps** (11.0 MB/s) | 160 Mbps |
| Four parallel flows, aggregate | **269 Mbps** | 237 Mbps |
| YouTube page fetch, 5x | 0.40-0.53 s, connect 0.04-0.07 s | 0.45-0.71 s, connect 0.05-0.06 s |
| TCP connect + TLS to google/YouTube/Facebook/Cloudflare | connect 0.08-0.15 s, TLS 0.26-0.41 s | — |
| Wi-Fi link | 6 GHz ch 37, RSSI -24 dBm, 2402 Mbps PHY, WPA3-H2E | same (RSSI -17) |
| Path MTU | **1436** (payload 1408 passes, 1410 fails) | 1436 |

### The finding that matters — single-flow throughput is wildly variable, aggregate is not

24 rounds, one every ~13 s, 2026-10-15 14:17:45-14:23:00 UTC, 20 MB each:

```
round  Mbps    round  Mbps    round  Mbps    round  Mbps
   1   80.5      7  112.1      13  100.4      19  102.8
   2  121.7      8   72.2      14  112.7      20   53.4
   3   44.3      9  106.1      15  101.2      21   50.6
   4  107.6     10   83.6      16   59.0      22   69.8
   5   45.7     11  112.3      17   73.9      23   79.7
   6   84.7     12   56.8      18   93.5      24   61.4
```

min 44.3, max 121.7, mean ~84 Mbps. **Zero packet loss in every round.** Latency in the same rounds
stayed at avg 18-56 ms, with occasional spikes to 283 ms.

That is the whole answer to "the internet is slow right now". A speed test takes one sample from
this distribution, so it reads "very good" or "slow" depending on which second it landed in. The
aggregate path is *better* than last night (269 vs 237 Mbps) and there is no loss — this is a shared
cellular uplink's scheduling, not a broken link and not the router stack.

---

## 4. What the second router actually costs — four defects, all measured

### 4.1 IPv6 is dead on the LAN, and the gateway says it should not be

The T-Mobile gateway reports `hasIPv6: true`. On the LAN, no interface has a global IPv6 address
and there is no IPv6 default route at all — `ping -6 2001:4860:4860::8888` returns
`transmit failed. General failure` (2026-10-15 14:14 UTC; identical on 2026-10-14).

The only thing between the gateway and the LAN is the Verizon. Every device behind it is IPv4-only
while DNS still hands out AAAA records — `www.youtube.com` resolves to eight IPv6 addresses before
any IPv4 ones. Apps that prefer IPv6 either take the fallback path or stall on it.

**Honest weight:** with *no* IPv6 route at all, a modern OS fails the v6 connect instantly rather
than waiting, so this is a configuration regression more than a proven stall. It is still wrong and
it is on the list. It was not different last night, so it does not explain today.

### 4.2 The path MTU is 1436 and the router still believes it is 1500

`ping -f -l N 8.8.8.8` bisected twice, 2026-10-14 and again 2026-10-15: payload 1408 passes,
1412 fails. Largest passing packet 1436. Both laptop adapters are configured 1500.

The failure is *not* silent — `192.0.0.1` returns ICMP type 3 code 4 ("needs fragmenting but DF
set"), so PMTUD works and TCP eventually adapts. The cost is at the start of a new connection, when
the first full-size segments are dropped until the path size is learned.

**Honest weight:** I tried to prove this with an A/B — same fresh-connection probes with the
interface at 1500 and then at 1436 — and **could not run it**: changing an interface MTU needs
elevation and this shell is not elevated. Both phases therefore ran at 1500 and the difference
between them (TLS +26 ms, TTFB +35 ms, total +172 ms) is noise between two identical conditions,
not a result. Handshake times measured normally (connect 0.08-0.15 s, TLS 0.26-0.41 s), which does
not support a stall. Treat the MTU gap as a latent defect with a cheap fix, not as a proven cause.

### 4.3 Double NAT

Two routers in a row. Outbound works; inbound does not, and it was already impossible one layer up
because T-Mobile Home Internet sits behind carrier-grade NAT. The practical costs in the house are
local: discovery broadcast (mDNS/SSDP/NetBIOS) does not cross the second router, so printers, NAS
shares and casting targets behind the Verizon are invisible to anything wired to the T-Mobile.

### 4.4 The T-Mobile gateway's own Wi-Fi is still on, on the same 5 GHz channel

Scanned 2026-10-15 14:11 UTC: `TMOBILE-32C0` at 94% signal, 802.11ax, **5 GHz channel 157** — the
same channel the Verizon is using for 5 GHz. On 2026-10-14 it had 4 connected stations at 5%
channel utilisation. Also visible: `ORBI5203` (802.11ac, 5 GHz ch 48 and 2.4 ch 8, 57-60%), an
unrelated `MyOptimum bed683` (802.11ax, 5 GHz ch 36, 2.4 ch 11), and a printer's direct SSID.

Two APs from the same house transmitting on one channel is direct airtime contention for every
5 GHz client — and the owner was told on 2026-10-14 to turn the T-Mobile radios off once the Verizon
was serving clients. That has not been done. **The 6 GHz band the laptop uses (ch 37, RSSI -24 dBm)
is clean**, which is why the Yoga measures well while an iPhone sitting on 5 GHz ch 157 would not.

---

## 5. What is *not* the cause, stated plainly

- **Not bandwidth.** 269 Mbps aggregate, more than last night.
- **Not loss.** 0% across every one of the ~250 pings taken today and 110 last night.
- **Not DNS.** Warm lookups 1-27 ms; the 694 ms and 1692 ms outliers are the first lookup after
  hours of idleness, and the second lookup to the same name is 2 ms.
- **Not Wi-Fi signal at the laptop.** 6 GHz, RSSI -24 dBm, 2402 Mbps PHY, WPA3-H2E.
- **Not the second router's latency.** Crossing into the T-Mobile hop costs 0-1 ms.
- **Not the cellular radio.** n41, SINR 28 dB, 4 bars, registered, no roaming.

The variable is the cellular uplink's per-flow rate. T-Mobile Home Internet is the lowest-priority
traffic class on the tower; this is what that looks like.

---

## 6. Open actions, ranked by value per minute

1. **Turn the T-Mobile gateway's Wi-Fi off.** Two radios, one channel. Needs the T-Mobile admin
   password (the written settings API is token-gated). Cheapest real improvement for any 5 GHz
   client — which is likely the iPhone.
2. **Find out which band the iPhone is on.** If it is on 5 GHz ch 157 it is sharing airtime with
   the T-Mobile AP; if it is on 2.4 GHz ch 1 it is sharing with the Verizon's own IoT SSID. The
   Verizon Home app's client list shows band and rate per device. This is a 30-second read and it
   decides everything else.
3. **Set the Verizon's WAN MTU to 1436** (web UI at `192.168.1.1`, Network connections, General,
   MTU, Manual). The app cannot do it; the app has no LAN-side controls at all.
4. **Consider removing the second router.** The CHR30A's extender mode pairs only with another
   CHR30A, so there is no true bridge to the T-Mobile. The working move if discovery and IPv6
   matter more than the better radio: wire the T-Mobile to a Verizon **LAN** port, turn the
   Verizon's DHCP off and give it a free address inside 192.168.12.0/24 — one flat network, IPv6
   passes, and the Wi-Fi 7 radios still serve the house.
5. **Do not chase the MTU as a fix for the slowdown.** It is a real defect; it is not the cause.

---

## 7. Evidence

Raw logs, all on ZABZ-YOGA:

| File | What |
|---|---|
| `~/net-diag.txt` .. `net-diag7.txt` | 2026-10-14 20:49-22:50, last night's rounds 1-4 + QUIC attempts |
| `~/code/out/net-measure-<session>.txt` | 2026-10-15 14:10, the first full sweep |
| `~/code/out/net-round2.txt` | 2026-10-15 14:14, apples-to-apples vs last night |
| `~/code/out/net-burst.txt` | 2026-10-15 14:17, the 24-round variance series |
| `~/code/out/net-mtu-ab.txt` | 2026-10-15 14:23, the MTU A/B that could not run |
| `harness-config/scripts/net/house-net-measure.ps1` | re-runnable sweep, from any Windows node |
| `harness-config/scripts/net/house-net-burst.ps1` | re-runnable variance series |

The owner's own session that produced the question: DSH session
`39c17540-25c6-48d1-8e6e-cacfed1690cd`, host `secratary-cloud`, project `--home-zabz-phone--`,
titled "Verizon vs T-Mobile router comparison", 2026-10-14 19:33Z to 2026-10-15 02:52Z,
486 events, 291 zstd frames, 0 failed frames. Its own conclusion is in §3 of the record; its
lesson is journal entry L4512.
