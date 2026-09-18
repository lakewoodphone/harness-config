@echo off
rem journal.cmd — run the journal tool from anywhere on Windows (cmd.exe or PowerShell).
rem
rem   journal.cmd status
rem   journal.cmd newest handoff 2
rem   journal.cmd show L173
rem   journal.cmd search "stale database" --kind lessons
rem
rem The tool infers the journal root from its own location, so this only launches it.
setlocal
set "TOOL=%~dp0..\journal.py"
if not exist "%TOOL%" (
    echo journal.cmd: cannot find journal.py next to %~f0 1>&2
    exit /b 2
)

if defined JOURNAL_PYTHON (
    "%JOURNAL_PYTHON%" "%TOOL%" %*
    exit /b %ERRORLEVEL%
)

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 "%TOOL%" %*
    exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python "%TOOL%" %*
    exit /b %ERRORLEVEL%
)

echo journal.cmd: no python3 on PATH ^(set JOURNAL_PYTHON to one^) 1>&2
exit /b 2
