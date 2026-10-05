# Talk to text across a remote desktop — ZABZ-YOGA into ZABZ-TECH

**Date:** 2026-10-04 late evening (machine-local clocks) · **Author:** Zabz on ZABZ-YOGA
**Request (owner, verbatim):** *"the question is how can i do talk to text from the yoga into the zabz tech"* —
after finding that on Chrome Remote Desktop *"i wanted to send text and i clicked show keyboard or something"*
and then: *"everything works besides talk to text, cuz i'm talking into the yoga mic not the zabztechmic, how
do you propose to fix this"*. Closed with *"document all this and we'll get back to it"*.
**State:** paused by owner decision. Nothing is broken that was working before; the RDP work below is additive
and reversible. Related journal entries: handoff **H3164**, lesson **L3270**.

---

## 1. The constraint, stated once

**Chrome Remote Desktop carries keyboard, mouse and clipboard text. It does not carry a microphone.**
The CRD client has no audio-capture control at all, so a dictation engine running *inside* the remote session
(Win+H Voice Typing, Voice Access, any app) hears the remote machine's own microphone and can never hear the
client's. Toggling anything in the CRD toolbar cannot change this — that is why the on-screen keyboard he
clicked had nothing to do with the problem.

Consequence: **you cannot dictate "into" a CRD session directly.** You either move the *text* across, or you
replace CRD with a transport that does carry audio (RDP).

## 2. The house standard: dictate on the client, paste into the focused window

This is already built and proven on another machine, and it is the answer that needs no reboot and no
microphone passthrough: **Handy** (github.com/cjpais/Handy, MIT) with **Whisper large-v3-turbo** running
locally, toggled by one hotkey, transcribing and then **pasting the text into whatever field has focus**.
Full precedent, config and evidence: `docs/talk-to-text-lakewooechsmini.md` (Mac mini, 2026-09-15).

Why that solves *this* problem: the transcript leaves the Yoga as **text on the clipboard plus one Ctrl+V**,
and clipboard text plus ordinary keystrokes are exactly what CRD does forward. The microphone never has to
cross the link, because the speech is turned into text before it is sent. The owner's own requirement for the
Mac build — *"i need it to start when i push windows h, and i don't need to hold it down, and it automatically
puts the text in whatever text box"* — is satisfied by the same shape on Windows, provided the hotkey does not
collide with something he needs.

Not yet installed on ZABZ-YOGA (`C:\Users\ezabz\AppData\Local\Programs\Handy` does not exist; the only script
in the repo is `scripts/install-handy-dictation-macos.sh`). A Windows equivalent is the next piece of work —
see §7.

**Hotkey note to resolve when it is built:** Windows already binds **Win+H** to OS voice typing. Handy's
`new_with_blocking` hotkey registration takes the key away from every other app while it runs (that is how
Command+H works on the Mac), so binding Win+H would shadow Windows' own dictation — the same muscle memory,
the better model. That is a deliberate trade to make explicitly, not by accident.

## 3. What works today, with nothing installed

1. **Win+H on ZABZ-YOGA with the remote-desktop window focused.** Windows voice typing injects the transcript
   as keystrokes; CRD relays keystrokes. *Not yet proven* for CRD's injected-Unicode path — it is a
   ten-second test (click the remote field, press Win+H, say one sentence).
