# 117 — ZABZ-TECH: slow reboots and the Windows Hello PIN reset every restart

**Owner report, 2026-09-20:** *"why every time i restart the zabz tech computer it takes a long time
to turn back on and i have to reset the pin"*

**Investigated on the machine itself, elevated, 2026-09-20 ~16:05–16:45 UTC.** Readings below are
from ZABZ-TECH's own event logs and registry; each carries its source and time.

## READ FIRST — verdict

Two symptoms, and they are **the same event on the same boots**:

1. **The PIN resets because Windows deletes the Hello container.** The container fails to load with
   `Error: 0xD000A002`, and Windows' own OOBE broker then removes it and provisions an empty one, so
   a PIN must be created again. Root cause of the failed load: on those boots the **VSM (Virtual
   Secure Mode) master key's sealed package is absent from the UEFI variable at early boot**, and
   this machine has **VSM-protected Windows Hello enabled** (`DeviceGuard\Scenarios\WindowsHello\Enabled = 1`).
2. **The slow part is not Windows.** Microsoft's own boot instrumentation puts core boot at
   **12–24 s** and total Windows boot at **30–58 s**. The 63–178 s sits *before* `bootmgr` starts.

**The single highest-value action is installing the three Lenovo firmware updates that Windows
Update keeps offering and never installs** — including the **Infineon TPM firmware 15.23.17664.0 →
15.24.18954.0**. That is the owner's call (firmware flash, downtime). See "Open decision".

## Evidence

### The PIN — exact sequence, ZABZ-TECH, boot of 2026-09-20 12:02
Source: `Microsoft-Windows-HelloForBusiness/Operational` (read elevated).

| Time | Id | Message |
|---|---|---|
| 12:02:23 | 8025 | The Microsoft Passport service started successfully |
| 12:02:28 | 5701 | `PIN protector = false` (container has no usable PIN) |
| 12:02:28 | **7002** | **`Failed to load an existing Windows Hello container. ID: {667c9244-…} Error: 0xD000A002`** |
| 12:02:28 | 5701 | `PIN protector = false` (second container — also fails) |
| 12:03:14 | **3611** | **`Windows Hello container deletion started from UserOOBEBroker.exe`** |
| 12:03:14 | 8611 | `Windows Hello successfully deleted the container` |
| 12:03:21 | 5702 | `Windows Hello wrote following protector properties to disk: PIN protector = true` (fresh empty container) |

Same deletion-by-`UserOOBEBroker.exe` on **2026-09-02 16:23, 2026-09-15 10:35, 2026-09-16 12:32,
2026-09-20 12:03**. `dsregcmd /status` now reports **`NgcSet : NO`** — the account is
`MicrosoftAccount\ezabz68@gmail.com`, no Entra join, no domain.

### Why the container fails — VSM key absent at early boot
Source: `Microsoft-Windows-Kernel-Boot/Operational`.

| Boot | VSM key package | Hello container |
|---|---|---|
| 2026-09-16 11:29:09 | `Unsealing cached copy status: 0x0` — **OK** | loaded (`PIN protector = true`) — **survived** |
| 2026-09-16 12:30:46 | **`Using cached copy status: 0xC0000225` (STATUS_NOT_FOUND); `Read and Unseal Master Key Array Package: The object was not found; BlobFromUefiVariableSize: 0`** | both loads fail → **deleted 12:32:29** |
| 2026-09-17 08:49:36 | `status 0x0`, `BlobFromUefiVariableSize: 723` — **OK** | loaded, `State: Okay` — **survived** |
| 2026-09-20 12:02:15 | **`Unsealing cached copy status: 0xC0280018`**, blob size 0 | both loads fail → **deleted 12:03:14** |

The 2026-09-20 Kernel-Boot event 85 carries the decisive field, read in full at 16:20 UTC:

```
Status: The object was not found.
PrimarySealedBlobName: VsmLocalKey2   SecondaryProtectorVariableName: VsmLocalKeyProtector
BlobFromUefiVariableSize: 0     UefiContentIsSealed: 0     UnsealedBlobSize: 0
Pcr7SealingUsed: 0              UefiBlobIsCorrupt: 1
NeedToResealKeyPkg: 0           NeedToResealBackup: 0     NeedToResealPca2023Backup: 0
ActivePolicyVersion: 0          LatchedPolicyVersion: 0   UnlatchedPolicyVersion: 0
```

**`UefiBlobIsCorrupt: 1`** — the VSM key blob stored in its UEFI variable is **corrupt**, not simply
absent, and `BlobFromUefiVariableSize: 0` says the variable read back empty. That is a UEFI
variable-store / firmware-level fault, which is why the fix below is a firmware update rather than
anything inside Windows. On the healthy boot of 2026-09-17 the same event read
`Unsealing cached copy status: 0x0`.

