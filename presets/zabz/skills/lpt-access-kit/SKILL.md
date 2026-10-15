---
name: lpt-access-kit
description: Use whenever the owner wants to get INTO a machine rather than read about it — "tunnel you in", "full access", "remote in", "open access", a customer PC that has to be diagnosed at the bench, the LPT USB stick, 3-OPEN-ACCESS / 4-CLOSE-ACCESS, installing OpenSSH on a target, or any question about why an access window did not open. Covers the two actions the operator performs, key custody, how to prove the kit works without asking anyone to walk to a machine, and the eleven ways this path has already failed.
---

# Getting into a machine with the LPT access kit

**The full record is `personal-secretary-mvp/tools/lpt-access-kit/T1-WINDOW-LIFECYCLE.md`, and it also
travels on the stick.** Read it before opening a window on anyone's machine. This skill is the working
summary and the parts that are not in that file.

---

## 1. The rule that governs everything here

**Prove it on a machine you can drive before you ask anyone to walk to one.** On 2026-10-15 this kit failed
six times in a row, and each time the owner was sent back to a bench with a stick. His words, twice:
*"can you test it yourself fully before telling me to try again"* and *"i don't have time to do your work"*.

**The operator's part is exactly two actions:** plug the stick in, double-click **`3-OPEN-ACCESS`**, click
Yes; and later **`4-CLOSE-ACCESS`**, reboot, run **`4`** again. Nothing is typed, nothing is read off a
screen. If a procedure you write needs him to read a value and report it, that is a missing read on your
side — the stick logs everything and he brings it back.

**On T1 the stick does NOT need to come back mid-session.** The private half is on the operator machine.

## 2. Key custody — one rule

| half | where |
|---|---|
| public | shipped in the kit at `transport\shop-lan-access-public.pub`, installed into the target's `administrators_authorized_keys` |
| private | **only** on the operator machine: `%USERPROFILE%\.ssh\lpt-access-t1` on ZABZ-TECH. Never in a repo, never on the stick, never on the target. |

```
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL `
    -i "$env:USERPROFILE\.ssh\lpt-access-t1" -p <port> <account>@<target-ip> hostname
