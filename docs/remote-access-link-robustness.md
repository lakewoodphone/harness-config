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
