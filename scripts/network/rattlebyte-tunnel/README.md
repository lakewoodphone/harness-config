# rattlebyte.com workaround — domain-scoped PAC + SSH SOCKS tunnel

**Why this exists.** On 2026-09-16 the RattleByte vendor support portal would not load from **ZABZ-YOGA** on the home
(T-Mobile) line. The site was not down: it answered `302` from the office server, from Hetzner, from the mac-mini, and
from **8/8** independent check-host.net nodes, while `google`, `cloudflare` and — decisively — **`1984.is` (the site's own
hosting company)** all answered fine from the same laptop.

What was actually wrong: **`185.112.144.0/22` is silently dropped from that line only.** Every port on the site's IP timed
out (`22, 25, 80, 443, 8080`), and the whole `/22` plus `1984hosting.com` were unreachable, while the office and Hetzner
paths crossed the **same Zayo routers** (`64.125.22.0 → 64.125.31.111 → 64.125.28.15`) that the home trace died on. So the
route exists and only that line's traffic is discarded for that prefix — an external peering/filtering fault, not the ISP
being down, not the router, not DNS, and not the site.

**What this installs.** Only `rattlebyte.com` is routed through the office server; everything else stays `DIRECT`.

```
browser ── PAC (only rattlebyte.com) ──► SOCKS5 127.0.0.1:11080 ──► ssh -D ──► secratary (office) ──► rattlebyte.com
                                          ▲
                       pac-server.ps1 serves the PAC at http://127.0.0.1:1081/proxy.pac
                       rattlebyte-tunnel.ps1 supervises both and restarts either if it dies
```

| File | Role |
|---|---|
| `rattlebyte.pac` | the routing rule: `rattlebyte.com` → SOCKS5 `127.0.0.1:11080`, everything else `DIRECT` |
| `pac-server.ps1` | serves that PAC at `http://127.0.0.1:1081/proxy.pac` using a raw `TcpListener` (no admin needed) |
| `rattlebyte-tunnel.ps1` | supervisor: keeps the PAC server up and keeps `ssh -D 127.0.0.1:11080` to `secratary-ts` alive |
| `verify-rattlebyte.ps1` | one-command health check |
| startup entry | `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\zabz-rattlebyte-tunnel.vbs` (starts it hidden at logon) |
| Windows setting | `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings\AutoConfigURL` = `http://127.0.0.1:1081/proxy.pac` |

## Installing it on another machine

1. Copy this folder to `%USERPROFILE%\.dsh-network\` (drop the `.md` files; keep the four scripts + the `.pac`).
2. Set the registry value:
   ```powershell
   Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' `
                    -Name AutoConfigURL -Value 'http://127.0.0.1:1081/proxy.pac'
   ```
3. Drop the `.vbs` launcher into the user's Startup folder (see `startup-zabz-rattlebyte-tunnel.vbs.txt`), or just run
   `pwsh -NoProfile -WindowStyle Hidden -File .\rattlebyte-tunnel.ps1` once.
4. Confirm: `pwsh -File .\verify-rattlebyte.ps1` — expect both listeners `True`, the tunnel `code=302`/`200`, and the
   **direct** attempt still failing (that failure is what proves the tunnel is doing the work).

## Undo (30 seconds, no admin)

```powershell
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -Name AutoConfigURL
Get-CimInstance Win32_Process -Filter "Name='pwsh.exe'" |
  Where-Object { $_.CommandLine -like '*.dsh-network\rattlebyte-tunnel.ps1*' -and $_.ProcessId -ne $PID } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Remove-Item "$([Environment]::GetFolderPath('Startup'))\zabz-rattlebyte-tunnel.vbs"
```
Blast radius is bounded by design: if the tunnel or the PAC server is down, the PAC still answers `DIRECT` for everything
else, and `rattlebyte.com` simply fails exactly as it did before.

## Traps this cost real calls to learn (2026-09-16)

- **A `file://` PAC is ignored by Chromium on Windows.** With `AutoConfigURL = file:///…/rattlebyte.pac` the browser gave
  `net::ERR_CONNECTION_TIMED_OUT`; changing **only** the delivery to `http://127.0.0.1:1081/proxy.pac` made the same
  browser render the real page. Serve the PAC over HTTP.
- **`chrome.exe --headless=new --dump-dom` is useless for this** — Windows Chrome/Edge detach from the launcher and the
  command returns 0 bytes with exit 21. Verify with Playwright (CDP), which reports properly.
- **Never nest PowerShell inside `powershell.exe -Command "…"` from pwsh** — `\$` is not an escape, so the inner command
  arrives mangled. Write a `.ps1` and run it with `-File`.
- **Do not kill processes by command-line pattern without excluding `$PID`** — the command you are running contains the
  same string, so you kill your own shell (this happened, and the following calls hung until the harness recovered).

## Related

- Case record (business side, with the firmware work): `lpt-hub`
  `hardware-diagnostics/panasonic-dmp-bd84-rattlebyte-diagnostic-2026-09-12.md`.
- Journal: lessons `L1738`/`L1739`, decision `D213`, handoff `H392`, pain `P214`.
