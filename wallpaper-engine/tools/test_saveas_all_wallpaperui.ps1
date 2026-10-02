param(
    [ValidatePattern('^\d+$')]
    [Parameter(Mandatory = $true)]
    [string]$WorkshopId,
    [string]$OutputDir = 'D:\7_Video\20_Wallpaper Engine\temp\mpkg',
    [string]$ConvertedOutputDir,
    [int]$TimeoutMinutes = 20,
    [string]$LoopAnalysisPath,
    [switch]$IncludeLikelyLoopOverrides,
    [switch]$PreserveInteractiveEffects,
    [switch]$SkipRepackg
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Keep the Windows PowerShell child-process environment stable.
$processPath = [Environment]::GetEnvironmentVariable('Path', 'Process')
if ($null -ne $processPath) {
    [Environment]::SetEnvironmentVariable('PATH', $null, 'Process')
    [Environment]::SetEnvironmentVariable('Path', $processPath, 'Process')
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$wallpaperRoot = 'E:\1_Game\steam\steamapps\common\wallpaper_engine'
$exporter = Join-Path $PSScriptRoot 'export_wallpaper_mpkg.ps1'
$holdBackend = Join-Path $PSScriptRoot 'hold_save_dialog.ps1'
$controller = Join-Path $projectRoot 'temp\logs\save_dialog_controller_build\save_dialog_controller.exe'
$hookDll = Join-Path $projectRoot 'temp\logs\native_save_dialog_hook_build\save_dialog_hook.dll'
$hookManifest = Join-Path $projectRoot 'temp\logs\native_save_dialog_hook_build\current_hook_dll.txt'
$injector = Join-Path $projectRoot 'temp\logs\native_save_dialog_hook_build\save_dialog_injector.exe'
$controllerBuild = Join-Path $PSScriptRoot 'build_save_dialog_controller.ps1'
$hookBuild = Join-Path $PSScriptRoot 'build_native_save_dialog_hook.ps1'
$extractor = Join-Path $PSScriptRoot 'extract_mpkg_mp4.ps1'
$repkg = 'D:\0_Vital document\tools\RePKG-GUI_v1.0.1\RePKG.exe'
$scriptsPath = Join-Path $wallpaperRoot 'ui\dist\scripts\scripts.js'

$targetDir = [IO.Path]::GetFullPath($OutputDir)
$fileName = "$WorkshopId.mpkg"
$targetPath = [IO.Path]::GetFullPath((Join-Path $targetDir $fileName))
$wrongPath = Join-Path ([Environment]::GetFolderPath('MyDocuments')) $fileName
$runStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$logDir = Join-Path $projectRoot 'temp\logs'
$runLog = Join-Path $logDir "saveas_all_wallpaperui_${WorkshopId}_$runStamp.log"
$controllerLog = Join-Path $logDir "save_dialog_controller_${WorkshopId}_${runStamp}_all.log"
$controllerStdout = "$controllerLog.stdout.log"
$controllerStderr = "$controllerLog.stderr.log"
$watcherLog = Join-Path $logDir "save_dialog_watcher_${WorkshopId}_${runStamp}_all.log"
$watcherStdout = "$watcherLog.stdout.log"
$watcherStderr = "$watcherLog.stderr.log"
$hookLog = Join-Path $logDir "native_save_dialog_hook_${WorkshopId}_${runStamp}_all.log"
$exportStdout = Join-Path $logDir "export_wallpaper_mpkg_${WorkshopId}_${runStamp}_all.stdout.log"
$exportStderr = Join-Path $logDir "export_wallpaper_mpkg_${WorkshopId}_${runStamp}_all.stderr.log"
$convertedDir = if ($ConvertedOutputDir) {
    [IO.Path]::GetFullPath($ConvertedOutputDir)
} else {
    Join-Path $projectRoot "temp\converted\${WorkshopId}_test_${runStamp}"
}
$hookConfig = Join-Path $logDir 'native_save_dialog_hook.ini'
$reportPath = Join-Path $projectRoot "report\MPKG自动导出验证_${WorkshopId}_${runStamp}.md"

foreach ($required in @(
        $exporter, $holdBackend, $controller, $hookDll, $injector,
        $controllerBuild, $hookBuild, $extractor, $repkg, $scriptsPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required path not found: $required"
    }
}

New-Item -ItemType Directory -Path $logDir, $targetDir -Force | Out-Null
if (Test-Path -LiteralPath $targetPath) {
    throw "Refusing to overwrite existing test output: $targetPath"
}

$originalBytes = [IO.File]::ReadAllBytes($scriptsPath)
$originalHash = (Get-FileHash -LiteralPath $scriptsPath -Algorithm SHA256).Hash
if ($originalHash -ne 'BE104CF40BD7FE1E3598F7387F1CFA545C4A71282D9A3A3B30DCC4A8B262373E') {
    throw "scripts.js baseline hash mismatch: $originalHash"
}

function Write-RunLog([string]$message) {
    $line = "$(Get-Date -Format o) $message"
    $line | Tee-Object -FilePath $runLog -Append
}

function Quote-Argument([object]$value) {
    $text = [string]$value
    if ($text -match '[\s"]') {
        return '"' + ($text -replace '"', '\"') + '"'
    }
    return $text
}

function Get-LiveWallpaperUi {
    @(Get-Process -Name wallpaperui -ErrorAction SilentlyContinue |
        Where-Object { -not $_.HasExited })
}

function Stop-AllWallpaperUi {
    for ($pass = 1; $pass -le 4; $pass++) {
        $remaining = @(Get-LiveWallpaperUi)
        if ($remaining.Count -eq 0) {
            return
        }
        foreach ($process in $remaining) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            Write-RunLog "WALLPAPERUI_STOPPED pid=$($process.Id) pass=$pass"
        }
        Start-Sleep -Milliseconds 500
    }
    $remaining = @(Get-LiveWallpaperUi)
    if ($remaining.Count -gt 0) {
        Write-RunLog "WALLPAPERUI_STOP_WARNING pids=$($remaining.Id -join ',')"
    }
}

$watcherCode = @'
param(
    [Parameter(Mandatory = $true)][string]$HookDll,
    [Parameter(Mandatory = $true)][string]$Injector,
    [Parameter(Mandatory = $true)][string]$LogPath,
    [Parameter(Mandatory = $true)][string]$HookLog,
    [int]$TimeoutSeconds = 1500
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Log([string]$message) {
    "$(Get-Date -Format o) $message" | Add-Content -LiteralPath $LogPath -Encoding UTF8
}

function Get-Candidates {
    @(Get-CimInstance Win32_Process -Filter "Name='wallpaperui.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match '(?i)(-weuimain|--weuimain|-window\s+browsewallpapers|--window\s+browsewallpapers)' -and
            $_.CommandLine -notmatch '(?i)--type=utility|--utility-sub-type=|--type=gpu|--type=renderer'
        } |
        Sort-Object ProcessId)
}

New-Item -ItemType Directory -Path (Split-Path -Parent $LogPath) -Force | Out-Null
Set-Content -LiteralPath $LogPath -Value @(
    "target_hook=$HookDll"
    "watcher_process_id=$([Diagnostics.Process]::GetCurrentProcess().Id)"
) -Encoding UTF8

$seen = New-Object 'System.Collections.Generic.HashSet[int]'
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    foreach ($candidate in @(Get-Candidates)) {
        $processId = [int]$candidate.ProcessId
        if ($seen.Contains($processId)) {
            continue
        }
        [void]$seen.Add($processId)
        Log "CANDIDATE pid=$processId command_line='$($candidate.CommandLine)'"
        try {
            & $Injector $processId $HookDll $HookLog 2>&1 |
                ForEach-Object { Log "INJECT pid=$processId $_" }
            Log "INJECT_RESULT pid=$processId exit_code=$LASTEXITCODE"
        } catch {
            Log "INJECT_EXCEPTION pid=$processId message='$($_.Exception.Message)'"
        }
    }
    Start-Sleep -Milliseconds 250
}
Log "WATCHER_TIMEOUT seen=$($seen.Count)"
'@

