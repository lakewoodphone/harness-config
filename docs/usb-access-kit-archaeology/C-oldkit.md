# USB archaeology — the OLD LPT/CopilotSshAccess kit, how it got a shell, and what the new kit does differently

Written 2026-10-15 on **ZABZ-TECH** (desktop, Windows). Read-only pass: nothing was run from the
stick, no service was touched, no host was changed. Everything below is quoted from a file I actually
read, with the path and the commit sha (or, for uncommitted files, the mtime+machine) it came from.

---

## 0. Where the old generation actually lives

The task's list of names is **one kit in two halves plus one earlier generation**. All of it is in
`C:\Users\ezabz\Code\personal-secretary-mvp`, and the whole of "CopilotSshAccess" is the folder name the
kit created **on the USB stick**, not a repo directory:

| | Generation A | Generation B ("v2") | Generation C (diagnostics half) |
|---|---|---|---|
| repo path | `scripts/windows/` | `scripts/copilot-ssh-field-kit/` | `tools/lpt-diagnostics-kit/` |
| added | `7775e17e` 2026-05-21 | `e1538fdb` 2026-07-05, `d7cd4ecf` 2026-07-07 | `c34588e1` 2026-09-02 |
| later edits | — | `f8f7dd93` 2026-08-11, `99f7134d` 2026-10-05 | — |
| main file | `Install-CopilotSshAccess.ps1` (240 lines) | `Install-CopilotSshAccess.ps1` (717 lines, 41 017 B) | `Run-LptDiagnostics.ps1` |
| USB folder | `D:\CopilotSshAccess\` | `D:\CopilotSshAccess\` | same stick, other folder |
| key auth | key in both key files | key in both key files + reverse key | none (self-contained) |

The exact names in the brief map like this:

* `Collect-PcDiagnostics.ps1` → `scripts/copilot-ssh-field-kit/Collect-PcDiagnostics.ps1` (20 354 B, added `d7cd4ecf`); a `Collect-PcDiagnostics.cmd` sits beside it. It writes `$usbDrive\CopilotSshAccess\diagnostics-$stamp-$hostname`.
* `Enable-ShopSsh.ps1` → `scripts/copilot-ssh-field-kit/Enable-ShopSsh.ps1`. **Two content revisions exist**: `d7cd4ecf` (14 795 B) and `99f7134d` (15 289 B). The laptop has a third byte-size (15 081 B).
* `Disable-Techloq.ps1` → `scripts/copilot-ssh-field-kit/Disable-Techloq.ps1` (2 218 B), with `Enable-Techloq.ps1` as its partner.
* `CopilotSshAccess (a folder)` → the USB folder `D:\CopilotSshAccess\` (see the transcript on line 8 of the log quoted in §2: `... -File D:\CopilotSshAccess\Install-CopilotSshAccess.ps1 ...`), plus `%ProgramData%\CopilotSshAccess\` on the target, plus `scripts\windows\Export-CopilotSshAccessUsb.ps1` which creates it (`$Destination = Join-Path $removable.DeviceID "CopilotSshAccess"`).
* `tools/lpt-diagnostics-kit` → present, 8 files, the diagnostics half only ("self-contained (no keys, no install)" — `REMOTE-ACCESS.md:64-66`).

**The kit was retired on 2026-10-05.** `scripts/copilot-ssh-field-kit/MOVED.md` was added by
`f3d52ad8` (2026-10-05 13:44) and later deleted from the working tree; its content is the index to
everything here:

> `# MOVED - this is no longer a source of truth`
> `**As of 2026-10-05, the laptop access + diagnostics kit lives in ONE place:**` `tools/lpt-access-kit/`
> …
> `| Install-CopilotSshAccess.ps1 | lpt-access-kit\transport\T1-LanSsh.ps1 (+ T2/T3 by tier) |`
> `| Enable-ShopSsh.ps1 | lpt-access-kit\transport\T1-LanSsh.ps1 |`
> `| Disable-Techloq.ps1 / Enable-Techloq.ps1 | **not replaced** - the filter is routed around by tier, never disabled |`
>
> — `git show f3d52ad8:scripts/copilot-ssh-field-kit/MOVED.md`

`MOVED.md` is also the only place that records **the stick was ahead of the repo**, which is why the
biggest copies are not in git:

> `- **The stick was ahead of the repo** for two files (`Collect-PcDiagnostics.ps1` 25,727 B on the stick vs 20,354 B in the repo; `Enable-ShopSsh.ps1` 29,802 vs 15,081), which is the opposite of a source of truth.`

---

## 1. The one run that PROVES the old kit worked

The stick's own `LPT-Runs` no longer holds an old-kit run (§5), but **the desktop's repo working tree
still holds the uncommitted output of one**, and it is a green run:

```
C:\Users\ezabz\Code\personal-secretary-mvp\scripts\copilot-ssh-field-kit\latest-run\
    (untracked — not in any commit; files mtime 2026-07-04 23:22–23:40, machine MIRIAM)
```

`latest-run\CopilotAccess.txt` (514 B, 2026-07-04 23:37:04) — the operator handoff, verbatim:

```
CopilotSshAccess handoff
generated=2026-07-04 23:37:01
status=REVERSE_TUNNEL_ACTIVE
hostname=MIRIAM
user=Miriam
sshd=Running
port22_listening=True
ip=192.168.50.239 interface=Wi-Fi gateway=192.168.50.1
direct_ssh=ssh Miriam@192.168.50.239
reverse_ssh=ssh -p 2222 Miriam@127.0.0.1
reverse_host=192.168.50.138
reverse_port=2222
reverse_runner_pid=5008
reverse_log_dir=C:\ProgramData\CopilotSshAccess\runs\20260704-233346-MIRIAM\tunnel
run_dir=D:\CopilotSshAccess\runs\20260704-233346-MIRIAM
problems=0
```

`latest-run\CopilotSshAccess.log` (the PowerShell transcript, 4 871 B) — the window OPEN, in the kit's
own words:

