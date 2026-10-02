param(
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'
$pluginRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $pluginRoot
$configPath = Join-Path $pluginRoot 'config.json'
$runnerPath = Join-Path $pluginRoot 'run_wallpaper_backup_plugin.ps1'
$taskName = 'WallpaperEngineArchivePlugin'

$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($config.activation_mode -ne 'apply') {
    throw 'Startup task installation is blocked while config activation_mode is not apply.'
}
if (-not (Test-Path -LiteralPath $runnerPath -PathType Leaf)) {
    throw "Plugin runner is missing: $runnerPath"
}

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $backupDir = Join-Path $projectRoot "database\backups\$stamp\plugin_startup_task"
    if (-not $WhatIf) {
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath (Join-Path $backupDir "$taskName.xml") -Encoding UTF8
    }
}

$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runnerPath`" -Apply"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 4) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if ($WhatIf) {
    Write-Host "WHATIF: register $taskName for $env:USERNAME"
    Write-Host "WHATIF: $arguments"
    exit 0
}

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Once-per-boot Wallpaper Engine Workshop archive plugin.' -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State, TaskPath
