param(
    [switch]$Apply,
    [switch]$SkipStartupWait,
    [switch]$ForceRescan,
    [switch]$PlanOnly
)

$ErrorActionPreference = 'Stop'
$pluginRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $pluginRoot
$entry = Join-Path $pluginRoot 'wallpaper_backup_plugin.mjs'
$config = Join-Path $pluginRoot 'config.json'

$arguments = @($entry, '--config', $config)
if ($Apply) { $arguments += '--apply' }
if ($SkipStartupWait) { $arguments += '--skip-startup-wait' }
if ($ForceRescan) { $arguments += '--force-rescan' }
if ($PlanOnly) { $arguments += '--plan-only' }

Push-Location $projectRoot
try {
    & node.exe @arguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}

