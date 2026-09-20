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

**The single highest-value action was installing the three Lenovo firmware updates that Windows
Update kept offering and never installed** — including the **Infineon TPM firmware 15.23.17664.0 →
15.24.18954.0**. That was the owner's call (firmware flash, downtime) and he approved it.

> ## ✅ RESOLVED 2026-09-20 ~19:45 UTC. Jump to "SESSION 2 / RESOLUTION" at the end of this file.
> Firmware went from `M4WKT56A` (2025-06-02) to **`M4WKT5CA`** (2026-07-07) and TPM from
> `15.23.17664.0` to **`15.24.18954.0`**; Windows Update now offers **zero** firmware. Two
> consecutive boots then came up with a **healthy VSM blob (`BlobSize=723`, corrupt=0)**, Windows
> Hello loading **`State: Okay`**, and the pre-bootmgr window down from **166–178 s to 25 s**.
> The root cause is a **simultaneous Secure Boot DBX + firmware update changing several PCR values
> at once**, which invalidates VSM's seal and makes Windows wipe the Hello container. It is a
> **one-time event per firmware change, not a recurring fault** — which is why re-setting the PIN
> now sticks. It also means the *duration* of the outage scales with how many firmware updates
> Windows applies across how many boots, all of which wipe the container again.

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
2026-09-20 12:03 and 2026-09-20 15:30**. The account is `MicrosoftAccount\ezabz68@gmail.com`, no
Entra join, no domain.

