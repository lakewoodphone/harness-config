# ZABZ-YOGA — the two USB-C ports, and the Dell dock

**Written 2026-10-02** (ZABZ-YOGA, session with the owner). Read this before diagnosing
"the screens are dark" on this laptop again.

Host: `zabz-yoga`, Lenovo **Yoga 9 2-in-1 14IMH9** (machine type **83AC**), BIOS **NNCN37WW**
(2026-04-30). Adapter: **Intel Arc Graphics**, driver 32.0.101.9033 (2026-09-23).
Dock: **Dell Thunderbolt 4 Dock** (USB4 router `VID_8087&PID_0B26`).

## 1. The two ports are NOT one system

The owner's observation, 2026-10-02: *"i changed ports and it's working now, even though both
ports on the left of the laptop are the same system, maybe one of them is broken."*

The ports look identical and are **not** the same system. This box exposes **two Intel USB4 /
Thunderbolt 4 host routers**, one PCI function each:

| Physical port | Intel device | PCI function | Host-router instance |
|---|---|---|---|
| the one the dock works on | `7EC3` | `0&6B` | `USB4\ROOT_DEVICE_ROUTER&VID_8086&PID_7EC3\4&1f2c478c&0&0` |
| the one that failed | `7EC2` | `0&6A` | `USB4\ROOT_DEVICE_ROUTER&VID_8086&PID_7EC2\4&1bae3532&0&0` |

Each port also has its own USB3 xHCI behind it (only one xHCI, `7EC0`, was enumerated in the
failure reading; the other port's superspeed hub tree was the one that reset-failed).

Consequence: **one port can fail while the other is perfect, and there is no single
"USB-C works on this laptop" fact to record.** Any future report must name the port.

## 2. What the failure looked like, and the trap in it

Dock on the **7EC3** port, three Dell monitors dark, 2026-10-02 ~11:10-11:40 local. Readings
taken while it was broken:

| Reading | Value while broken | What it actually means |
|---|---|---|
| `Win32_VideoController` | one adapter, current mode **2880x1800** | the internal panel; no external framebuffer |
| `Screen.AllScreens` | **1** screen, DISPLAY1 1440x900 | one live output |
| `WmiMonitorBasicDisplayParams` | 3 instances `Active=True`, **two of them Dell** | **NOT a link check** — registry last-known state |
| `Get-PnpDevice -Class Monitor` | both Dell monitors `OK` | **same trap** |
| `Get-PnpDevice` non-OK list | `Unknown USB Device (Port Reset Failed)` `USB\VID_0000&PID_0001\5&2F4067DA&0&4`, problem `CM_PROB_PHANTOM` (45) | the only reading that described reality |

**The rule this establishes:** on this laptop, "the monitor is in the device tree with status OK"
and `WmiMonitorBasicDisplayParams.Active = True` are **not** evidence that a display is lit.
Presence is never the signal; **absence** is. A stale `DISPLAY\...` entry and a code-45 phantom
of the failed hub are the honest trace.

Also note: the machine had been **rebooted at 11:06:27** (Kernel-Power 109/577) before this was
reported, so this was *not* a resume-from-sleep artifact.

## 3. Diagnosis in two commands

```powershell
# is the dock actually tunnelled, and on which port?
Get-PnpDevice | Where-Object { $_.FriendlyName -match 'USB4|Thunderbolt' } |
  Select-Object Status,FriendlyName,InstanceId

# is any external output actually live?
Get-CimInstance Win32_VideoController |
  Select-Object Name,CurrentHorizontalResolution,CurrentVerticalResolution
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Screen]::AllScreens
```

If the video controller reports the internal panel's native mode (2880x1800) and
`AllScreens` is 1, **the dock's DP tunnels did not come up** — regardless of what the monitor
entries claim. The dock's presence in the USB4 list is then the controlling fact: the dock
enumerated (it will usually still show `OK` on one router), and the displays still did not.

## 4. Working state, for comparison (captured 2026-10-02 12:0x, same session)

- Active monitors: internal `LEN8ABA` + `DELA275` (S2725QS) + two `DELD1C2` (S2725DSM).
- Screens: DISPLAY1 1440x900 primary, DISPLAY2 2560x1440, DISPLAY3 2560x1440, DISPLAY4 2560x1440.
- `Windows-USB-USB4DeviceRouter-EventLogs` id **1**: *"A monitor attached to your hub or dock was
  successfully enumerated by the USB4 Connection Manager."* — this event is the positive
  confirmation, and there were 12 of them in the last 7 days. **It is the event to look for after
  any dock replug.**

## 5. Recurrence procedure

The owner moves this laptop between the shop and home, so this will recur. Order matters:

1. **Unplug the dock, wait ~10 s, replug the same port.** Cheapest, often enough.
2. **Move to the other USB-C port.** Confirmed working on 2026-10-02. This is the fix that
   needs no reboot and no power-down.
3. **Full power drain** (shut down, hold power 15-30 s, boot) — required to distinguish *a port
   stuck in a bad state* from *a port that is physically dead*. Also flushes Intel USB4 host
   router state, which a plain restart does not.
4. If a specific port fails this way **twice in a row** with the power drain not fixing it, that
   is hardware (retimer / connector), and it is a warranty question for Lenovo — machine type
   83AC, BIOS NNCN37WW.

## 6. Open, not yet decided

- **Is 7EC2 dead or only stuck?** Needs the power drain in §5.3, which requires the owner to
  take the machine down. Until then neither claim is proven, and saying either one is guessing.
- **BIOS / USB4 firmware currency.** `NNCN37WW` (2026-04-30) is what is installed. Lenovo's own
  support pages for 83AC were not readable from this machine (JS-rendered), so the *available*
  version is **not** established. Lenovo Vantage is not installed (`LenovoVantageService` runs,
  no Vantage app directory). Worth one check from a browser before the next hardware conclusion.