$watcherPath = Join-Path $logDir "save_dialog_watcher_${WorkshopId}_${runStamp}_all.ps1"
$watcherCode | Set-Content -LiteralPath $watcherPath -Encoding UTF8

$controllerProcess = $null
$watcherProcess = $null
$exportProcess = $null
$exportExitCode = $null
$extractExitCode = $null
$extractOutput = ''
$failure = $null
$controllerText = ''
$hookSeen = $false
$hookReady = $false
$finalHash = $null
$exportMayHaveModifiedScripts = $false

try {
    Write-RunLog "TEST_START workshop=$WorkshopId target='$targetPath'"
    Write-RunLog "scripts_baseline_sha256=$originalHash"
    Write-RunLog "wrong_location_check='$wrongPath'"

    try {
        $writeProbe = [IO.File]::Open(
            $scriptsPath,
            [IO.FileMode]::Open,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::ReadWrite)
        $writeProbe.Close()
        $writeProbe.Dispose()
        Write-RunLog "SCRIPTS_WRITE_ACCESS_CONFIRMED path='$scriptsPath'"
    } catch {
        throw "SCRIPTS_WRITE_ACCESS_FAILED: $($_.Exception.Message)"
    }

    @"
[save]
output_dir=$targetDir
file_name=$fileName
log_path=$hookLog
"@ | Set-Content -LiteralPath $hookConfig -Encoding Unicode
    Set-Content -LiteralPath $hookLog -Value '' -Encoding Unicode
    Write-RunLog "HOOK_CONFIG_WRITTEN path='$hookConfig' output='$targetDir' file='$fileName' log='$hookLog'"

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $controllerBuild |
        ForEach-Object { Write-RunLog "BUILD_CONTROLLER $_" }
    if ($LASTEXITCODE -ne 0) {
        throw 'Controller rebuild failed.'
    }

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $hookBuild |
        ForEach-Object { Write-RunLog "BUILD_HOOK $_" }
    if ($LASTEXITCODE -ne 0) {
        throw 'Hook rebuild failed.'
    }

    if (Test-Path -LiteralPath $hookManifest -PathType Leaf) {
        $builtHookDll = (Get-Content -LiteralPath $hookManifest -Raw -Encoding UTF8).Trim()
        if ($builtHookDll -and (Test-Path -LiteralPath $builtHookDll -PathType Leaf)) {
            $hookDll = [IO.Path]::GetFullPath($builtHookDll)
            Write-RunLog "HOOK_DLL_SELECTED path='$hookDll'"
        }
    }

    $controllerArgs = @(
        $targetDir, $fileName, $controllerLog, ($TimeoutMinutes * 60 + 30)
    )
    $controllerProcess = Start-Process -FilePath $controller `
        -ArgumentList ($controllerArgs | ForEach-Object { Quote-Argument $_ }) `
        -WindowStyle Hidden -RedirectStandardOutput $controllerStdout `
        -RedirectStandardError $controllerStderr -PassThru
    Write-RunLog "CONTROLLER_STARTED pid=$($controllerProcess.Id) log='$controllerLog'"
    Start-Sleep -Seconds 2
    if ($controllerProcess.HasExited) {
        throw "Controller exited before export: $($controllerProcess.ExitCode)"
    }

    $watcherArgs = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $watcherPath,
        '-HookDll', $hookDll, '-Injector', $injector,
        '-LogPath', $watcherLog, '-HookLog', $hookLog,
        '-TimeoutSeconds', ($TimeoutMinutes * 60 + 30)
    )
    $watcherProcess = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList ($watcherArgs | ForEach-Object { Quote-Argument $_ }) `
        -WindowStyle Hidden -RedirectStandardOutput $watcherStdout `
        -RedirectStandardError $watcherStderr -PassThru
    Write-RunLog "WATCHER_STARTED pid=$($watcherProcess.Id) log='$watcherLog'"
    Start-Sleep -Seconds 2
    if ($watcherProcess.HasExited) {
        throw 'Wallpaperui watcher exited before export.'
    }

    $exportArgs = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', $exporter,
        '-WallpaperRoot', $wallpaperRoot,
        '-WorkshopId', $WorkshopId,
        '-OutputDir', $targetDir,
        '-SaveBackendPath', $holdBackend,
        '-WaitForMpkgOnly',
        '-Force',
        '-TimeoutMinutes', $TimeoutMinutes
    )
    if ($LoopAnalysisPath) {
        $exportArgs += @('-LoopAnalysisPath', ([IO.Path]::GetFullPath($LoopAnalysisPath)))
    }
    if ($IncludeLikelyLoopOverrides) { $exportArgs += '-IncludeLikelyLoopOverrides' }
    if ($PreserveInteractiveEffects) { $exportArgs += '-PreserveInteractiveEffects' }
    $exportProcess = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList ($exportArgs | ForEach-Object { Quote-Argument $_ }) `
        -WindowStyle Hidden -RedirectStandardOutput $exportStdout `
        -RedirectStandardError $exportStderr -PassThru
    $exportMayHaveModifiedScripts = $true
    Write-RunLog "EXPORT_STARTED pid=$($exportProcess.Id) stdout='$exportStdout'"

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes + 3)
    $hookReadyDeadline = (Get-Date).AddSeconds(90)
    while (-not $exportProcess.HasExited -and (Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $hookLog) {
            $hookText = Get-Content -LiteralPath $hookLog -Raw -Encoding Unicode -ErrorAction SilentlyContinue
            if ($hookText -match 'HOOK_READY pid=\d+' -and
                $hookText -match 'IAT scan patched entries=\d+') {
                $hookReady = $true
            }
            if ($hookText -match 'SetFolder .*hr=0x00000000' -and
                $hookText -match 'SetFileName .*hr=0x00000000') {
                $hookSeen = $true
            }
            if (-not $hookReady -and (Get-Date) -gt $hookReadyDeadline) {
                throw 'IAT_HOOK_NOT_READY: no verified hook readiness within 90 seconds'
            }
        }
        Start-Sleep -Seconds 1
    }

    if (-not $exportProcess.HasExited) {
        throw "Export timed out after $TimeoutMinutes minutes."
    }
    $exportProcess.WaitForExit()
    $exportProcess.Refresh()
    $exportExitCode = [int]$exportProcess.ExitCode
    Write-RunLog "EXPORT_EXIT code=$exportExitCode hook_ready=$hookReady hook_seen=$hookSeen"
    if ($exportExitCode -ne 0) {
        throw "Export process failed with exit code $exportExitCode."
    }
    if (-not $hookReady) {
        throw 'IAT_HOOK_NOT_READY: export ended without hook readiness evidence'
    }
    if (-not $hookSeen) {
        throw 'SAVE_FOLDER_HOOK_NOT_CONFIRMED: SetFolder/SetFileName evidence missing'
    }

    $controllerDeadline = (Get-Date).AddSeconds(45)
    $controllerText = ''
    while ((Get-Date) -lt $controllerDeadline) {
        $controllerText = if (Test-Path -LiteralPath $controllerLog) {
            Get-Content -LiteralPath $controllerLog -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
        } else {
            ''
        }
        if ($controllerText -match 'STATE=SUCCESS' -or
            $controllerText -match 'STATE=FAILED') {
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if ($controllerText -notmatch 'STATE=INVOKING_SAVE') {
        throw 'SAVE_CONTROLLER_INVOKE_NOT_CONFIRMED: controller did not reach INVOKING_SAVE'
    }
    if ($controllerText -notmatch 'STATE=SUCCESS') {
        throw 'SAVE_CONTROLLER_SUCCESS_NOT_CONFIRMED: controller did not report SUCCESS within 45 seconds after export exit'
    }
    Write-RunLog 'SAVE_CONTROLLER_INVOKE_AND_SUCCESS_CONFIRMED'

    if (-not (Test-Path -LiteralPath $targetPath -PathType Leaf)) {
        throw "Target MPKG was not created: $targetPath"
    }
    $targetItem = Get-Item -LiteralPath $targetPath
    if ($targetItem.Length -le 0) {
        throw 'Target MPKG is empty.'
    }
    $targetHash = (Get-FileHash -LiteralPath $targetPath -Algorithm SHA256).Hash
    Write-RunLog "MPKG_SUCCESS full_name='$($targetItem.FullName)' size=$($targetItem.Length) sha256=$targetHash"

    if (-not $SkipRepackg) {
        $extractArgs = @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $extractor,
            '-MpkgPath', $targetPath, '-OutputDir', $convertedDir,
            '-RePKGPath', $repkg, '-Force'
        )
        $extractOutput = (& powershell.exe @extractArgs | Out-String).Trim()
        $extractExitCode = $LASTEXITCODE
        $extractExitCode = [int]$extractExitCode
        Write-RunLog "EXTRACT_EXIT code=$extractExitCode output=$extractOutput"
        if ($extractExitCode -ne 0) {
            throw "RePKG/MP4 extraction failed with exit code $extractExitCode."
        }
    }
}
catch {
    $failure = $_.Exception.Message
    Write-RunLog "TEST_FAILED reason='$failure'"
}
finally {
    if ($exportProcess -and -not $exportProcess.HasExited) {
        Stop-Process -Id $exportProcess.Id -Force -ErrorAction SilentlyContinue
        Write-RunLog "EXPORT_STOPPED pid=$($exportProcess.Id)"
    }
    if ($controllerProcess -and -not $controllerProcess.HasExited) {
        Stop-Process -Id $controllerProcess.Id -Force -ErrorAction SilentlyContinue
        Write-RunLog "CONTROLLER_STOPPED pid=$($controllerProcess.Id)"
    }
    if ($watcherProcess -and -not $watcherProcess.HasExited) {
        Stop-Process -Id $watcherProcess.Id -Force -ErrorAction SilentlyContinue
        Write-RunLog "WATCHER_STOPPED pid=$($watcherProcess.Id)"
    }

    Stop-AllWallpaperUi

    if ($exportMayHaveModifiedScripts -and
        (Select-String -LiteralPath $scriptsPath -Pattern 'CODEX_AUTOMATED_MPKG_EXPORT_BEGIN' -Quiet -ErrorAction SilentlyContinue)) {
        try {
            [IO.File]::WriteAllBytes($scriptsPath, $originalBytes)
            Write-RunLog 'SCRIPTS_RESTORED_FROM_BASELINE'
        } catch {
            Write-RunLog "SCRIPTS_RESTORE_FAILED reason='$($_.Exception.Message)'"
        }
    }
    $finalHash = (Get-FileHash -LiteralPath $scriptsPath -Algorithm SHA256).Hash
    Write-RunLog "SCRIPTS_FINAL_SHA256=$finalHash baseline=$originalHash restored=$($finalHash -eq $originalHash)"

    $report = @(
        "# MPKG 自动导出验证：$WorkshopId"
        ''
        "- 日期：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')"
        "- 目标：$targetPath"
        "- 结果：$(if ($failure) { 'FAILED' } else { 'SUCCESS' })"
        "- 失败原因：$failure"
        "- Hook 目录/文件名事件：$hookSeen"
        "- Export 退出码：$exportExitCode"
        "- Controller Invoke/Success：$($controllerText -match 'STATE=INVOKING_SAVE' -and $controllerText -match 'STATE=SUCCESS')"
        "- scripts.js SHA-256：$finalHash"
        "- scripts.js 已恢复：$($finalHash -eq $originalHash)"
        ''
        '## 日志'
        ''
        "- 主日志：$runLog"
        "- Controller：$controllerLog"
        "- Hook：$hookLog"
        "- Watcher：$watcherLog"
        "- Export：$exportStdout"
        ''
        '## MPKG'
        ''
    )
    if (Test-Path -LiteralPath $targetPath -PathType Leaf) {
        $finalItem = Get-Item -LiteralPath $targetPath
        $finalHashValue = Get-FileHash -LiteralPath $targetPath -Algorithm SHA256
        $report += "- FullName：$($finalItem.FullName)"
        $report += "- 大小：$($finalItem.Length) bytes"
        $report += "- SHA-256：$($finalHashValue.Hash)"
    } else {
        $report += '- 目标文件：不存在'
    }
    if ($extractOutput) {
        $report += ''
        $report += '## RePKG/MP4'
        $report += ''
        $report += '```text'
        $report += $extractOutput
        $report += '```'
    }
    [IO.File]::WriteAllLines($reportPath, $report, (New-Object Text.UTF8Encoding($false)))
}

if ($failure) {
    throw $failure
}

Write-Output (@{
    WorkshopId = $WorkshopId
    Target = $targetPath
    ConvertedOutputDir = $convertedDir
    ConvertedMp4 = if (Test-Path -LiteralPath (Join-Path $convertedDir "$WorkshopId.mp4") -PathType Leaf) {
        [IO.Path]::GetFullPath((Join-Path $convertedDir "$WorkshopId.mp4"))
    } else {
        $null
    }
    HookSeen = $hookSeen
    ExportExitCode = $exportExitCode
    Report = $reportPath
    RunLog = $runLog
} | ConvertTo-Json -Depth 5)
