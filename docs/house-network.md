# The house network — measured topology, what actually slows it, and how to measure it

Updated: 2026-10-15 (ZABZ-YOGA, session 784c436d). Supersedes the 2026-10-15 morning draft: the
router itself was read later the same morning and changed two of the conclusions, and the owner
corrected a third in person at the end of the day.

**CORRECTION, 2026-10-15 evening, from the owner, verbatim: "You know the office is on [Fios] but
the house is on [T-]mobile."** An earlier version of this document said a Fios service was installed
at this address and was not feeding the router, and drew a "you are paying for fiber you are not
using" conclusion from it. That is wrong. The Fios install (order `NJ12338123101`, 2026-09-14, about
30 a month, ONT serial `ALCLECEF1FB204`) is at the **office**, 1001 W Kennedy Blvd — which is what the
order's service address said all along, and H206 flagged the ambiguity at the time. **This house has
one uplink: the T-Mobile cellular gateway.** The measured topology below is unaffected and was
confirmed from the router itself; only the inference about the fiber was wrong.

Owner's question, 2026-10-15: *"the Verizon router after the T-Mobile one causes problems and makes
the Internet slow. Right now, the Internet slows. I want to know if it's related to that."*

**Short answer: no.** The router stack adds about 1 ms and zero loss. What can actually be slow is
(1) a client that has landed on the **2.4 GHz radio** — measured at 11–26 Mbps PHY against 2268 Mbps
on 6 GHz from the same router at the same moment — and (2) the **cellular uplink's own per-flow rate,
which swings 44–122 Mbps minute to minute** and which no router setting can fix.

---

## 1. Topology, read off the machines

```
phone / laptop
      |
  Verizon_ZYFY4N          Verizon CHR30A-R (WNC), 192.168.1.1   <- the house's Wi-Fi
  (192.168.1.0/24)        WAN 192.168.12.245, gateway 192.168.12.1
      |
  192.168.12.1            T-Mobile 5G Gateway, Arcadyan TMO-G4AR  <- the actual uplink
      |
  192.0.0.1               T-Mobile carrier NAT (CGNAT)
      |
  10.177.60-61.x          T-Mobile 5G core -> internet
```

Read from the CHR30A's own API 2026-10-15 14:37 UTC (`getRouterDetails`):
`ipv4AddressWan 192.168.12.245`, `gatewayIPAddress 192.168.12.1`, `broadbandPhysicalConnection
Ethernet`, `ipv4AddressingType DHCP`. `tracert 1.1.1.1` from ZABZ-YOGA agrees: hop 1 `192.168.1.1`,
hop 2 `192.168.12.1`, hop 3 `192.0.0.1`.

**The tell for a future session:** hop 2 `192.168.12.1` means the T-Mobile gateway is upstream and the
Verizon is a second router behind it. `192.168.12.1` answering `<title>T-Mobile Gateway</title>` is the
proof that address is not a Verizon box.

**This house's only uplink is the T-Mobile line.** There is no fiber here: the Verizon Fios install
of 2026-09-14 is at the office, 1001 W Kennedy Blvd (see the correction at the top). The CHR30A and
its ONT photographs belong to that install; the same model of router is doing duty at the house
behind the cellular gateway. Do not reason about this house from the office's service record.

---

## 2. What actually slows the internet here

### 2.1 The phones are on 2.4 GHz, and that is the whole number

`getDeviceDetails` from the router, 2026-10-15 14:38 UTC — every client, with the band the router
says it is on:

