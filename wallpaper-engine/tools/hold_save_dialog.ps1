param(
    [string]$OutputDir,
    [string]$FileName,
    [int]$TimeoutMinutes = 2
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$logPath = Join-Path $OutputDir 'native_hook_hold_backend.log'
"$(Get-Date -Format o) hold backend started file=$FileName" |
    Set-Content -LiteralPath $logPath -Encoding UTF8
$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 250
}
"$(Get-Date -Format o) hold backend ended" |
    Add-Content -LiteralPath $logPath -Encoding UTF8
