# Remote access ZABZ-YOGA ↔ ZABZ-TECH, hardened end to end

**Date:** 2026-10-05 (machine-local clocks) · **Author:** Zabz on ZABZ-YOGA
**Owner's report that started this:** *"it's working better now but the connection was lost a few times"*, then
*"research online and get to work on making this connection and system way better and more robust fully end to
end"*, plus *"also make it 2 way so i can use the yoga from the desktop and the desktop from the yoga"*.
**Related:** `docs/talk-to-text-across-remote-desktop.md` (how the connection was set up and why RDP was
chosen), journal handoff **H3186/H3187**, lesson **L3270**.

---

## 1. Why it dropped — measured, not guessed

Two independent causes, both visible in the host's own logs.

**(a) The network path changed under a long-lived TCP session.** The owner's Yoga is on **T-Mobile home
internet (carrier-grade NAT)**: Ethernet 192.168.12.104 → gateway 192.168.12.1, public address
**172.59.215.103**, and Tailscale's own port-mapping probe reports `PortMapping:` **empty** — i.e. the Yoga can
never be reached inbound. Earlier the same link was `direct 71.104.140.242:41642` at 29 ms; by 02:00 both
directions reported `via DERP(nyc)` and `direct connection not established`. When the carrier IP re-maps, the
RDP TCP connection dies outright:

```
LocalSessionManager event 40: Session 1 has been disconnected, reason code 2147942464
  = 0x80070040 ERROR_NETNAME_DELETED  "the specified network name is no longer available"
RdpCoreTS: SetErrorInfo(0x80070079)   = ERROR_SEM_TIMEOUT, the transport stalled
```

**(b) Two doors competing for one session.** A client Windows (Windows 11 Home *and* Pro) allows exactly one
interactive session. Chrome Remote Desktop, AnyDesk, TeamViewer and the physical console all attach to that
same session, so connecting with one kicks the other:

```
reason code 5  = "Another user connected to the server, forcing the disconnection of the current connection"
reason code 12 = "The user logged off his or her session"
reason code 11 = user disconnected their own session
```

The event cluster at 01:40–01:55 contains several `reason code 5` and `Event 41 Begin session arbitration`
entries — that is CRD/console and RDP stepping on each other, not a fault in either protocol.

**What is *not* a cause, checked rather than assumed:** the RDP listener, the RDP services, the firewall rule,
and the disk/CPU of either machine. `Test-NetConnection 3389` succeeded on every one of the nine probe ticks,
and `EnableAutoReconnect`/autoreconnect did recover the session twice (`Event 25 Session reconnection
succeeded`) rather than failing.

## 2. What the link actually is (measurements, 2026-10-05 01:55–02:05)

| Fact | Value | How it was measured |
|---|---|---|
| Yoga local | Ethernet 192.168.12.104, gw 192.168.12.1, Wi-Fi **disconnected** | `Get-NetIPConfiguration`, `netsh wlan show interfaces` |
| Yoga public | 172.59.215.103:24807, **no** port mapping | `tailscale netcheck` |
| Office public | 71.104.140.242:57865, port mapping **UPnP, NAT-PMP, PCP** | `tailscale netcheck` on ZABZ-TECH |
| Current path | **RELAY** via DERP `nyc`, 24–48 ms, 9/9 samples | `tailscale ping`, `link-keepwarm.log` |
| Earlier path | `direct` 29 ms (when the Yoga was on home Wi-Fi) | `tailscale ping` at 22:55 |
| RDP reachability | TCP 3389 reachable on 9/9 ticks | probe every 30 s |
| Sessions on host | `console` connected + `ezabz` session 3 **disconnected but retained** | `qwinsta` |

## 3. What was changed

### ZABZ-TECH (the RDP host) — all reversible, nothing deleted

| Setting | Value | Why | Kicker |
|---|---|---|---|
| Sleep / hibernate / disk timeout (AC) | 0 (never) | a sleeping host is an outage | `powercfg /query SCHEME_CURRENT SUB_SLEEP` |
| `HiberbootEnabled` | 0 | Fast Startup keeps a stale kernel state across "shutdown" | `Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power'` |
| `PnPCapabilities` per NIC | 24 | stops the NIC being powered down under the session | registry under `...\Control\Class\{4d36e972-...}` |
| `KeepAliveEnable` / `KeepAliveInterval` | 1 / 1 minute | keeps the TCP flow (and NAT mappings) alive when idle | `Get-ItemProperty 'HKLM:\SYSTEM\...\Terminal Server\WinStations\RDP-Tcp'` |
| `MaxDisconnectionTime`, `MaxIdleTime` | 0 / 0 | a dropped session is **retained**, so the agent processes on the host survive and RDP can reconnect into it | same key |
| `NoAutoRebootWithLoggedOnUsers` + `AUOptions` | 1 + 4 | Windows Update must not reboot the machine under a live or disconnected session | `HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU` |
| Watchdog **`Zabz RDP health`** | every 2 min, SYSTEM | see §4 | `Get-ScheduledTask 'Zabz RDP health'` |