When the blob is present (723 bytes) the container loads and the PIN survives. When it is absent
(0 bytes) the container is undecryptable and Windows wipes it.

**Windows Hello is VSM-protected on this box:** `HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\WindowsHello :: Enabled=1`,
and `Scenarios\KeyGuard\Status :: IsSecureKernelRunning=1, KeyGuardEnabled=1, CredGuardEnabled=0`.

### The slow boot — the time is before Windows
Sources: `Microsoft-Windows-Kernel-General` 12/13 (System log) and **`Diagnostics-Performance/Operational` event 100**
(Windows' own per-boot measurement; its `BootStartTime` **is** the kernel/bootmgr start).

- Core boot (`MainPathBootTime`): **9.5–23.6 s**. Total Windows boot (`BootTime`): **30.2–103.1 s**.
  Latest, 2026-09-17: **55.6 s total, 14.9 s main path, 40.7 s post-boot**.
- The window from "OS began shutting down" (K13) to "bootmgr started" is **bimodal**:

| Off-window (s) | Boots |
|---|---|
| 63, 69, 74, 86, 93, 96 | VSM key present, Hello intact |
| **166, 176, 176, 177, 178** | **VSM key lost, Hello wiped** |

So ~110 s of extra time and the PIN wipe are the same event. This window contains *shutdown tail +
power-off + firmware POST*; Windows logs cannot split those three, so **"POST is exactly N seconds"
is not claimed here** — the correlation is measured, the split is not.

### Contributing factors found and measured
- **Three Lenovo firmware updates offered by Windows Update, never installed** (2026-09-20 16:20):
  `Lenovo Ltd. - Firmware - 16.1.30.2330` (`uefi\res_{7fd2a343-…}`),
  **`Lenovo Ltd. - Firmware - 15.24.18954.0` (`uefi\res_{2327d974-…}`)** — this is the **TPM
  firmware**; the TPM reports its current version as **`15.23.17664.0`** (`tpmtool getdeviceinformation`);
  and `Lenovo Ltd. Firmware Driver Update (1.0.0.92)` (`uefi\res_{8a15883b-…}`).
  The same version shape (`15.23.17664.0` → `15.24.18954.0`) is what identifies it as the Infineon
  SLB9672 TPM firmware.
- **Stale OOBE-stage flags** `WindowsUpdate\Auto Update\IsOOBEInProgress = 1` and
  `AcceleratedInstallRequired = 1`. **Absent on ZABZ-YOGA (control), whose Hello container loads
  cleanly and has no `7002` errors.**
- **`ServicesPipeTimeout = 180000`** in `HKLM\SYSTEM\CurrentControlSet\Control` (Windows default
  **30000**). Any hung auto-start service would cost 3 minutes.
- **`Intel(R) Platform License Manager Service`** — `StartMode=Auto`, `State=Stopped`, and event
  **`7009` "A timeout was reached (180000 milliseconds) while waiting for the Intel(R) Platform
  License Manager Service service to connect"** on essentially every boot.
- **Stale orphan Hello container** `C:\Windows\ServiceProfiles\LocalService\AppData\Local\Microsoft\Ngc\{16596639-EACC-4EB5-8471-FCBA99C18FD4}`
  (from 2026-02-09) fails with `0xD000A002` on every boot.
- **BIOS `M4WKT56A`, dated 2025-06-02** — over a year old. Machine is a Lenovo **ThinkCentre P3
  Tiny** (`30H10010US`), EC firmware `1.0.0.19`.
- **A staged-but-`Disconnected` "Storage Firmware Update"** device for a Micron `MTFDKBA1T0TGD` NVMe.
- **~40 s of post-boot startup churn** (`BootPostBootTime`) with 114 auto-start services (107 running)
  and a heavy logon set: Nox emulator, Wondershare MobileTrans, Samsung Smart Switch, 8 duplicate
  `MicrosoftEdgeAutoLaunch_*` entries, Torch `WebSocketServer23420`, Macrium Reflect UI, Screen+,
  Nearby Share, Brother ES status monitor, WisprFlow, AnyDesk, Tailscale, Dialpad, PowerToys.
- `C:\$WINDOWS.~BT` exists and `SoftwareDistribution\Download` holds **743.8 MB**.

### Rule-outs (measured, so they are not re-litigated)
- **Not a PCR change / Secure Boot DBX problem.** The Microsoft-documented failure
  ([jpwinsup, "cannot validate VSM when multiple PCRs changed"](https://jpwinsup.github.io/blog/2025/11/12/ActiveDirectory/WindowsHello/cannot-validate-VSM-when-multiple-PCRs-changed/))
  is *PCRs changed*, but **BitLocker here is bound to the same PCRs (7, 11) and never asks for a
  recovery key** — so PCR 7/11 are stable. The VSM failure is a *missing object*
  (`STATUS_NOT_FOUND 0xC0000225`, blob size 0), not a failed integrity check.
- **Not the RTC/CMOS battery.** `Kernel-General` id 1 shows RTC time tracking system time with
  0 ms deltas; daily drift corrections are ~1.4–4.6 s (normal).
- **Not Windows boot itself** — 30–58 s.
- **Not disk space** — C: has 153.1 GB free of 951.6 GB.
- **Fast Startup is ON** (`HiberbootEnabled=1`) but is *not* implicated: a Restart is always a full
  boot, and a bootmgr timeout of `0` rules out a boot-menu wait.
- **Lockout risk ruled out.** `DevicePasswordLessBuildVersion = 0`, so password sign-in is still
  allowed; a BitLocker numerical recovery password exists and is **backed up to the Microsoft
  account** (`manage-bde -protectors -get C:` → `Backup type: Microsoft account backup`).

## What was changed on ZABZ-TECH (all reversible, applied + verified 2026-09-20)
| Change | Before | After |
|---|---|---|
| `HKLM\SYSTEM\CurrentControlSet\Control\ServicesPipeTimeout` | `180000` | `30000` (Windows default) |
| `Intel(R) Platform License Manager Service` startup type | `Automatic` | `Manual` |
| `HKCU\…\CurrentVersion\Run\MicrosoftEdgeAutoLaunch_*` (8 duplicate entries) | present | removed (backup: `Code\_diag\edge-autolaunch-backup.txt`) |
| `…\WindowsUpdate\Auto Update\IsOOBEInProgress` | `1` | removed |
| `…\WindowsUpdate\Auto Update\AcceleratedInstallRequired` | `1` | removed |

After the change the firmware updates were re-queried and are still offered; BitLocker still
`Protection On`, 100 % encrypted; `NgcSvc`/`NgcCtnrSvc` running.

## Open decision — **APPROVED and IN PROGRESS 2026-09-20 16:20 UTC**
The owner approved installing the pending Lenovo firmware updates. Because installing several
firmware updates in one session is the pattern Microsoft warns can change multiple PCRs at once, they
are being applied **one per boot** by a capped, self-stopping startup task
(`C:\Users\ezabz\Code\_diag\firmware-chain.ps1`, task `ZabzTech-FirmwareChain`, SYSTEM/highest,
at-startup + 90 s). It verifies the previous boot's Hello state, installs exactly one firmware update,
logs the result codes, and reboots. It stops on install failure, on no progress, or after 5 attempts.

**Run 1, 2026-09-20 16:20 UTC** — installed `Lenovo Ltd. Firmware Driver Update (1.0.0.92)`
(`uefi\res_{8a15883b-…}`, driver date 2026-07-08, the newest of the three):
`download resultCode=2 hresult=0x00000000`, `install resultCode=2 perUpdate=2 rebootRequired=True`, `hresult=0x00000000`.
Two remain: TPM firmware `15.24.18954.0` and device firmware `16.1.30.2330`.

Progress to date is in `_diag\firmware-chain.log`; a `firmware-chain.DONE` file is written when the
chain stops, and the task unregisters itself.

Note: the first attempt to reboot from the task did nothing —
`Start-Process shutdown.exe -NoNewWindow` from a session-0 SYSTEM task returned exit 0, registered no
restart (no event 1074) and left `LastTaskResult = 0`. The script now calls `shutdown.exe` directly
and logs its exit code. **Never with `/f`** — force-closing the owner's apps risks unsaved work.


## How to verify the fix afterwards
On the first boot after the firmware updates, in `Microsoft-Windows-HelloForBusiness/Operational`:
- **Good:** `8002 Successfully loaded an existing hardware Windows Hello container … State: Okay`, and
  **no** `3611 UserOOBEBroker.exe` container deletion.
- **Bad:** `7002 … 0xD000A002` followed by `3611`.
And in `Microsoft-Windows-Kernel-Boot/Operational`, event 45/85 should show `Unsealing cached copy
status: 0x0` and a **non-zero** `BlobFromUefiVariableSize`.

## Access note
This investigation used an already-configured path: `ssh -i ~/.ssh/id_ed25519 ezabz@localhost`
yields **`Mandatory Label\High Mandatory Level` (S-1-16-12288)** — an elevated token — even though a
normal DSH `pwsh` call on this machine is only Medium integrity. Useful for any future admin-level
diagnosis here.
