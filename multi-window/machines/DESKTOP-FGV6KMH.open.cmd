@echo off
rem ============================================================================
rem Her desktop launcher -- the thing the desktop shortcut actually runs.
rem
rem THE CHAIN, and there is exactly one of each link:
rem   shortcut  ->  THIS FILE  ->  scheduled task "Yocheved DSH Window"
rem             ->  DESKTOP-FGV6KMH.launch.cmd  ->  dshw.ps1 ensure + new
rem
rem WHY THE TASK IS IN THE MIDDLE. A window created by a process that is not inside her interactive
rem session is created on no desktop anybody can see. The task runs with an Interactive logon type, so
rem it is inside her session by construction, whatever launched this file. (The shortcut itself no
rem longer asks for elevation -- nothing here needs administrator rights -- so the session-0 trap is
rem gone as well; the task is kept because it is independent of who clicks.)
rem
rem WHY THIS FILE DOES NOT WIN32-LAUNCH ANYTHING ITSELF. It used to be the only path, and it was the
rem path that broke: it invoked dshw.ps1 without the machine's own config, so the launcher ran against
rem the OWNER's directories, failed to write its own log, and closed -- a console flash with no window
rem (2026-09-15). The environment and the config path now live in ONE place, launch.cmd, and every
rem entry point funnels through it.
rem
rem IT REPORTS. A click that silently does nothing is the failure being fixed here, so this window
rem waits, then says what happened and where the log is.
rem ============================================================================

setlocal
set "TASK=Yocheved DSH Window"
set "HERE=%~dp0"
set "LOG=C:\Users\cheve\.dsh\multi-window\logs\launcher.log"

echo Starting the shop assistant...
echo.

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
