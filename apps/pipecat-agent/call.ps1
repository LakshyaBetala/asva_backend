# Place a Priya call. Usage:
#   .\call.ps1 9876543210                                   (default Hindi, SPC tenant)
#   .\call.ps1 9876543210 Suresh ta                         (Tamil, SPC tenant)
#   .\call.ps1 9876543210 Naman hi demo-broker-tenant       (Hindi, real estate broker)
#   .\call.ps1 +919876543210 Suresh en spc-tenant
#
# Args: <number> [name] [lang] [tenant]
#   lang   accepts: hi | ta | en  OR  hi-IN | ta-IN | en-IN
#   tenant defaults to spc-tenant; use demo-broker-tenant for the real estate brain.
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$To,
    [Parameter(Position = 1)][string]$Name = "Sir",
    [Parameter(Position = 2)][string]$Lang = "hi-IN",
    [Parameter(Position = 3)][string]$Tenant = "spc-tenant"
)

# Normalise lang shortcuts so Tamil calls are one keystroke.
$lcLang = $Lang.ToLower()
switch ($lcLang) {
    "ta"      { $Lang = "ta-IN" }
    "tamil"   { $Lang = "ta-IN" }
    "ta-in"   { $Lang = "ta-IN" }
    "hi"      { $Lang = "hi-IN" }
    "hindi"   { $Lang = "hi-IN" }
    "hi-in"   { $Lang = "hi-IN" }
    "en"      { $Lang = "en-IN" }
    "english" { $Lang = "en-IN" }
    "en-in"   { $Lang = "en-IN" }
    default   { $Lang = $lcLang }
}
if ($Lang -notin @("hi-IN", "ta-IN", "en-IN")) {
    Write-Host "Unsupported lang '$Lang'. Use ta / hi / en (or ta-IN / hi-IN / en-IN)." -ForegroundColor Red
    exit 1
}

# Normalise: bare 10-digit Indian number -> +91XXXXXXXXXX. Keep +<...> as-is.
if ($To -notmatch '^\+') {
    $digits = $To -replace '\D', ''
    if ($digits.Length -eq 10) { $To = "+91$digits" } else { $To = "+$digits" }
}

$body = @{ to = $To; lead_first_name = $Name; lang_hint = $Lang; tenant_id = $Tenant } | ConvertTo-Json -Compress
Write-Host "Calling $To  (name=$Name, lang=$Lang, tenant=$Tenant) ..." -ForegroundColor Cyan
try {
    $resp = Invoke-RestMethod -Method Post -Uri "http://localhost:8080/exotel/calls" `
        -ContentType "application/json" -Body $body -TimeoutSec 20
    Write-Host "OK  call_sid=$($resp.call_sid)  status=$($resp.status)" -ForegroundColor Green
}
catch {
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Is the agent running? Start it with .\start-stack.ps1" -ForegroundColor Yellow
}