| device | band | width | PHY rate | RSSI | last active (local) |
|---|---|---|---|---|---|
| a phone, randomised MAC `62:3E:76:55:36:D6` | **2.4 GHz** | 20 MHz | **11.0 Mbps** | -69 | **10-15 10:34** |
| `iPhone` | **2.4 GHz** | 20 MHz | **25.8 Mbps** | -67 | 10-14 21:33 |
| phone `96:C7:B4:6F:E3:E1` | 5 GHz | 80 MHz | 6.0 Mbps | -63 | 10-14 22:53 |
| `zabz-yoga` (Wi-Fi) | 6 GHz | 160 MHz | **2268.5 Mbps** | -40 | 10-15 10:04 |
| `zabz-yoga` (Ethernet) | wired | — | 2500 Mbps | — | 10-14 22:28 |
| three others | mostly 5 GHz | — | 6–234 Mbps | — | offline since 10-14 19:01 |

The device active minutes before this was read — a phone, which is what the owner was asking about —
is on **2.4 GHz at an 11 Mbps PHY rate**. The laptop, in the same house, is on 6 GHz at 2268 Mbps.
That is a factor of 200 between two devices on one network, and it is a radio-band problem, not an
uplink problem: a phone doing 11 Mbps of PHY is slower than the cellular uplink's worst minute.

Radio settings the same moment (`getRadioSettings`): 2.4 GHz on **channel 1**, 20/40 MHz, auto;
5 GHz on **channel 157**, 80 MHz; 6 GHz on **channel 37**, 160 MHz. All three radios on, and the same
SSID on all three.

**Why 2.4 GHz and not 6 GHz:** 6 GHz has roughly 10 dB more path loss than 2.4 GHz. A phone reading
-67/-69 dBm on 2.4 GHz would read about -78/-80 on 6 GHz and -73/-75 on 5 GHz, so the client picks
2.4 GHz on its own. The fix is not a router toggle so much as distance: get the phone, or the access
point, closer. Second choice is to stop the main SSID from offering 2.4 GHz at all and leave
`Verizon_ZYFY4N-IoT` (2.4 GHz, same key) for the legacy gear — but that can drop a phone that is
genuinely out of 5 GHz range, so it is a change to make with the phone in hand.

**Second reading, same day 2026-10-16 01:06 UTC (21:06 local) — both phones are on 5 GHz.** The same
`getDeviceDetails` call now shows `iPhone` at 5 GHz, RSSI -52 dBm, SNR 40, max rate 1201 Mbps, and
`62:3E:76:55:36:D6` at 5 GHz, 80 MHz, RSSI -67, SNR 25, max rate 2401.9 Mbps. So 2.4 GHz is not a
fixed state, it is what those clients land on at some places and times and not others. **Treat a
single `getDeviceDetails` reading as a moment, not a condition** — and note that `phyRate`,
`currentRxModulationRate` and `currentTxModulationRate` fall to the 6 Mbps basic rate when a client is
idle, so they are not the field to compare clients by. `maximumRxModulationRate` / `snr` / `rssi` are.

**There is no iPod-style band picker on iOS.** Apple's own page (`support.apple.com/en-us/102285`)
documents exactly one setting, *Wi-Fi 6E mode*, reached at Settings > Wi-Fi > (i) on the connected
network, and it is an **off switch** for 6 GHz that appears only once the phone is already connected to
a Wi-Fi 6E or 7 network. Nothing in iOS forces a device onto a band; the client and the AP's band
steering decide. The only reliable client-side action is to forget the network and rejoin while
standing next to the router.

### 2.2 The uplink is cellular, and its rate swings threefold

24 rounds, 13 s apart, 2026-10-15 14:17:45–14:23:00 UTC, 20 MB each:

```
round  Mbps    round  Mbps    round  Mbps    round  Mbps
   1   80.5      7  112.1      13  100.4      19  102.8
   2  121.7      8   72.2      14  112.7      20   53.4
   3   44.3      9  106.1      15  101.2      21   50.6
   4  107.6     10   83.6      16   59.0      22   69.8
   5   45.7     11  112.3      17   73.9      23   79.7
   6   84.7     12   56.8      18   93.5      24   61.4
```

