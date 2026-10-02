param(
    [string]$WallpaperRoot,
    [Parameter(Mandatory = $true)]
    [string[]]$WorkshopId,
    [string[]]$ScenePkg,
    [string]$MpkgOutputDir = 'D:\7_Video\20_Wallpaper Engine\temp\mpkg',
    [string]$Mp4OutputDir = 'D:\7_Video\20_Wallpaper Engine\temp\converted',
    [string]$RePKGPath = 'D:\0_Vital document\tools\RePKG-GUI_v1.0.1\RePKG.exe',
    [string]$LoopAnalysisPath,
    [switch]$IncludeLikelyLoopOverrides,
    [switch]$PreserveInteractiveEffects,
    [switch]$Force,
    [int]$TimeoutMinutes = 90,
    [string]$CdpEndpoint
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StableSaveAsScript = Join-Path $ScriptDir 'test_saveas_all_wallpaperui.ps1'
$ExtractScript = Join-Path $ScriptDir 'extract_mpkg_mp4.ps1'

foreach ($required in @($StableSaveAsScript, $ExtractScript, $RePKGPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required file not found: $required"
    }
}

New-Item -ItemType Directory -Path $MpkgOutputDir, $Mp4OutputDir -Force | Out-Null

$targets = @()
if ($WorkshopId -and $WorkshopId.Count -gt 0) {
    foreach ($id in $WorkshopId) {
        foreach ($part in ([string]$id -split ',')) {
            if (-not [string]::IsNullOrWhiteSpace($part)) {
                $targets += $part.Trim()
            }
        }
    }
}
if ($ScenePkg -and $ScenePkg.Count -gt 0) {
    foreach ($path in $ScenePkg) {
        $full = [System.IO.Path]::GetFullPath(($path -replace '/', '\'))
        $targets += (Split-Path -Leaf (Split-Path -Parent $full))
    }
}
if ($targets.Count -eq 0) {
    $targets = @('3164915229', '3803169219')
}

$results = @()
$sourceRoot = 'E:\1_Game\steam\steamapps\workshop\content\431960'
foreach ($id in $targets) {
    $mpkg = Join-Path $MpkgOutputDir "$id.mpkg"
    if ($id -notmatch '^\d+$') {
        throw "WorkshopId must be numeric: $id"
    }
    $sourceDir = Join-Path $sourceRoot $id
    foreach ($requiredSource in @('project.json', 'scene.pkg')) {
        $requiredPath = Join-Path $sourceDir $requiredSource
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw "Workshop source is incomplete for $id. Missing: $requiredPath"
        }
    }
    $converted = Join-Path $Mp4OutputDir $id
    $stableArgs = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', $StableSaveAsScript,
        '-WorkshopId', $id,
        '-OutputDir', $MpkgOutputDir,
        '-ConvertedOutputDir', $converted,
        '-TimeoutMinutes', ([Math]::Max(20, $TimeoutMinutes))
    )
    if ($LoopAnalysisPath) {
        $stableArgs += @('-LoopAnalysisPath', ([System.IO.Path]::GetFullPath($LoopAnalysisPath)))
    }
    if ($IncludeLikelyLoopOverrides) { $stableArgs += '-IncludeLikelyLoopOverrides' }
    if ($PreserveInteractiveEffects) { $stableArgs += '-PreserveInteractiveEffects' }
    if ($Force -and (Test-Path -LiteralPath $mpkg -PathType Leaf)) {
        Remove-Item -LiteralPath $mpkg -Force
    }

    $jsonText = & powershell.exe @stableArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Stable MPKG→MP4 orchestration failed for $id with exit code $LASTEXITCODE."
    }
    if (-not (Test-Path -LiteralPath $mpkg -PathType Leaf)) {
        throw "Expected MPKG was not created after verified Save As flow: $mpkg"
    }
    $canonicalMp4 = Join-Path $converted "$id.mp4"
    if (-not (Test-Path -LiteralPath $canonicalMp4 -PathType Leaf)) {
        throw "Expected verified MP4 was not created: $canonicalMp4"
    }
    $results += ($jsonText | Out-String)
}

$results | ForEach-Object { Write-Host $_.Trim() }
