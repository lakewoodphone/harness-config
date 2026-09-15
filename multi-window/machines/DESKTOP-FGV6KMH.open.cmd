@echo off
rem ============================================================================
rem Her desktop launcher -- the thing the shortcut actually runs.
rem
rem WHY THIS EXISTS INSTEAD OF CALLING dshw DIRECTLY
rem
rem The previous shortcut ran dshw.ps1 straight from cmd.exe. When the shortcut is
rem launched it is elevated, and an elevated process here runs in SESSION 0 -- the
rem service session, which has NO DESKTOP. The engine starts fine from there (it is
rem headless), but every browser window it asks for is created on a desktop nobody
rem can see. That is exactly the reported symptom: "allowed the uac prompt and
rem nothing opened". Verified: the launcher's own log showed the engine starting and
rem then stopping, and all 16 msedge processes were session 1 but launched as plain
rem `--profile-directory=Default` with no `--app=` URL, i.e. it never got as far as
rem the window.
rem
rem Windows will not let session 0 put a window on the interactive session. A
rem scheduled task CAN, because a task with an Interactive logon type runs INSIDE
rem the logged-on user's session. So this file does one thing: it starts the task
rem that already proved it works, waits for it, and exits.
rem
rem UAC NOTE: the engine and the window both now run as her, at her normal level.
rem There is nothing here that needs administrator rights -- the engine listens on
rem 127.0.0.1 and reads her own profile -- so the shortcut no longer asks for
rem elevation, and the launcher does not sit in a session-0 process tree.
rem ============================================================================

setlocal
set "TASK=Yocheved DSH Window"
set "LOG=C:\Users\cheve\.dsh\multi-window\logs\launcher.log"

echo Starting the shop assistant...
echo.

rem Start the task that runs in HER session, then wait for it to finish so this
rem window can report a real outcome instead of vanishing.
schtasks /run /tn "%TASK%" >nul 2>&1
if errorlevel 1 (
  echo The launcher task "%TASK%" could not be started.
  echo Its log is at %LOG%
  pause
  exit /b 1
)

rem Wait for the task to leave the Running state (bounded), so a failure is visible.
set /a TRIES=0
:wait
set /a TRIES+=1
for /f "tokens=*" %%S in ('schtasks /query /tn "%TASK%" /fo list 2^>nul ^| findstr /i "Status"') do set "STATUS=%%S"
echo %STATUS% | findstr /i "Running" >nul
if not errorlevel 1 (
  if %TRIES% lss 60 (
    timeout /t 2 /nobreak >nul
    goto wait
  )
)

echo Done. If no window appeared, the reason is in:
echo   %LOG%
echo.
echo This window closes itself in 5 seconds.
timeout /t 5 /nobreak >nul
endlocal