min 44.3, max 121.7, mean ~84 Mbps, **zero packet loss in every round**, latency in the same rounds
18–56 ms with occasional 283 ms spikes. Aggregate across four parallel flows: 269 Mbps. Same battery
on 2026-10-14: single flow 160 wired / 219 Wi-Fi, four flows 237 aggregate.

The gateway's own radio, read the same morning over its unauthenticated API: n41, 4 bars,
RSRP -89 dBm, RSRQ -10, RSSI -78, **SINR 28 dB**, registered, no roaming, up 4.5 days. A clean link.

So a speed test samples a distribution that swings 3x and reports whatever second it landed in. This
is T-Mobile Home Internet, the lowest-priority class on a shared tower, and it is this house's only
uplink — there is no fiber at this address to fall back to. A different uplink is the only thing that
removes it.

### 2.3 What the second router costs — four defects, none of them today's slowdown

1. **The LAN has no IPv6, because no prefix is delegated.** The CHR30A's WAN IPv6 is *up*:
   `broadbandIpv6Status Up`, WAN address `2607:fb90:2e04:4d42::1`, DHCPv6-PD, DNS `fe80::fa3e:b0ff:fe40:32c0`.
   But `delegatedPrefix` is empty, `wanIpv6AddressPrefix` is empty, `lanPrefix` is empty and
   `lanHostIpv6Address` is empty. Nothing to hand to the LAN, so every client is IPv4-only while DNS
   still returns AAAA. T-Mobile's CGNAT gives a prefix to its own gateway and does not delegate one to
   a router behind it.
2. **WAN MTU is 1500 against a 1436 path.** `getNetworkConnections` shows `"alias":"broadband",
   "mtu":1500,"mtuType":1`. `ping -f -l N 8.8.8.8` bisected twice (2026-10-14 and 2026-10-15):
   payload 1408 passes, 1410 fails, so the largest passing packet is 1436. Not silent — `192.0.0.1`
   returns ICMP type 3 code 4, so PMTUD works and endpoints recover.
   The A/B that would have proven a stall **could not be run**: `netsh interface ipv4 set subinterface`
   needs elevation, this shell is not elevated (Administrators is deny-only), so both arms ran at 1500
   and their 26–172 ms difference is noise between two identical conditions — a null, not a negative.
   Measured handshakes are normal (connect 0.08–0.15 s, TLS 0.26–0.41 s), which does not support a stall.
3. **Double NAT.** No inbound (already impossible one layer up under CGNAT), and mDNS/SSDP/NetBIOS do
   not cross the second router, so a printer or casting target behind one router is invisible to
   anything wired to the other.
4. **The T-Mobile gateway's own Wi-Fi is still on, on the Verizon's 5 GHz channel.** Scanned
   2026-10-15 14:11 UTC: `TMOBILE-32C0` at 94%, 802.11ax, **5 GHz channel 157** — the same channel the
   CHR30A uses for 5 GHz. It had 4 connected stations on 2026-10-14. The advice to switch it off was
   given on 2026-10-14 and has not been done.

---

## 3. What is *not* the cause, stated plainly

- **Not bandwidth.** 269 Mbps aggregate, better than last night.
- **Not loss.** 0% in every one of ~250 pings today and 110 last night.
- **Not DNS.** Warm lookups 1–27 ms. The 694 ms and 1692 ms outliers are the first lookup after hours
  idle, and the next lookup to the same name is 2 ms.
- **Not the second router's latency.** Crossing into the T-Mobile hop costs 0–1 ms.
- **Not the cellular radio's signal.** n41, SINR 28 dB, 4 bars.
- **Not Wi-Fi at the laptop.** 6 GHz, RSSI -40 dBm, 2268 Mbps, WPA3-H2E.

---

## 4. Two credentials that are already in the record, and both routers answer JSON

Both boxes serve their own web app as a React bundle, and both expose the API behind it.

**Verizon CHR30A-R** — admin at `https://192.168.1.1`, admin password `6CVBTT3B3` (recorded in
`personal-secretary-mvp/docs/network/verizon-fios-home-2026-09-14/`; the same value is on the rear
label). Login is two calls:

