# Starts the local stack: Supabase in Docker (DB + auth + REST + realtime) and the CRM on :3000.
# Then place a voice call with:  cd apps/pipecat-agent; python -m voice_agent.local_audio --lead-id <uuid> --record-seconds 0
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Starting Docker Desktop..."
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    for ($i = 0; $i -lt 60; $i++) { Start-Sleep 3; docker info *> $null; if ($LASTEXITCODE -eq 0) { break } }
}

Push-Location packages/db
npx -y supabase@2.54.11 start --workdir . -x edge-runtime,vector,imgproxy,logflare,supavisor
Pop-Location

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot'; npx -y pnpm@9.15.9 --filter @ai-voice/web dev"
Write-Host "CRM starting at http://localhost:3000  (login admin@spc.test / demo-password-change-me)"
