@echo off
rem ============================================================================
rem DSH Windows - the one double-click that starts the fleet and opens a window.
rem
rem WHY THIS IS A .cmd AND NOT THE SHORTCUT ITSELF
rem A .lnk can carry a "run as administrator" flag, but Windows refuses to elevate a
rem .cmd/.bat directly - it needs an executable, so the shell shows "This app can't
rem run" or silently runs it unelevated. A shortcut may, however, point at cmd.exe
rem and pass this file as an argument, and then the flag applies to cmd.exe, which
rem elevates the whole tree: this script, the pwsh it spawns, the DSH engine, and
rem every Edge window it opens. That is what the shortcut on each desktop does.
rem
rem WHAT IT DOES
rem   1. if the engine is not listening, start it (dshw up - no windows)
rem   2. open ONE window (dshw new)
rem The second step is the point: double-clicking a shortcut must end with DSH on
rem screen, not with a silent engine and nothing to look at.
rem ============================================================================

setlocal
set "DSHW_DIR=%~dp0"
set "DSHW=%DSHW_DIR%dshw.ps1"
set "PWSH=%ProgramFiles%\PowerShell\7\pwsh.exe"
if not exist "%PWSH%" set "PWSH=pwsh.exe"

"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%DSHW%" up
"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%DSHW%" new

endlocal