```
Start time: 20260704233346
Username: Miriam\Miriam        Machine: MIRIAM (Microsoft Windows NT 10.0.22000.0)
Host Application: C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe -NoExit -NoProfile -ExecutionPolicy Bypass -File D:\CopilotSshAccess\Install-CopilotSshAccess.ps1 -AuthorizedKey ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIABBFsFNMrp8GKz+log6KofDriGvoyBuX9rVOoDusjRq ezabz@zabz-tech -KeyDir D:\CopilotSshAccess\keys -ReverseTunnelPort 2222 -ReverseTunnelVerifySeconds 30 -KeepAliveMinutes 180 -NoElevate
...
== 2. OpenSSH Server ==
[OK]   sshd running (Automatic)
== 3. OpenSSH policy ==
[OK]   sshd_config patched and validated
== 4. Authorized keys ==
[OK]   Reverse key added to user and admin authorized_keys
[OK]   User key:  C:\Users\miria\.ssh\authorized_keys
[OK]   Admin key: C:\ProgramData\ssh\administrators_authorized_keys
...
== 5. Firewall ==
[OK]   Profile Private: Phone & Tech
[OK]   TCP/22 Any profile Any remote
[OK]   sshd.exe rule
[OK]   netsh fallback
== 6. Restart sshd ==
[OK]   sshd: Running
[OK]   TCP/22 LISTENING
...
== 10. Reverse SSH tunnel (fallback) ==
  Testing SSH key auth to 192.168.50.138:22...
[OK]   SSH key auth OK to 192.168.50.138
  Desktop reachable at 192.168.50.138. Opening reverse tunnel on port 2222...
[OK]   REVERSE TUNNEL ACTIVE to 192.168.50.138:2222
[OK]   Copilot can connect: ssh -p 2222 Miriam@127.0.0.1
== 11. Writing handoff ==
[OK]   Handoff written
```

`latest-run\reverse_tunnel_check.txt` and the tail of `CopilotAccess.json` show the listener on the
desktop side, i.e. the channel the operator would use:

```
"attempt desktop=192.168.50.138 port=2222 listener=[  TCP    127.0.0.1:2222         0.0.0.0:0              LISTENING\r\n]"
```

and `CopilotAccess.json` carries:

```
"reverse_tunnel_active":  true,
"reverse_tunnel_host":  "192.168.50.138",
"reverse_tunnel_port":  2222,
"reverse_connect_command":  "ssh -p 2222 Miriam@127.0.0.1"
```

Same file, the reverse-key auth test from the target out to the desktop — a genuine successful login
(`AUTH_OK` is the remote command output):

```
debug1: Authenticating to 192.168.50.138:22 as 'ezabz'
debug1: Offering public key: C:\Users\miria\.ssh\copilot_reverse_ed25519 ED25519 SHA256:i2LF1ydG5/VNY4Ln9sFganJPDhojKUL9H10RFaJwMS8 explicit
debug1: Server accepts key: ...
debug1: Authentication succeeded (publickey).
debug1: Sending command: echo AUTH_OK; hostname
AUTH_OK
zabz-tech
debug1: Exit status 0
```

**One honest caveat about "staff used it".** The same run's *functional* check of the reverse path
failed, and the kit recorded it rather than hiding it:

```
functional=[ssh : Miriam@127.0.0.1: Permission denied (publickey,keyboard-interactive).]
```

and `latest-run\techloq_ssh_self_connect_test.txt` shows the target could not ssh into *itself* as
`Miriam` either. Both failures are the same thing: those probes presented **no key**, while the only
authorised key on the target was the desktop's `ezabz@zabz-tech`. So this run proves
**sshd Running + TCP/22 LISTENING + firewall open + key installed with correct ACLs + a live reverse
listener on the desktop** — the window — but it does not itself contain a log line of the operator
logging *into* Miriam. I could not find such a line anywhere (§6).

---

## 2. The seven questions, answered with the code

### Q1 — sshd on a NON-default port? No. The old kit never wrote a Port directive.

This is the single most important correction to the premise. **The old kit left sshd on port 22, the
default, on purpose.** Proof, in three independent files:

**(a) The config it produced.** `latest-run\sshd_config.after` (2026-07-04, MIRIAM), first six lines —
the whole managed block, and there is no `Port` in it:

```
# >>> CopilotSshAccess
PubkeyAuthentication yes
AuthorizedKeysFile C:\ProgramData\ssh\administrators_authorized_keys
PasswordAuthentication no
PermitEmptyPasswords no
# <<< CopilotSshAccess
```

Line 28 of the same file is still `#Port 22` — commented out, i.e. sshd obeyed its built-in default.
`sshd_config.before` differs only by having no `AuthorizedKeysFile` line, so **the port was never
touched at any point in the run.**

**(b) The code that writes it.** `scripts/copilot-ssh-field-kit/Install-CopilotSshAccess.ps1:361-371`
(working tree = commit `f8f7dd93`, 2026-08-11):

```powershell
        $managed = @(
            "# >>> CopilotSshAccess",
            "PubkeyAuthentication yes",
            "AuthorizedKeysFile C:\ProgramData\ssh\administrators_authorized_keys",
            "PasswordAuthentication no",
            "PermitEmptyPasswords no",
            "AllowUsers $script:OriginalUser",
            "# <<< CopilotSshAccess",
            ""
        )
        Set-Content $cfg -Value ($managed + $out) -Encoding ascii
```

No `Port`. The only `Port 22` literals in the whole file are inside the "there is no sshd_config at
all, so invent one" template at `:320` and `:334`:

```powershell
# OpenSSH Server configuration - generated by CopilotSshAccess
Port 22
Subsystem sftp sftp-server.exe
```

(c) The same holds for the other revision. `scripts/copilot-ssh-field-kit/Enable-ShopSsh.ps1:26-29`,
`:171` — `$SSHPort = 22` and then it **overwrites** `sshd_config` from scratch:

```powershell
$TempUser      = "repairtech"
$SSHPort       = 22
...
$desiredConfig = @"
# OpenSSH Server configuration for shop access
Port 22
PasswordAuthentication yes
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
PermitEmptyPasswords no
"@
$desiredConfig | Set-Content $sshdConfig -Encoding ASCII -Force
```

**So where did a non-default port come from?** From the old kit's *fallback* leg, and it is a port on the
**desktop**, not on the target's sshd. `Install-CopilotSshAccess.ps1:137-142`:

```powershell
# Pick dynamic reverse tunnel port if not specified (avoids conflicts with stale tunnels)
if ($ReverseTunnelPort -eq 0) {
    $script:ReverseTunnelPort = 2200 + (Get-Random -Minimum 1 -Maximum 100)
} else {
    $script:ReverseTunnelPort = $ReverseTunnelPort
}
```

and `latest-run\reverse-tunnel-runner.ps1`:

```powershell
$DesktopHost = '192.168.50.138'
$Port = 2222
...
$reverseArg = "127.0.0.1:" + $Port + ":127.0.0.1:22"
& $SshExe -vv -T -i $KeyPath ... -N -R $reverseArg "ezabz@$DesktopHost"
```

**Did it edit `%ProgramData%\ssh\sshd_config`?** Yes — that exact file, in place, with two backups:
`Copy-Item $cfg (Join-Path $RunDir "sshd_config.before")` and `Copy-Item $cfg "$cfg.copilot-backup"`
(`:341-343`). **Not** a separate config file, **not** `sshd -f` for serving (it used `sshd.exe -t -f $cfg`
only to *validate*), and **not** a port forward for the sshd port.

