# Agent server runner — spawned by start-stack.ps1 (or run directly).
# Pins PYTHONPATH to THIS repo's src so a stray `pip install -e` of another
# voice_agent (the old ai_voice SPC repo) can never shadow it again, and
# refuses to boot if the wrong package would load.

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
$env:PYTHONPATH = Join-Path $here 'src'

python (Join-Path $here 'check_import.py')
if ($LASTEXITCODE -ne 0) {
    Write-Host "Refusing to start: wrong voice_agent package on sys.path." -ForegroundColor Red
    exit 1
}

python -m uvicorn voice_agent.server:app --host 0.0.0.0 --port 8080 --env-file .env