```

Port and account are in the run folder's `handoff.txt`. The account is derivable without it:
`AccessWindow.psm1:62` builds `lptwin` + the last six characters of the hostname, lowercased —
`DESKTOP-3BC7C0C` → `lptwinbc7c0c`.

## 3. Where the kit is, and how to put it on a stick

- Source: `C:\Users\ezabz\Code\personal-secretary-mvp\tools\lpt-access-kit` (on ZABZ-TECH the working copy
  is the linked worktree `C:\Users\ezabz\Code\_worktrees\usb-access-kit`).
- **It is on branch `zabz/lpt-access-kit-open-fix-20261015`, NOT on `origin/master`** (journal **L5345**).
  A deploy from a `master` checkout ships an older kit and its own gate still says `A1 PASS`. Check with
  `git merge-base --is-ancestor <sha> origin/master` — and note that here commit identity is not a reliable
  test either, because the same change has reached `master` by a different route. **Compare file content.**
- Deploy: `Deploy-LptAccessKit.ps1 -Drive D` → must end `DEPLOY OK` (that is acceptance test A1; it
  hash-compares every deployed file). It never deletes, so `vendor\` and `LPT-Runs\` survive.
- Gates before deploying: `tests\Test-KitIntegrity.ps1` (12), `tests\Test-AccessKitLib.ps1` (57),
  `teardown\Test-TeardownDryRun.ps1` (11), `transport\Test-Transport.ps1` (50), `collect\Test-Collector.ps1` (39).

## 4. How to TEST it yourself — the part that took a whole evening to work out

- **ZABZ-TECH cannot run the open path: it is not elevated, and the open path creates a local account,
  rewrites `sshd_config` and adds a firewall rule.**
- **ZABZ-YOGA gives an ELEVATED shell over SSH** (`ssh laptop-ts` → `IsInRole(Administrator)` = True) and is
  a real Windows laptop. Use it.
- **`scp` does NOT work to it** (`Connection closed`, both clients). Get the kit there with git:
  `git fetch origin <branch>` then `git worktree add --detach C:\lpt-accesstest\kit FETCH_HEAD` in its
  `personal-secretary-mvp` clone.
- **Run anything that moves sshd from a detached scheduled task**, not `Start-Process` and not inline over
  SSH: `schtasks /Create /TN LptT1Test /SC ONCE /ST 00:00 /RL HIGHEST /F /TR "powershell ... -File <script>"`
  then `/Run`. `Start-Process` from an SSH session dies with the session, and **T1 sets `Port <random>` and
  rewrites `sshd_config`, so your SSH connection to the laptop drops mid-run** and only comes back when the
  teardown restores the config.
- **Restore the machine afterwards and prove you did**: `sshd` back to `Running/Automatic`, and the
  `sshd_config` SHA256 identical to the before-hash. And a `sshdServicePreExisting`-TRUE window only
  *stops and disables* sshd — it does not delete it — so restore is `Set-Service sshd -StartupType Automatic; Start-Service sshd`.
- **T1 refuses a window state whose `tier` is not T1**, correctly. To test T1 you must build a T1 state:
  `Import-Module ...\lib\AccessWindow.psm1; New-AccessWindow -RunId <id> -HostName <host> -Tier T1`, then run
  `T1-LanSsh.ps1 -OutDir <run> -PublicKeyPath <pub> -AuthProbePrivateKeyPath <throwaway priv>`. Use a
  throwaway keypair generated on the test machine so no real private key is copied anywhere.

## 5. Reading a failed run — do this before theorising

1. `<stick>\LPT-Runs\_launcher-<stamp>.log` — the launcher's transcript. **It only exists because it had to
   be added**; before 2026-10-15 a failed run left no reason anywhere.
2. `<run folder>\transport-<tier>.log` — the FULL transport output, also added 2026-10-15. Before that,
   `Run-LptAccess.ps1` printed ten pattern-matched lines and discarded the rest, and every diagnosis was
   reconstructed from which fields were missing out of a JSON file. **Never diagnose from absence of fields
   when you can keep the output.**
3. `<run folder>\access-window.json` — everything the teardown needs. `handoff.txt` — the revocation.
4. `<stick>\LPT-Runs\_launcher-log.txt` — one line per run: mode, host, exit, seconds.

## 6. The failure signatures

The full table is in `T1-WINDOW-LIFECYCLE.md` §5 (eleven entries, each with signature and fix). The three
that cost the most, because they are invisible:

- **A non-zero exit with a receipt that says the opposite.** `mode=Open | exit=1 | access window opened`.
  The launcher's detail string is not evidence; the exit code is.
- **The selector's verdict is not the transport's verdict.** `Select-Transport` writes `transport = T3 READY`
  into the handoff *before* any transport runs. A transport that then refuses without updating it leaves a
  handoff that reads READY. **The transport's exit code is the outcome.**
- **A blocker with no evidence.** "TCP/<port> is NOT listening" named no cause and cost a round trip. It now
  reports the service status, the `Port` lines in `sshd_config`, and the ports sshd *is* on.

## 7. Standing facts that are easy to get wrong

- **Install checkpoints are ordered for a reason**: capture → decide → **arm the teardown** → open. If arming
  fails the window is NOT opened. Never reorder it.
- **PowerShell variable names are case-insensitive.** `$action = ...` inside a function that takes `$Action`
  **overwrites the parameter**. That single line killed two runs. `Test-KitIntegrity.ps1` now fails the build
  for any function that shadows its own parameter — keep that check.
- **Windows caps a local account `Description` at 48 characters.** 49 characters killed a run.
- **Windows ships the OpenSSH CLIENT, not the server.** The kit carries the server payload at
  `vendor\OpenSSH-Win64.zip` (pinned, `sha256 BD48FE98…96530C`, Microsoft-signed) and uses it first;
  `Add-WindowsCapability` is the fallback and measured about **eight minutes** with nothing on screen.
- **The window is 8 hours by default** (`AccessWindow.psm1:32`), ceiling 72.
- **The close removes the state file**, so `Test-Absence` must be pointed at
  `access-window-destroyed.json`. Without that it always reports `PARTIAL` and A4 can never PASS.
- **A window's leftovers are only removable with the stick present** — the armed destructor reads its state
  from the stick, so at boot without it the plan reduces to removing its own service and task and the
  account, key line and firewall rule stay behind.

## 8. Still unproven — do not report these as working

- **A4 and A5 have never been run green end to end.** The chain open → connect with the kit-installed key →
  close → absence **PASS** has not been completed. Arming, the destructor's `-RunNow`, correct refusal of a
  wrong-tier state, and full state recovery *are* proven.
- **T2 and T3 still build their own key comment** rather than taking it from the window state, and T3
  reported READY without creating a tunnel. The launcher now masks the second; the source is not fixed.