### ZABZ-YOGA (the client)

| Setting | Value | Why |
|---|---|---|
| Watchdog **`Zabz link keepwarm`** | every 1 min | `tailscale ping` to ZABZ-TECH keeps the NAT mappings and the path-discovery warm, and logs every path change to `~\.dsh\logs\link-keepwarm.log` |
| `.rdp` | `autoreconnection enabled:i:1`, full screen, dynamic resolution | reconnects into the retained session after a path change |

## 4. The watchdog, and how to read the trail afterwards

`C:\Users\ezabz\.dsh\tools\rdp-health.ps1` → task **Zabz RDP health** (SYSTEM, every 2 minutes).
**It is safe by construction: it only restarts the RDP services when the listener is already missing**, so it
can never drop a live session. Each run writes:

- `C:\Users\ezabz\.dsh\logs\rdp-health-state.json` — current truth: listener present, Tailscale path, sessions,
  last session-event id.
- `C:\Users\ezabz\.dsh\logs\rdp-health.log` — one line per **change**, and every session-relevant event
  translated into English, e.g. *"ANOTHER CONNECTION TOOK THE SESSION (client Windows allows one — CRD/console
  vs RDP)"* or *"ERROR_NETNAME_DELETED — the network connection disappeared (path/NAT change)"*.

Known failure catalogue it covers:

| Failure | What happens now |
|---|---|
| RDP listener missing while services look Running (the wedge that needed a reboot on 2026-10-05 00:22) | auto-detected and repaired in place every 2 minutes; logged `HEALED: re-created the RDP listener without a reboot`. If it cannot be repaired it logs `RDP LISTENER MISSING … needs a reboot` instead of pretending |
| Carrier IP change / path drops to DERP | session is retained on the host; the client auto-reconnects into it; the reason is in the log as `ERROR_NETNAME_DELETED` |
| CRD / console / AnyDesk / TeamViewer taking the single session | logged as reason code 5. **Rule: one door per machine at a time.** RDP into ZABZ-TECH while a CRD session to it is open *will* fight |
| Tailscale service stopped | restarted by both watchdogs |

## 5. Deliberately **not** changed, with the reason

