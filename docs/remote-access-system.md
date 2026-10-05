# The remote-access system — READ THIS FIRST

**Status:** paused at the owner's request (2026-10-05 03:10 local). Nothing here needs attention unless the
desktop stops answering; every component below is deployed and running.
**Stack:** ZABZ-YOGA (home, Windows 11 Home, T-Mobile home internet behind carrier-grade NAT) ↔ ZABZ-TECH
(office, Windows 11 Pro, NVIDIA T1000, 3840x2160 console) — reachable from each other only over Tailscale
(`tail93e6e6.ts.net`), measured as a **direct** path at ~30–50 ms most of the time.
**Detail documents:** [`remote-access-link-robustness.md`](remote-access-link-robustness.md) §1–§10 (every
measurement, round by round) · [`talk-to-text-across-remote-desktop.md`](talk-to-text-across-remote-desktop.md)
(the mic/dictation workstream, which is separate and still open) · [`mesh/130-child-program-one-line.md`](mesh/130-child-program-one-line.md)
(the mesh fan-out fix, committed `e35d1237`, waiting on an engine restart to take effect).

---

## 1. The map — what runs where

| Component | Lives on | Runs | What it does |
|---|---|---|---|
| `Documents\Default.rdp` | Yoga | read by every launch | The settings: full screen, 32 bpp, `desktopscalefactor:i:150` with **`dynamic resolution:i:0`** (with it at 1 the client re-requests the native 3840x2160 and the scale factor is ignored), mic redirected, TCP-only transport |
| **`ZABZ-TECH (RDP + mic).lnk`** | Yoga Desktop + Start Menu | **Ctrl+Alt+Z** | Runs **`mstsc /v:<host>`** — *not* the `.rdp` file, because since the **April 2026 cumulative updates** opening a saved `.rdp` shows the "Caution: Unknown remote connection" warning **every time** and makes you re-tick clipboard/mic. With `/v:` there is no warning ([source](https://woshub.com/security-warnings-opening-rdp-files-windows/)) |
| **`ZABZ-TECH session (auto-reconnect).lnk`** | Yoga Desktop + Start Menu | **Ctrl+Alt+K** | Connect, and **re-open the session after a drop**; closes the failure dialog itself when the link is down (every step logged) |
| **`ZABZ-TECH link status.lnk`** | Yoga Desktop + Start Menu | **Ctrl+Alt+L** | Says whether the link is usable *before* you try: path, round trip, 3389 reachable, plain verdict |
| `scripts/rdp-session.ps1` | Yoga `~/.dsh/tools` | via Ctrl+Alt+K | The wrapper above |
| `scripts/rdp-link-status.ps1` | Yoga `~/.dsh/tools` | via Ctrl+Alt+L | The status tool above |
| `scripts/link-probe.ps1` | Yoga `~/.dsh/tools` | task **`Zabz link probe`**, every 10 min | 5 samples, 30 s apart: path, rtt, 3389, **whether this side's internet is up**, and a second tailnet node |
| `scripts/link-keepwarm.ps1` | Yoga `~/.dsh/tools` | task `Zabz link keepwarm` — **disabled on purpose** | A once-a-minute ping. It was credited with restoring a direct path and then suspected of *causing* path flapping; neither was proven, so it is off and the probe above measures instead |
| `scripts/rdp-health.ps1` | ZABZ-TECH `~\.dsh\tools` | task **`Zabz RDP health`**, every 2 min, SYSTEM | Services, listener (`qwinsta` + 3389), Tailscale path, and every session event **translated**: it repairs the wedged-listener state in place and can never drop a live session |
| `scripts/Enforce-RdpPolicies.ps1` | ZABZ-TECH `~\.dsh\tools` | task **`Zabz RDP policy`**, every 5 min, SYSTEM | Re-applies the three RDP policy values and **logs every re-application** (see §2 — they have vanished twice unexplained) |
| `scripts/mesh-node-health.ps1` | ZABZ-TECH `~\.dsh\tools` | task **`Zabz mesh node health`**, every 10 min, as ezabz | Enforces the rule that `$DSH_HOME\profiles\node_modules` must **not** be a link (that single junction cost the mesh a whole night), and reports any other untraversable profile link |
| Desktop `.rdp`/shortcuts | Yoga Desktop | — | Also present: `zabz-tech - mic.rdp` (the file the shortcuts point at) |

**Host settings that make the above work** (all verified live on 2026-10-05 03:05):

| Setting | Value | Why |
|---|---|---|
| `SelectTransport` | `1` (TCP only) | the tailnet path changes under this link and RDP-UDP dies when it changes |
| `AVC444ModePreferred` | `0` | AVC444 is a lossy **video** codec: it made text unsharp and its pipeline logged `0x80004005` where sessions died |
| `AVCHardwareEncodePreferred` | `0` | keeps the T1000's H.264 encoder out of the text path |
| firewall `RDP over Tailscale` | enabled, remote `100.64.0.0/10` | 3389 is reachable from the tailnet and **not** from the office LAN |
| `MaxDisconnectionTime` / `MaxIdleTime` | `0` / `0` | a dropped session is **retained**: a reconnect returns to the same desktop with everything still running |
| `KeepAliveEnable` / `KeepAliveInterval` | `1` / `1` min | idle NAT mappings do not expire mid-session |
| sleep / hibernate / disk AC timeout | never | a sleeping host is an outage |
| `HiberbootEnabled` | `0` | Fast Startup off |
| `NoAutoRebootWithLoggedOnUsers` | `1` | Windows Update must not reboot under a live session |

## 2. Invariants, and the one command that checks each

```powershell
# the door itself (from the Yoga)
tailscale ping -c 1 zabz-tech ; Test-NetConnection zabz-tech.tail93e6e6.ts.net -Port 3389 -InformationLevel Quiet
# the listener on the desktop, and the remote-access trail in one line each
ssh 100.85.153.96 "powershell -NoProfile -Command \"qwinsta; Get-Content C:\Users\ezabz\.dsh\logs\rdp-health.log -Tail 5\""
# the three enforced policies
ssh 100.85.153.96 "reg query \"HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services\" /v SelectTransport"
# the rule the mesh depends on: profiles\node_modules must be a DIRECTORY, never a junction
ssh 100.85.153.96 "cmd /c dir /a C:\Users\ezabz\.dsh\profiles | findstr node_modules"
```

Expected: `direct` or `RELAY` (both work), `True`, `rdp-tcp … Listen`, `SelectTransport REG_DWORD 0x1`,
`<DIR> node_modules`.

## 3. Runbook — "the desktop is not answering / it froze / the text looks wrong"

1. **Ctrl+Alt+L** first: it separates "not reachable" from "reachable but the session is unhappy", which no
   RDP error dialog will tell you (they all say *"possibly due to network connectivity problems"*).
2. Read the desktop's trail — `~\.dsh\logs\rdp-health.log` on ZABZ-TECH. It translates every session event:

| Code / id | Meaning | What it means here |
|---|---|---|
| `reason code 5` | another connection took the session | the single-session rule: RDP, Chrome Remote Desktop, AnyDesk, TeamViewer and the console share **one** session on a client Windows. Retry once; do not run two doors at once |
| `reason code 12` | user logged off | a session ended deliberately |
| `2147942464` | `0x80070040 ERROR_NETNAME_DELETED` | the network path went away (carrier re-mapping) |
| `2147942521` | `0x80070039` | the client's transport broke abruptly |
| `RdpCoreTS id=67 … (0x80004005)` | the RemoteFX graphics pipeline failed | this is what the freezes were; `AVC444ModePreferred=0` addresses it |
| `RdpCoreTS id=162 … Initial profile: N` | graphics profile negotiated | **2 = AVC444** (bad for text). After the 03:00 change it should not be 2 |
| `RdpCoreTS id=168 … resolution requested` | session geometry | should be near 2560x1440, not 3840x2160 |
| `path=UNREACHABLE` in the trail | the tailnet path to the Yoga is gone | carrier-side; the client probe on the Yoga says whether *its* internet was up |
| a **popup every half minute** while connected | almost always a **relaunch loop**, not Windows: something is opening a new session repeatedly, and each launch evicts the last (`reason code 5`). Check `~\.dsh\logs\rdp-session.log` on the Yoga for attempts seconds apart, and confirm the `.rdp` file is not being opened directly (the April-2026 redirection warning needs a click every launch; `/v:` avoids it) |

3. **`Zabz link probe`'s log** (`~\.dsh\logs\link-probe.log` on the Yoga) is the other half: `internet=False`
   means this side is offline; `internet=True` with `tcp3389=False` means the office side or the path.
4. If the listener is missing while the services look fine, the 2-minute watchdog normally repairs it in
   place. If it logs `RDP LISTENER MISSING … needs a reboot`, that is a real reboot, and it has happened once.
5. If the policy values have disappeared again, `~\.dsh\logs\rdp-policy.log` on the desktop records every
   re-application — read it before assuming the setting is gone.

## 4. What actually went wrong, in order (so it is never re-litigated)

| Symptom | Real cause | Where the evidence is |
|---|---|---|
| "credentials did not work, whatever password I try" | the account on the desktop is a **Microsoft account** whose cached password was from 22 Jul 2025 while the same account on the Yoga was last set 18 Dec 2025 — the cloud password changed and the desktop never re-cached it. RDP pre-auth validates the **stored** copy | robustness §4.4, event 4625 substatus `0xC000006A` |
| "it took a few tries" / "session is in use" | **one interactive session per client Windows**; the console session (held by CRD) must be evicted first | §3, `reason code 5` |
| "connection lost a few times" | the **carrier-grade NAT path** re-maps: `ERROR_NETNAME_DELETED`, path flapping direct↔relay, one `UNREACHABLE` blip | §1, §9, §10, both probe logs |
| "fonts look funny, not sharp" | the session ran **AVC444** — a lossy, chroma-subsampled *video* codec — on an 8.3 MP desktop | §10, `id=162 profile 2` |
| "froze, then crashed" | the **RemoteFX graphics pipeline erroring** (`0x80004005`) under that load | §10, `id=67` |
| the mesh lost every child for a night | a **junction** at `$DSH_HOME\profiles\node_modules` (untrusted mount point) plus a **multi-line program eaten from the shared stdin pipe** | `mesh/130`, pains P2826/P2835 resolved |

## 5. Deliberately NOT done, with the reason (do not re-open without new evidence)

- **Multi-monitor RDP** (`use multimon:i:1`): needs uniform DPI across client monitors; this client is 150 %
  and 200 % mixed.
- **RDP over UDP**: measured to die on this link's path changes; the client also has `fClientDisableUDP=1`.
- **Disabling Chrome Remote Desktop on the desktop**: it is the owner's reach-it-from-anywhere door. The cost
  is the single-session rule, documented in §3.
- **Forcing the DERP relay** (which would be more stable than a flapping direct path): Tailscale has no
  supported per-peer knob for that.
- **Auto-retry wrapper**: refused in round one because the failure dialog is modal — then built as
  **Ctrl+Alt+K**, because closing that dialog is safe when the link is *down* (the normal "connecting" window
  shares its title, so the rule is conditional).

## 6. Open items

1. **Engine restart** to load the mesh fan-out fix — kills live sessions, so it is the owner's timing. Until
   then, `subagent` from an already-running engine behaves as before. **The fix is two commits on two
   branches:** `e35d1237` (the transport: the child program is delivered as one base64 launcher line, so
   PowerShell cannot lose the unread tail of a multi-line program to the child's stdin — `land/mesh-one-line-program`)
   and `abfff255` (a second session's follow-on: a child that loses its completion frame is now a failure to
   the broker rather than a success, with a `repro-mesh-dispatch.mjs` — `fix/mesh-provider-dispatch`). The
   second explicitly builds on the first, so they must land **together**.
2. **Owner queue #277** — buy Windows 11 Pro for the Yoga so control works identically in both directions
   (the desktop → Yoga direction is Chrome Remote Desktop today, which does not lock that screen).
3. **Owner queue #262** — reboot timing / the microphone route (RDP `audiocapturemode` is prepared; the
   credential step is outstanding).
4. **Dictation on the Yoga** (Handy + local Whisper, one hotkey) — separate doc, still the next build.
5. **`personal-secretary-mvp\.venv\Scripts\python.exe` on ZABZ-TECH cannot be launched**
   (`The file cannot be accessed by the system`) though it exists with full ACLs; every mesh child pays ~1–2 s
   and a wall of errors for it. Unexplained.
6. **The three RDP policy values vanished twice with no explanation** — the local GPO is innocent and
   `gpupdate /force` does not reproduce it. Now enforced every 5 minutes and logged, so the next occurrence is
   a line in a log rather than a mystery freeze.

## 7. This workstream in the journal (one line each)

`H3164` setup + wedged listener · `H3185` credential trap · `H3186` RDP chosen + one-click shortcut · `H3187`
full screen + why Maximize did not fill · `H3188` the mesh was unusable that night · `H3209` keep-warm
credited with restoring a direct path · `H3213`/`H3214` the 02:30 drop explained · `H3215` correction: the
keep-warm was not proven to cause the flapping · `H3219` the Ctrl+Alt+L tool died on an encoding trap ·
`H3221` AVC444 + 8.3 MP session + policy enforcement · lessons `L3270` (CRD carries no microphone), `L3315`
(reason codes, CGNAT, repairs that only touch broken state), `L3319` (one-line child program), `L3322`
(PS 5.1 + no BOM + non-ASCII = silent death).

## 8. Redeploying what is here

Every script above is committed under `harness-config/scripts/`, and the deployed copies were verified
byte-for-byte against those files (hash-checked 2026-10-05). To move one to a machine:

```powershell
scp scripts/rdp-health.ps1 100.85.153.96:C:/Users/ezabz/.dsh/tools/rdp-health.ps1     # desktop scripts
Copy-Item scripts/rdp-session.ps1 "$env:USERPROFILE\.dsh\tools\" -Force               # laptop scripts
# then re-register its task exactly as §1 names it (SYSTEM for the desktop watchdogs,
# the user for the laptop probe), and run it once to prove LastTaskResult 0.
```

**Two rules for anything added here, both paid for on 2026-10-05:** a script that Windows PowerShell 5.1
executes must be **ASCII-only and written with a BOM** (one em dash inside a string, in a BOM-less file, killed
a whole tool silently behind a hidden window — `L3322`), and a watchdog's paths must be **absolute** if it runs
as SYSTEM (there, `$env:USERPROFILE` is the system profile, i.e. a log nobody will ever read).
