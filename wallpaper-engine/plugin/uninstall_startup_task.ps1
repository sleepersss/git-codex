param(
    [switch]$ConfirmRemoval
)

$ErrorActionPreference = 'Stop'
$taskName = 'WallpaperEngineArchivePlugin'
if (-not $ConfirmRemoval) {
    throw 'Pass -ConfirmRemoval to remove the startup task. Project files and archive data are never deleted.'
}
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "$taskName is not installed."
    exit 0
}
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host "$taskName removed. Project files, database, reports and archives were not changed."
