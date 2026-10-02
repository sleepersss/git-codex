param(
    [string]$WallpaperRoot,
    [switch]$RestartBrowseUi
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$BackupDir = Join-Path $ProjectRoot 'runtime\backups'

function Get-SteamRoots {
    $roots = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in @(
        (Join-Path ${env:ProgramFiles(x86)} 'Steam'),
        (Join-Path ${env:ProgramFiles} 'Steam'),
        (Get-ItemPropertyValue -Path 'HKCU:\Software\Valve\Steam' -Name SteamPath -ErrorAction SilentlyContinue),
        (Get-ItemPropertyValue -Path 'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam' -Name InstallPath -ErrorAction SilentlyContinue),
        (Get-ItemPropertyValue -Path 'HKLM:\SOFTWARE\Valve\Steam' -Name InstallPath -ErrorAction SilentlyContinue)
    )) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        $full = [System.IO.Path]::GetFullPath(($candidate -replace '/', '\'))
        if ((Test-Path -LiteralPath $full) -and -not $roots.Contains($full)) { $roots.Add($full) }
    }
    foreach ($steam in @($roots)) {
        $vdf = Join-Path $steam 'steamapps\libraryfolders.vdf'
        if (-not (Test-Path -LiteralPath $vdf)) { continue }
        foreach ($line in Get-Content -LiteralPath $vdf -ErrorAction SilentlyContinue) {
            if ($line -match '^\s*"path"\s+"([^"]+)"') {
                $library = ($matches[1] -replace '\\\\', '\')
                if ((Test-Path -LiteralPath $library) -and -not $roots.Contains($library)) { $roots.Add($library) }
            }
        }
    }
    return @($roots)
}

function Find-WallpaperRoot {
    if ($WallpaperRoot) {
        $full = [System.IO.Path]::GetFullPath(($WallpaperRoot -replace '/', '\'))
        if (Test-Path -LiteralPath (Join-Path $full 'ui\dist\scripts\scripts.js')) { return $full }
        throw "Wallpaper Engine UI bundle not found under $full"
    }
    foreach ($steam in Get-SteamRoots) {
        $candidate = Join-Path $steam 'steamapps\common\wallpaper_engine'
        if (Test-Path -LiteralPath (Join-Path $candidate 'ui\dist\scripts\scripts.js')) { return $candidate }
    }
    throw 'Could not locate Wallpaper Engine.'
}

$root = Find-WallpaperRoot
$scriptsPath = Join-Path $root 'ui\dist\scripts\scripts.js'
$apputilPath = Join-Path $root 'bin\apputil32.exe'
$wallpaper32Path = Join-Path $root 'wallpaper32.exe'

Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match 'saveas_autosaver|export_wallpaper_mpkg|CODEX_AUTOMATED'
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

$marker = 'CODEX_AUTOMATED_MPKG_EXPORT_BEGIN|CODEX_MPKG_EXPORT_INJECTION_BEGIN|CODEX_SINGLE_MPKG_EXPORT_INJECTION_BEGIN|codex-mpkg'
$hasMarker = Select-String -LiteralPath $scriptsPath -Pattern $marker -Quiet
if ($hasMarker) {
    $backup = Get-ChildItem -LiteralPath $BackupDir -Filter 'scripts.js.*.backup' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $backup) {
        throw "scripts.js contains Codex marker but no backup was found in $BackupDir"
    }
    Copy-Item -LiteralPath $backup.FullName -Destination $scriptsPath -Force
    Write-Host "Restored scripts.js from $($backup.FullName)"
} else {
    Write-Host 'No known Codex marker found in scripts.js.'
}

$stillHasMarker = Select-String -LiteralPath $scriptsPath -Pattern $marker -Quiet
Write-Host "Marker present after repair: $stillHasMarker"
if ($stillHasMarker) { throw 'Repair failed: marker remains in scripts.js.' }

Write-Host 'Leaving wallpaper32/wallpaper64/wallpaperui running.'

if ($RestartBrowseUi) {
    Write-Host 'RestartBrowseUi ignored: Wallpaper Engine background and browse UI are never closed by repair.'
}
