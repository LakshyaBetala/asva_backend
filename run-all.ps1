# One command for the whole local demo: clean up old runs, start DB + CRM, open the lead, start a voice call.
#   run-all                      -> calls the newest lead that has no call yet, in English
#   run-all <lead-id> hi-IN      -> calls that lead, starting in Hindi
#   run-all -SkipCall            -> only (re)start DB + CRM
param([string]$LeadId = "", [string]$Lang = "en-IN", [switch]$SkipCall)
$root = $PSScriptRoot

Write-Host "[1/5] Stopping previous CRM and voice-agent runs..."
Get-CimInstance Win32_Process -Filter "Name='node.exe' OR Name='python.exe' OR Name='powershell.exe' OR Name='cmd.exe'" |
    Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match '@ai-voice/web dev|next dev -p 3000|voice_agent\.local_audio' } |
    ForEach-Object { taskkill /PID $_.ProcessId /T /F *> $null }

Write-Host "[2/5] Starting Docker and the local database..."
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    for ($i = 0; $i -lt 60; $i++) { Start-Sleep 3; docker info *> $null; if ($LASTEXITCODE -eq 0) { break } }
}
Push-Location "$root\packages\db"
npx -y supabase@2.54.11 start --workdir . -x edge-runtime,vector,imgproxy,logflare,supavisor | Select-String "API URL|running" | ForEach-Object { "      $_" }
Pop-Location

Write-Host "[3/5] Starting the CRM (own window)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "`$host.UI.RawUI.WindowTitle='ASVA CRM - localhost:3000'; cd '$root'; npx -y pnpm@9.15.9 --filter @ai-voice/web dev"
$ready = $false
for ($i = 0; $i -lt 60 -and -not $ready; $i++) {
    Start-Sleep 2
    try { $ready = (Invoke-WebRequest http://localhost:3000/login -TimeoutSec 5 -UseBasicParsing).StatusCode -eq 200 } catch {}
}
if (-not $ready) { Write-Host "CRM did not come up; check the 'ASVA CRM' window."; exit 1 }
Write-Host "      CRM ready: http://localhost:3000  (login admin@spc.test / demo-password-change-me)"
if ($SkipCall) { exit 0 }

Write-Host "[4/5] Choosing the lead..."
if (-not $LeadId) {
    $LeadId = (docker exec supabase_db_ai-voice psql -U postgres -tAc "select l.id from public.leads l left join public.calls c on c.lead_id = l.id where c.id is null order by l.created_at desc limit 1").Trim()
}
Write-Host "      Lead page: http://localhost:3000/leads/$LeadId"
Start-Process "http://localhost:3000/leads/$LeadId"

Write-Host "[5/5] Starting the voice call. ENTER = talk, ENTER = stop, q = end call."
& "$root\apps\pipecat-agent\local-call.cmd" $LeadId $Lang
