@echo off
rem ============================================================================
rem DSH - one double-click: elevated engine, then the windows you had open.
rem
rem WHY A .cmd AND NOT THE SHORTCUT ITSELF
rem A .lnk can carry a "run as administrator" flag, but Windows refuses to elevate a
rem .cmd/.bat directly - it needs an executable, so the shortcut targets cmd.exe and
rem carries the flag. cmd.exe then elevates this whole tree: this script, the pwsh it
rem spawns, the DSH engine, and every Edge window it opens.
rem
rem NOTHING HERE DELETES OR CLEANS ANYTHING
rem A reinstall of one plugin removed a DIFFERENT plugin's directory from the profile
rem and the owner could not launch DSH. Install steps copy files; a single file being
rem replaced is deleted one file at a time. Nothing recursive, ever.
rem
rem WHAT IT DOES, IN ORDER, EACH STEP VERIFIED
rem   1. dshw ensure  - is the engine answering? if not, start it and wait, with a
rem                    bounded retry. This is what stops the ERR_CONNECTION_REFUSED
rem                    the owner saw when a window was opened against a dead port.
rem   2. dshw restore - reopen exactly the windows that were open when DSH was last
rem                    closed. A window closed on purpose stays closed.
rem ============================================================================

setlocal
set "DSHW_DIR=%~dp0"
set "DSHW=%DSHW_DIR%dshw.ps1"
set "PWSH=%ProgramFiles%\PowerShell\7\pwsh.exe"
if not exist "%PWSH%" set "PWSH=pwsh.exe"

"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%DSHW%" ensure
"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%DSHW%" restore

endlocal