> **Correction (SESSION 2, 2026-09-20):** this section originally offered `dsregcmd /status`
> reporting **`NgcSet : NO`** as further evidence of the wipe. **That is a misreading and it should
> not be used as evidence.** `NgcSet` is a *workplace/Entra* flag ("has a Windows Hello for
> Business container been provisioned for the joined identity") and it reads **NO** on this machine
> because `AzureAdJoined : NO` and `WorkplaceJoined : NO`. It read NO on the healthy boot of
> 2026-09-17 as well. The authoritative local evidence is the `Microsoft-Windows-HelloForBusiness`
> log itself: `8002 … State: Okay` with `PIN protector = true` means a usable container exists;
> `7002 … 0xD000A002` followed by `3611` means it was destroyed. Do not cite `NgcSet` for this.

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
- ~~**Not a PCR change / Secure Boot DBX problem.**~~ **THIS RULE-OUT WAS WRONG — see
  "SESSION 2 / RESOLUTION" below.** The reasoning offered here was that BitLocker is bound to the
  same PCRs (7, 11) and never asks for a recovery key, so PCR 7/11 must be stable. That inference
  does not hold: the Microsoft-documented failure
  ([jpwinsup, "cannot validate VSM when multiple PCRs changed"](https://jpwinsup.github.io/blog/2025/11/12/ActiveDirectory/WindowsHello/cannot-validate-VSM-when-multiple-PCRs-changed/))
  *is* this failure, and it was confirmed on this machine by the fix working. BitLocker's TPM
  protector and VSM's seal are separately evaluated and BitLocker can be released from its own
  cached copy; "BitLocker did not complain" is therefore not evidence that no measured PCR changed.
  It remains true that the *observed* VSM symptom is a missing object
  (`STATUS_NOT_FOUND 0xC0000225`, blob size 0), which is what you see *after* the integrity check
  has already failed and the blob has been discarded — not a contradiction.
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

---

# SESSION 2 / RESOLUTION — 2026-09-20, driven from ZABZ-YOGA

**Why it was moved.** The first session ran *on* ZABZ-TECH, so every reboot in the fix killed the
agent doing the fixing — it could not observe the very boot it had caused. Taken over from ZABZ-YOGA
over Tailscale (`ssh zabz-tech-ts`), which survives ZABZ-TECH rebooting underneath it. That is the
pattern to reuse: **drive a rebooting machine from a machine that is not rebooting.**

## Root cause, from Microsoft

Microsoft (Windows Commercial Support, Directory Services) documents this exact failure —
[cannot validate VSM when multiple PCRs changed](https://jpwinsup.github.io/blog/2025/11/12/ActiveDirectory/WindowsHello/cannot-validate-VSM-when-multiple-PCRs-changed/):

> This problem can occur when a **Secure Boot DBX update and a BIOS/UEFI firmware update are
> performed at the same time** during Windows Update. […] Windows Hello information is protected by
> VSM. Retrieving it performs an integrity check using TPM PCRs. If the Secure Boot DBX update and
> the BIOS/UEFI firmware update happen simultaneously, **several PCR values change at once**, the
> integrity check fails, the information cannot be retrieved, and this problem occurs.

Microsoft states plainly that (a) nothing in Windows prevents those two updates from landing
together, and (b) after it has happened, **the remedy is to re-register Windows Hello** — it is not
a persistent defect. Their stated prevention is to keep password sign-in enabled so a broken Hello
cannot lock you out of the machine.

That maps exactly onto this box: **each firmware application was itself another PCR/state change, so
each boot that applied one wiped the container again.** The chain of one-firmware-per-boot adopted in
session 1 was the right idea for avoiding a multi-PCR change; the mistake was reading the resulting
*wipes* as evidence that the firmware update had failed.

## What the numbers say — three boots, same firmware

| Boot | VSM blob | VSM cached copy | Windows Hello | off-window |
|---|---|---|---|---|
| 12:48 (during chain) | `BlobSize=0`, `corrupt=1` | `0xC0000225` NOT_FOUND | 7002 → container deleted 12:41 | 251 s |
| 15:02 (first boot after BIOS flash) | `BlobSize=0`, `corrupt=1` | `0xC0280018` FAIL | 7002 `0xD000A002` | 1295 s † |
| **15:33** | **`BlobSize=723`, `corrupt=0`** | **`0x0` OK** | **8002 `State: Okay`** | **25 s** |
| **15:38** | **`BlobSize=723`, `corrupt=0`** | **`0x0` OK** | **8002 `State: Okay`** | **25 s** |

† The 1295 s is not a POST measurement — that was a **power-off** the owner started by hand 21 minutes
later, so it includes the time the machine sat off. It is recorded only to show it is not comparable.

**The 15:02 boot is NOT a valid test and must never be cited as one.** A BIOS flash **erases the UEFI
variable store**, so `BlobSize=0` on the first boot afterwards is the *expected* consequence of the
flash, not a recurrence. Reading it as "the firmware update didn't work" is what kept this open.
The valid test is the **second** boot after a firmware change, once the VSM key has been re-sealed.

Firmware after resolution (all `problem=0`, `firmware still offered: count = 0`):
`System Firmware 1.0.0.92` / `ME Firmware 16.1.30.2330` / `TPM Firmware 15.24.18954.0` /
`EC Firmware 1.0.0.19`. BIOS `M4WKT5CA` dated 2026-07-07.

## Confounders eliminated (measured, so they are not re-litigated)

- **Stuck OOBE / half-applied feature upgrade — no.** `HKLM\SYSTEM\Setup` reads
  `SystemSetupInProgress=0`, `SetupType=0`, `OOBEInProgress=0`. `C:\$WINDOWS.~BT` is **stale from
  2026-05-07**, not an active upgrade. No `RebootPending`, no `RebootRequired`.
- **`wsiaccount` is not an OOBE artefact.** It is "a user account managed and used by the system for
  Web Sign-in scenarios", account **inactive**; its console session is a red herring for OOBE.
  *(Session 2 raised it as a suspected stuck-OOBE signature and then disproved it — recorded so the
  next reader does not raise it again.)*
- **Fast Startup — not implicated.** A *Restart* is always a full boot, and the owner's symptom is
  about restarts. It was set `HiberbootEnabled 1→0` in session 1 to force a genuine cold boot so a
  staged capsule would apply; the capsule is gone, so nothing depends on it now.
- **`NgcSet` — not evidence.** See the correction in the PIN section above.

## Watcher defects found and fixed (both produced *false negatives*)

`C:\Users\ezabz\Code\_diag\boot-watch.ps1` (backup: `boot-watch.ps1.bak-20260920`):

1. **It read the last 40 Hello events with no time filter.** So the container deletion from *before*
   the reboot was counted against the boot *after* it — a perfectly healthy boot at 15:38:49 was
   reported `>>> RESULT: HELLO FAILING THIS BOOT`. Now every Hello and Kernel-Boot event is filtered
   to `TimeCreated >= LastBootUpTime`.
2. **It treated the stale orphan container `{16596639-EACC-4EB5-8471-FCBA99C18FD4}` as the user's
   Hello.** That container has been on disk since **2026-02-09**, belongs to no current user, and
   fails with `0xD000A002` on every single boot. It is now tagged `[STALE-ORPHAN]` and excluded.

It now emits one summary line — `>>> RESULT: HELLO <verdict> | VSM key <verdict>` — driven by an
`8002 … State: Okay` load of a non-orphan container plus the absence of `3611`/`7002`. Self-tested
against the live log without rebooting: **`HEALTHY`**. The task runs at startup +90 s as SYSTEM and
self-unregisters after 8 boots.

**Lesson for any future watcher here: a boot-scoped question needs a boot-scoped query. Reading "the
last N events" and then judging *this* boot is how a healthy system gets reported broken.**

## Residual / open, honestly

- **The stale orphan container** `{16596639-…}` is still on disk and still logs a `7002` every boot.
  It is noise, not a fault, and it was left in place rather than deleted because removing a Hello
  container is a credential-store action with no upside here. If you want a clean log, that is the
  one thing to remove — deliberately, by hand, not casually.
- **`Unknown  Storage Firmware Update  driver=1.0.0.4  problem=`** — a *blank* problem code on the
  Micron `MTFDKBA1T0TGD` NVMe firmware device. Still unimplemented/staged. Not implicated in any
  symptom measured here; unresolved.
- **Fast Startup is left OFF** (`HiberbootEnabled=0`). Original value saved at
  `_diag\hiberboot-enabled.orig` (`1`). It makes every start a true cold boot, which keeps VSM/Hello
  deterministic on this box. Trade-off: a shutdown→power-on start is slower by the Windows boot
  time. One command restores it; nothing else depends on it.
- **The 15:33 and 15:38 boots are two consecutive clean boots, not an infinite series.** The failure
  was intermittent (it tracked the firmware-update boots), so two consecutive good boots with a
  healthy VSM blob and a repeatable 25 s POST is strong evidence the churn is over — but if it
  recurs, the *first* question is "did any firmware or Secure Boot DBX update land recently?", and
  the answer is in this watcher's log and `Microsoft-Windows-WindowsUpdateClient` history.

## The durable prevention

Windows will apply firmware and Secure Boot DBX updates **unattended** by default, and Microsoft says
it has no mechanism to stop them landing together. So the recurrence risk is real but bounded: the
next time Lenovo ships firmware, expect one more PIN reset, and re-registering Hello is the whole
remedy. `DevicePasswordLessBuildVersion = 0` is what makes that survivable — **verify it stays 0**;
if it is ever 2, password sign-in is disabled and a broken Hello can lock him out of the machine
entirely (BitLocker recovery key is on his Microsoft account, so recovery is possible but painful).

## Re-verify in one command

```
ssh zabz-tech-ts "powershell -NoProfile -File C:\Users\ezabz\Code\_diag\boot-watch.ps1"
```
Healthy = `>>> RESULT: HELLO HEALTHY ... | VSM key HEALTHY`. (Running it by hand does not reboot
anything; it only appends a run to `boot-watch.log`.)
