@echo off
rem Whole local demo in one command (see run-all.ps1). Usage: run-all [lead-id] [en-IN^|hi-IN^|ta-IN]
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-all.ps1" %*
rem Keep the window open when started by double-click, so the call summary stays readable.
pause
