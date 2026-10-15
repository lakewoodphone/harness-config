# B — Every FILE, SCRIPT, DOC and GIT COMMIT belonging to the LPT "USB access kit"

**Compiled by:** an agent running on host **ZABZ-TECH** (`zabz-tech`), 2026-10-15 (evening ET).
**Method:** read-only. No script from the USB stick was executed. No file was modified, moved or deleted.
No `git checkout` was performed in any existing working tree; `git show` / `git log` / `git ls-tree` /
`git cat-file` were used instead. The only files created by this work are the working notes in
`C:\Users\ezabz\Code\_scratch\usb-archaeology\` (`_git-*.txt`, `_inventory-*.txt`, `_other-copies.txt`,
`_heads.txt`) and this report.
**Sibling report:** `A-archive.md` (the archived AI sessions) — see `h-archaeology.md`.

---

## 1. What the thing actually is

The kit puts a **time-boxed SSH/HTTPS access window and a machine-state capture onto a customer's Windows
PC from a USB stick**, so an agent can work on the machine remotely. The operator's entire part is:
plug the stick in, double-click **one** numbered icon, click **Yes** once, bring the stick back.

Four icons, one launcher (`launch\Lpt-Launch.ps1`), one output root (`<stick>\LPT-Runs`):

| icon | mode | changes the machine? |
|---|---|---|
| `1-QUICK-SCAN.cmd` | `-Mode Quick` | no — specs, health, battery, network, BitLocker key, activation (seconds) |
| `2-FULL-CAPTURE.cmd` | `-Mode Deep` | no — adds full event logs, registry hives, SMART, inventories (minutes) |
| `3-OPEN-ACCESS.cmd` | `-Mode Open` | **yes** — creates a temp local account, installs/enables OpenSSH, opens a LAN firewall rule, arms its own teardown first |
| `4-CLOSE-ACCESS.cmd` | `-Mode Close` | yes — removes all of that, then **checks it is really gone** (run again after the reboot to record the proof) |

Transport tiers are chosen by `transport\Select-Transport.ps1`: **T1** LAN OpenSSH (no secret on the
target), **T2** reverse SSH, **T3** HTTPS tunnel. `T1-LanSsh.ps1` is the tier that has been worked on.

---

## 2. The dated family tree — and which artefacts are the same thing at different ages

```
2026-05-15  gen 0a  scripts/windows/* + docs/mac-mini-ssh-access.md
                    "remote CLI access" over Tailscale, SSH wrappers, Cloudflared access proxy
                    69318468, 7af91850, ec875614 (05-17), 084c016a (05-18), f385e064 (05-27)
2026-05-21  gen 0b  scripts/windows/Install-CopilotSshAccess.ps1   <-- FIRST USB access installer
                    + Run-CopilotSshAccess.cmd + Export-CopilotSshAccessUsb.ps1   (7775e17e)
2026-07-05  gen 1   scripts/copilot-ssh-field-kit/   "CopilotSshAccess v2 - Shop USB Field Kit"
    07-07           consolidated by d7cd4ecf (+ Collect-PcDiagnostics, Enable/Disable-Techloq,
                    Setup-DesktopTunnelUser, Fix-TunnelUser*, Enable-ShopSsh, Enable-LinuxAccess)
    07-14           side line: scripts/ssh-customer.ps1 + deploy-customer-ssh-key.ps1 + sshpass.exe (c1951834)
    08-11           f8f7dd93  PS 5.1 compatibility fix (Stop-Job -Force is PS7-only)
2026-08-14  gen 2   scripts/lpt-full-diagnostics/Run-FullDiagnostics.ps1   (4a40c3ad)
                    offline QC harness: CPU/RAM/disk stress + report.json + SUMMARY.md on the stick
2026-09-02  gen 3   tools/lpt-diagnostics-kit/    "LPT Laptop Diagnostics Kit (Canonical Source of Truth)"
                    Deploy-LptDiagnostics.ps1 / Ingest-LptDiagnostics.ps1 / Run-LptDiagnostics.ps1 (c34588e1)
                    same day: ca6982a7 exports Enable-LinuxAccess.sh to the USB bundle
2026-10-05  gen 4   tools/lpt-access-kit/  <-- THE MERGE. two stale half-kits retired (MOVED.md in both)
    13:14           99f7134d  diagnostics kit stops lying about its results; captures the BitLocker key
    13:17..14:28    the 26-commit build of the new kit (see §5)
2026-10-15  gen 5   the T1 open-fix chain on branch zabz/lpt-access-kit-open-fix-20261015
    17:05..18:08    7d152dee -> e5333385 -> 834602e9 -> da382067 -> 4a1356b0 -> e3e56331 -> fa4b1bb1
                    NOT on origin/master
```

### Same thing, different ages (the important answer)

| one capability | its older names | comment |
|---|---|---|
| "give me SSH into this Windows box" | `Install-CopilotSshAccess.ps1` (05-21) → `copilot-ssh-field-kit\Enable-ShopSsh.ps1` (07-07) → `lpt-diagnostics-kit\Run-LptDiagnostics.ps1` (09-02) → `lpt-access-kit\3-OPEN-ACCESS.cmd` + `transport\T1-LanSsh.ps1` (10-05/10-15) | the *capability* is 5 months old; the newest name is the only one that arms a teardown first |
| "read the machine" | `Collect-PcDiagnostics.ps1` (07-05) → `Run-FullDiagnostics.ps1` (08-14) → `Run-LptDiagnostics.ps1` (09-02) → `collect\Collect-LptState.ps1` (10-05) | `collect\Collect-LptState.ps1` is 162 KB and is the 2026-10-05 generation of the same idea |
| "put the kit on the stick" | `Export-CopilotSshAccessUsb.ps1` (05-21) → `Deploy-LptDiagnostics.ps1` (09-02) → `Deploy-LptAccessKit.ps1` (10-05) | only the last one **hash-verifies** what it wrote (`DEPLOY OK`) |
| "take it away again / prove it's gone" | nothing older than 10-05 | `teardown\Install-Destructor.ps1` + `teardown\Test-Absence.ps1` are genuinely new |
| the two retired halves | `scripts/copilot-ssh-field-kit/` **and** `tools/lpt-diagnostics-kit/` | `tools/lpt-access-kit` is the single system that replaced both; both carry a `MOVED.md` dated 2026-10-05 |
| the very first run of the new kit | `C:\Users\ezabz\Code\lpt-access-20261005-132139\decision.json` | a transport decision (`T1 READY`, ZABZ-TECH, 2026-10-05T13:21:44) — the only survivor of that run folder |

---

## 3. CURRENT GENERATION — `tools/lpt-access-kit` (35 files, 553 KB)

**The task's first path, `C:\Users\ezabz\Code\personal-secretary-mvp\tools\lpt-access-kit`, DOES NOT EXIST.**
The checkout at `C:\Users\ezabz\Code\personal-secretary-mvp` is on branch `hk/item85-ssh-large-capture-20261013`
(HEAD `8ca891df`), whose tree has no `tools/lpt-access-kit` at all. There are exactly **two live copies of the
current kit on this host**: the git worktree below, and the USB stick (§4).

### 3.1 `C:\Users\ezabz\Code\_worktrees\usb-access-kit\tools\lpt-access-kit`
worktree HEAD `fa4b1bb1` on branch **zabz/lpt-access-kit-open-fix-20261015**; **35 tracked files, 553,459 B**.

| file (relative) | last modified | size | what it does |
|---|---|---|---|
| `1-QUICK-SCAN.cmd` | 2026-10-12 15:22 | 472 | double-click entry: `Lpt-Launch.ps1 -Mode Quick` (read-only, seconds) |
| `2-FULL-CAPTURE.cmd` | 2026-10-12 15:22 | 629 | double-click entry: `-Mode Deep` (read-only, minutes) |
| `3-OPEN-ACCESS.cmd` | 2026-10-12 15:22 | 699 | double-click entry: `-Mode Open` — creates the access window |
| `4-CLOSE-ACCESS.cmd` | 2026-10-12 15:22 | 707 | double-click entry: `-Mode Close` — removes it and proves absence |
| `Deploy-LptAccessKit.ps1` | 2026-10-15 18:04 | 10,678 | copies the allow-list to the stick and **hash-compares every file**; ends `DEPLOY OK` (acceptance A1). `-RetireLegacyKit` moves, never deletes |
| `Ingest-LptAccessKit.ps1` | 2026-10-12 15:22 | 16,915 | brings a returned run folder back into the estate, turns a run into a case record |
| `Run-LptAccess.ps1` | 2026-10-15 18:04 | 20,539 | the elevation wrapper: output root = the stick you ran from, records the receipt, calls the launcher |
| `Run-LptAccess.cmd` | 2026-10-12 15:22 | 2,782 | older interactive single entry (`%~d0\LPT-Runs`); superseded by the four numbered icons |
| `launch\Lpt-Launch.ps1` | 2026-10-15 17:48 | 9,461 | the one launcher: selects transport, captures, opens/closes, writes `_launcher-*.log` + `_launcher-log.txt` |
| `lib\AccessWindow.psm1` | 2026-10-12 15:22 | 11,260 | the window state contract (`lpt-access-window/1`): account, port, deadline, key comment, firewall rule. 8 h default TTL, 72 h ceiling |
| `lib\Guard.psm1` | 2026-10-12 15:22 | 7,796 | precondition/admin/refusal guards |
| `lib\Handoff.psm1` | 2026-10-12 15:22 | 14,203 | builds `handoff.json` / `handoff.txt` (the revocation instructions) |
| `collect\Collect-LptState.ps1` | 2026-10-12 15:22 | 162,854 | the collector: all 40 numbered sections + deep passes |
| `collect\Test-Collector.ps1` | 2026-10-12 15:22 | 17,122 | gate: 39 checks over the collector |
| `probes\Test-TechloqOutboundSsh.ps1` | 2026-10-12 15:22 | 8,248 | M1 probe — detects the Techloq filter so a transport is not chosen blindly |
| `transport\Select-Transport.ps1` | 2026-10-12 15:22 | 33,345 | decides T1/T2/T3 and writes `decision.json` (MEASURED vs ASSUMED) |
| `transport\T1-LanSsh.ps1` | 2026-10-15 18:11 | **43,069** | **tier 1: LAN OpenSSH.** Creates the account, installs OpenSSH (stick payload first), rewrites `sshd_config`, adds the firewall rule. **Working tree is 15 lines ahead of any commit** (§7.2) |
| `transport\T2-ReverseSsh.ps1` | 2026-10-12 15:22 | 26,105 | tier 2: reverse SSH from the target |
| `transport\T3-HttpsTunnel.ps1` | 2026-10-12 15:22 | 37,556 | tier 3: HTTPS tunnel |
| `transport\Test-Transport.ps1` | 2026-10-12 15:22 | 16,573 | gate: 50 checks over the transports |
| `transport\shop-lan-access-public.pub` | 2026-10-15 17:01 | 102 | **the shipped public half** of the access key (`lpt-shop-lan-access`). Private half never in the repo/stick/target. **Branch-only — not on `origin/master`** |
| `teardown\Install-Destructor.ps1` | 2026-10-15 17:28 | 49,791 | arms the self-destructing teardown (service + scheduled task) **before** the window opens; also the remover |
| `teardown\Test-Absence.ps1` | 2026-10-12 15:22 | 25,084 | after the close: proves the account/key line/firewall rule/service are gone (A4) |
| `teardown\Test-TeardownDryRun.ps1` | 2026-10-12 15:22 | 13,054 | gate: 11 checks, walks the teardown plan without executing it |
| `tests\Invoke-Acceptance.ps1` | 2026-10-12 15:22 | 10,388 | runs the acceptance tests this machine can run and **refuses to fake the rest** |
| `tests\Test-AccessKitLib.ps1` | 2026-10-12 15:22 | 11,443 | gate: 57 checks over the libs |
| `tests\Test-KitIntegrity.ps1` | 2026-10-15 17:28 | 14,028 | gate: 12 checks incl. "no function may shadow its own parameter" (the bug that killed two runs) |
| `README.md` | 2026-10-12 15:22 | 5,619 | what the kit is, the four icons, "this folder is the only source of truth" |
| `RUNBOOK.md` | 2026-10-15 18:04 | 5,517 | the operator's one page |
| `DESIGN.md` | 2026-10-12 15:22 | 22,569 | the design contract + acceptance tests A1–A8 |
| `T1-WINDOW-LIFECYCLE.md` | 2026-10-15 18:03 | 10,179 | **written 2026-10-15**: key custody, step order, and the eleven T1 failures with their signatures |
| `REMOTE-ACCESS.md` | 2026-10-12 15:22 | 4,873 | the tier tree |
| `REMOTE-USB-FLOW.md` | 2026-10-12 15:22 | 3,685 | the shape of the flow; supersedes the diagnostics-kit version |
| `vendor\README.md` | 2026-10-15 18:01 | 1,707 | provenance of the OpenSSH payload; pins `sha256 BD48FE98…96530C`. **`vendor\OpenSSH-Win64.zip` is NOT in the worktree and NOT in git** (§7.4) |

---

## 4. THE USB STICK — drive `D:` (read-only, nothing run)

### 4.1 `D:\LPT-Access` — the deployed kit (25 files/dirs, 5.0 MB)

Allow-list deployment of the worktree kit. **Hash-compared against the worktree: every deployed file
matches except one.**

| path | last modified | size | note |
|---|---|---|---|
| `1/2/3/4-*.cmd` | 2026-10-12 15:22 | 472/629/699/707 | identical to the repo |
| `Run-LptAccess.ps1` | 2026-10-15 18:04 | 20,539 | identical |
| `RUNBOOK.md` | 2026-10-15 18:04 | 5,517 | identical |
| `T1-WINDOW-LIFECYCLE.md` | 2026-10-15 18:04 | 10,179 | identical |
| `launch\Lpt-Launch.ps1` | 2026-10-15 17:48 | 9,461 | identical |
| `lib\AccessWindow.psm1` / `Guard.psm1` / `Handoff.psm1` | 2026-10-12 15:22 | 11,260 / 7,796 / 14,203 | identical |
| `collect\Collect-LptState.ps1` | 2026-10-12 15:22 | 162,854 | identical |
| `probes\Test-TechloqOutboundSsh.ps1` | 2026-10-12 15:22 | 8,248 | identical |
| `transport\Select-Transport.ps1` / `T2` / `T3` | 2026-10-12 15:22 | 33,345 / 26,105 / 37,556 | identical |
| `transport\shop-lan-access-public.pub` | 2026-10-15 17:01 | 102 | identical |
| **`transport\T1-LanSsh.ps1`** | 2026-10-15 18:08 | **41,787** | **DIFFERENT** — blob `5fcb1f5b…` = commit `fa4b1bb1` exactly; the worktree's 43,069 B version is uncommitted (§7.2) |
| `teardown\Install-Destructor.ps1` | 2026-10-15 17:28 | 49,791 | identical |
| `teardown\Test-Absence.ps1` | 2026-10-12 15:22 | 25,084 | identical |
| `vendor\OpenSSH-Win64.zip` | 2026-10-15 18:01 | 4,856,219 | **the only copy on the stick; not in git** (§7.4) |
| `vendor\README.md` | 2026-10-15 18:01 | 1,707 | identical |
| `Logs\`, `results\` | 2026-10-12 15:32 | — | empty output dirs |

Deliberately **not** deployed (allow-list): `Deploy-LptAccessKit.ps1`, `DESIGN.md`,
`Ingest-LptAccessKit.ps1`, `Run-LptAccess.cmd`, `tests\*` (all three), `transport\Test-Transport.ps1`,
`collect\Test-Collector.ps1`, `teardown\Test-TeardownDryRun.ps1`. That is by design, not drift.

### 4.2 `D:\LPT-Runs` — every run the kit has left on the stick (9 run folders + launcher logs)

| run folder | when | machine |
|---|---|---|
| `20261012-154253_YZ-PINTER-LAPTO` | 2026-10-12 15:42 | YZ-PINTER-LAPTO |
| `20261015-155618_NB-CG7202203-LT` | 2026-10-15 15:56 | NB-CG7202203-LT |
| `20261015-164721_DESKTOP-3BC7C0C` | 2026-10-15 16:47 | DESKTOP-3BC7C0C (the failed open — the run folder that produced `h-access-open-fix.md`) |
| `20261015-172507_DESKTOP-3BC7C0C` | 2026-10-15 17:25 | DESKTOP-3BC7C0C |
| `20261015-173708_DESKTOP-3BC7C0C` | 2026-10-15 17:37 | DESKTOP-3BC7C0C |
| `20261015-175142_DESKTOP-3BC7C0C` | 2026-10-15 17:51 | DESKTOP-3BC7C0C |
| `20261015-180307_DESKTOP-3BC7C0C` | 2026-10-15 18:03 | DESKTOP-3BC7C0C |
| `20261015-180613_DESKTOP-3BC7C0C` | 2026-10-15 18:06 | DESKTOP-3BC7C0C (+ `sshd_config.before/after`, `transport-T1.log`) |
| `20720310-222649_LAPTOP-3VVAPOT5` | (clock reads 2072 — bad RTC on the target) | LAPTOP-3VVAPOT5 |

Launcher transcripts at the root of `LPT-Runs`: `_launcher-20261015-172506.log`, `-173707`, `-175142`,
`-180306`, `-180612`, and the one-line-per-run index `_launcher-log.txt`; plus
`WHO-AM-I-20261015-155614.txt`.
**Nine of these `access-window.json` files carry a plaintext `accountPassword` field for the window account
on a real customer machine** (§7.6).

### 4.3 `D:\LPT-KeyCheck` — BitLocker proof sub-kit (not part of the access kit proper)

| file | last modified | size | what it does |
|---|---|---|---|
| `Get-BitLockerKeyProof.ps1` | 2026-10-15 13:11 | 21,118 | reads the recovery password **out of the volume**, proves shape/ownership/identification field, writes it to the stick and reads it back |
| `Get-BitLockerKeyProof.cmd` | 2026-10-15 13:03 | 1,630 | double-click wrapper |
| `BITLOCKER-KEY-PF3F2810-20720311-000459\KEY-RECORD-PF3F2810.json` | 2072-03-10 | 2,990 | output record (again the 2072 clock) |
| `BITLOCKER-KEY-PF3F2810-20720311-000459\RECOVERY-KEY-PF3F2810.txt` | 2072-03-10 | 1,958 | **the recovery key itself** |

Same script is also kept at `_scratch\ullman\Get-BitLockerKeyProof.ps1` (2026-10-15 13:11, 21,118 B).

### 4.4 Loose scripts at `D:\` root (all 2026-10-15, all read-only or single-value)

| file | size | what it does |
|---|---|---|
| `RUN-ME.ps1` (+`.cmd`, 15:59) | 2,945 | "who am I": hostname, signed-in user, elevation, network — writes `LPT-Runs\WHO-AM-I-*.txt`. READ ONLY |
| `USB-HISTORY.ps1` (+`.cmd`, 16:11) | 5,665 | what USB device has ever been plugged into this machine and when: `Enum\USBSTOR`/`Enum\USB` + `setupapi*.log`. READ ONLY, no admin |
| `FIX-SENZER.ps1` (+`.cmd`, 16:48) | 7,699 | **WinRE**: clears the Safe Mode boot flag (BCD backed up), reads the BitLocker key to the stick, clears Windows caches. Logs to the stick |
| `DRIVE-FIX.ps1` (+`.cmd`, 17:32) | 8,322 | shop-PC version for a **non-booting** attached customer disk: offline BCD Safe Mode flag, offline USB history, BitLocker state. Refuses if the disk is the running one |
| `DRIVE-FIX-20261015-173254.log` | 403 | run log |
| `RECOVERY-FIX-20261015-164906.log` | 452 | run log |
| `JOB-LOG-senzer.md` | 1,471 | the Senzer job's log |
| `Brooks-Recovered\`, `System Volume Information\` | — | unrelated data / filesystem |

**There is no `D:\CopilotSshAccess` folder on the stick** — the old bundled folder the legacy kits wrote
(`CopilotSshAccess\runs\`) is not present on this stick any more; the only legacy bundle that survives is
what `RetireLegacyKit` would have *moved aside*, and it is not here.

---

## 5. GIT HISTORY — the whole record

Repo: `C:\Users\ezabz\Code\personal-secretary-mvp` (remote `origin` =
`github.com/lakewoodphone/personal-secretary-mvp`). `git rev-list --all --count` = **2,138** commits.
27 worktrees exist; the kit worktree is `C:\Users\ezabz\Code\_worktrees\usb-access-kit` at `fa4b1bb1`.
There is also a `land/lpt-access-kit` worktree at `c0f9673f`.

### 5.0 THE TWO LINEAGES — the single most important thing in this report

Every kit commit from 2026-10-05 has **two SHAs with the identical subject, author and timestamp**. They are
not duplicates of each other; they sit on **two divergent lines**:

| | lineage **M** (on `origin/master`) | lineage **B** (branch `zabz/lpt-access-kit-open-fix-20261015`) |
|---|---|---|
| tip | `c0f9673f` (2026-10-05 14:28) | `fa4b1bb1` (2026-10-15 18:08) |
| kit commits | 27 | 34 |
| `T1-LanSsh.ps1` | blob 28,164 B | blob 41,787 B |
| `T1-WINDOW-LIFECYCLE.md` | **absent** | present |
| `transport\shop-lan-access-public.pub` | **absent** | present |
| `vendor\README.md` | **absent** | present |
| `git merge-base --is-ancestor <sha> origin/master` | True for `dd484fbf`, `c0f9673f` | True for `fa4b1bb1`, `e3e56331`, `4a1356b0`, `da382067`, `834602e9`, `e5333385`, `7d152dee` → **all False** |

`99f7134d` (2026-10-05 13:14, the diagnostics-kit honesty/BitLocker fix) is also **not** an ancestor of
`origin/master` — so `origin/master`'s `tools/lpt-diagnostics-kit/Run-LptDiagnostics.ps1` is the *pre-fix*
version (24,103 B on the cloud deploy vs 31,050 B in the worktree).
`l5284.md` measured the same thing on 2026-10-15: *"The access kit is 12 commits ahead of `master` and its
own gate says PASS."*

### 5.1 Lineage M — kit commits on `origin/master` (27)

| sha | date (iso) | subject |
|---|---|---|
| `c34588e1` | 2026-09-02 19:36:09 -0400 | ops: disk cleanup, Exalt exclusions, LPT diagnostics kit, recovery/sync tooling |
| `dd484fbf` | 2026-10-05 13:17:23 -0400 | lpt-access-kit: the interface layer, and a design contract with acceptance tests |
| `270b9499` | 2026-10-05 13:19:43 -0400 | lpt-access-kit: the M1 probe and a verified deploy path (A1 PASS on the real stick) |
| `882da66b` | 2026-10-05 13:22:16 -0400 | lpt-access-kit: ingest verified, plus the first two build streams (teardown, transport selector) |
| `1d47afff` | 2026-10-05 13:23:30 -0400 | lpt-access-kit: one aggregate token in Test-Absence; teardown dry-run now 11/11 |
| `9de010fa` | 2026-10-05 13:24:17 -0400 | lpt-access-kit: transport stream complete (T2/T3 + destructor final); collect/ still not delivered |
| `45565cc1` | 2026-10-05 13:25:16 -0400 | lpt-access-kit: the state contract teardown reads by name, and the authorized_keys hole it exposed |
| `64293d90` | 2026-10-05 13:31:12 -0400 | lpt-access-kit: the teardown actually removes things now; collect/ delivered and verified |
| `6eecf6ca` | 2026-10-05 13:37:01 -0400 | lpt-access-kit: SUMMARY.md now writes - root cause was @() on a List[object], which throws |
| `3a98f399` | 2026-10-05 13:39:16 -0400 | lpt-access-kit: the teardown now removes the SSH key LINE it added (P2852 closed) |
| `7728761f` | 2026-10-05 13:41:17 -0400 | lpt-access-kit: ALL GATES GREEN - 165 checks across five suites, 17 files, 0 parse or ASCII faults |
| `f3d52ad8` | 2026-10-05 13:44:37 -0400 | lpt-access-kit: ONE entry point, the operator RUNBOOK, and the two stale kits retired |
| `2fdda45d` | 2026-10-05 13:46:42 -0400 | lpt-access-kit: the docs the objective names - README, REMOTE-ACCESS, REMOTE-USB-FLOW - and DESIGN section 7 corrected |
| `7813245e` | 2026-10-05 13:49:49 -0400 | lpt-access-kit: docs updated to the corrected step order (capture first), and the A2 evidence recorded |
| `efc7e8c8` | 2026-10-05 13:49:34 -0400 | lpt-access-kit: fix the one-folder integration bug found by the FIRST REAL RUN; acceptance test A2 evidence |
| `9f832b01` | 2026-10-05 13:52:18 -0400 | lpt-access-kit: the kit-integrity gate - completeness, one source of truth, and A8 without false positives |
| `b0cfca65` | 2026-10-05 13:52:35 -0400 | lpt-access-kit: README gate list now names the integrity gate (six gates, 174 checks) |
| `d3dd59aa` | 2026-10-05 13:56:54 -0400 | lpt-access-kit: ACCEPTANCE TEST A6 EVIDENCE - the first Deep run on a real machine, and it degrades honestly |
| `8878871e` | 2026-10-05 13:57:14 -0400 | lpt-access-kit: the dry run printed a hand-written string, not the arguments it executes |
| `763a2654` | 2026-10-05 13:59:21 -0400 | lpt-access-kit: Select-Transport no longer writes into the current directory |
| `b6a4aea6` | 2026-10-05 14:02:00 -0400 | lpt-access-kit: Invoke-Acceptance.ps1 - run the acceptance tests this machine can run, and refuse to fake the rest |
| `cbd87a33` | 2026-10-05 14:10:24 -0400 | lpt-access-kit: the output root is automatic - it is the stick you ran from, and there is nothing to type |
| `153bc7c3` | 2026-10-05 14:14:49 -0400 | lpt-access-kit: four fire-and-forget launchers - pick the icon, click Yes once, bring the stick back |
| `36e85cc4` | 2026-10-05 14:22:34 -0400 | lpt-access-kit: fix the registry-hives folder bug the FIRST REAL DEEP RUN exposed |
| `7e14c2b3` | 2026-10-05 14:26:07 -0400 | lpt-access-kit: 'the tier was available' and 'access exists' are different facts - the handoff conflated them |
| `c0f9673f` | 2026-10-05 14:28:57 -0400 | collect: an empty headphone jack is not a fault - the audio verdict warned on every healthy laptop |

### 5.2 Lineage B — kit commits on `zabz/lpt-access-kit-open-fix-20261015` (34)

The 2026-10-05 block (identical subjects/dates to §5.1, different SHAs): `e235a583`, `b6851740`,
`6af62754`, `3091957c`, `3306e78c`, `0d44bbf3`, `84ccc764`, `613cf546`, `a08a7e57`, `cf12ea0c`, `6fb623dd`,
`78cc2e90`, `4ad6c457`, `ff1b00f0`, `8d94adea`, `5fbb9fa3`, `b837f805`, `bfd9cf39`, `80e1cb38`, `7d7b753c`,
`8ba89125`, `a54862e4`, `ebc65bee`, `e86a33c1`, `df642e9f` — plus the shared `c34588e1` and `99f7134d`.

**The 2026-10-15 branch-only commits — the seven that exist nowhere else:**

| sha | date (iso) | subject |
|---|---|---|
| `7d152dee` | 2026-10-15 17:05:47 -0400 | lpt-access-kit: the T1 open path fixed so a window can actually be entered and provably closed |
| `e5333385` | 2026-10-15 17:31:29 -0400 | lpt-access-kit: fix the parameter clobber that killed arming - the window never opened because of it |
| `834602e9` | 2026-10-15 17:39:42 -0400 | lpt-access-kit: T1 installs the OpenSSH server it needs, and a refusal can finally be recorded |
| `da382067` | 2026-10-15 17:49:37 -0400 | lpt-access-kit: three defects found by running it end to end on a real Windows machine |
| `4a1356b0` | 2026-10-15 18:02:26 -0400 | lpt-access-kit: OpenSSH from the stick first, Windows Update second - and the two bugs the last run found |
| `e3e56331` | 2026-10-15 18:05:18 -0400 | lpt-access-kit: the whole day written down where the next person will find it, plus the listener check |
| `fa4b1bb1` | 2026-10-15 18:08:34 -0400 | lpt-access-kit: sshd is RESTARTED now, not merely started - the window was installed on a dead port |

Files each of them touched:

| sha | files | +/- |
|---|---|---|
| `7d152dee` | `Deploy-LptAccessKit.ps1`, `Run-LptAccess.ps1`, `launch\Lpt-Launch.ps1`, `tests\Test-KitIntegrity.ps1`, `transport\T1-LanSsh.ps1`, **new `transport\shop-lan-access-public.pub`** | +154 −21 (6 files) |
| `e5333385` | `teardown\Install-Destructor.ps1`, `tests\Test-KitIntegrity.ps1` | +45 −3 |
| `834602e9` | `transport\T1-LanSsh.ps1` | +56 −6 |
| `da382067` | `Run-LptAccess.ps1`, `launch\Lpt-Launch.ps1` | +33 −2 |
| `4a1356b0` | `transport\T1-LanSsh.ps1`, **new `vendor-README.md`** | +93 −4 |
| `e3e56331` | `Deploy-LptAccessKit.ps1`, `RUNBOOK.md`, `Run-LptAccess.ps1`, **new `T1-WINDOW-LIFECYCLE.md`**, `transport\T1-LanSsh.ps1`, rename `vendor-README.md`→`vendor\README.md` | +166 −10 (6 files) |
| `fa4b1bb1` | `transport\T1-LanSsh.ps1` | +9 −1 |

Master-vs-branch diff for the kit, `git diff --stat origin/master fa4b1bb1 -- tools/lpt-access-kit`:
**10 files, +552 −43** — `T1-LanSsh.ps1` +229, `T1-WINDOW-LIFECYCLE.md` +119, `Run-LptAccess.ps1` +83,
`Test-KitIntegrity.ps1` +71, `launch\Lpt-Launch.ps1` +36, `vendor\README.md` +26, `Install-Destructor.ps1`
+13, `Deploy-LptAccessKit.ps1` +11, `RUNBOOK.md` +6, `shop-lan-access-public.pub` +1.

### 5.3 Per-file first appearance and last change (all refs; the two lineages share dates, not SHAs)

| path | first added | added on | last changed | changed on |
|---|---|---|---|---|
| `tools/lpt-access-kit/lib/AccessWindow.psm1` | `dd484fbf` | 2026-10-05 13:17 | `3a98f399` | 2026-10-05 13:39 |
| `tools/lpt-access-kit/lib/Guard.psm1` | `dd484fbf` | 2026-10-05 13:17 | `6eecf6ca` | 2026-10-05 13:37 |
| `tools/lpt-access-kit/tests/Test-AccessKitLib.ps1` | `dd484fbf` | 2026-10-05 13:17 | `64293d90` | 2026-10-05 13:31 |
| `tools/lpt-access-kit/DESIGN.md` | `dd484fbf` | 2026-10-05 13:17 | `2fdda45d` | 2026-10-05 13:46 |
| `tools/lpt-access-kit/Deploy-LptAccessKit.ps1` | `270b9499` | 2026-10-05 13:19 | `e3e56331` | **2026-10-15 18:05** |
| `tools/lpt-access-kit/probes/Test-TechloqOutboundSsh.ps1` | `270b9499` | 2026-10-05 13:19 | `270b9499` | 2026-10-05 13:19 |
| `tools/lpt-access-kit/Ingest-LptAccessKit.ps1` | `882da66b` | 2026-10-05 13:22 | `7e14c2b3` | 2026-10-05 14:26 |
| `tools/lpt-access-kit/teardown/Install-Destructor.ps1` | `882da66b` | 2026-10-05 13:22 | `e5333385` | **2026-10-15 17:31** |
| `tools/lpt-access-kit/teardown/Test-Absence.ps1` | `882da66b` | 2026-10-05 13:22 | `9de010fa` | 2026-10-05 13:24 |
| `tools/lpt-access-kit/teardown/Test-TeardownDryRun.ps1` | `882da66b` | 2026-10-05 13:22 | `1d47afff` | 2026-10-05 13:23 |
| `tools/lpt-access-kit/transport/Select-Transport.ps1` | `882da66b` | 2026-10-05 13:22 | `763a2654` | 2026-10-05 13:59 |
| `tools/lpt-access-kit/transport/T1-LanSsh.ps1` | `882da66b` | 2026-10-05 13:22 | `fa4b1bb1` | **2026-10-15 18:08** |
| `tools/lpt-access-kit/transport/T2-ReverseSsh.ps1` | `3091957c` | 2026-10-05 13:23 | `64293d90` | 2026-10-05 13:31 |
| `tools/lpt-access-kit/transport/T3-HttpsTunnel.ps1` | `3306e78c` | 2026-10-05 13:24 | `9de010fa` | 2026-10-05 13:24 |
| `tools/lpt-access-kit/transport/Test-Transport.ps1` | `0d44bbf3` | 2026-10-05 13:25 | `45565cc1` | 2026-10-05 13:25 |
| `tools/lpt-access-kit/collect/Collect-LptState.ps1` | `0d44bbf3` | 2026-10-05 13:25 | `c0f9673f` | 2026-10-05 14:28 |
| `tools/lpt-access-kit/collect/Test-Collector.ps1` | `0d44bbf3` | 2026-10-05 13:25 | `7728761f` | 2026-10-05 13:41 |
| `tools/lpt-access-kit/Run-LptAccess.ps1` | `6fb623dd` | 2026-10-05 13:44 | `e3e56331` | **2026-10-15 18:05** |
| `tools/lpt-access-kit/Run-LptAccess.cmd` | `6fb623dd` | 2026-10-05 13:44 | `cbd87a33` | 2026-10-05 14:10 |
| `tools/lpt-access-kit/RUNBOOK.md` | `6fb623dd` | 2026-10-05 13:44 | `e3e56331` | **2026-10-15 18:05** |
| `tools/lpt-diagnostics-kit/MOVED.md` | `6fb623dd` | 2026-10-05 13:44 | `f3d52ad8` | 2026-10-05 13:44 |
| `scripts/copilot-ssh-field-kit/MOVED.md` | `6fb623dd` | 2026-10-05 13:44 | `f3d52ad8` | 2026-10-05 13:44 |
| `tools/lpt-access-kit/README.md` | `78cc2e90` | 2026-10-05 13:46 | `153bc7c3` | 2026-10-05 14:14 |
| `tools/lpt-access-kit/REMOTE-ACCESS.md` | `78cc2e90` | 2026-10-05 13:46 | `2fdda45d` | 2026-10-05 13:46 |
| `tools/lpt-access-kit/REMOTE-USB-FLOW.md` | `78cc2e90` | 2026-10-05 13:46 | `7813245e` | 2026-10-05 13:49 |
| `tools/lpt-access-kit/tests/Test-KitIntegrity.ps1` | `8d94adea` | 2026-10-05 13:52 | `e5333385` | **2026-10-15 17:31** |
| `tools/lpt-access-kit/tests/Invoke-Acceptance.ps1` | `7d7b753c` | 2026-10-05 14:02 | `b6a4aea6` | 2026-10-05 14:02 |
| `tools/lpt-access-kit/1/2/3/4-*.cmd` | `a54862e4` | 2026-10-05 14:14 | `153bc7c3` | 2026-10-05 14:14 |
| `tools/lpt-access-kit/launch/Lpt-Launch.ps1` | `a54862e4` | 2026-10-05 14:14 | `da382067` | **2026-10-15 17:49** |
| `tools/lpt-access-kit/transport/shop-lan-access-public.pub` | `7d152dee` | 2026-10-15 17:05 | `7d152dee` | 2026-10-15 17:05 |
| `tools/lpt-access-kit/T1-WINDOW-LIFECYCLE.md` | `e3e56331` | 2026-10-15 18:05 | `e3e56331` | 2026-10-15 18:05 |
| `tools/lpt-access-kit/vendor/README.md` | `4a1356b0` (as `vendor-README.md`) | 2026-10-15 18:02 | `e3e56331` | 2026-10-15 18:05 |
| `tools/lpt-diagnostics-kit/Run-LptDiagnostics.ps1` | `c34588e1` | 2026-09-02 19:36 | `99f7134d` | 2026-10-05 13:14 |
| `scripts/copilot-ssh-field-kit/Enable-ShopSsh.ps1` | `d7cd4ecf` | 2026-07-07 16:40 | `99f7134d` | 2026-10-05 13:14 |
| `scripts/copilot-ssh-field-kit/Enable-LinuxAccess.sh` | `ca6982a7` | 2026-09-02 19:35 | `99f7134d` | 2026-10-05 13:14 |
| `scripts/copilot-ssh-field-kit/Install-CopilotSshAccess.ps1` | `e1538fdb` | 2026-07-05 00:12 | `f8f7dd93` | 2026-08-11 15:15 |
| `scripts/windows/Export-CopilotSshAccessUsb.ps1` | `7775e17e` | 2026-05-21 02:44 | `ca6982a7` | 2026-09-02 19:35 |
| `scripts/windows/Install-CopilotSshAccess.ps1` | `7775e17e` | 2026-05-21 02:44 | `7775e17e` | 2026-05-21 02:44 |
| `scripts/windows/Run-CopilotSshAccess.cmd` | `7775e17e` | 2026-05-21 02:44 | `7775e17e` | 2026-05-21 02:44 |

### 5.4 Older-generation commits (the ancestors, with dates)

Found with `git log --all -S'CopilotSshAccess' --oneline`, `-S'Enable-ShopSsh'`, `-S'Disable-Techloq'`,
`-S'AccessWindow'`, and path history over `scripts/windows`, `scripts/copilot-ssh-field-kit`,
`scripts/lpt-full-diagnostics`, `tools/lpt-diagnostics-kit`:

| sha | date (iso) | subject | relevance |
|---|---|---|---|
| `69318468` | 2026-05-15 13:27 | Add Windows remote CLI and accounting transfer setup | earliest access tooling |
| `7af91850` | 2026-05-15 13:33 | Prepare remote CLI access over Tailscale | |
| `ec875614` | 2026-05-17 03:43 | ops: harden secretary and desktop access paths | adds `scripts/windows/CloudflaredAccessSshProxy.ps1` |
| `43757f42` | 2026-05-17 09:27 | fix: preserve desktop ssh wrapper exit codes | |
| `40ae301f` | 2026-05-17 09:39 | ops: harden desktop remote access - watchdog tunnel + setup script | |
| `084c016a` | 2026-05-18 22:59 | ops: enable Mac mini SSH, add access doc and desktop install script | |
| `774a7df6` | 2026-05-19 11:37 | feat: add chat sync and autopilot support tooling | |
| **`7775e17e`** | **2026-05-21 02:44** | **ops: add Windows access helpers and audit logs** | **creates `scripts/windows/{Install-CopilotSshAccess.ps1, Run-CopilotSshAccess.cmd, Export-CopilotSshAccessUsb.ps1}` — generation 0** |
| `2fb7da99` | 2026-05-26 19:44 | feat: LIN bench v4 - multi-model firmware, car-day launcher, dashboard, tools | |
| `f385e064` | 2026-05-27 15:34 | ops: harden five-node access mesh | |
| `fc2402ff` | 2026-05-28 13:31 | Harden machine access mesh recovery | |
| `dd84d2a2` | 2026-06-10 15:53 | chore(scripts): AI platform ops, extension deploy, cost tracking | |
| `c60a667b` | 2026-06-08 13:20 | chore(repo): organize workspace snapshot | |
| `4dc58d20` | 2026-06-26 13:49 | Accumulated changes: AI gateway, cost control, fleet MDM, finance cleanup, customer cases, tests, scripts | |
| `fb7d4871` | 2026-06-26 13:50 | New scripts: LPT SMS send flow, DRN deploy, laptop inventory, QC reader, wallpaper templates, gateway test | |
| `9f56c820` | 2026-06-30 12:56 | 2026-06-30: budget cut, remove American frontier models & OpenRouter | |
| `52d8d2d5` | 2026-07-02 19:25 | Techloq filter reference guide + Asher Benno case file | Techloq context for `Disable-Techloq` |
| `e1538fdb` | 2026-07-05 00:12 | chore: cleanup stale files, update gitignore, add remaining artifacts | first `Install-CopilotSshAccess.ps1` in the field-kit path |
| **`d7cd4ecf`** | **2026-07-07 16:40** | **chore: workspace sweep 2026-07-07 — archive stale docs, add SSH field kit, …** | **the field kit becomes a kit: Collect-PcDiagnostics, Enable/Disable-Techloq, Enable-ShopSsh, Setup-DesktopTunnelUser, Fix-TunnelUser*** |
| `85783755` | 2026-07-13 12:11 | Reconciliation pipeline overhaul: identity linker, health endpoint, … | |
| `c1951834` | 2026-07-14 13:45 | Add customer SSH access tools: sshpass, ssh-customer.ps1, deploy-customer-ssh-key.ps1 | a *separate* customer-SSH line (per-customer key, not a kit) |
| `ce5f09c5` | 2026-07-22 22:21 | chore: apply preserved stash — mesh access check infrastructure + Cloudflare proxy fix | |
| `0571b783` | 2026-08-04 19:12 | fix: Windows PowerShell 5.1 parsing of .ps1 scripts (UTF-8 BOM + ASCII quotes/dashes) | the PS 5.1 trap that still bites |
| `f8f7dd93` | 2026-08-11 15:15 | fix(ssh-field-kit): Stop-Job -Force is PS7-only — use plain Stop-Job for PS 5.1 targets; bump update timeout to 10min | last change to the field kit |
| `4a40c3ad` | 2026-08-14 12:51 | feat(scripts): laptop sourcing suite + full diagnostics + recovery tools | creates `scripts/lpt-full-diagnostics` |
| `b6e95949` | 2026-08-24 13:07 | Housekeeping: untrack nested lpt-hub mirror from this repo | |
| `2a41e323` | 2026-08-24 23:53 | docs: supercharge Yocheved handoff - key-deploy script, Techloq fallbacks, access ladder, GitHub report-back protocol | access ladder doc |
| `21e69906` | 2026-08-24 23:58 | yocheved: 2026-08-24 session report | |
| `1eac6841` | 2026-08-24 23:20 | docs: Yocheved laptop setup handoff (Techloq-safe, BYOK, spoke node) | |
| `4a8255a6` | 2026-08-24 17:09 | fix(mesh): make laptop a full inbound SSH node — desktop can now ssh laptop | |
| `cb3ff255` | 2026-09-02 19:35 | ops: drop chromadb from backups (rebuildable cache); note SMS/SSH kit docs | |
| `ca6982a7` | 2026-09-02 19:35 | ssh: export Linux access kit (Enable-LinuxAccess.sh) to USB bundle | |
| **`c34588e1`** | **2026-09-02 19:36** | **ops: disk cleanup, Exalt exclusions, LPT diagnostics kit, recovery/sync tooling** | **creates `tools/lpt-diagnostics-kit` (17 files, +2,536)** |
| `99f7134d` | 2026-10-05 13:14 | diagnostics kit: capture the BitLocker key and the access state honestly; stop the kit lying about its own results | last commit of generation 3; **not on master** |

Pickaxe searches that found nothing extra: `git log --all -S'Export-CopilotSshAccessUsb'` matches only
`7775e17e`. `-S'CopilotSshAccess'` also matches `d7cd4ecf`, `e1538fdb`, `f8f7dd93`, `ca6982a7`, `c34588e1`,
`99f7134d`, `b6e95949`, `21e69906`, `c60a667b`, `4dc58d20`, `fb7d4871`, `9f56c820`, `52d8d2d5`, `85783755`
and the whole 2026-10-05 access-kit chain.

---

## 6. OTHER LOCATIONS

### 6.1 `C:\Users\ezabz\Code\_scratch` — the archaeology workspace and the 2026-10-15 notes

| file | last modified | size | what it is |
|---|---|---|---|
| `usb-archaeology\` | 2026-10-15 | — | this report's folder. Also contains a sibling agent's `_probe.sh` (searches the fleet for old kit copies by size) — not mine, left untouched |
| `h-archaeology.md` | 2026-10-15 18:12 | 6,376 | the brief for this whole exercise (owner: "stop reinventing the wheel"), and the index of reports A/B |
| `h-access-open-fix.md` | 2026-10-15 17:06 | 4,518 | the four T1 defects found on run `20261015-164721_DESKTOP-3BC7C0C`; branch + `7d152dee` + DEPLOY OK |
| `h-t1test.md` | 2026-10-15 17:49 | 4,645 | the ZABZ-YOGA end-to-end test: what it proved, the three further defects, and that a green T1 run is still NOT proven |
| `t1-e2e.ps1` | 2026-10-15 17:44 | 6,026 | the end-to-end test script (throwaway keypair; run as a detached scheduled task) |
| `t1-run2.ps1` | 2026-10-15 18:09 | 4,298 | the second (proper) test, building a real `tier=T1` state with `New-AccessWindow` |
| `repro-install.ps1` | 2026-10-15 17:27 | 1,586 | reproduces the destructor install-mode failure against the real state file |
| `prove-startupfix.ps1` | 2026-10-15 17:28 | 1,799 | behavioural proof of the `RegisterAtStartup` parameter-clobber fix (the `$action`/`$Action` bug) |
| `keygen-test.ps1` | 2026-10-15 16:58 | 1,271 | empirical test of the exact `ssh-keygen` argv under **Windows PowerShell 5.1** |
| `awstate\access-window.json` | 2026-10-15 17:25 | 1,640 | a real window state for DESKTOP-3BC7C0C (`lptwinbc7c0c`, port 45880, 8 h). **Holds the account password in clear — see §7.6** |
| `openssh-vendor\OpenSSH-Win64-v9.5.0.0p1-Beta.zip` | 2026-10-15 18:01 | 4,856,219 | the pinned OpenSSH payload, out of the repo |
| `openssh-vendor\extract\OpenSSH-Win64\` | 2026-10-15 18:01 | ~11 MB | the extracted payload (sshd.exe 1,343,920 B, ssh.exe, install-sshd.ps1, SPDX manifest, …) |
| `lpt-access-kit-RUNBOOK.md` | 2026-10-12 15:20 | 5,114 | a **copy of the kit `RUNBOOK.md`** taken out to the scratch dir; superseded (the live one is 5,517 B with the T1 warning) |
| `l5030-body.md` | 2026-10-15 15:54 | 3,635 | lesson L5030 — "pushed and remote-verified" is a claim about a moment |
| `l5284.md` | 2026-10-15 16:43 | 4,509 | **lesson L5284 — `DEPLOY OK` proves the stick matches a checkout, not that the checkout is the mainline; the kit is 12 commits ahead of `master`** |
| `l5346.md` | 2026-10-15 16:45 | 3,379 | lesson L5346 — the operator runs ONE icon and hands back the hardware; anything asked to be read off a screen is undone work |
| `journal-lesson-ssh-reset-vs-auth.txt` | 2026-10-05 13:18 | 2,988 | journal family from the 2026-10-05 build (see next row) |
| `commit-msg-usb-kit-hardening.txt` | 2026-10-05 13:14 | 2,188 | the commit message for the first access-kit commit |
| `commit-msg-accesskit-lib.txt` / `-ingest-teardown.txt` | 2026-10-05 13:17 / 13:22 | 1,997 / 3,528 | commit messages for the lineage's first two commits |
| `journal-handoff-accesskit-round{2,3,5,8,9,10,11}*.txt` | 2026-10-05 13:23 → 14:02 | 2.7–6.9 KB each | the **round-by-round record of the original 2026-10-05 build** — the closest thing to a session log for generation 4 |
| `journal-pain-authorizedkeys-hole.txt` | 2026-10-05 13:25 | 2,782 | the `authorized_keys` hole (`P2852`) |
| `journal-pain-reboot-cleanup.txt`, `journal-lesson-cleanup-promise.txt` | 2026-10-05 13:14 | 2,447 / 2,234 | why the closed-window leftovers survive a reboot without the stick |
| `journal-lesson-at-list-coercion.txt` | 2026-10-05 13:36 | 3,198 | `@()` on `List[object]` throws — the `SUMMARY.md` bug |
| `journal-decisions-accesskit.txt` | 2026-10-05 13:46 | 3,652 | design decisions taken during the build |

Note: `_scratch` also holds **no** copy of the kit scripts themselves — only these notes and the OpenSSH payload.

### 6.2 `C:\Users\ezabz\Code\lpt-access-20261005-132139\`

One file: **`decision.json`** — 2,453 B, 2026-10-05 13:21. Schema `lpt-transport-decision/1`,
runId `20261005-132139-ZABZ-TECH`, host `ZABZ-TECH`, mode `MEASURED`, **tier `T1`, state `READY`**, reasons
*"this machine is on the shop LAN 192.168.50.0/24"* and *"no filter signal present … the only tier that puts
NO secret on the target"*. It is the output of `Select-Transport.ps1` from the **first run of the new kit**,
12 minutes after the kit's first commit, on this very machine. The rest of that run folder is gone.

### 6.3 Older generations still on disk (retired, read-only)

**`C:\Users\ezabz\Code\_worktrees\usb-access-kit\tools\lpt-diagnostics-kit\`** (9 files, 2026-10-12 15:22 in
the worktree; the main checkout has 8):

| file | size | what it does |
|---|---|---|
| `Run-LptDiagnostics.ps1` | 31,050 | the scan (identity, CPU/RAM/GPU, disks+SMART, battery health, WiFi, PnP problems, audio endpoint state, BitLocker key + access state after `99f7134d`) |
| `Run-LptDiagnostics.cmd` | 649 | double-click wrapper |
| `Deploy-LptDiagnostics.ps1` | 1,917 | copy to the stick |
| `Ingest-LptDiagnostics.ps1` | 2,908 | bring results back |
| `Remote-RunScript.ps1` | 4,067 | run a script on the target over SSH |
| `README.md` / `REMOTE-ACCESS.md` / `REMOTE-USB-FLOW.md` | 6,613 / 3,629 / 5,109 | the generation-3 docs |
| `MOVED.md` | 2,198 | **"this is no longer a source of truth"**, with the measured stick-vs-repo drift table |

**`C:\Users\ezabz\Code\_worktrees\usb-access-kit\scripts\copilot-ssh-field-kit\`** — 17 tracked files +
untracked run artefacts (89 files total on disk):

| file | size | what it does |
|---|---|---|
| `Install-CopilotSshAccess.ps1` | 41,017 | the v2 one-shot SSH installer (OpenSSH server, key in both Windows locations, ACLs, LAN firewall rule) |
| `Enable-ShopSsh.ps1` / `.cmd` | 15,289 / 1,717 | the "open the shop's SSH door" pair, incl. Techloq handling |
| `Disable-Techloq.ps1` / `Enable-Techloq.ps1` | 2,159 / 678 | turn the content filter off/on for the session |
| `Collect-PcDiagnostics.ps1` / `.cmd` | 20,139 / 673 | the pre-2026 diagnostic collector |
| `Enable-LinuxAccess.sh` | 4,446 | the Ubuntu/Debian equivalent (openssh-server, `copilot` user, firewall, `LinuxAccess.txt`) |
| `Setup-DesktopTunnelUser.ps1` | 8,362 | reverse-tunnel user on the operator desktop |
| `Setup-DesktopReverseEndpoint.ps1` + `.cmd` | 6,536 / 873 | reverse endpoint setup |
| `Fix-TunnelUserPermissions.ps1` / `Fix-TunnelUser-FINAL.ps1` | 2,180 / 2,447 | the tunnel-user permission fixes, both kept |
| `Run-CopilotSshAccess.ps1` / `.cmd` | 1,201 / 1,905 | entry points |
| `README.txt` | 5,835 | "CopilotSshAccess v2 - Shop USB Field Kit" |
| `MOVED.md` | 2,323 | retired 2026-10-05 with measurements (3 handoff formats; stick ahead of repo) |
| `keys\copilot_reverse_ed25519` (+ `.pub`) | 432 / 113 | **a private key in the working tree** — but `.gitignore:233` ignores `scripts/copilot-ssh-field-kit/keys/` and `git ls-files` confirms it is **untracked** |
| `latest-run\` (≈50 files) | 2026-07-04 23:33–23:37 | a real capture, incl. `CopilotAccess.json` 576,227 B, `CopilotAccess.zip` 151,515 B, `sshd_config.before/after`, `CopilotSshAccess.log`, `local_tunnel_logs/` — untracked (`.gitignore:234`) |
| `DesktopReverseEndpointSetup.log` | 1,467 | untracked log |

**`scripts\windows\` legacy (generation 0)** — tracked in the repo, still present:

| file | size | what it does |
|---|---|---|
| `Install-CopilotSshAccess.ps1` | 9,941 | the **original** 2026-05-21 installer (OpenSSH server + key + ACLs + LAN firewall rule) |
| `Run-CopilotSshAccess.cmd` | 353 | double-click wrapper |
| `Export-CopilotSshAccessUsb.ps1` | 1,884 | copies the installer to the first removable drive into `CopilotSshAccess\` — the original "put it on a stick" |
| `CloudflaredAccessSshProxy.ps1` | 3,895 | Cloudflare access proxy for SSH |
| `Configure-DesktopSshCloudflareTunnel.ps1`, `Connect-DesktopSsh.ps1`, `Enable-RemoteCliAccess.ps1`, `Ensure-MachineAccessMesh.ps1`, `Install-LaptopSshServer.ps1`, `Install-MacMiniAccess.ps1`, `Start-DesktopTunnelWatchdog.ps1` … | 4-30 KB | the 2026-05 access-mesh family (installers for each node, wrappers, watchdogs) |

**`scripts\lpt-full-diagnostics\`** (generation 2, 2 files): `Run-FullDiagnostics.ps1` 33,430 B
(4-phase offline QC: snapshot → CPU/RAM/disk stress → interactive dead-pixel/checklist → `report.json` +
`SUMMARY.md` on the stick) and `Run-FullDiagnostics.cmd` 1,120 B. A copy of the same pair also sits in
`_scratch\ullman\fulldiag\` (2026-10-15 11:23) from the Ullman case.

**`scripts\ssh-customer.ps1`** (5,946 B) and **`scripts\deploy-customer-ssh-key.ps1`** (3,480 B) — added
`c1951834` 2026-07-14; a *per-customer* key deployment rather than a USB kit. Related: `scripts\sshpass.exe`.

### 6.4 Other hosts (read-only over ssh)

**`secratary-ts`** (`ssh secratary-ts` → hostname `secratary`; the shop's authority box):
* `~/personal-secretary-mvp` — HEAD `31c9707d` 2026-10-13 (branch `checkout-health…`). `tools/` contains
  `lpt-diagnostics-kit`, `communication`, `phone-backup`, `samsung-carrier-flash`, `web`, `wpd-tool`.
  **No `tools/lpt-access-kit`.** Only remote kit branch present: `remotes/origin/zabz/usb-kit-hardening-20261005`.
* `scripts/copilot-ssh-field-kit/` and `scripts/windows/` **are** present (same legacy families).
* `~/repos` holds `lpt-hub`, `phone-and-tech-full`, etc. — no kit.
* `/opt` has `actions-runner`, `fleet-dashboard`, `google` — no kit.
* The kit *does* exist all over the ts box's **worktrees and rescue copies** (each an old snapshot of the
  repo, never a live deploy): `~/tmp-rescue-20261002/*/`, `~/hk501/`, `~/hk470/`, `~/hk496b/`, `~/hk502/`,
  `~/hk151-scratch/`, `~/_fcwt/probe/`, `~/_verify_co_20260928/`, `~/_lpt447_wt/`, `~/wt-*/` … each carrying
  `tools/lpt-diagnostics-kit` + `scripts/copilot-ssh-field-kit` + `scripts/windows/…`.
* A targeted `find ~ /opt ~/repos -maxdepth 7` for `*lpt-access*`, `*access-kit*`, `*CopilotSshAccess*`,
  `*access-window*`, `*T1-LanSsh*` returned **no `lpt-access-kit` anywhere on secratary-ts**.

**`secratary-cloud`** (`ssh secratary-cloud` → hostname `secratary-cloud`; the production cloud box):
* **`/opt/company/tools/lpt-access-kit` EXISTS** — 30 files, all stamped 2026-10-13 01:42 by a deploy.
  This is the **`origin/master` (generation-4) version**, i.e. *older than the branch*:
  `T1-LanSsh.ps1` 28,164 B (vs 41,787 on the stick), `Run-LptAccess.ps1` 15,950 B,
  `Deploy-LptAccessKit.ps1` 9,794 B, `RUNBOOK.md` 5,007 B, no `T1-WINDOW-LIFECYCLE.md`, no `vendor/`,
  no `transport\shop-lan-access-public.pub`.
* `/opt/company/tools/lpt-diagnostics-kit` — 9 files, `Run-LptDiagnostics.ps1` **24,103 B** (pre-`99f7134d`;
  the honesty/BitLocker fix is not on master).
* `/opt/company/scripts/copilot-ssh-field-kit/` — 17 files; note **host drift**: its `Enable-ShopSsh.ps1`
  is 14,795 B and `Collect-PcDiagnostics.ps1` 20,139 B against 15,289 B / 20,139 B locally.
* `/opt/company/scripts/windows/` — includes `Export-CopilotSshAccessUsb.ps1` (1,884 B, 2026-09-02),
  `Install-CopilotSshAccess.ps1` (9,941 B), `Run-CopilotSshAccess.cmd`, `CloudflaredAccessSshProxy.ps1`,
  the whole access-mesh family, and the newer `dsh-ssh-run.ps1`, `seat-ssh-run.py`, `seat-ssh-putget.py`.
* `/opt/company/scripts/lpt-full-diagnostics/` — `Run-FullDiagnostics.ps1` 33,430 B, `.cmd` 1,120 B.
* `git branch -a` on `/opt/company` has `remotes/origin/zabz/lpt-access-kit-open-fix-20261015`
  **and** `remotes/origin/zabz/usb-kit-hardening-20261005`, but HEAD is `332f7615` (2026-10-15 15:49 UTC,
  an unrelated r7 commit) and its `git log -- tools/lpt-access-kit` tip is `c0f9673f` (2026-10-05 14:28).
* **No `CopilotSshAccess` folder as a deployment anywhere** on either host (only the repo source paths).

---

## 7. DRIFT, GAPS AND THINGS THAT WILL LOSE INFORMATION

**7.1 The task's first location is empty.** `C:\Users\ezabz\Code\personal-secretary-mvp\tools\lpt-access-kit`
does not exist; that checkout is on `hk/item85-ssh-large-capture-20261013`. The two live copies are the
worktree and `D:\LPT-Access`. Anyone reading "current generation" from the main checkout sees nothing.

**7.2 The worktree is 15 lines ahead of every commit.** `tools\lpt-access-kit\transport\T1-LanSsh.ps1` in
`_worktrees\usb-access-kit` is 43,069 B (blob `67fed7ef…`) while commit `fa4b1bb1` holds 41,787 B (blob
`5fcb1f5b…`). `git status` shows it as ` M`. The 15 added lines exist **only as that uncommitted file on
this disk** — not in git, not on the stick, not on either server.

**7.3 The stick matches the commit, not the working tree.** `D:\LPT-Access\transport\T1-LanSsh.ps1` hashes
exactly to `fa4b1bb1`. So the deployed stick is *reproducible from git*, and the only thing that would
change it is the next `Deploy`. Every other deployed file hash-matches the worktree.

**7.4 The OpenSSH payload is not in git.** `vendor\OpenSSH-Win64.zip` (4,856,219 B,
`sha256 BD48FE98…96530C`) is neither in the worktree nor tracked nor ignored — the only copies are
`D:\LPT-Access\vendor\OpenSSH-Win64.zip` and `_scratch\openssh-vendor\` (zip + extracted tree). If the stick
is erased the kit can only fall back to `Add-WindowsCapability`, measured at ~8 minutes and impossible
offline or behind a filter. A source URL and hash are recorded in `vendor\README.md`, so it is recoverable —
but only with internet.

**7.5 The branch is not the mainline, and the gate cannot see that.** Seven commits, ~552 net lines of kit
change, the shipped public key and the whole `T1-WINDOW-LIFECYCLE.md` exist only on
`zabz/lpt-access-kit-open-fix-20261015`. `A1 PASS` / `DEPLOY OK` compares the stick to *one working tree*.
The production cloud deploy (`/opt/company`, 2026-10-13) is the **old** generation. `origin/master` still
carries `T1-LanSsh.ps1` at 28,164 B. `l5284.md` is the standing lesson for this.

**7.6 Secrets in plaintext outside git.**
* `_scratch\awstate\access-window.json` — a real `access-window` state for **DESKTOP-3BC7C0C** including
  `accountPassword` (clear text), the account `lptwinbc7c0c`, port `45880` and the 8-hour deadline.
* **Nine** `access-window.json` files under `D:\LPT-Runs\*` each carry an `accountPassword` for a window
  account created on a real customer machine. They are the teardown's state, so they cannot simply be
  deleted without care — but they are credentials sitting on a loose USB stick.
* `D:\LPT-KeyCheck\BITLOCKER-KEY-PF3F2810-20720311-000459\RECOVERY-KEY-PF3F2810.txt` — a BitLocker
  recovery key on the same stick.
* `scripts\copilot-ssh-field-kit\keys\copilot_reverse_ed25519` — a private key on disk; `.gitignore:233`
  keeps it out of git (verified: untracked).

**7.7 The T1 path is still not proven green.** `h-t1test.md` (2026-10-15 17:49) states plainly that
acceptance **A4/A5 have never completed end to end**: arming, the destructor's `-RunNow`, correct refusal
of a wrong-tier state and full state recovery are proven; "open → connect with the kit-installed key →
close → absence PASS" is not. `T1-WINDOW-LIFECYCLE.md` §8 names this and the T2/T3 key-comment bug.
`D:\LPT-Runs\20261015-180613_DESKTOP-3BC7C0C\transport-T1.log` is the newest evidence.

**7.8 A 2072 clock.** `D:\LPT-Runs\20720310-222649_LAPTOP-3VVAPOT5\` and
`D:\LPT-KeyCheck\BITLOCKER-KEY-PF3F2810-20720311-000459\` are stamped 2072 — a target with a dead RTC.
Any date-based triage of the stick will mis-sort them.

**7.9 The retired halves still hold captures.** `scripts\copilot-ssh-field-kit\latest-run\` (2026-07-04) holds
`CopilotAccess.json` (576 KB) and `CopilotAccess.zip` (151 KB) from a real customer capture, untracked and
ignored — it survives only on this disk's copy of the worktree. `MOVED.md` explicitly says the old
`CopilotSshAccess\runs\` holds unarchived customer captures and that `-RetireLegacyKit` *moves* rather than
deletes.

---

## 8. Method and limits

* `git log --all`, `--diff-filter=A`, `-S`, `--first-parent`, `branch -a --contains`,
  `merge-base --is-ancestor`, `ls-tree`, `cat-file`, `hash-object`, `worktree list` — all read-only, on
  `C:\Users\ezabz\Code\personal-secretary-mvp` and the `_worktrees\usb-access-kit` worktree.
* File inventories by `Get-ChildItem -Recurse -Force`; content comparisons by SHA-256.
* Nothing on `D:\` was executed. The legacy `keys\` private key and the `access-window.json` passwords were
  identified by inspection only and are **not reproduced** in this report.
* Not covered here: the archived AI session transcripts (that is report **A**), the estate's other repos
  (`lpt-hub`, `phone-and-tech-full`) beyond the paths named, and git objects reachable only from
  `refs/bundle/*` or packed bundles.
* Total kit commits catalogued: **34** on lineage B + **27** on lineage M (52 distinct SHAs) + **7** older
  generation-0/1 commits with `CopilotSshAccess` in them + the generation-0/1/2 path history (**29** dated
  commits in §5.4).
