param(
    [switch]$Watch
)

$Source = Join-Path $PSScriptRoot "addon\service.gammaseries"
$Destination = Join-Path $env:APPDATA "Kodi\addons\service.gammaseries"

function Deploy-Addon {
    if (-not (Test-Path $Destination)) {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    }
    robocopy $Source $Destination /MIR /XD __pycache__ /XF *.pyc lastdate.tmp *.bkp /NFL /NDL /NJH /NJS /NC /NS | Out-Null
    Write-Host "$(Get-Date -Format 'HH:mm:ss') - Addon deploye vers $Destination (redemarre Kodi pour appliquer)" -ForegroundColor Green
}

Deploy-Addon

if ($Watch) {
    Write-Host "Mode watch actif (verification toutes les 2s) - Ctrl+C pour arreter" -ForegroundColor Cyan
    while ($true) {
        Start-Sleep -Seconds 2
        Deploy-Addon
    }
}
