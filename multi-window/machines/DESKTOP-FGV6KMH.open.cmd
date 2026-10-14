@echo off
rem ============================================================================
rem Her desktop launcher -- the thing the desktop shortcut actually runs.
rem
rem THE CHAIN, and there is exactly one of each link:
rem   shortcut  ->  THIS FILE  ->  scheduled task "Yocheved DSH Window"
rem             ->  DESKTOP-FGV6KMH.launch.cmd new  ->  dshw.ps1 ensure + new
rem
rem WHY THE TASK IS IN THE MIDDLE. A window created by a process that is not inside her interactive
rem session is created on no desktop anybody can see. The task runs with an Interactive logon type, so
rem it is inside her session by construction, whatever launched this file. (The shortcut itself does not
rem ask for elevation -- verified: no RunAsUser flag in the .lnk -- so the session-0 trap is gone too;
rem the task is kept because it is independent of who clicks.)
rem
rem WHY THIS FILE DOES NOT WIN32-LAUNCH ANYTHING ITSELF. It used to be the only path, and it was the
rem path that broke: it invoked dshw.ps1 without the machine's own config, so the launcher ran against
rem the OWNER's directories, failed to write its own log, and closed -- a console flash with no window
rem (2026-09-15). The environment and the config path now live in ONE place, launch.cmd, and every
rem entry point funnels through it.
rem
rem "OPEN MY ASSISTANT" MEANS ONE *WORKING* WINDOW, AND SHE CAN SEE IT. Measured 2026-09-15: the
rem task's verb is `new`, which picks the first slot with no live window -- so clicking the shortcut
rem with a window already open opened a SECOND window in profile w2, and every later click added
rem another. That question belongs here, where the click is. But "already open" was answered by
rem counting Edge processes, which is not the same question as "is the page in it authenticated
rem against the engine running now" -- and the answer was never RAISED, only printed. Revised
rem 2026-10-13 (see the long note further down): a live window is brought to the FRONT, a stale one
rem is replaced rather than reported, and only a genuinely live window suppresses a new one. The `+`
rem control is still how she asks for another window, and it reaches launch.cmd directly.
rem
rem IT REPORTS. A click that silently does nothing is the failure being fixed here, so this window waits,
rem then says what happened and where the log is.
rem ============================================================================

setlocal
set "TASK=Yocheved DSH Window"
set "HERE=%~dp0"
set "LOG=C:\Users\cheve\.dsh\multi-window\logs\launcher.log"

echo Starting the shop assistant...
echo.

rem WHAT THIS ASKS NOW, AND WHY IT CHANGED (2026-10-13).
rem
rem It used to ask windowcount.ps1 -- "how many Edge `--app=` processes are alive for this profile" --
rem and treat a non-zero answer as "she already has a working assistant". That is a statement about
rem PROCESSES, not about whether the page inside them is authenticated against the engine running
rem NOW. The engine mints a NEW launch token on every start and a window keeps the token it was born
rem with, so a window that outlived one engine restart renders "dsh web authentication required" --
rem and was still counted. The click then took the "already open" branch, opened nothing, RAISED
rem nothing (no verb in dshw has ever been able to raise a window), and she was left looking at a
rem dead or invisible window with the one action that would have fixed it refused by design.
rem That is the fault behind "it keeps stopping to work".
rem
rem windowstate.ps1 asks the real question: it takes each window's OWN token and makes a REAL request
rem to the engine. 401 = that window is dead. A refused connection = no engine to judge against, so
rem the answer is "unknown", never "dead" -- otherwise a healthy window would be duplicated.
set "TOTAL=0"
set "LIVE=0"
set "DEAD=0"
set "UNREACH=0"
for /f "tokens=1,2,3,4" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%DESKTOP-FGV6KMH.windowstate.ps1" -Summary 2^>nul') do (
  set "TOTAL=%%A"
  set "LIVE=%%B"
  set "DEAD=%%C"
  set "UNREACH=%%D"
)

