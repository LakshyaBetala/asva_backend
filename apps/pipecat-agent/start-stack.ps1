# Start the Priya calling stack: ngrok tunnel + the agent server.
# Run this ONCE from apps\pipecat-agent. Each opens in its own window.
# Then place calls with:  .\call.ps1 <number> [name] [lang]

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Starting ngrok on port 8080 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'ngrok http 8080'

Start-Sleep -Seconds 3
Write-Host "Starting the agent server ..." -ForegroundColor Cyan
# The server command lives in run-server.ps1 (its own file — nested quoting
# through Start-Process is unreliable). That script pins PYTHONPATH to this
# repo's src and refuses to boot if another voice_agent package would load
# (the old ai_voice SPC editable install shadowed us on 2026-06-11).
Start-Process powershell -WorkingDirectory $here -ArgumentList '-NoExit', '-File', (Join-Path $here 'run-server.ps1')

Write-Host ""
Write-Host "Two windows opened: ngrok + agent." -ForegroundColor Green
Write-Host "Check the agent window's FIRST line: voice_agent -> ...almmatix_voice\..." -ForegroundColor Yellow
Write-Host "1) In the ngrok window, copy the https URL." -ForegroundColor Yellow
Write-Host "   If it changed since last time, update the Voicebot applet URL in Exotel:" -ForegroundColor Yellow
Write-Host "   wss://<that-host>/exotel/stream/live   then Save." -ForegroundColor Yellow
Write-Host "2) Then call:  .\call.ps1 9876543210 Suresh ta" -ForegroundColor Green
