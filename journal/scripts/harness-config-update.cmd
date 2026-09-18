@echo off
rem ============================================================================
rem harness-update.cmd — bring THIS machine's harness configuration up to date.
rem
rem WHY THIS EXISTS. Until now the checkout under code\harness-config was a copy of
rem files, not a git repository, so nothing could ever update it: the HarnessSync task
rem dutifully re-applied whatever was already on disk every 15 minutes, and the machine
rem drifted a day and a half behind the fleet (measured 2026-09-15 - the launcher ran
rem against the owner's directories, and a fix had to be copied here by hand).
rem
rem THE TRANSPORT IS GITHUB OVER HTTPS, deliberately. This machine sits behind the
rem Techloq filter on a mobile connection: the authority's git remote (ssh) is blocked
rem outright and Tailscale will not come up, while https://github.com works. A public
rem mirror needs no credential on disk at all, which matters because this box has
rem already leaked one account-wide token through the git credential manager.
rem
rem TWO STEPS, IN THIS ORDER, because they are different guarantees:
rem   1. FETCH  - get the fleet's committed configuration onto this disk.
rem   2. APPLY  - harness-sync.mjs turns it into ~/.dsh (settings, presets, plugins),
rem               self-checks what it wrote, and reports what it changed.
rem A failure in 1 must not stop 2: applying the config already on disk is still the
rem right thing to do, and reporting "nothing to do" would hide a stale machine.
rem
rem Nothing here deletes anything. `git merge --ff-only` refuses rather than
rem overwrites, and harness-sync never removes a preset it did not create.
rem ============================================================================
setlocal
set "HC=C:\Users\cheve\code\harness-config"
set "LOG=C:\Users\cheve\.dsh\logs\harness-update.log"
set "DSH_HOME=C:\Users\cheve\.dsh"
set "USERPROFILE=C:\Users\cheve"
set "HOME=C:\Users\cheve"
set "GIT_TERMINAL_PROMPT=0"

set "NODE="
for %%N in ("C:\Users\cheve\node-v24.12.0-win-x64\node.exe" "C:\Program Files\nodejs\node.exe") do (
  if not defined NODE if exist %%N set "NODE=%%~fN"
)
if not defined NODE set "NODE=node"

>>"%LOG%" echo.
>>"%LOG%" echo [%DATE% %TIME%] === harness-update start (host=%COMPUTERNAME%) ===

cd /d "%HC%"
if not exist "%HC%\.git" (
  >>"%LOG%" echo [%DATE% %TIME%] NOT A CHECKOUT: %HC% has no .git - fetch skipped, applying what is on disk
  goto :apply
)

rem --- 1. FETCH: the fleet's committed configuration -------------------------------------------
where git >nul 2>&1
if errorlevel 1 (
  >>"%LOG%" echo [%DATE% %TIME%] git not on PATH - fetch skipped
  goto :apply
)

>>"%LOG%" echo [%DATE% %TIME%] before: %HC%
git rev-parse --short HEAD >>"%LOG%" 2>&1
>>"%LOG%" echo [%DATE% %TIME%] fetching origin (https)
rem --deepen, NOT a one-commit shallow fetch, and the reason is the check below: with
rem only one commit of history git cannot tell whether this machine's current commit is
rem an ancestor of the published one, so the ancestry guard fired on a machine that had
rem nothing to lose and the config stayed stale (measured here 2026-09-15, first run of
rem this file). A few hundred commits of text is a trivial download and makes the
rem history real enough for merge-base, for a journal, and for anyone auditing later.
git fetch --deepen=200 origin master >>"%LOG%" 2>&1
if errorlevel 1 (
  >>"%LOG%" echo [%DATE% %TIME%] FETCH FAILED - staying on the commit already on disk
  goto :apply
)

rem WHY `reset --hard` AND NOT `merge --ff-only`, measured here 2026-09-15: the shallow
rem fetch above has no common ancestor with the branch this machine already holds, so
rem `git merge` refuses with "unrelated histories" and the machine silently stays old --
rem the exact failure this file exists to end. The ancestry check below does the one job
rem `--ff-only` was there for (refuse to discard a commit the fleet does not have) and
rem then moves the branch, which is a fast-forward by construction.
rem
rem Safe for this machine's own files because they are NOT tracked: the task wrappers,
rem hidden-tasks\*.vbs and .env are untracked or ignored, so a reset cannot touch them
rem (verified on this box before this line was written).
rem
rem FLAT, NOT NESTED, on purpose: the first version nested four levels of `if (...)` with
rem a caret-escaped `->` inside, and cmd.exe died with "- was unexpected at this time"
rem before doing anything at all. A batch file is not a language to be clever in.
for /f %%H in ('git rev-parse HEAD 2^>nul') do set "LOCALHEAD=%%H"
for /f %%H in ('git rev-parse FETCH_HEAD 2^>nul') do set "REMOTEHEAD=%%H"
if "%LOCALHEAD%"=="%REMOTEHEAD%" goto :uptodate
git merge-base --is-ancestor HEAD FETCH_HEAD
if errorlevel 1 goto :localcommits
git reset --hard FETCH_HEAD >>"%LOG%" 2>&1
if errorlevel 1 goto :resetfailed
>>"%LOG%" echo [%DATE% %TIME%] advanced %LOCALHEAD% to %REMOTEHEAD%
goto :apply

:uptodate
>>"%LOG%" echo [%DATE% %TIME%] already up to date: %LOCALHEAD%
goto :apply

:localcommits
>>"%LOG%" echo [%DATE% %TIME%] LOCAL COMMITS EXIST HERE - %LOCALHEAD% is not an ancestor of %REMOTEHEAD%; nothing was changed
goto :apply

:resetfailed
>>"%LOG%" echo [%DATE% %TIME%] reset FAILED - staying on %LOCALHEAD%


:apply
rem --- 2. APPLY ---------------------------------------------------------------------------------
>>"%LOG%" echo [%DATE% %TIME%] applying configuration to %DSH_HOME%
"%NODE%" "%HC%\scripts\harness-sync.mjs" --repo "%HC%" --dsh-home "%DSH_HOME%" --hostname "%COMPUTERNAME%" >>"%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
>>"%LOG%" echo [%DATE% %TIME%] harness-sync exit=%RC% === harness-update end ===

rem A scheduled task's exit code is the only thing an operator sees at a glance, so the
rem apply step decides it - the fetch already reported itself in the log.
endlocal & exit /b %RC%
