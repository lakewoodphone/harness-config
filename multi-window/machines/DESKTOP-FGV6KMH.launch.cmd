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

rem --- WEB SEARCH: route it through our own Worker, because the default endpoint is blocked ---
rem Added 2026-09-15. The harness web-search provider is a DeepSeek Anthropic-format Messages call, and
rem it defaults to https://api.deepseek.com/anthropic/v1 -- which Techloq blocks by URL category on this
rem machine. Chat never noticed, because chat goes through the deepseek-proxy route; search has its own
rem endpoint and its own config, so it failed on EVERY call. Evidence, from her own session archive
rem (session 901efff6): every web search returned
rem   "DeepSeek search request failed: TypeError: fetch failed ... endpoint
rem    https://api.deepseek.com/anthropic/v1/messages"
rem and the workaround was a dozen r.jina.ai page fetches per answer -- a search that silently degrades
rem into fetching one URL at a time.
rem
rem The Worker fronting this zone passes the request path straight through to api.deepseek.com, so it
rem carries /anthropic/v1/messages unchanged. Verified 2026-09-15: that path through
rem ds.abletelsolutions.com returned HTTP 200 with a real Anthropic Messages body, while the same path
rem on api.deepseek.com returned the filter's HTML block page (HTTP 200, text/html, 2498 bytes).
rem
rem THIS VARIABLE CANNOT LIVE IN A .env FILE. The harness classifies DEEPSEEK_SEARCH_BASE_URL as
rem bootstrap-only (dsh-app-boot, BOOTSTRAP_NAMES): it "decides how it reaches the network", and the
rem only .env layer allowed to carry such a name is the harness home, for proxy names alone. Put it in
rem ~/.dsh/.env and the engine refuses to start at all -- which is exactly what happened, and it looked
rem like a launcher fault rather than a settings one. So it is set HERE, in the process that starts the
rem engine, and the scheduled task is pointed at THIS FILE rather than at dshw.ps1 directly.
if not defined DEEPSEEK_SEARCH_BASE_URL set "DEEPSEEK_SEARCH_BASE_URL=https://ds.abletelsolutions.com/anthropic/v1"

rem --- the verb to run, defaulting to her normal "give me my assistant" behaviour ----------------
rem The scheduled task passes `new` (what the desktop shortcut always meant); a bare invocation
rem behaves the same way.
set "DSHW_VERB=%~1"
if "%DSHW_VERB%"=="" set "DSHW_VERB=new"

"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%DSHW%" ensure
"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%DSHW%" %DSHW_VERB%

endlocal