rem Engine down and windows present: that is "cannot tell", not "broken". Bring the engine up and
rem ask again, so a perfectly good window is never mistaken for a dead one and duplicated.
if "%LIVE%"=="0" if not "%UNREACH%"=="0" (
  call "%HERE%DESKTOP-FGV6KMH.launch.cmd" ensure >nul
  for /f "tokens=1,2,3,4" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%DESKTOP-FGV6KMH.windowstate.ps1" -Summary 2^>nul') do (
    set "TOTAL=%%A"
    set "LIVE=%%B"
    set "DEAD=%%C"
    set "UNREACH=%%D"
  )
)

if "%LIVE%"=="0" goto no_live_window

rem --- A WORKING WINDOW EXISTS ---
rem Still check the engine (a window onto a dead engine shows nothing), then BRING THE WINDOW TO THE
rem FRONT. A window she cannot see is the same to her as no window at all, and raising it is the
rem half that was missing from this launcher entirely.
rem
rem NOTE ON SHAPE: this is deliberately NOT an `if (...)` block with a set-then-read inside it.
rem `set "X=0"` followed by `if "%X%"=="0"` in the SAME parenthesised block reads the value from
rem before the set, because cmd expands %X% when the block is parsed. `if errorlevel N` is a
rem run-time test, so it is used here instead, and the branch is taken with goto.
call "%HERE%DESKTOP-FGV6KMH.launch.cmd" ensure >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%DESKTOP-FGV6KMH.focuswindow.ps1" -Quiet >nul 2>&1
if errorlevel 1 (
  echo Your assistant is already open ^(%LIVE% working window^(s^)^).
  echo It could not be brought to the front automatically -- look for the Edge window,
  echo or use the + button to open another.
) else (
  echo Brought your assistant to the front. ^(%LIVE% working window^(s^)^)
)
timeout /t 4 /nobreak >nul
endlocal
exit /b 0

:no_live_window
rem Live = 0. Either nothing is open, or what is open is left over from an earlier engine start and
rem its token no longer authenticates. Say WHICH -- the old code said "already open" over a 401 page,
rem and that one sentence is what made this fault take eight days to be reported. Then fall through
rem and open a window carrying a token that DOES authenticate. That is also a DIFFERENT url, which is
rem why Chromium will create a window here rather than focusing the stale one: replaying an identical
rem `--app=` url is a measured no-op that just focuses the existing browser.
if not "%DEAD%"=="0" (
  echo Your assistant window is out of date -- it was left over from an earlier start.
  echo Opening a fresh one. You can close the old window afterwards.
  echo.
)

schtasks /run /tn "%TASK%" >nul 2>&1
if errorlevel 1 (
  rem The task could not be started at all. Do not just report it -- this console is already inside her
  rem session, so run the launcher here instead and let her get an assistant.
  echo The launcher task could not be started; starting the assistant directly...
  call "%HERE%DESKTOP-FGV6KMH.launch.cmd" new
  goto report
)

rem Wait (bounded) for the task to leave the Running state, so "it finished" means something.
set /a TRIES=0
:wait
set /a TRIES+=1
set "STATUS="
for /f "tokens=*" %%S in ('schtasks /query /tn "%TASK%" /fo list 2^>nul ^| findstr /i "Status"') do set "STATUS=%%S"
echo %STATUS% | findstr /i "Running" >nul
if not errorlevel 1 (
  if %TRIES% lss 45 (
    timeout /t 2 /nobreak >nul
    goto wait
  )
)

:report
rem VERIFY, DO NOT ASSUME. Count the Edge app windows actually running against her harness. "The task
rem exited 0" is not evidence that a window appeared -- measured on this box, a task can report 0 while
rem doing nothing at all.
set "WINDOWS=0"
for /f %%C in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%DESKTOP-FGV6KMH.windowcount.ps1" 2^>nul') do set "WINDOWS=%%C"
echo.
if "%WINDOWS%"=="0" (
  echo No assistant window appeared. The reason is written to:
  echo   %LOG%
  echo   C:\Users\cheve\.dsh\multi-window\logs\open.log
  echo.
  echo This window closes itself in 20 seconds.
  timeout /t 20 /nobreak >nul
) else (
  echo The assistant is open (%WINDOWS% window^(s^)^).
  timeout /t 3 /nobreak >nul
)
endlocal
