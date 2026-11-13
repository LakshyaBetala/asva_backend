@echo off
rem Local mic call that is logged to the CRM. Works from any folder.
rem   local-call <lead-id> [en-IN^|hi-IN^|ta-IN]
rem The agent reads .env from this folder and its code lives in .\src, hence the cd + PYTHONPATH.
if "%~1"=="" (
  echo Usage: local-call ^<lead-id^> [en-IN^|hi-IN^|ta-IN]
  echo Copy the lead id from the CRM URL: http://localhost:3000/leads/^<lead-id^>
  exit /b 1
)
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "CALL_LANG=%~2"
if "%CALL_LANG%"=="" set "CALL_LANG=en-IN"
python -m voice_agent.local_audio --lead-id %1 --lang %CALL_LANG% --record-seconds 0