**Restart or start?** Both, and the restart is the one that mattered. `:290-296` starts it if not
running, then `:470-474` does the forced restart *after* the config edit and then proves the listener:

```powershell
try { Restart-Service sshd -Force -ErrorAction Stop; Start-Sleep 3; Write-Ok "sshd: $(Get-SafeServiceStatus 'sshd')" } catch { Write-WarnLine "Restart: $_" }
$port22ok = $false
try { if (netstat -an 2>$null | Select-String "0\.0\.0\.0:22\s+.*LISTEN|:::22") { Write-Ok "TCP/22 LISTENING"; $port22ok = $true } else { Write-FailLine "TCP/22 NOT LISTENING"; Add-Problem "critical" "TCP/22 not listening" } } catch { Write-WarnLine "netstat: $_" }
```

Generation A did the same with `Restart-Service -Name sshd -Force` (`7775e17e`, line 212).

**This is exactly the defect the new kit shipped with.** `T1-LanSsh.ps1` inherited
"start only if not running" and therefore installed a window on a port nothing listened on. Its own
comment, in
`C:\Users\ezabz\Code\_worktrees\usb-access-kit\tools\lpt-access-kit\transport\T1-LanSsh.ps1:610-617`:

```powershell
    # hour earlier is what proved it: the patched sshd_config on disk DID contain "Port 54563" (the run
    # folder's own sshd_config.after shows it), and sshd was reported Running - listening on [22, 22]. This
    # line used to be `if ($svc.Status -ne 'Running') { Start-Service }`, so a service that was ALREADY
    # running was left alone, and sshd does not re-read sshd_config because the file changed. The window was
    # therefore installed on a port nothing was listening on, every time, while the config looked right.
    # A restart is what makes "the sshd_config edit took effect" true instead of assumed.
    if ($svc.Status -eq 'Running') { Restart-Service -Name 'sshd' -Force -ErrorAction Stop }
    else { Start-Service -Name 'sshd' -ErrorAction Stop }
```

---

### Q2 — Did it require OpenSSH Server, install it, or ship its own?

It **required or installed** the one Windows supplies; **it never shipped its own sshd**.

Generation A had exactly one route (`7775e17e`, `scripts/windows/Install-CopilotSshAccess.ps1:80-91`):

```powershell
  $service = Get-Service -Name sshd -ErrorAction SilentlyContinue
  if (-not $service) {
    $capability = Get-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
    if ($capability.State -ne "Installed") {
      Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
    }
  }
  Set-Service -Name sshd -StartupType Automatic
  if ((Get-Service -Name sshd).Status -ne "Running") { Start-Service -Name sshd }
```

Generation B has a 3-tier ladder, and `README.txt:34` describes it as *"3-tier fallback
(Add-WindowsCapability, DISM, register existing)"* — **the code's order is the opposite, and that
matters offline.** `Enable-ShopSsh.ps1:64-125`:

```powershell
# Try 1: Register existing binaries (fastest, works offline)
    $sshdExe = Join-Path $env:WINDIR "System32\OpenSSH\sshd.exe"
    if (Test-Path $sshdExe) {
        $null = & sc.exe create sshd binPath="$sshdExe" start=auto 2>&1
...
# Try 2: DISM (works offline from local sources, no Windows Update needed)
    $job = Start-Job { dism /online /Add-Capability /CapabilityName:OpenSSH.Server~~~~0.0.1.0 /Quiet /NoRestart /LimitAccess 2>&1 }
...
# Try 3: Add-WindowsCapability (needs Windows Update - last resort, short timeout)
    $job = Start-Job { Add-WindowsCapability -Online -Name "OpenSSH.Server~~~~0.0.1.0" 2>&1 }
```

`Install-CopilotSshAccess.ps1:222-285` runs the ladder in the *documented* order instead —
Add-WindowsCapability (gated on `Test-Connection -ComputerName 8.8.8.8`), then `dism /online /Add-Capability
/CapabilityName:OpenSSH.Server~~~~0.0.1.0 /Quiet /NoRestart`, then `sc.exe create sshd binPath="$sshdExe"
start=auto`. Both always point at `%WINDIR%\System32\OpenSSH\sshd.exe`. **No `OpenSSH-Win64.zip`, no
`vendor\` folder anywhere in either old kit.**

The other half of "Windows has no server by default" is that a default OpenSSH session lands in
`cmd.exe`. Both generations fixed it — `Install-CopilotSshAccess.ps1:302-305`:

```powershell
    $psExe = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
    New-Item "HKLM:\SOFTWARE\OpenSSH" -Force -ErrorAction SilentlyContinue | Out-Null
    New-ItemProperty "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell -Value $psExe -PropertyType String -Force -ErrorAction SilentlyContinue | Out-Null
