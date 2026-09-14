@echo off
rem ============================================================================
rem DSH launcher for Yocheved's laptop (DESKTOP-FGV6KMH).
rem
rem WHY THIS FILE EXISTS SEPARATELY FROM dshw-launch.cmd
rem Two environment facts about THIS machine cannot live in the shared launcher, and both are the
rem difference between a working engine and one that fails every network call:
rem
rem   1. This machine sits behind the Techloq filter, which intercepts TLS for EVERY destination.
rem      Node does not trust that interception unless NODE_EXTRA_CA_CERTS names the filter CA.
rem      Machine-scope environment variables are NOT reliably inherited here -- a process spawned
rem      by a service started before the variable existed does not see it (measured 2026-09-14:
rem      Node failed every handshake with "unable to get local issuer certificate" while the
rem      variable was set at Machine scope). So it is set HERE, explicitly, in the process that
rem      actually starts the engine.
rem   2. IPv6 is blackholed on her network, so npm/undici can hang for minutes resolving AAAA
rem      first. --dns-result-order=ipv4first is declared for the whole engine process tree here,
rem      so every MCP bridge and tool inherits it.
rem
rem Nothing here deletes or cleans anything. Install steps copy files; a file being replaced is
rem deleted one file at a time, never recursively.
rem ============================================================================

setlocal
set "DSHW_DIR=%~dp0"
set "DSHW=%DSHW_DIR%dshw.ps1"
set "PWSH=%ProgramFiles%\PowerShell\7\pwsh.exe"
if not exist "%PWSH%" set "PWSH=pwsh.exe"

rem --- Techloq TLS interception: Node must trust the filter CA ---
if exist "C:\Users\cheve\certs\techloq-ca.pem" (
  set "NODE_EXTRA_CA_CERTS=C:\Users\cheve\certs\techloq-ca.pem"
)

rem --- IPv6 is a black hole on this network; resolve IPv4 first ---
set "NODE_OPTIONS=--dns-result-order=ipv4first"

rem --- keep the harness home explicit rather than inferred from a possibly-SYSTEM profile ---
set "DSH_HOME=C:\Users\cheve\.dsh"

"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%DSHW%" ensure
"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%DSHW%" restore

endlocal