- **RDP UDP transport left at its default (both TCP and UDP).** The evidence points at network loss
  (`ERROR_NETNAME_DELETED`) and session takeover (reason 5), not at UDP. If drops continue *with reason codes
  that are neither 5 nor 2147942464*, the one-line change is the host policy
  `HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services\SelectTransport = 1` ("Use only TCP"),
  documented [here](https://gpedit.tplant.com.au/en-us/policy/TerminalServer/TS_SELECT_TRANSPORT). It is a
  test, not a default.
- **Multi-monitor RDP** (`use multimon:i:1`): off. It requires a uniform DPI across client monitors and this
  client is mixed (200% laptop panel, 100/150% Dells).
- **The competing doors (CRD, AnyDesk, TeamViewer hosts) are left installed on ZABZ-TECH.** They are the
  owner's other ways in; disabling them would trade one outage for another. The conflict is documented above.

## 6. Open items

1. **Two-way control.** Direction YOGA → ZABZ-TECH is RDP and working. The reverse needs either (a) the CRD
   host that is *already installed and registered* on ZABZ-YOGA (`Chromoting` service Running,
   `C:\ProgramData\Google\Chrome Remote Desktop\host.json`) — free, but browser-based, no screen lock, no mic;
   or (b) **Windows 11 Pro on the Yoga**, which is the only way to host real RDP on that machine and would
   make both directions identical (full screen, credentials stored, mic passthrough, tailnet-scoped firewall).
   (b) is a purchase decision and is queued for the owner.
2. **Dictation (Handy + local Whisper) on the Yoga** — still the next build; it needs no credentials and no
   passthrough.
3. **The mesh is not usable over this link yet.** Four `subagent` placements dispatched during this work all
   failed — three landed on ZABZ-TECH and died with *"the remote process exited 0 but printed no completion
   frame — the target profile did not run"*, one with *"ssh_dispatch_run_fatal: Connection to
   100.85.153.96 port 22: Connection timed out"*. Everything in this document was therefore done **locally**,
   under one roof, not by a fleet.

## 7. How to prove all of this again

```powershell
# host side (from the Yoga)
ssh 100.85.153.96 "powershell -c \"Get-Content C:\Users\ezabz\.dsh\logs\rdp-health.log -Tail 20; Get-Content C:\Users\ezabz\.dsh\logs\rdp-health-state.json\""
# client side
Get-Content "$env:USERPROFILE\.dsh\logs\link-keepwarm.log" -Tail 20
tailscale ping -c 4 zabz-tech ; tailscale netcheck
Test-NetConnection zabz-tech.tail93e6e6.ts.net -Port 3389 -InformationLevel Quiet   # expect True
```

## 8. Verification, 2026-10-05 02:08 (an hour after the changes)


Everything below is an observed result, not a configuration claim.

- **The client probe (30 s cadence) ran 20 ticks: 0 failures.** TCP 3389 reachable on every tick, round trip
  24 / 35 / 48 ms min/avg/max, no unreachable samples.
- **The keep-warm task restored a direct path by itself, within one minute of the fallback.** Its own log:
  `02:01:24 RELAY … 02:04:01 RELAY … 02:04:37 RELAY … 02:05:34 direct … 02:06:32 direct … 02:07:33 direct`,
  and `tailscale ping` now reports `via 71.104.140.242:41642` — the office's UPnP mapping, not DERP. This is the
  measurable effect of the once-a-minute ping, and it is the single most useful thing in this document.
- **Host watchdog healthy:** task `Zabz RDP health` ran with `LastTaskResult 0`, its state file was under
  90 seconds old, `listenerTcp=true`, `pathToYoga=direct`, `healed=[]`, `needsAttention=[]` — i.e. it found
  nothing to repair, which is the correct reading for a healthy machine (and it did log the real session
  events from 01:41–01:55 correctly).
- **Settings read back from the registry, not from memory:** `KeepAliveEnable=1`, `KeepAliveInterval=1`,
  `MaxDisconnectionTime=0`, `MaxIdleTime=0`, `UserAuthentication=1`; `standby-timeout-ac=0`;
  `HiberbootEnabled=0`; `NoAutoRebootWithLoggedOnUsers=1`.
- **Session retention proven again:** the RDP session (`ezabz`, session 3) is still present in `qwinsta` as
  `Disc` from 01:55 onward while `console` (session 2) and the listener are up — the desktop and everything
  running on it survived every drop, and the two earlier recoveries are on record as `Event 25 Session
  reconnection succeeded` (01:41:44, 01:43:02).
- **Efficiency fix:** the 1-minute keep-warm loop no longer runs `tailscale netcheck` every tick (netcheck
  probes every DERP region); it now runs netcheck only when the path changes or roughly every 15 minutes.
- **Version gap found and deliberately left alone:** ZABZ-YOGA runs Tailscale **1.98.1**, ZABZ-TECH runs
  **1.102.2**. That is hygiene, not the cause — the measured failures are carrier re-mapping and session
  takeover, neither of which is a client bug — and restarting Tailscale on the Yoga would sever the very link
  this work runs over. It is recorded here as the next change to make at a quiet moment.
- **Deliberate non-test, stated openly:** the self-heal branch was *not* exercised by breaking the listener on
  purpose. That wedge costs a reboot if the repair fails, and this machine is the owner's only door. The
  detection and translation halves of the watchdog are proven on real events; the repair half is proven from
  its earlier behaviour (the same restart sequence is what the reboot accomplished) but not by simulation.

## 9. The 02:30 drop, the wrong colours, and "the session is in use" (2026-10-05 02:35)

The owner's report: *"It took a few tries to get it to turn on, and then it said the session is in use and I had
to try again. And then after I finally connected, it froze a few times and a minute later, it just
disconnected. Also, the colours seem to be very off."* All three are visible in the watchdog's own trail, which
is the first time this system could explain a drop it had not watched happen.

**(a) The tailnet path is FLAPPING, and RDP's UDP transport cannot survive that.** The host watchdog records
the path only when it changes, and it changed every two minutes:
`02:06 direct · 02:10 RELAY · 02:12 direct · 02:22 RELAY · 02:24 direct · 02:26 RELAY · 02:28 direct · 02:30 RELAY · 02:32 direct`.
RDP uses two transports at once: TCP, which WireGuard re-routes transparently when the path changes, and
**RDP-UDP (multitransport)**, which is a separate UDP flow that simply dies when the path changes — freeze,
then disconnect. That is the mechanism behind "it froze a few times and a minute later it disconnected", and it
is not the TCP transport failing (no `ERROR_NETNAME_DELETED` this time).

**(b) The colours were being downgraded on purpose.** The `.rdp` carried `connection type:i:7` with
`networkautodetect:i:1` and `bandwidthautodetect:i:1` — i.e. "adapt the experience to the bandwidth you think
you have", which lowers colour depth and drops visual features. Over a path that is flapping constantly, RDP
re-decides constantly. Fixed by pinning the session: `session bpp:i:32`, `connection type:i:6` (LAN),
`networkautodetect:i:0`, `bandwidthautodetect:i:0`, plus `bitmapcachepersistenable:i:1` so a reconnect repaints
from cache instead of redrawing everything.

**(c) "The session is in use" is the single-session rule again, not a fault.** `qwinsta` shows
`console 2 Conn` — the console session is *connected* (Chrome Remote Desktop holds it; LogonType 2 sessions at
00:23, 01:40 and 01:53), and a client Windows allows one interactive session, so an RDP login has to take it
over. Retrying works; the events show it: `reason code 5` ("another user connected") then `id=25 Session
reconnection succeeded`. The rule stands: **one door per machine at a time** — a CRD session to ZABZ-TECH and
an RDP session to it cannot coexist, and whichever connects last evicts the other.

**Changes made, each reverting to a default-shaped config:**

| change | where | value | why |
|---|---|---|---|
| RDP transport | ZABZ-TECH policy | `SelectTransport = 1` ("Use only TCP") | a path change cannot kill a TCP flow; UDP is the transport that was dying |
| RDP-UDP off | ZABZ-YOGA client registry | `fClientDisableUDP = 1` (HKLM + HKCU) | belt and braces: the client never offers UDP at all |
| Colour/quality | the `.rdp` | `session bpp:i:32`, LAN profile, autodetect off | stop RDP downgrading the picture |
| Keep-warm | ZABZ-YOGA task | **paused** | experiment: it may be the *cause* of the two-minute flapping; the host watchdog still logs the path every two minutes, so the next readings decide it |

The keep-warm was added earlier tonight because it restored a direct path within a minute. If the flapping
stops while it is paused, the honest conclusion is that a once-a-minute ping *provokes* re-evaluation on this
link, and the trade is direct-but-flapping against relayed-but-stable — a different answer from the one §8
recorded, and one to write down rather than argue about.

**Experiment result, 02:45 — and then the correction, 02:50.** Paused at 02:36; by 02:45 the watchdog had
recorded **no path change at all** and the link was still `direct` at 40 ms, where the half hour before flipped
every two minutes. Host load is not implicated: CPU **5 %**, **46 GB** physical free, commit 23.5 of 69 GB,
11 node processes.

That looked like a verdict, and it was written here as one. **It was premature.** With the keep-warm still
disabled, the host log then recorded `path=unreachable` at **02:38:26** and further session events at 02:40:23 —
so the link drops on its own, carrier-side, and thirteen quiet minutes were not evidence that the task caused
the flapping. The keep-warm stays **disabled** for now, not because it was proven harmful but because it is
unproven either way, and the simplest configuration that still carries keep-alive traffic (the host's own
two-minute path probe) is the one to measure first. Nothing in this section should be quoted as settled.

**What did hold up from the same evidence:** Chrome Remote Desktop is *not* the thief — its own log shows the
last viewer attached 01:20:32 and disconnected 01:40:57, with nothing attached during the 02:29–02:40 failures.
The `reason code 5` evictions are the nameless, connected `console` session fighting the RDP login: the
single-session rule, unchanged.

**Now measured from both sides, permanently.**

- Host: `Zabz RDP health`, every 2 minutes — services, listener, path, and every session event translated.
- Client: `Zabz link probe`, every 10 minutes, 5 samples 30 s apart, appending to `.dsh\logs\link-probe.log`
  with `path`, `rtt`, `tcp3389` **and a third-node reference** (`secratary`), so a future "unreachable" says
  whether this side's internet was up at the time. First readings: `02:41:36 direct 36 ms tcp=True
  secratary=True`, `02:42:07 direct 31 ms tcp=True secratary=True`.

**And a tool for the owner**, because none of this is visible from an RDP error dialog — every one of these
failures reports itself as *"possibly due to network connectivity problems"*: **`ZABZ-TECH link status`** on
the Desktop and in the Start Menu, hotkey **Ctrl+Alt+L**. It prints the current path, the round trip, whether
3389 answers, and a plain verdict, and it reminds him that a CRD session to that machine must be evicted first.

## 10. The 03:00 round: the freezes were the graphics pipeline, and what "not sharp" actually was

The owner's second report: *"it froze and crashed again and the font looks funny, the display is not showing
sharp words, get this actually fixed for real."*

**His side of the link was fine the whole time.** The client probe the previous round installed recorded
`path=direct, rtt 30-53 ms, tcp3389=True, internet=True, secratary=True` straight through the freeze, with a
single `path=UNREACHABLE` blip at 02:54:13. So this was **not** the network, and blaming the carrier again
would have been wrong.

**The host's own logs named two real causes.**

*The graphics pipeline was failing.* `RdpCoreTS` recorded, at the exact moments the sessions died:

```
02:39:18  id=67  The RemoteFX protocol connection RDP-Tcp#0 encountered an error (0x80004005)
02:49:25  id=67  The RemoteFX protocol connection RDP-Tcp#0 encountered an error (0x80004005)
02:54:06  id=162 The client supports version 0xA0600 ... AVC available: 1, Initial profile: 2
```

`Initial profile: 2` is **AVC444** — H.264, chroma-subsampled, designed for video. That is the "funny, not
sharp" text: it is a lossy video codec rendering glyphs. And it was erroring out under load.

*The session was enormous.* `id=168` records what the client asked for: `(3840, 2160)` and `(2880, 1800)` —
up to **8.3 megapixels** of desktop, on a client whose own display runs at 150 % scaling.

*And every connection in that window came from 100.72.162.5 — the Yoga itself.* No other client, and Chrome
Remote Desktop's last viewer was 01:40. The `reason code 5` evictions are his own client reconnecting after
each of those failures, not a competing door.

**Changed, and why each one follows from the evidence:**

| change | where | value | evidence it addresses |
|---|---|---|---|
| AVC444 off | ZABZ-TECH policy | `AVC444ModePreferred = 0` | `Initial profile: 2` + text that reads as video-compressed |
| hardware H.264 encode off | ZABZ-TECH policy | `AVCHardwareEncodePreferred = 0` | the T1000's encoder is the thing that logged `0x80004005` |
| session scale | the `.rdp` | `desktopscalefactor:i:150` | 8.3 MP session on a 150 % client: ~3.7 MP, and text at the size he actually sees |
| video playback mode off | the `.rdp` | `videoplaybackmode:i:0` | removes the one feature whose whole purpose is to keep the AVC path engaged |
| policy enforcement | ZABZ-TECH task | `Zabz RDP policy`, every 5 min | see below |

**The values vanished twice, unexplained — so they are now enforced rather than set.** `SelectTransport = 1`
was written and read back at 02:36; by 03:00 it was gone. The local GPO is innocent (`Registry.pol` is 330
bytes and mentions none of these names), and `gpupdate /force` does not reproduce the removal. So the fix is
not "set it again": `scripts/Enforce-RdpPolicies.ps1` — deployed as the task **`Zabz RDP policy`**, every 5
minutes, as SYSTEM — re-applies all three values and **logs every re-application with the reason**, plus one
config line a day proving they are still in place. Its repair path was proven by deleting `SelectTransport`
by hand and watching the next run restore it and say so. (First version of that script wrote to
`$env:USERPROFILE` under SYSTEM — the *system* profile, i.e. a log nobody would ever read; the paths are
absolute now.)

**Deliberately not built, again, and for a measured reason:** an "auto-retry" wrapper was ruled out last round
because the failure dialog is modal. This round it *is* built — `scripts/rdp-session.ps1`, shortcut
**Ctrl+Alt+K** — but only because the modal problem has a safe solution: the wrapper closes that dialog itself
**only when the link is down**, since the normal "connecting" window carries the same title, and it re-opens
the session when the link is healthy again (bounded attempts, every step logged to `.dsh\logs\rdp-session.log`).
A session that ran more than five minutes and then closed is treated as him finishing, not a drop.

**What to expect on the next connection.** Policies are read when a session is created, so nothing above
affects a session already open. The next connect should show, in `RdpCoreTS` event 162, a *different*
graphics profile than 2, and event 168 a resolution near 2560x1440 rather than 3840x2160. Both are checkable
after the fact, and that is the test of this round.




