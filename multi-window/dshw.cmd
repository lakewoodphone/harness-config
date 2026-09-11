@echo off
rem dshw - the control command for the DSH multi-window setup.
rem Put this directory on PATH, or call it directly by path.
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0dshw.ps1" %*