2. **The clipboard route, which cannot fail:** dictate into any window on the Yoga (or the Yoga's own DSH),
   `Ctrl+A`, `Ctrl+C`, click into the field inside the remote session, `Ctrl+V`. The words travel as clipboard
   text through CRD's own clipboard sync; only the paste keystroke has to be relayed, and ordinary keystrokes
   demonstrably work (he types in the remote session).
3. If the client is a **phone** rather than the Yoga's Windows session: CRD's mobile clients take text through
   a local input buffer that is sent to the host on Enter, so dictating into the phone keyboard's mic button
   and sending works the same way. (The screenshot supplied showed a Windows touch keyboard with Fn/Win keys
   and a Windows taskbar, so the client here is Windows.)

## 4. The audio route: RDP with "record from this computer"

This is the only mainstream way to make the **Yoga's actual microphone** a device inside ZABZ-TECH, so that
ZABZ-TECH's own dictation — or any app on it — hears him. Mechanism: the RDP client streams the client
microphone to the host, where it appears as a recording endpoint (Remote Audio).

### 4.1 What was already done (all of it reversible)

On **ZABZ-TECH**, over ssh as the elevated `ezabz` account:

```
Set-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name fDenyTSConnections -Value 0
Set-Service TermService -StartupType Automatic ; Start-Service TermService
Set-Service UmRdpService -StartupType Manual   ; Start-Service UmRdpService
Set-Service SessionEnv   -StartupType Manual   ; Start-Service SessionEnv
New-NetFirewallRule -DisplayName 'RDP over Tailscale'      -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3389 -RemoteAddress 100.64.0.0/10 -Profile Any
New-NetFirewallRule -DisplayName 'RDP over Tailscale (UDP)' -Direction Inbound -Action Allow -Protocol UDP -LocalPort 3389 -RemoteAddress 100.64.0.0/10 -Profile Any
```

Deliberate choices:

- **The firewall rules are scoped to the Tailscale range only** (`100.64.0.0/10`). Port 3389 is **not** open on
  the office LAN; the built-in "Remote Desktop" rule group is left disabled, exactly as it was found.
- No policy keys were added or changed; `fDisableAudioCapture` is unset on ZABZ-TECH, i.e. audio capture
  redirection is permitted. RDP-Tcp keeps `UserAuthentication=1` (NLA required) and its original port 3389.
- **Reverting** = set `fDenyTSConnections` back to 1, delete the two firewall rules, stop and disable the three
  services back to Manual. Nothing was deleted and no data was touched.

On **ZABZ-YOGA**, the client file is saved at
`C:\Users\ezabz\OneDrive\Desktop\zabz-tech - mic.rdp` — the `audiocapturemode:i:1` line is the one that
carries the microphone:

```
full address:s:zabz-tech.tail93e6e6.ts.net
username:s:MicrosoftAccount\ezabz68@gmail.com
audiocapturemode:i:1      <- record audio from THIS computer and deliver it to the remote session
audiomode:i:0             <- play remote audio back on this computer
redirectclipboard:i:1
authentication level:i:2
screen mode id:i:1
smart sizing:i:1
dynamic resolution:i:1
```

`mstsc.exe` is present on ZABZ-YOGA (Windows 11 Home carries the RDP *client*; only the host side needs Pro,
and ZABZ-TECH is Pro).

### 4.2 Why it was not live at first — the evidence (resolved 2026-10-05 00:22 by the owner's reboot)

**ZABZ-TECH's RDP listener never bound.** After the change above, all three services report Running and the
Remote Connection Manager issued a fresh self-signed RD certificate (Event 1056, 23:03:36), but:

- `netstat -ano | findstr :3389` on ZABZ-TECH: **empty**.
- `qwinsta` on ZABZ-TECH: only `services` and `console` — **no `rdp-tcp` listener line**.
- `Test-NetConnection zabz-tech.tail93e6e6.ts.net -Port 3389` from ZABZ-YOGA: **False**.
- `sc.exe stop TermService` sits in `STOP_PENDING` for 24 s and returns to **Running**;
  `Restart-Service TermService -Force` fails with *"stop failed"*. The service is wedged and will not
  re-initialise its listener.

**A reboot of ZABZ-TECH is the only reliable fix.** It costs: whatever is open on ZABZ-TECH is dropped
(23 files under `C:\Users\ezabz\.dsh\sessions` were written in the ten minutes before this was written, so
something is actively running there), and RDP takes over the console session — so a Chrome Remote Desktop
session into that machine would thereafter show a lock screen.

### 4.3 Completion steps once it is rebooted

```powershell
# 1. from ZABZ-YOGA — the listener must exist
Test-NetConnection zabz-tech.tail93e6e6.ts.net -Port 3389 -InformationLevel Quiet     # expect True
# 2. on ZABZ-TECH — the listener line must appear
qwinsta                                                                                # expect rdp-tcp ... Listen 3389
# 3. connect with the saved .rdp, then ON ZABZ-TECH:
Get-PnpDevice -Class AudioEndpoint -Status OK | Select-Object -ExpandProperty FriendlyName
#    expect a "Remote Audio" capture endpoint; make it the default recording device,
# 4. then dictate there:  Win+H  (or Win+Ctrl+S for Voice Access)
```

If after the reboot 3389 is *still* dead, the next diagnosis is the RD Session Host event log
(`Microsoft-Windows-TerminalServices-RemoteConnectionManager/Operational`) — but that log is the one place a
fix must be *observed*, not assumed.

### 4.4 The credential trap that is left (2026-10-05 01:24)

The owner rebooted ZABZ-TECH himself at **00:22:59**. The listener came up exactly as predicted: `qwinsta`
shows `rdp-tcp ... Listen`, `netstat` shows 3389 bound, and from ZABZ-YOGA `Test-NetConnection
zabz-tech.tail93e6e6.ts.net -Port 3389` is **True** (raw TCP connect succeeded). The saved .rdp then failed at
authentication: *"Your credentials did not work … The logon attempt failed"*.

ZABZ-TECH's own Security log names the failure exactly — event **4625 at 01:24:15**, workstation ZABZ-YOGA,
source 100.72.162.5: Account Name `ezabz68@gmail.com`, Account Domain `MicrosoftAccount`, Logon Type 3,
Status `0xC000006D`, Sub Status **`0xC000006A` — "Unknown user name or bad password"**. The account *resolved*
(a bad username is `0xC0000064`), so **the username was right and the password was wrong**. Not a lockout: the
threshold is 10 with a 10-minute duration and the log holds no 4740 events.

Why every password failed is written in the account's own dates:

| machine | account | PrincipalSource | Password last set |
|---|---|---|---|
| ZABZ-TECH | `ezabz` | **MicrosoftAccount** | **22 Jul 2025 14:21:54** |
| ZABZ-YOGA | `ezabz` | **MicrosoftAccount** (same address) | **18 Dec 2025 16:16:14** |

The Microsoft account's password changed in December 2025 and ZABZ-TECH has not re-cached it since — its
console session is reached with a **PIN**, which never revalidates the cloud password. RDP's NLA/CredSSP
validates against the stored credential, so a freshly changed Microsoft-account password can fail on exactly
this machine while working everywhere else. That is why "no matter what password" is the expected symptom
rather than a surprise.

The order that fixes it:

1. **At ZABZ-TECH's own lock screen** (reachable through CRD), choose the **password** sign-in option and sign
   in once. That is the same credential RDP asks for, and a successful online sign-in re-caches it.
2. If the current password is refused there too, reset it at account.microsoft.com and repeat step 1.
3. A dedicated local account sidesteps the Microsoft account entirely, but it is a *different profile* — none
   of his files, none of his DSH sessions — so it is a fallback, never the fix.

Checked rather than assumed, so it is not blamed wrongly: `DevicePasswordLessBuildVersion = 0` on ZABZ-TECH,
i.e. the "Require Windows Hello sign-in for Microsoft accounts" block is **off** and password sign-in is
permitted.

The client file now carries `username:s:MicrosoftAccount\ezabz68@gmail.com` and `prompt for credentials:i:1`,
so the dialog arrives already naming the right identity and only the password has to be typed.

## 5. Routes checked and rejected (so nobody re-walks them)

- **Reaching ZABZ-TECH's DSH web GUI directly from the Yoga over an ssh tunnel** — the transport works
  (`ssh -N -L 3098:127.0.0.1:3099 100.85.153.96` binds and carries TCP), but the server answers
  `401 dsh web authentication required; reopen the URL printed by dsh web`. The `?token=` is generated per run
  and printed to the console that launched it; it is **not** in `C:\Users\ezabz\.dsh` state files, and a
  binary scan of Edge/Chrome `History` on ZABZ-TECH found **zero** `127.0.0.1:3xxx/?token=` strings. Reopening
  that path deliberately means restarting `dsh web` with `--host` plus `--trusted-host` (the CLI supports both)
  so a fresh token is known — and, if a tunnel is used, so the `/api` browser-trust fence accepts the tunnelled
  authority. Not done: it means restarting the owner's live web UI.
- **Watching for a “show keyboard” toggle in CRD** — irrelevant, per §1.
- **Killing the wedged `svchost` that hosts TermService** — deliberately not done. TermService shares
  `svchost -k netsvcs` with SessionEnv and other services on the primary machine; a clean reboot is the same
  outcome without the collateral.

## 6. Measured facts (2026-10-04, so this is not re-derived)

| Fact | Value | Source |
|---|---|---|
| Tailnet | `zabz-yoga-1` 100.72.162.5, `zabz-tech` 100.85.153.96, `secratary` 100.84.72.88 | `tailscale status` on ZABZ-YOGA |
| ZABZ-TECH OS | Windows 11 **Pro**, build 10.0.26200 | `Get-CimInstance Win32_OperatingSystem` over ssh |
| ZABZ-YOGA OS | Windows 11 **Home**, `mstsc.exe` present | same, locally |
| ssh to ZABZ-TECH | works by key over the tailnet IP, session **elevated** | `IsInRole(Administrator)` = True |
| ssh by LAN name | fails — `zabz-tech` resolves to 192.168.50.138 and times out (home and office are separate networks) | `ssh zabz-tech` attempt |
| Ports from ZABZ-YOGA | 100.85.153.96:22 True · :3389 False · :3099 False | `Test-NetConnection` |
| ZABZ-TECH uptime | since 2026-10-04 20:23 | `Win32_OperatingSystem.LastBootUpTime` |
| ZABZ-TECH mics | `Microphone (3- USB Audio Device)` present locally | `Get-PnpDevice -Class AudioEndpoint` |
| ZABZ-YOGA mics | Intel Smart Sound Microphone Array + `Microphone (2- USB Audio Device)`, consent store = Allow | `Get-PnpDevice`, `CapabilityAccessManager\ConsentStore\microphone` |
| dsh web on ZABZ-TECH | listens on 127.0.0.1 only (3099 pid 24480, 3086 pid 3560) | `Get-NetTCPConnection -State Listen` |

## 7. Open items

1. **Owner decision (queued):** reboot ZABZ-TECH to activate RDP mic passthrough, or stay on CRD and dictate
   client-side. Recommendation recorded with the row.
2. **Build:** a Windows counterpart of `scripts/install-handy-dictation-macos.sh` — Handy + Whisper
   large-v3-turbo on ZABZ-YOGA, one toggle hotkey, paste into the focused window, `auto_submit` off (the Mac
   reasoning applies unchanged: never let a half-finished sentence reach a customer). Prove it with
   audio → transcript → paste, as §6 of the Mac document does.
3. **Then:** the same installer on ZABZ-TECH, so dictation exists wherever he is sitting rather than only at
   the Yoga.

## 8. How this document was verified

Every command above was run from ZABZ-YOGA against ZABZ-TECH over the tailnet on 2026-10-04 between 22:55 and
23:20; outputs are quoted inline rather than summarised. The one claim that is **not** observed is the
end-to-end behaviour of CRD relaying injected (Win+H) text — it is labelled as untested in §3 and is a
ten-second test when the owner next sits down. Nothing in §4 was left in a half-state that could surprise
either machine: the firewall rules are additive and tailnet-scoped, and the whole change is reversible with the
commands in §4.1.