```bash
# 1. get an auth cookie
curl -sk -c jar -X POST -H "Content-Type: application/json" \
  -H "Authorization: Basic <base64('admin:PASSWORD')>" \
  --data-binary '{"keepMeSignIn":false}' https://192.168.1.1/CRSP/open/login
# 2. get the CSRF token, then send it as a header on every read
curl -sk -b jar -c jar -X POST -H "Content-Length: 0" https://192.168.1.1/CreateXSRFToken
curl -sk -b jar -X POST -H "x-xsrf-token: <token>" -H "Content-Type: application/json" \
  --data-binary '{}' https://192.168.1.1/CRSP/getDeviceDetails
```

Open (no auth): `/CRSP/open/getModelName`, `getLoginMetadata`, `getLoginToken`. Everything else needs
the token. 163 endpoints; the useful reads are `getRouterDetails` (WAN addresses, uptime, firmware),
`getNetworkConnections` (per-interface MTU and counters), `getDeviceDetails` (every client with band,
width, PHY rate, RSSI, SNR), `getRadioSettings`, `getIpv6Configuration`, `getARPTable`. All are POST
with a JSON body — a GET returns 405.

**T-Mobile TMO-G4AR gateway** — reads are open, no login:

```bash
curl http://192.168.12.1/TMI/v1/gateway?get=signal
curl http://192.168.12.1/TMI/v1/gateway?get=all
```

Returns band, bars, RSRP/RSRQ/RSSI/SINR, APN, registration, `hasIPv6`, firmware, uptime. Writes are
token-gated and were not attempted.

Re-runnable instruments: `harness-config/scripts/net/house-net-measure.ps1` (full sweep) and
`house-net-burst.ps1` (variance series).

---

## 5. Open actions, ranked by value per minute

1. **There is nothing to unplug and nothing to cancel — the cellular line is this house's only
   internet.** The fiber is the office's. Changing the uplink means buying a service at this address,
   which is the owner's decision and not a defect to fix.
2. **Get the phones off 2.4 GHz when they land there.** Confirm the band with `getDeviceDetails`,
   then either move the phone closer to the router, or turn the 2.4 GHz radio off for the main SSID
   and leave `Verizon_ZYFY4N-IoT` for the 2.4-only gear. This is the fix for the owner's own
   experience and costs nothing.
3. **Turn the T-Mobile gateway's Wi-Fi off** once the uplink question is settled — two APs on 5 GHz
   channel 157 in one house.
4. **Set the CHR30A's WAN MTU to 1436** if the T-Mobile stays in the path. Latent defect, cheap fix,
   not proven to matter.
5. Do not chase the MTU, and do not blame the stack, for the phone's speed.

---

## 6. Evidence

| File | What |
|---|---|
| `~/net-diag.txt` .. `net-diag7.txt` (ZABZ-YOGA) | 2026-10-14 20:49–22:50, last night's rounds 1–4 + QUIC attempts |
| `~/code/out/net-measure-<session>.txt` | 2026-10-15 14:10, first full sweep |
| `~/code/out/net-round2.txt` | 2026-10-15 14:14, apples-to-apples vs last night |
| `~/code/out/net-burst.txt` | 2026-10-15 14:17, the 24-round variance series |
| `~/code/out/net-mtu-ab.txt` | 2026-10-15 14:23, the MTU A/B that could not run |
| `~/code/out/vz-conn.json` | 2026-10-15 14:38, the CHR30A's raw network-connection dump |

The owner's session that produced the question: DSH session
`39c17540-25c6-48d1-8e6e-cacfed1690cd`, host `secratary-cloud`, project `--home-zabz-phone--`,
"Verizon vs T-Mobile router comparison", 2026-10-14 19:33Z to 2026-10-15 02:52Z, 486 events,
291 zstd frames, 0 failed. Its lesson is journal entry L4512.