```

and the MIRIAM log confirms it took: `[OK] DefaultShell = C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe`.

---

### Q3 — How was the key authorised? What comment? How did removal find it?

**Both files, always.** `Install-CopilotSshAccess.ps1:424-447`:

```powershell
    $userKey  = Join-Path $userProfile ".ssh\authorized_keys"
    $adminKey = Join-Path $env:ProgramData "ssh\administrators_authorized_keys"
    $sshDir   = Split-Path $userKey -Parent

    # Add keys to both files
    Add-AuthKey $userKey  $AuthorizedKey
    Add-AuthKey $adminKey $AuthorizedKey

    # Add reverse key to both files
    $reversePubPath = Join-Path $KeyDir "copilot_reverse_ed25519.pub"
    if (Test-Path $reversePubPath) {
        $reversePub = (Get-Content $reversePubPath -Raw).Trim()
        Add-AuthKey $userKey  $reversePub
        Add-AuthKey $adminKey $reversePub
...
    Set-StrictAcl $sshDir @("*${sid}:(OI)(CI)(F)", "*S-1-5-18:(OI)(CI)(F)")
    Set-StrictAcl $userKey @("*${sid}:F", "*S-1-5-18:F")
    Set-StrictAcl $adminKey @("*S-1-5-32-544:F", "*S-1-5-18:F")
```

and the ACLs really landed — `latest-run\authorized_keys_acl.txt`:

```
C:\Users\miria\.ssh\authorized_keys NT AUTHORITY\SYSTEM:(F)
                                    Miriam\Miriam:(F)
C:\ProgramData\ssh\administrators_authorized_keys NT AUTHORITY\SYSTEM:(F)
                                                  BUILTIN\Administrators:(F)
```

`AuthorizedKeysFile` was **forced to the absolute admin path**, because the shipped default's
`__PROGRAMDATA__` token is not understood by OpenSSH 8.1, and the `Match Group administrators` block was
stripped first (`:350-364`):

```powershell
            # Remove Match Group administrators blocks (breaks auth on OpenSSH 8.1, Issue #1948)
...
            # Remove orphaned AuthorizedKeysFile lines
            if ($ln -match '^\s*AuthorizedKeysFile\s+__PROGRAMDATA__') { continue }
...
        # CRITICAL: Set AuthorizedKeysFile to admin file with ABSOLUTE path
        # (__PROGRAMDATA__ token not supported on OpenSSH 8.1)
...
            "AuthorizedKeysFile C:\ProgramData\ssh\administrators_authorized_keys",
```

Note it **did not use a `Match` block** of its own — it deliberately deleted the one that exists.
Generation A instead set the *user-level* file (`7775e17e` line 142:
`"AuthorizedKeysFile .ssh/authorized_keys"`), which is precisely what the later RCA
(`docs/research/directives/024-copilot-ssh-field-kit-root-cause-analysis.md`, added `d7cd4ecf`) flagged:
*"`ezabz` is an admin user — Windows OpenSSH checks admin file first for admin users"*.

**The comment.** Two keys were installed, each with its own trailing comment:

* the desktop access key, default parameter `Install-CopilotSshAccess.ps1:9` and `7775e17e:16`:
  `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIABBFsFNMrp8GKz+log6KofDriGvoyBuX9rVOoDusjRq ezabz@zabz-tech`
* the reverse-tunnel key, `scripts/copilot-ssh-field-kit/keys/copilot_reverse_ed25519.pub` verbatim:
  `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFkXWqzlJTj9YW3rai/Y6b9Kvwib7ajZi3NP6+ETTajd copilot-usb-reverse-2026-05-29`

A third comment is recorded only in `MOVED.md`, and it is a security finding, not a mechanism:

> `- A **private SSH key** (`ssh-key`, comment `ezabz-customer-access`) and the **shop WiFi password in clear** (`wifi-info.txt`) sat in this folder's USB copy, on a stick that travels to customer premises.`

**How did removal find it again? It didn't — there was no removal.** The only key-touching function is
`Install-CopilotSshAccess.ps1:385-390`, and it is an *add-if-absent* keyed on the whole key string:

```powershell
    function Add-AuthKey([string]$path, [string]$key) {
        New-Item -ItemType Directory -Force (Split-Path $path) -ErrorAction SilentlyContinue | Out-Null
        if (-not (Test-Path $path)) { New-Item -ItemType File -Force $path -ErrorAction SilentlyContinue | Out-Null }
        $cur = Get-Content $path -Raw -ErrorAction SilentlyContinue
        if (-not $cur -or $cur -notmatch [regex]::Escape($key.Trim())) { Add-Content $path -Value $key.Trim() -Encoding ascii }
    }
```

Nothing else in either kit removes a key line (§Q7). The **new** kit is the one that had to learn this,
and it is documented as a fix rather than a design:
`tools/lpt-access-kit/teardown/Install-Destructor.ps1:117-121, 644-679`:

```powershell
  # P2852: without these two the teardown could never remove the key LINE it added. Its only mention of
...
function Remove-AuthorizedKeyLine {
    <#  Remove ONLY the key line(s) whose TRAILING COMMENT is this window's own. ...
      Why match a comment and not a fingerprint or the key text: ...
```

with the refusal spelled out at `:664-665`:
`if ([string]::IsNullOrWhiteSpace($Comment)) { return 'REFUSED: no comment to identify our own line, so this run removes nothing rather than guessing' }`

---

### Q4 — Windows has no OpenSSH *server* by default: how did it account for that?

See Q2 for the install ladder. The additional things it did about it:

1. **Registered the service from the binaries if they were already there** (`sc.exe create sshd binPath=... start=auto`) — the offline path.
2. **`DISM ... /LimitAccess`** so a machine with no Windows Update could still get the capability from local sources.
3. **Ran the install in a background job with a timeout** so a hung `Add-WindowsCapability` did not hang the operator — `Enable-ShopSsh.ps1:110-125` gives it a 30-second window and moves on; `Install-CopilotSshAccess.ps1:236-252` gives it 10 minutes with a progress counter every 15 s.
4. **Set `HKLM:\SOFTWARE\OpenSSH\DefaultShell`** (Q2).
5. **If it still failed, it kept going and said so**: `Enable-ShopSsh.ps1:127-129`
   `if (-not $installOk) { Write-Warn "Could not install OpenSSH Server. Continuing with account/firewall setup." }` — and `Install-CopilotSshAccess.ps1:296` adds a `critical` problem, `"sshd service missing"`.

The **new** kit's answer to the same question is materially different: it carries the payload
(`tools/lpt-access-kit/vendor/OpenSSH-Win64.zip`, 4 856 219 B on `D:\LPT-Access\vendor\`, added
2026-10-15) and uses it **first**, with `Add-WindowsCapability` demoted to fallback —
`T1-LanSsh.ps1:307-345`:

```powershell
  # sshd.exe carries a valid Microsoft Authenticode signature - verified when it was fetched.
  $vendorZip = Join-Path $kitRoot 'vendor\OpenSSH-Win64.zip'
  if (Test-Path -LiteralPath $vendorZip) {
...
    if (Get-Command Add-WindowsCapability -ErrorAction SilentlyContinue) {
      $capRes    = Add-WindowsCapability -Online -Name $capability -ErrorAction Stop
```

---

### Q5 — The firewall

**Generation 1 (`Enable-ShopSsh.ps1:151-159`) — LAN-scoped to RFC1918:**

```powershell
$ruleName = "OpenSSH Server (sshd) - Shop"
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if (-not $existing) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $SSHPort -Action Allow | Out-Null
}
# Restrict to LAN
Set-NetFirewallRule -DisplayName $ruleName -RemoteAddress "192.168.0.0/16","10.0.0.0/8","172.16.0.0/12" -ErrorAction SilentlyContinue
```

**Generation 2 (`Install-CopilotSshAccess.ps1:454-468`) — the opposite: TCP/22 from anywhere, by
several overlapping mechanisms:**

```powershell
try { Set-NetFirewallProfile -Profile Domain,Private,Public -AllowInboundRules True -ErrorAction SilentlyContinue; Write-Ok "Allow inbound rules" } catch { Write-WarnLine "AllowInbound: $_" }
Get-NetFirewallRule -DisplayName "Personal Secretary Copilot SSH*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
$sshdExe = Join-Path $env:WINDIR "System32\OpenSSH\sshd.exe"
try { New-NetFirewallRule -DisplayName "Personal Secretary Copilot SSH - TCP 22" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22 -Profile Any -RemoteAddress Any -ErrorAction Stop | Out-Null; Write-Ok "TCP/22 Any profile Any remote" } ...
if (Test-Path $sshdExe) { try { New-NetFirewallRule -DisplayName "Personal Secretary Copilot SSH - sshd.exe" -Direction Inbound -Action Allow -Program $sshdExe -Profile Any -RemoteAddress Any -ErrorAction Stop ... } ... }
try { New-NetFirewallRule -DisplayName "Personal Secretary Copilot SSH - ICMPv4" ... } ...
Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -match 'OpenSSH|SSH Server' } | ForEach-Object { try { Set-NetFirewallRule -Name $_.Name -Enabled True -Action Allow -Profile Any ... } catch {} }
try { netsh advfirewall firewall add rule name="Personal Secretary Copilot SSH - netsh TCP 22" dir=in action=allow protocol=TCP localport=22 profile=any remoteip=any | Out-Null; Write-Ok "netsh fallback" } ...
```

plus it promotes every active connection profile to `Private` (`:457-460`). It also removes
`Personal Secretary Copilot SSH*` rules at the start — **idempotency, not teardown** (see Q7).

Generation A is comparable to Gen 2 but keeps `-RemoteAddress LocalSubnet` as its default
(`7775e17e:205`: `New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22 -Profile Any -RemoteAddress $AllowedRemoteAddress`).

The new kit returns to a narrow rule, named from the window state so teardown can remove exactly it —
`T1-LanSsh.ps1:585-594`:

```powershell
  $prior = @(Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue)
  if ($prior.Count -gt 0) {
    $prior | Remove-NetFirewallRule -ErrorAction Stop
...
  New-NetFirewallRule -DisplayName $rule -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort $port -RemoteAddress '192.168.50.0/24' -Profile Any `
    -Description ('LPT access window ' + $runId + ' - teardown removes this rule by this exact name') | Out-Null
```

---

### Q6 — Anything about the Techloq filter

**In the open path: nothing effective, and what existed claimed success it did not have.** The installer
only *detected* the filter — `Install-CopilotSshAccess.ps1:512-524` is titled `# === STEP 8: Techloq
detection ===` and its final act is `$techloqFound = $true; Write-WarnLine "Techloq detected"; Add-Problem
"warn" "Techloq detected"`. There is no service stoppage, no driver unload, no routing change anywhere in
`Install-CopilotSshAccess.ps1`.

The separate `Disable-Techloq.ps1` is the one that *tries*, and `MOVED.md` measured it as a false claim:

> `- `Disable-Techloq.ps1` prints `[STOPPED]` / `[DISABLED]` unconditionally while every call behind it carries `-ErrorAction SilentlyContinue`, and the filter's own SOP records those exact calls failing with Error 1052 / Error 5. It never touches `tpd.sys`. **It reports success it did not achieve** - do not rely on it.`

That reads exactly as described in the file: `Disable-Techloq.ps1:27-28`
`Stop-Service -Name $s -Force -ErrorAction SilentlyContinue` then `Write-Host "  [STOPPED] $s"`, and
`:38-39` `Set-Service -Name $s -StartupType Disabled -ErrorAction SilentlyContinue` then
`Write-Host "  [DISABLED] $s startup"` — the message is printed whether or not the call worked.
`[DISABLED]`/`[STOPPED]` for `tpd` is also wrong on its face: the MIRIAM capture proves `tpd` is a
**kernel file-system driver** (`techloq_services.txt`: `ServiceType : FileSystemDriver`, `StartType :
System`, `RequiredServices : {FltMgr}`) that `Stop-Service` cannot meaningfully stop, while
`Disable-Techloq.ps1:23` lists only `WindowsFilterService`, `WindowsFilterAgentService`,
`WindowsFilterUpdateService`, `LMIGuardianSvc`.

**And yet the MIRIAM run worked with the filter present.** `CopilotAccess.json` records
`"techloq_logmein": true`; `techloq_services.txt` shows `tpd`, `WindowsFilterService` and
`WindowsFilterUpdateService` all `Status : Running`; `techloq_port_10001.txt` shows the filter's control
port listening; and `techloq_network_block_test.txt` in the same run shows LAN TCP/22 was **not** blocked:

```
target          ping tcp22 tcp443
------          ---- ----- ------
8.8.8.8         True  True   True
192.168.50.138  True  True   False
192.168.50.77   True  True   False
192.168.50.23   True  True   False
192.168.50.45   True  True   False
```

The old kit's own decision tree knows why, and says so as a standing fact —
`tools/lpt-diagnostics-kit/REMOTE-ACCESS.md:32-41`:

> `Techloq's kernel filter driver (`.sys`, often named `tpd)`) registers **WFP** filters that reset non-HTTP peer connections — **including SSH on loopback, on any port**, even with correct keys/config/firewall.`
> `This is a reset **before auth** — not a key, port, config, or firewall problem. Trying to fix keys/ports/firewall will waste hours. **Do not.**`

and `REMOTE-ACCESS.md:3-5` gives the operational rule the old kit lived by: *"When a laptop is **on the
bench (LAN)** it's easy: `Enable-ShopSsh.ps1` from the field kit, then `ssh` directly. When the laptop is
**somewhere else** … this page decides the path."*

The **new** kit makes a different, stronger call, and **this is the one place I think it is more
conservative than the old kit and it matters** — `tools/lpt-access-kit/transport/Select-Transport.ps1:388-394`:

```powershell
    if (-not $FilterPresent) {
      ...
      $reasons += 'no filter signal present, so inbound OpenSSH on the LAN is the simplest path and the only tier that puts NO secret on the target'
    } else {
      $reasons += ('filter signals present: ' + ($FilterEvidence -join '; '))
      $reasons += 'inbound SSH on the LAN would be reset by the filter, so T1 is not offered'
```

So when the filter probe says "present", the selector **declines T1** — the very tier that the old kit
ran, on a filter-present machine, successfully. In the 2026-10-12 stick run this shows up as the blocker
line in the handoff (§5): `- filter present, no usable outbound channel` / `transport = T4 NOT_READY`.
The new kit never disables the filter (`MOVED.md`: *"the filter is routed around by tier, never
disabled"*), which is right, but it also never attempts the thing that demonstrably worked. Whether that
gate is too strict is the most actionable open question in this whole report.

---

### Q7 — Was there a teardown, and did it work?

**There was no teardown. The kit claimed one in three places and implemented it nowhere.** The claim:

* `Enable-ShopSsh.ps1:16` — `CLEANUP: Account and SSH are auto-disabled on next reboot.`
* `Enable-ShopSsh.cmd:35` — `echo The account is auto-cleaned on next reboot.`
* `Run-CopilotSshAccess.cmd:34` — `echo The account is auto-cleaned on next reboot.`

`MOVED.md` records the verdict: *"`Enable-ShopSsh.ps1:21` promised cleanup on reboot that no code
implemented (`P2851`)."*

I checked this independently rather than taking it from the doc. A grep of the whole old kit for every
removal verb (`Remove-LocalUser`, `Remove-Item`, `Remove-NetFirewallRule`, `Remove-ItemProperty`,
`Unregister`, `Restore`, `revert`, `undo`) returns **exactly one hit**, and it is not a teardown —
`Install-CopilotSshAccess.ps1:462`, at the *top* of step 5:

```powershell
Get-NetFirewallRule -DisplayName "Personal Secretary Copilot SSH*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
```

which deletes its **own previous run's** rules so the run is idempotent, and then immediately re-creates
them three lines later. There is no `Remove-LocalUser`, no scheduled task, no `RunOnce`, no
`Unregister-ScheduledTask`, no key-line removal, and no sshd_config restore — the
`$cfg.copilot-backup` file written at `:343` is only ever restored when `sshd -t` rejects the new config
(`:375`) or on an exception (`:380`).

Consequences, all still true on any machine the old kit touched (including MIRIAM and this desktop):

* the account it created stayed (`repairtech` for Gen 1, with the password `ShopRepair2024!` hard-coded
  in the repo for months — `Enable-ShopSsh.ps1:26` — until `99f7134d` on 2026-10-05 replaced it with a
  per-machine random value and a comment that says why: *"Until 2026-10-05 it was the literal
  "ShopRepair2024!" on every machine the shop had ever touched, so one leaked USB stick unlocked all of
  them."*);
* the key line stayed in **both** authorized_keys files;
* the TCP/22 any-remote firewall rules stayed;
* the rewritten `sshd_config` stayed;
* `Disable-Techloq.ps1` leaves services set to `Disabled` with only a **manual** `Enable-Techloq.ps1` to undo it (`Disable-Techloq.ps1:58` — *"To re-enable Techloq later, run: Enable-Techloq.ps1"*).

The new kit has a real teardown — `teardown/Install-Destructor.ps1`, `teardown/Test-Absence.ps1`,
`teardown/Test-TeardownDryRun.ps1` — which `MOVED.md` describes honestly as the fix for this:
*"`keys and handoffs in this folder` → `eliminated; the teardown now removes key lines, and no secret is
left behind`."* But per the current kit's own status it is **more ambitious and less proven than the old
one**: the teardown dry-run is 11/11 and arming is proven, while **open → connect → close → absence PASS
has never been completed end to end.** The old kit's teardown was worthless but irrelevant; the new kit's
teardown is the right design and unproven, which is a different risk.

---

## 3. What the new kit does differently — side by side

| | OLD (`scripts/copilot-ssh-field-kit`, Gen B) | NEW (`tools/lpt-access-kit`, branch `zabz/lpt-access-kit-open-fix-20261015`) |
|---|---|---|
| sshd port | **22, the default; no `Port` directive written** | random high port written into `sshd_config` (`T1-LanSsh.ps1:518`) |
| does the edit take effect | `Restart-Service sshd -Force` then `netstat` proof (`:472-474`) | was `Start-Service` only ⇒ **silent no-op on a running sshd**; fixed to `Restart-Service -Force` 2026-10-15 (`:611-617`) |
| does it notice the edit failed | yes, `sshd -t` + netstat, and downgrades to a `critical` problem | yes, plus a new re-read assertion that refuses loudly (`:529-542`) |
| OpenSSH server | Windows' own, via Windows Update/DISM/`sc.exe create` | **ships `vendor\OpenSSH-Win64.zip`, used first**; capability is fallback |
| config touched | `%ProgramData%\ssh\sshd_config` in place, 2 backups | same file, backup `sshd_config.lpt-backup-<runId>`, restores on `sshd -t` failure |
| `Match Group administrators` | stripped | stripped (`:500-505`) |
| `AuthorizedKeysFile` | forced to the absolute admin path | same (`:520`) |
| key files written | **both** user `.ssh\authorized_keys` and admin file | **admin file only** (`:424`); user `.ssh` tightened defensively but not written (`:432-443`) |
| key comment | `ezabz@zabz-tech` / `copilot-usb-reverse-2026-05-29` | `authorizedKeysComment` from the window state, e.g. `LPT-ACCESS-WINDOW 20261015-164721DESKTOP-3BC7C0C` (`:243-251`) |
| key removal | **none** | removes the one line whose trailing comment is the window's own, by regex anchored at end-of-line (`Install-Destructor.ps1:644-679`) |
| firewall | TCP/22, **Any remote**, Any profile, + program rule + ICMPv4 + netsh + forces all OpenSSH rules open | `LocalPort <random>`, **`-RemoteAddress 192.168.50.0/24`**, named from state |
| Techloq | detected; `Disable-Techloq.ps1` tried and lied | routed around: probe → tier T1/T2/T3/T4; **and T1 is not offered at all when the filter is detected** (`Select-Transport.ps1:388-394`) |
| teardown | **none** (claimed on reboot, never coded) | real destructor + absence test; **never run green end to end** |
| secrets on the target | private reverse key **and**, on the stick copy, a private key commented `ezabz-customer-access` | public half only; T1 refuses to generate a key on the target (`T1-LanSsh.ps1:6-13`) |
| honest reporting | writes `status=REVERSE_TUNNEL_ACTIVE` / `problems=0` even when its own auth test failed (see §1 caveat; also called out in `T1-LanSsh.ps1:31-38`) | never reports READY without a successful key auth |

The new kit's own header names the old files as the source of its trap list, which is a useful
cross-check on everything above — `T1-LanSsh.ps1:15-29`:

```powershell
  THE TRAPS FROM THE OLD INSTALLER, ALL HANDLED HERE
  Install-CopilotSshAccess.ps1:299-380, 382-452, 454-468 and Enable-ShopSsh.ps1:83 are the source of
  this list. ...
    1. BACKUP sshd_config before editing and RESTORE it if `sshd -t` rejects the result (line 341-375).
    2. AuthorizedKeysFile must be an ABSOLUTE path - the __PROGRAMDATA__ token is not understood by
       OpenSSH 8.1 (line 356-364).
    3. The `Match Group administrators` block must be removed/sidestepped or auth breaks on 8.1 ...
    4. ACLs: .ssh is user+SYSTEM only; the admin authorized_keys file is Administrators+SYSTEM only ...
    5. OpenSSH 8.1 needs DefaultShell set under HKLM:\SOFTWARE\OpenSSH (line 302-305) ...
    6. A random high port taken from the window state, and a firewall rule NAMED FROM THE STATE FILE
       so teardown can find and remove it.
```

---

## 4. `git log --all -S` results (the searches the brief asked for)

Run against `C:\Users\ezabz\Code\personal-secretary-mvp` (working tree left untouched; I read
committed content with `git show`).

```
$ git log --all --diff-filter=A --oneline -- '*Enable-ShopSsh.ps1' '*Collect-PcDiagnostics.ps1' \
      '*Disable-Techloq.ps1' '*Install-CopilotSshAccess.ps1' '*Run-CopilotSshAccess.ps1' '*Setup-DesktopTunnelUser.ps1'
d7cd4ecf 2026-07-07 chore: workspace sweep 2026-07-07 — ... add SSH field kit ...
e1538fdb 2026-07-05 chore: cleanup stale files, update gitignore, add remaining artifacts
7775e17e 2026-05-21 ops: add Windows access helpers and audit logs

$ git log --all -S'ShopRepair2024!' --oneline
dd484fbf / e235a583 lpt-access-kit: the interface layer, and a design contract with acceptance tests
99f7134d diagnostics kit: capture the BitLocker key and the access state honestly; stop the kit lying about its own results
c34588e1 ops: disk cleanup, Exalt exclusions, LPT diagnostics kit, recovery/sync tooling
ca6982a7 ssh: export Linux access kit (Enable-LinuxAccess.sh) to USB bundle
d7cd4ecf chore: workspace sweep 2026-07-07 ...

$ git log --all -S'administrators_authorized_keys' --oneline      → 20 commits
    (newest: e3e56331, 7d152dee, 3a98f399, 45565cc1 ... - all the lpt-access-kit teardown work)
    (oldest relevant: d7cd4ecf, e1538fdb, 4a8255a6, 57823595 "docs: NEXT ACTION for her Copilot - fix admin authorized_keys (Match Group administrators gotcha)")

$ git log --all -S'ezabz-customer-access' --oneline
f3d52ad8 / 6fb623dd lpt-access-kit: ONE entry point, the operator RUNBOOK, and the two stale kits retired
dd484fbf / e235a583 lpt-access-kit: the interface layer, and a design contract with acceptance tests
c1951834 Add customer SSH access tools: sshpass, ssh-customer.ps1, deploy-customer-ssh-key.ps1

$ git log --all -S'sshd -f' --oneline        → (no results)
$ git log --all -S'Port 22' --oneline        → 20+ commits, the recent ones all lpt-access-kit, the old ones d7cd4ecf/e1538fdb/7775e17e
$ git log --all -S'AllowUsers' --oneline     → 85783755, d7cd4ecf, 9f56c820, d8ac0fef
$ git log --all --just the kit folder:
f3d52ad8 2026-10-05 lpt-access-kit: ONE entry point, the operator RUNBOOK, and the two stale kits retired
6fb623dd 2026-10-05 (same message, other branch)
99f7134d 2026-10-05 diagnostics kit: capture the BitLocker key and the access state honestly ...
ca6982a7 2026-09-02 ssh: export Linux access kit (Enable-LinuxAccess.sh) to USB bundle
cb3ff255 2026-09-02 ops: drop chromadb from backups ...
f8f7dd93 2026-08-11 fix(ssh-field-kit): Stop-Job -Force is PS7-only ...
d7cd4ecf 2026-07-07 chore: workspace sweep 2026-07-07 ...
e1538fdb 2026-07-05 chore: cleanup stale files ...
```

Two useful side-finds from the same search space:

* `docs/research/directives/024-copilot-ssh-field-kit-root-cause-analysis.md` (added `d7cd4ecf`, later
  deleted) — the RCA of the *reverse-tunnel* leg. It is a diagnosis, not a fix; its own last line is
  *"A clear root cause analysis and a concrete fix plan. No more patching — get it right."* Its key
  measurement: *"**Desktop authorized_keys** has reverse key: `AAAAC3NzaC1lZDI1NTE5AAAAIEkBZ2hlH7YPcor0c9bHvSPvrmE5ZLwj6aoWnCwJeptI` (old) / **USB reverse key** is: `AAAAC3NzaC1lZDI1NTE5AAAAIFkXWqzlJTj9YW3rai/Y6b9Kvwib7ajZi3NP6+ETTajd` (new)"* — the second of those is exactly the comment-bearing key in `keys/copilot_reverse_ed25519.pub` quoted in §Q3.
* `6e0fe531` / `548661ec` (2026-08-25) — *"tpd driver resets SSH on loopback, tunnel needs port 2222"* / *"confirm Techloq root cause, tunnel ingress -> 2222"*. Same conclusion as `REMOTE-ACCESS.md`, reached on the laptop.

---

## 5. `D:\LPT-Runs` and the stick

**What is on the stick now.** `D:\LPT-Access\` is **the NEW kit, not the old one** — deployed 2026-10-12
15:22, updated 2026-10-15. Confirmed by content, not by name: its `README.md` is 5 619 B and is
byte-identical in size to
`C:\Users\ezabz\Code\_worktrees\usb-access-kit\tools\lpt-access-kit\README.md` (5 619 B), and it carries
`vendor\OpenSSH-Win64.zip` (4 856 219 B, 2026-10-15 18:01) which no old kit ever had. There is **no
`D:\CopilotSshAccess\` on the stick any more** — that folder name does not exist anywhere on `D:`,
`C:\ProgramData`, or the laptop's `D:` (I searched all of them). The old kit's *own* USB output
directory, had it survived, would have been `D:\CopilotSshAccess\runs\<yyyyMMdd-HHmmss>-<HOST>\` (per
the MIRIAM handoff, `run_dir=D:\CopilotSshAccess\runs\20260704-233346-MIRIAM`, and README.txt:50
*"All saved under `runs\<timestamp>-<hostname>\techloq_*.txt`"*).

**What is in `D:\LPT-Runs`.** Eight run folders and five launcher logs. **Only two predate the 2026-10-12
redeploy, and both of those are NEW-kit runs** — the test is the collector's own banner, which the old
kit never printed:

```
$ Get-Content D:\LPT-Runs\20720310-222649_LAPTOP-3VVAPOT5\run.log -First 1
LPT state collector v1.0.0 starting; depth=Quick; host=LAPTOP-3VVAPOT5; run=D:\LPT-Runs\20720310-222649_LAPTOP-3VVAPOT5

$ Get-Content D:\LPT-Runs\20261012-154253_YZ-PINTER-LAPTO\run.log -First 1
LPT state collector v1.0.0 starting; depth=Quick; host=YZ-PINTER-LAPTO; run=D:\LPT-Runs\20261012-154253_YZ-PINTER-LAPTO
```

Both have `access-window.json` with `"schema": "lpt-access-window/1"`, which is `lib/AccessWindow.psm1`'s
schema — a new-kit artifact.

* `20720310-222649_LAPTOP-3VVAPOT5` — real date 2026, the machine's RTC was set to 2072 (host
  `LAPTOP-3VVAPOT5`, user `camps`). Not a "different folder naming, older dates" old-kit run: the naming
  is the new kit's `yyyyMMdd-HHmmss_HOST`. Its handoff is a failure:
  ```
  transport     = T4  NOT_READY
  port          = 0
  blockers:
    - COULD NOT READ - shop-lan probe: COULD_NOT_READ; no tier may be claimed ready without it
  ```
* `20261012-154253_YZ-PINTER-LAPTO` — same shape, and the failure is the Techloq gate from §Q6:
  ```
  handoff.txt:
  network       = 192.168.101.123 iface=Wi-Fi gw=192.168.101.1 shopLan=False
  filter        = detected=True
  transport     = T4  NOT_READY
  account       = 
  port          = 0
  blockers:
    - filter present, no usable outbound channel

  access-window.json: "tier": "T4", "port": 47567, "account": "lptwinrlapto",
                      "authorizedKeysPaths": [], "authorizedKeysComment": "LPT-ACCESS-WINDOW 20261012-154253YZ-PINTER-LAPTO"
  ```
  Note the state was **armed** (`port 47567`, an account name, a key comment, an empty
  `authorizedKeysPaths`) while the transport reported **NOT_READY** and no channel existed — i.e. this is
  the "selector's verdict is not the transport's verdict" failure, and it is exactly the class of
  dishonesty the old kit's `status=REVERSE_TUNNEL_ACTIVE`/`problems=0` had. Nothing here shows a window
  anyone could have used.

**So: there is no old-kit run folder on the stick, and no handoff on the stick showing a window open.**
The only surviving handoff of a working old-kit window is the uncommitted `latest-run\` quoted in §1,
which lives on this desktop in the repo working tree (and on `C:\ProgramData\CopilotSshAccess\runs\` on
MIRIAM, which I cannot reach). The stick's `D:\LPT-Access\results\` and `D:\LPT-Access\Logs\` are empty.

Adjacent stick files I checked and found irrelevant to this question: `D:\USB-HISTORY.ps1` (USB device
history, read-only, writes only to `-OutDir`), `D:\RUN-ME.ps1`, `D:\FIX-SENZER.ps1`, `D:\DRIVE-FIX.ps1`,
`D:\LPT-KeyCheck\Get-BitLockerKeyProof.ps1` (all 2026-10-15, BitLocker/drive-repair tools for
`PF3F2810`, not the access kit). `D:\Brooks-Recovered\` is recovered media files.

---

## 6. What remains unknown — stated as unknown, not guessed

1. **The 29 802-byte `Enable-ShopSsh.ps1` (and 25 727-byte `Collect-PcDiagnostics.ps1`) that `MOVED.md`
   says were on the stick are not in git and I could not find them on any host.** Repo history holds at
   most 15 289 B (`Enable-ShopSsh.ps1`) and 20 139 B (`Collect-PcDiagnostics.ps1`). I searched: every ref
   in `personal-secretary-mvp` on this desktop; `C:\Users\ezabz\Code\_scratch` and `_worktrees`; all of
   `D:\`; `C:\ProgramData\CopilotSshAccess` here and on ZABZ-YOGA; and, over ssh, `secratary-ts`
   (`find / -xdev`, all its worktrees under `/home/zabz` and `/var/tmp`), `secratary-cloud`
   (`/root/_hk168_wt`, `/root/finance-fleet-20261013/...`, `/root/_wt-voice-doc-20261014`) and
   `zabz-tech-linux` (`/home/zabz/personal-secretary-mvp`). Nothing exceeded 41 734 B, and no file at
   those two sizes exists. **If a version of `Enable-ShopSsh.ps1` gave the shop a non-default sshd port,
   it was in that uncommitted 29 802-byte copy and I have not seen it.** Everything I *did* read — both
   committed revisions plus the laptop's 41 734-byte `Install-CopilotSshAccess.ps1` — uses port 22.
2. **No log of a successful login *into* a target.** The MIRIAM run proves the target's sshd was Running
   and LISTENING, the firewall was open, the key was installed with the right ACLs and the reverse
   listener was up — but its two "functional" probes failed by presenting no key, and I found no
   operator-side session log, no `sshd` auth-success event, and no shell history showing
   `ssh Miriam@192.168.50.239`. The `direct_ssh=` line and the ACL/port evidence are what I have.
3. **Whether the old kit ever wrote a `Port` directive in some intermediate state.** From the two
   committed revisions plus the laptop's revision the answer is a clear no, and the MIRIAM
   `sshd_config.before`/`.after` pair shows the port untouched within a run. I cannot rule out a variant
   I never saw (see unknown 1).
4. **The three other Windows nodes could hold more old-kit output I did not enumerate.**
   `ZABZ-TECH-LAPTOP` (`ZABZ-TECH-LAPTOP` per `AGENTS.md`) and the mac-mini I did not reach;
   `ZABZ-YOGA` I reached and its four `C:\ProgramData\CopilotSshAccess\runs\2026070*` folders are **empty**
   (they are the reverse tunnel's `reverse_tunnel_local_log_dir` and the logs are gone). MIRIAM is not a
   machine I can reach at all, and `C:\ProgramData\CopilotSshAccess\runs\` on **this** desktop holds only
   two empty folders, `20260625-143022-ZABZ-TECH` and `20260703-174514-ZABZ-TECH`.
5. **Whether the new kit's T1 refusal under a detected filter is wrong.** I have a code path
   (`Select-Transport.ps1:388-394`) and one counter-example (MIRIAM, filter running, T1 succeeded on the
   shop LAN). I do **not** have a measurement of a T1 attempt on a filter-present machine *from the new
   kit*, because the selector never tries. That is a hypothesis with evidence, not a conclusion.
6. `Disable-Techloq.ps1`'s actual effect on the real WFP filters. `MOVED.md` cites the filter's own SOP
   recording `Error 1052` / `Error 5`; I did not read that SOP, so I am reporting its conclusion as a
   quotation, not as something I verified.

---

## 7. The one-paragraph answer

The old kit worked because it did the boring thing: install or register Windows' own OpenSSH server,
leave `sshd_config` on **port 22 with no `Port` directive at all**, set `AuthorizedKeysFile` to the
**absolute** `C:\ProgramData\ssh\administrators_authorized_keys` after deleting the
`Match Group administrators` block, write the key into **both** key files with `/grant:r` ACLs, open
TCP/22 in the firewall, and then **force-restart `sshd` and prove with `netstat` that the port was
listening** before declaring anything. Its escape hatch was a reverse tunnel on a non-default desktop
port (2222, or 2200+random), which is the only non-default port in the whole design. It shipped no
server payload, no teardown, and no honest Techloq handling (its own `Disable-Techloq.ps1` never touched
`tpd.sys` and printed success anyway). The new kit does the *right* things the old kit could not — public
half only, a key comment it can find again, a named firewall rule, a real destructor — but it wrote a
random `Port` into `sshd_config` and then **failed to restart a running `sshd`**, so the port it chose was
never the port that was listening; that single `Start-Service`-instead-of-`Restart-Service` line is the
failure the owner remembers, and it is now fixed. The old kit's equivalent line was
`Restart-Service sshd -Force`.
