param(
    [string]$WallpaperRoot,
    [string]$OutputDir = 'D:\7_Video\20_Wallpaper Engine\temp\mpkg',
    [Parameter(Mandatory = $true)]
    [string[]]$WorkshopId,
    [string[]]$ScenePkg,
    [switch]$Force,
    [switch]$PreserveInteractiveEffects,
    [string]$LoopAnalysisPath,
    [switch]$IncludeLikelyLoopOverrides,
    [switch]$WaitForMpkgOnly,
    [switch]$KeepWallpaperForeground = $true,
    [switch]$SkipBrowseUiCacheClear,
    [string]$SaveBackendPath,
    [int]$TimeoutMinutes = 90
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$RuntimeDir = Join-Path $ProjectRoot 'runtime'
$BackupDir = Join-Path $RuntimeDir 'backups'
$LogDir = Join-Path $RuntimeDir 'logs'
if (-not $SaveBackendPath) {
    throw 'Direct export requires an explicit SaveBackendPath. Use tools\export_mpkg_then_extract_mp4.ps1 for the verified Save As flow.'
}
$AutosaverPath = [System.IO.Path]::GetFullPath($SaveBackendPath)
$CaptureScriptPath = Join-Path $ScriptDir 'capture_wallpaper_temp_mp4.ps1'
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)

New-Item -ItemType Directory -Path $RuntimeDir, $BackupDir, $LogDir, $OutputDir -Force | Out-Null
$runStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$runLog = Join-Path $LogDir "export_$runStamp.log"

function Write-RunLog([string]$message) {
    $line = "$(Get-Date -Format o) $message"
    Write-Host $message
    $line | Add-Content -LiteralPath $runLog -Encoding UTF8
}

$windowApiCode = @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class CodexWindowApi {
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, StringBuilder text, int count);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int command);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
  [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [StructLayout(LayoutKind.Sequential)]
  public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
  public static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
  public static readonly IntPtr HWND_NOTOPMOST = new IntPtr(-2);
  public static readonly IntPtr HWND_BOTTOM = new IntPtr(1);
}
'@
Add-Type $windowApiCode -ErrorAction SilentlyContinue

function Get-TopLevelWindows {
    $script:CodexVisibleWindows = New-Object System.Collections.Generic.List[object]
    [CodexWindowApi]::EnumWindows({
        param($hWnd, $lParam)
        $titleBuilder = New-Object System.Text.StringBuilder 512
        $classBuilder = New-Object System.Text.StringBuilder 256
        [void][CodexWindowApi]::GetWindowText($hWnd, $titleBuilder, 512)
        [void][CodexWindowApi]::GetClassName($hWnd, $classBuilder, 256)
        $processId = [uint32]0
        [void][CodexWindowApi]::GetWindowThreadProcessId($hWnd, [ref]$processId)
        $script:CodexVisibleWindows.Add([pscustomobject]@{
            Handle = $hWnd
            Title = $titleBuilder.ToString()
            Class = $classBuilder.ToString()
            ProcessId = $processId
            Visible = [CodexWindowApi]::IsWindowVisible($hWnd)
            Iconic = [CodexWindowApi]::IsIconic($hWnd)
        })
        return $true
    }, [IntPtr]::Zero) | Out-Null
    return $script:CodexVisibleWindows.ToArray()
}

function Get-VisibleTopWindows {
    return @(Get-TopLevelWindows | Where-Object { $_.Visible })
}

function Get-WindowRectText($handle) {
    $rect = New-Object CodexWindowApi+RECT
    if (-not [CodexWindowApi]::GetWindowRect($handle, [ref]$rect)) {
        return 'unknown'
    }
    $width = $rect.Right - $rect.Left
    $height = $rect.Bottom - $rect.Top
    return "${width}x${height} at $($rect.Left),$($rect.Top)"
}

function Show-WindowBehind($window) {
    if (-not $window) {
        return $false
    }
    $handle = $window.Handle
    $before = Get-WindowRectText $handle
    $swpNosize = [uint32]0x0001
    $swpNomove = [uint32]0x0002
    $swpNoactivate = [uint32]0x0010
    $flags = $swpNosize -bor $swpNomove -bor $swpNoactivate
    $moved = [CodexWindowApi]::SetWindowPos($handle, [CodexWindowApi]::HWND_BOTTOM, 0, 0, 0, 0, $flags)
    $after = Get-WindowRectText $handle
    if (-not $script:WallpaperUiSizeLogged) {
        Write-RunLog "window rect before=$before after=$after"
        $script:WallpaperUiSizeLogged = $true
    }
    if ($before -ne $after) {
        Write-RunLog "WARNING: window rect changed; this function must not resize"
    }
    return $moved
}

function Show-WindowForeground($window, [string]$reason) {
    if (-not $window) {
        return $false
    }

    $handle = $window.Handle
    if ($window.Iconic) {
        [void][CodexWindowApi]::ShowWindow($handle, 9)
    }
    [void][CodexWindowApi]::BringWindowToTop($handle)
    [void][CodexWindowApi]::SetForegroundWindow($handle)
    Start-Sleep -Milliseconds 150

    $foreground = [CodexWindowApi]::GetForegroundWindow()
    $foregroundPid = [uint32]0
    [void][CodexWindowApi]::GetWindowThreadProcessId($foreground, [ref]$foregroundPid)
    $isForeground = ($foreground -eq $handle)
    Write-RunLog ("foreground request reason={0} title='{1}' class={2} hwnd={3} result={4} foreground_hwnd={5} foreground_pid={6}" -f `
        $reason, $window.Title, $window.Class, $handle.ToInt64(), $isForeground, $foreground.ToInt64(), $foregroundPid)
    return $isForeground
}

function Get-WallpaperUiWindow {
    return Get-TopLevelWindows |
        Where-Object {
            $_.Visible -and
            $_.Class -ne 'EVRFullscreenVideo' -and
            $_.Title -notmatch 'EVR Fullscreen' -and
            $_.Class -notmatch 'IME|tooltips|WorkerW|Progman|HwndWrapper' -and
            (
                $_.Title -match '^(Wallpaper Engine|Wallpaper UI)\b' -or
                $_.Title -match '^壁纸引擎' -or
                $_.Class -eq 'WPEUI'
            )
        } |
        ForEach-Object {
            $rectText = Get-WindowRectText $_.Handle
            $width = 0
            $height = 0
            $x = 0
            $y = 0
            if ($rectText -match '^(\d+)x(\d+) at (-?\d+),(-?\d+)$') {
                $width = [int]$Matches[1]
                $height = [int]$Matches[2]
                $x = [int]$Matches[3]
                $y = [int]$Matches[4]
            }
            $_ | Add-Member -NotePropertyName RectWidth -NotePropertyValue $width -Force
            $_ | Add-Member -NotePropertyName RectHeight -NotePropertyValue $height -Force
            $_ | Add-Member -NotePropertyName RectX -NotePropertyValue $x -Force
            $_ | Add-Member -NotePropertyName RectY -NotePropertyValue $y -Force
            $_
        } |
        Where-Object {
            $_.RectWidth -ge 400 -and
            $_.RectHeight -ge 300 -and
            $_.RectX -gt -10000 -and
            $_.RectY -gt -10000
        } |
        Sort-Object {
            if ($_.Title -match '^Wallpaper Engine') { 0 }
            elseif ($_.Class -eq 'WPEUI') { 1 }
            else { 2 }
        }, { -$_.RectWidth * $_.RectHeight } |
        Select-Object -First 1
}

function Get-WindowRectObject($handle) {
    $rect = New-Object CodexWindowApi+RECT
    if (-not [CodexWindowApi]::GetWindowRect($handle, [ref]$rect)) {
        return $null
    }
    return [pscustomobject]@{
        Left = $rect.Left
        Top = $rect.Top
        Width = $rect.Right - $rect.Left
        Height = $rect.Bottom - $rect.Top
    }
}

function Save-WallpaperUiRect {
    $ui = Get-WallpaperUiWindow
    if (-not $ui) {
        Write-RunLog 'no on-screen Wallpaper UI rect to save'
        return $false
    }
    $rect = Get-WindowRectObject $ui.Handle
    if (-not $rect -or $rect.Width -lt 400 -or $rect.Height -lt 300) {
        Write-RunLog "refusing to save tiny Wallpaper UI rect $(Get-WindowRectText $ui.Handle)"
        return $false
    }
    $script:SavedUiRect = $rect
    $rectPath = Join-Path $RuntimeDir 'wallpaper_ui_rect.json'
    $rect | ConvertTo-Json | Set-Content -LiteralPath $rectPath -Encoding UTF8
    Write-RunLog ("saved Wallpaper UI rect {0}x{1} at {2},{3}" -f $rect.Width, $rect.Height, $rect.Left, $rect.Top)
    return $true
}

function Import-WallpaperUiRect {
    if ($script:SavedUiRect) {
        return $true
    }
    $rectPath = Join-Path $RuntimeDir 'wallpaper_ui_rect.json'
    if (Test-Path -LiteralPath $rectPath) {
        $loaded = Get-Content -LiteralPath $rectPath -Raw | ConvertFrom-Json
        if ($loaded.Width -ge 400 -and $loaded.Height -ge 300) {
            $script:SavedUiRect = $loaded
            Write-RunLog ("loaded saved Wallpaper UI rect {0}x{1} at {2},{3}" -f $loaded.Width, $loaded.Height, $loaded.Left, $loaded.Top)
            return $true
        }
    }
    $script:SavedUiRect = [pscustomobject]@{ Left = 624; Top = 250; Width = 1263; Height = 996 }
    Write-RunLog 'using last known Wallpaper UI rect 1263x996 at 624,250'
    return $true
}

function Restore-WallpaperUiRect {
    if (-not $script:SavedUiRect) {
        return $false
    }
    $ui = Get-WallpaperUiWindow
    if (-not $ui) {
        return $false
    }
    $before = Get-WindowRectText $ui.Handle
    $rect = $script:SavedUiRect
    $swpNoactivate = [uint32]0x0010
    $moved = [CodexWindowApi]::SetWindowPos(
        $ui.Handle,
        [CodexWindowApi]::HWND_BOTTOM,
        [int]$rect.Left,
        [int]$rect.Top,
        [int]$rect.Width,
        [int]$rect.Height,
        $swpNoactivate
    )
    $after = Get-WindowRectText $ui.Handle
    Write-RunLog "restored Wallpaper UI rect before=$before after=$after result=$moved"
    return $moved
}

function Open-BrowseUiWithoutKillingBackground {
    $wallpaper64 = Get-Process wallpaper64 -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $wallpaper64) {
        if (-not (Test-Path -LiteralPath $wallpaper64Path)) {
            throw "wallpaper64.exe not found: $wallpaper64Path"
        }
        Start-Process -FilePath $wallpaper64Path | Out-Null
        Write-RunLog "started wallpaper64: $wallpaper64Path"
        Start-Sleep -Seconds 4
    }

    $wallpaper32 = Get-Process wallpaper32 -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $wallpaper32) {
        if (-not (Test-Path -LiteralPath $wallpaper32Path)) {
            throw "wallpaper32.exe not found: $wallpaper32Path"
        }
        Start-Process -FilePath $wallpaper32Path | Out-Null
        Write-RunLog "started wallpaper32 fallback: $wallpaper32Path"
        Start-Sleep -Seconds 4
    }

    [void](Invoke-TrayWindowOpen)
    Start-Process -FilePath $apputilPath -ArgumentList '-showbrowse' | Out-Null
    Write-RunLog 'browse UI requested via wallpaper64 + tray + apputil -showbrowse'
}

function Reset-StaleBrowseUi {
    $stale = @(Get-Process wallpaperui -ErrorAction SilentlyContinue |
        Where-Object { -not $_.HasExited })
    if ($stale.Count -eq 0) {
        Write-RunLog 'no stale wallpaperui processes to reset'
        return
    }

    $pids = @($stale | Select-Object -ExpandProperty Id)
    Write-RunLog "resetting stale wallpaperui processes only: $($pids -join ',')"
    foreach ($process in $stale) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1

    $remaining = @(Get-Process wallpaperui -ErrorAction SilentlyContinue)
    if ($remaining.Count -gt 0) {
        throw "Could not reset stale wallpaperui processes: $(@($remaining | Select-Object -ExpandProperty Id) -join ',')"
    }
    Write-RunLog 'stale wallpaperui reset complete; wallpaper32/wallpaper64 were left running'
}

function Write-WallpaperProcessLog([string]$stage) {
    $rows = @(Get-Process wallpaper32, wallpaper64, wallpaperui -ErrorAction SilentlyContinue |
        Where-Object { -not $_.HasExited } |
        ForEach-Object { '{0}:{1}' -f $_.ProcessName, $_.Id })
    if ($rows.Count -eq 0) {
        Write-RunLog "wallpaper processes ${stage}: none"
    } else {
        Write-RunLog ("wallpaper processes {0}: {1}" -f $stage, ($rows -join ', '))
    }
}

function Get-WallpaperEnginePids {
    return @(Get-Process wallpaper32, wallpaper64, wallpaperui -ErrorAction SilentlyContinue |
        Where-Object { -not $_.HasExited } |
        Select-Object -ExpandProperty Id)
}

function Invoke-TrayWindowOpen {
    $tray = Get-TopLevelWindows |
        Where-Object { $_.Class -eq 'WPETrayWindow' } |
        Select-Object -First 1
    if (-not $tray) {
        Write-RunLog 'no WPETrayWindow found'
        return $false
    }
    Write-RunLog "posting open messages to WPETrayWindow pid=$($tray.ProcessId)"
    foreach ($msg in @(0x0201, 0x0202, 0x0203, 0x0400)) {
        [void][CodexWindowApi]::PostMessage($tray.Handle, [uint32]$msg, [IntPtr]::Zero, [IntPtr]::Zero)
    }
    return $true
}

function Ensure-ExportWindowForeground {
    $windows = Get-TopLevelWindows
    $saveDialog = $windows |
        Where-Object {
            $_.Class -eq '#32770' -and
            $_.Visible -and
            -not [string]::IsNullOrWhiteSpace($_.Title)
        } |
        Select-Object -First 1
    if ($saveDialog) {
        return (Show-WindowForeground $saveDialog 'save-dialog')
    }

    $wallpaperUi = Get-WallpaperUiWindow
    if ($wallpaperUi) {
        $raised = Show-WindowForeground $wallpaperUi 'wallpaper-ui'
        if (-not $script:WallpaperUiForegroundLogged) {
            Write-RunLog ("raised Wallpaper UI title='{0}' class={1} pid={2} visible={3} result={4}" -f $wallpaperUi.Title, $wallpaperUi.Class, $wallpaperUi.ProcessId, $wallpaperUi.Visible, $raised)
            $script:WallpaperUiForegroundLogged = $true
        }
        return $raised
    }

    return $false
}

function Get-SteamRoots {
    $roots = New-Object System.Collections.Generic.List[string]
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Steam'),
        (Join-Path ${env:ProgramFiles} 'Steam'),
        (Get-ItemPropertyValue -Path 'HKCU:\Software\Valve\Steam' -Name SteamPath -ErrorAction SilentlyContinue),
        (Get-ItemPropertyValue -Path 'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam' -Name InstallPath -ErrorAction SilentlyContinue),
        (Get-ItemPropertyValue -Path 'HKLM:\SOFTWARE\Valve\Steam' -Name InstallPath -ErrorAction SilentlyContinue)
    )
    foreach ($candidate in $candidates) {
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
    throw 'Could not locate Wallpaper Engine. Pass -WallpaperRoot explicitly.'
}

function Resolve-ProjectInput([string]$workshopDir, [string]$fallbackPkg) {
    if ($fallbackPkg -and (Test-Path -LiteralPath $fallbackPkg -PathType Leaf)) {
        return [System.IO.Path]::GetFullPath($fallbackPkg)
    }

    $projectJsonPath = Join-Path $workshopDir 'project.json'
    if (Test-Path -LiteralPath $projectJsonPath -PathType Leaf) {
        try {
            $project = Get-Content -LiteralPath $projectJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $projectFile = [string]$project.file
            if (-not [string]::IsNullOrWhiteSpace($projectFile)) {
                $candidate = Join-Path $workshopDir $projectFile
                if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                    return [System.IO.Path]::GetFullPath($candidate)
                }
            }
        } catch {
            Write-RunLog "project.json parse warning for $workshopDir : $($_.Exception.Message)"
        }
    }

    foreach ($fallbackName in @('scene.json', 'gifscene.json', 'project.json')) {
        $candidate = Join-Path $workshopDir $fallbackName
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }

    throw "No Wallpaper Engine project input found under $workshopDir"
}

function Resolve-Targets {
    if ($ScenePkg -and $ScenePkg.Count -gt 0) {
        return @($ScenePkg | ForEach-Object {
            $full = [System.IO.Path]::GetFullPath(($_ -replace '/', '\'))
            if (-not (Test-Path -LiteralPath $full)) { throw "scene.pkg not found: $full" }
            $workshopDir = Split-Path -Parent $full
            $id = Split-Path -Leaf $workshopDir
            $input = Resolve-ProjectInput $workshopDir $full
            [pscustomobject]@{ File = ($input -replace '\\', '/'); Title = $id; Out = "$id.mpkg"; SourcePkg = ($full -replace '\\', '/') }
        })
    }
    $roots = Get-SteamRoots
    $normalizedIds = @($WorkshopId | ForEach-Object { ([string]$_ -split ',') } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    return @($normalizedIds | ForEach-Object {
        $id = $_
        $found = $null
        foreach ($steam in $roots) {
            $candidate = Join-Path $steam "steamapps\workshop\content\431960\$id\scene.pkg"
            if (Test-Path -LiteralPath $candidate) {
                $found = $candidate
                break
            }
        }
        if (-not $found) { throw "Could not find Workshop scene.pkg for ID $id." }
        $workshopDir = Split-Path -Parent $found
        $input = Resolve-ProjectInput $workshopDir $found
        [pscustomobject]@{ File = ($input -replace '\\', '/'); Title = $id; Out = "$id.mpkg"; SourcePkg = ($found -replace '\\', '/') }
    })
}

function Clear-BrowseUiCache([string]$root) {
    $cacheRoot = Join-Path $root 'ui\uicache\browsewallpapers\base'
    if (-not (Test-Path -LiteralPath $cacheRoot)) { return }
    $resolvedRoot = (Resolve-Path -LiteralPath $cacheRoot).Path.TrimEnd('\')
    foreach ($relative in @('Cache','Code Cache','GPUCache','Default\Cache','Default\Code Cache','Default\GPUCache','Default\Service Worker\CacheStorage')) {
        $candidate = Join-Path $resolvedRoot $relative
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        $resolved = (Resolve-Path -LiteralPath $candidate).Path
        if (-not $resolved.StartsWith($resolvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove cache outside browse UI root: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue
        Write-RunLog "cleared cache $resolved"
    }
}

$root = Find-WallpaperRoot
$targets = @(Resolve-Targets)
if ($targets.Count -ne 1) {
    throw "export_wallpaper_mpkg.ps1 now requires exactly one target per run. Use tools\export_wallpaper_mpkg_batch.ps1 for sequential batch processing."
}
$loopOverrides = [ordered]@{}
$loopAnalysisDecision = 'LEGACY_HEURISTIC'
if ($LoopAnalysisPath) {
    $analysisFullPath = [System.IO.Path]::GetFullPath($LoopAnalysisPath)
    if (-not (Test-Path -LiteralPath $analysisFullPath -PathType Leaf)) {
        throw "Loop analysis file not found: $analysisFullPath"
    }
    $analysisBatch = Get-Content -LiteralPath $analysisFullPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$analysisBatch.schema_version -ne 1) {
        throw "Unsupported loop analysis batch schema: $($analysisBatch.schema_version)"
    }
    $targetId = [string]$targets[0].Title
    $analysisItem = @($analysisBatch.results | Where-Object { [string]$_.workshopid -eq $targetId }) | Select-Object -First 1
    if (-not $analysisItem) {
        throw "Loop analysis result missing for Workshop ID $targetId"
    }
    if ([int]$analysisItem.schema_version -ne 1 -or [string]$analysisItem.plugin_phase -ne 'PRE_EXPORT_NORMALIZATION') {
        throw "Loop analysis contract mismatch for Workshop ID $targetId"
    }
    $sourceDir = Split-Path -Parent (($targets[0].SourcePkg) -replace '/', '\')
    $projectJsonPath = Join-Path $sourceDir 'project.json'
    $scenePkgPath = Join-Path $sourceDir 'scene.pkg'
    $currentProjectHash = (Get-FileHash -LiteralPath $projectJsonPath -Algorithm SHA256).Hash
    $currentSceneHash = (Get-FileHash -LiteralPath $scenePkgPath -Algorithm SHA256).Hash
    if ($currentProjectHash -ne ([string]$analysisItem.source_hashes.project_json_sha256).ToUpperInvariant()) {
        throw "STALE_PROJECT_JSON_SHA256 for Workshop ID $targetId"
    }
    if ($currentSceneHash -ne ([string]$analysisItem.source_hashes.scene_pkg_sha256).ToUpperInvariant()) {
        throw "STALE_SCENE_PKG_SHA256 for Workshop ID $targetId"
    }
    foreach ($property in $analysisItem.override_plan.auto_apply_user_properties.PSObject.Properties) {
        $loopOverrides[$property.Name] = $property.Value
    }
    if ($IncludeLikelyLoopOverrides) {
        foreach ($property in $analysisItem.override_plan.likely_user_properties.PSObject.Properties) {
            $loopOverrides[$property.Name] = $property.Value
        }
    }
    foreach ($property in $analysisItem.override_plan.scene_settings.PSObject.Properties) {
        $loopOverrides[$property.Name] = $property.Value
    }
    $loopAnalysisDecision = [string]$analysisItem.decision
    Write-RunLog "loop analysis loaded id=$targetId decision=$loopAnalysisDecision overrides=$($loopOverrides.Keys -join ',') include_likely=$($IncludeLikelyLoopOverrides.IsPresent)"
}
$loopOverrideJson = $loopOverrides | ConvertTo-Json -Compress -Depth 20
if ([string]::IsNullOrWhiteSpace($loopOverrideJson)) { $loopOverrideJson = '{}' }
$scriptsPath = Join-Path $root 'ui\dist\scripts\scripts.js'
$apputilPath = Join-Path $root 'bin\apputil32.exe'
$wallpaper32Path = Join-Path $root 'wallpaper32.exe'
$wallpaper64Path = Join-Path $root 'wallpaper64.exe'

foreach ($required in @($scriptsPath, $apputilPath, $wallpaper32Path, $wallpaper64Path, $AutosaverPath, $CaptureScriptPath)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required path not found: $required" }
}

$outputs = @()
foreach ($target in $targets) {
    $output = Join-Path $OutputDir $target.Out
    if ((Test-Path -LiteralPath $output) -and -not $Force) {
        throw "Output exists: $output. Use -Force to regenerate it."
    }
    if ($Force -and (Test-Path -LiteralPath $output)) {
        Remove-Item -LiteralPath $output -Force
    }
    $outputs += $output
}

$originalBytes = [System.IO.File]::ReadAllBytes($scriptsPath)
$originalText = [System.Text.Encoding]::UTF8.GetString($originalBytes)
try {
    $writeProbe = [System.IO.File]::Open(
        $scriptsPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::ReadWrite)
    $writeProbe.Close()
    $writeProbe.Dispose()
} catch {
    throw "SCRIPTS_WRITE_ACCESS_FAILED: $($_.Exception.Message)"
}
if ($originalText.Contains('CODEX_AUTOMATED_MPKG_EXPORT_BEGIN') -or
    $originalText.Contains('CODEX_MPKG_EXPORT_INJECTION_BEGIN') -or
    $originalText.Contains('CODEX_SINGLE_MPKG_EXPORT_INJECTION_BEGIN')) {
    throw 'scripts.js already contains a Codex injection marker. Run repair_wallpaper_engine_mpkg.ps1 first.'
}

$targetJson = '[' + ((@($targets | ForEach-Object { $_ | ConvertTo-Json -Compress })) -join ',') + ']'
$marker = '/* CODEX_AUTOMATED_MPKG_EXPORT_BEGIN */'
$injection = @"

$marker
(function () {
  if (window.__codexAutomatedMpkgExportStarted) return;
  window.__codexAutomatedMpkgExportStarted = true;
  var targets = $targetJson;
  if (!Array.isArray(targets)) targets = [targets];
  console.log("[codex-mpkg] target count", targets.length);
  var stripUiOnlyProperties = function (props) {
    if (!props || typeof props !== "object") return props || {};
    ["alignment","alignmentx","alignmenty","alignmentz","alignmentposition","alignmentfliph","pluginledextensionsenableleds","wec_e","wec_brs","wec_con","wec_sat","wec_hue","rate"].forEach(function (key) { delete props[key]; });
    return props;
  };
  var applyCleanLoopOverrides = function (props) {
    if (!props || typeof props !== "object") return props || {};
    if ($($PreserveInteractiveEffects.IsPresent.ToString().ToLowerInvariant())) return props;
    var analyzedOverrides = $loopOverrideJson;
    if (Object.keys(analyzedOverrides).length > 0) {
      Object.keys(analyzedOverrides).forEach(function (key) {
        var desired = analyzedOverrides[key];
        var descriptor = props[key];
        if (descriptor && typeof descriptor === "object" && Object.prototype.hasOwnProperty.call(descriptor, "value")) descriptor.value = desired;
        else props[key] = desired;
      });
      console.log("[codex-mpkg] applied analyzed loop overrides", JSON.stringify(analyzedOverrides));
      return props;
    }
    var falseKeys = [
      "cameraparallax", "camerashake", "mouseparticleeffect", "audioonoff",
      "audiovisualization", "audiovisualizer", "enablemusicplayer", "enableclock",
      "enablesecond", "datetime", "date", "clock", "clockleft", "clockright",
      "showclock", "showdate", "showtime", "albumtitle1", "artist", "songtitle",
      "musicplayer", "cursorparticle", "cursorparticles", "mouseparticles",
      "author", "authorname", "creator", "creatorname", "displayauthor",
      "displaytitle", "displayartist", "displaysong", "displaymusic"
    ];
    var falseKeySet = {};
    falseKeys.forEach(function (key) { falseKeySet[key] = true; });
    var cleanText = function (value) {
      return String(value || "").toLowerCase();
    };
    var shouldDisable = function (key, descriptor) {
      var keyText = cleanText(key);
      var labelText = cleanText(descriptor && (descriptor.text || descriptor.label || descriptor.name));
      var text = keyText + " " + labelText;
      return /mouse|cursor|parallax|shake|clock|date|time|author|creator|artist|song|music.?player|audio.?visual|visual.?audio|audio.?react|audio.?amount|audio.?bounds|audio.?exponent|audio.?processing/.test(text);
    };
    Object.keys(props).forEach(function (key) {
      var value = props[key];
      var descriptor = value && typeof value === "object" ? value : null;
      var current = descriptor && Object.prototype.hasOwnProperty.call(descriptor, "value") ? descriptor.value : value;
      var disable = !!falseKeySet[key.toLowerCase()] || shouldDisable(key, descriptor);
      if (!disable) return;
      if (descriptor && Object.prototype.hasOwnProperty.call(descriptor, "value")) {
        if (descriptor.type === "slider" || typeof current === "number") descriptor.value = 0;
        else if (descriptor.type === "color") return;
        else descriptor.value = false;
      } else if (typeof current === "boolean") props[key] = false;
      else if (typeof current === "number") props[key] = 0;
      else if (typeof current === "string" && /^(true|false)$/i.test(current)) props[key] = false;
    });
    falseKeys.forEach(function (key) {
      if (!Object.prototype.hasOwnProperty.call(props, key)) props[key] = false;
    });
    ["newproperty"].forEach(function (key) {
      if (typeof props[key] === "boolean") props[key] = false;
    });
    return props;
  };
  var waitForBridge = function () {
    return new Promise(function (resolve, reject) {
      var started = Date.now();
      var timer = setInterval(function () {
        if (window.angular && window.browseWallpaperObject &&
            typeof window.browseWallpaperObject.requestWallpaperProperties === "function" &&
            typeof window.browseWallpaperObject.exportMobilePkg === "function") {
          clearInterval(timer); resolve(); return;
        }
        if (Date.now() - started > 30000) {
          clearInterval(timer); reject(new Error("bridge unavailable after 30s"));
        }
      }, 250);
    });
  };
  var waitForMobileUploadController = function () {
    return new Promise(function (resolve, reject) {
      var started = Date.now();
      var timer = setInterval(function () {
        if (window.browseMobileUploadModalCtrl) {
          clearInterval(timer); resolve(window.browseMobileUploadModalCtrl); return;
        }
        if (Date.now() - started > 30000) {
          clearInterval(timer); reject(new Error("mobile upload modal controller unavailable after 30s"));
        }
      }, 250);
    });
  };
  var waitForModalInitialized = function (ctrl) {
    return new Promise(function (resolve) {
      var started = Date.now();
      var timer = setInterval(function () {
        if (ctrl.hostInitialized || Date.now() - started > 30000) {
          clearInterval(timer); resolve(); return;
        }
      }, 250);
    });
  };
  var callNative = function (objectName, methodName) {
    var args = Array.prototype.slice.call(arguments, 2);
    return new Promise(function (resolve, reject) {
      var callbackName = methodName + "Callback";
      var errorName = methodName + "CallbackError";
      var timeout = setTimeout(function () { reject(new Error(methodName + " timed out")); }, 30 * 60 * 1000);
      window[callbackName] = function () {
        clearTimeout(timeout);
        window[callbackName] = undefined;
        window[errorName] = undefined;
        resolve(arguments.length <= 1 ? arguments[0] : Array.prototype.slice.call(arguments));
      };
      window[errorName] = function () {
        clearTimeout(timeout);
        window[callbackName] = undefined;
        window[errorName] = undefined;
        reject(new Error(methodName + " failed: " + Array.prototype.slice.call(arguments).join(" ")));
      };
      try { window[objectName][methodName].apply(window[objectName], args); }
      catch (error) { clearTimeout(timeout); reject(error); }
    });
  };
  var exportOne = async function (target) {
    console.log("[codex-mpkg] opening official export modal", target.Title, target.File);
    var injector = angular.element(document.body).injector();
    var modals = injector.get("modals");
    var rootScope = injector.get("`$rootScope");
    var host = injector.get("host");
    var originalCallDeferred = host.callDeferred;
    host.callDeferred = function () {
      var args = Array.prototype.slice.call(arguments);
      var promise = originalCallDeferred.apply(host, args);
      if (args[0] === "browseWallpaperObject" && args[1] === "requestWallpaperProperties") {
        promise = promise.then(function (result) {
          if (result && Array.isArray(result.properties)) {
            result.properties.forEach(function (props) {
              stripUiOnlyProperties(props);
              applyCleanLoopOverrides(props);
            });
          } else if (result && result.properties) {
            stripUiOnlyProperties(result.properties);
            applyCleanLoopOverrides(result.properties);
          }
          return result;
        });
      }
      if (args[0] === "browseWallpaperObject" && args[1] === "exportMobilePkg") {
        console.log("[codex-mpkg] exportMobilePkg settings", JSON.stringify(args[3] || {}));
      }
      return promise;
    };
    var wallpaper = {
      allowmobileupload: true,
      file: target.File,
      project: target.SourcePkg || target.File,
      status: "installed",
      tags: "Scene,Wallpaper,Workshop",
      title: target.Title,
      type: "Scene",
      workshopid: target.Title,
      workshopurl: "steam://url/CommunityFilePage/" + target.Title
    };
    modals.open("browseMobileUpload", { data: { device: { name: "export" }, location: "Monitor0", isExporting: true, wallpapers: [wallpaper] } }).catch(function () {});
    rootScope.`$applyAsync();
    var ctrl = await waitForMobileUploadController();
    await waitForModalInitialized(ctrl);
    ctrl.device.preset = "low";
    ctrl.showAdvancedSettings.visible = true;
    ctrl.settings.compression = "high_performance";
    ctrl.settings.reduction = "reduction_x4";
    ctrl.settings.videopreset = "1080p";
    ctrl.settings.videouncroppedpreset = "original";
    ctrl.settings.videofps = "60";
    ctrl.settings.videocropping = "disabled";
    ctrl.settings.videoalignment = 50;
    console.log("[codex-mpkg] modal settings", JSON.stringify(ctrl.settings), "preset", ctrl.device.preset);
    rootScope.`$applyAsync();
    await new Promise(function (resolve) { setTimeout(resolve, 500); });
    ctrl.ok();
    rootScope.`$applyAsync();
    console.log("[codex-mpkg] modal ok requested", target.Title);
  };
  (async function () {
    console.log("[codex-mpkg] automated injection loaded");
    await waitForBridge();
    console.log("[codex-mpkg] bridge ready");
    for (var i = 0; i < targets.length; ++i) await exportOne(targets[i]);
    console.log("[codex-mpkg] all exports requested");
  })().catch(function (error) {
    console.error("[codex-mpkg] failed", error && (error.stack || error.message || error));
  });
})();
/* CODEX_AUTOMATED_MPKG_EXPORT_END */
"@

$backupPath = Join-Path $BackupDir "scripts.js.$runStamp.backup"
$autosaverProcess = $null
$captureProcesses = @()
$completed = $false
$restoreError = $null
$script:WallpaperUiForegroundLogged = $false
$script:WallpaperUiSizeLogged = $false
$script:SavedUiRect = $null
$captureRoot = Join-Path $ProjectRoot 'temp\converted'
$transcodePath = Join-Path $root 'projects\temp\transcode\wallpaper.mp4'

try {
    Write-RunLog "wallpaper root: $root"
    Write-RunLog "targets: $($targets.Title -join ', ')"
    Write-RunLog "export settings: preset=low/prerender_high_performance compression=high_performance reduction=reduction_x4 videocropping=disabled videouncroppedpreset=original videofps=60 videoalignment=50 preserve_interactive_effects=$($PreserveInteractiveEffects.IsPresent) loop_analysis_decision=$loopAnalysisDecision loop_analysis_overrides=$($loopOverrides.Count) wait_for_mpkg_only=$($WaitForMpkgOnly.IsPresent) keep_wallpaper_foreground=$($KeepWallpaperForeground.IsPresent)"
    try {
        $writeProbe = [System.IO.File]::Open(
            $scriptsPath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::ReadWrite)
        $writeProbe.Close()
        $writeProbe.Dispose()
        Write-RunLog "scripts.js write access confirmed: $scriptsPath"
    } catch {
        throw "SCRIPTS_WRITE_ACCESS_FAILED: $($_.Exception.Message)"
    }
    [System.IO.File]::WriteAllBytes($backupPath, $originalBytes)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($scriptsPath, $originalText + $injection, $utf8NoBom)
    Write-RunLog "temporary injection appended; backup=$backupPath"

    $autosaverArgs = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', $AutosaverPath,
        '-OutputDir', $OutputDir,
        '-TimeoutMinutes', $TimeoutMinutes,
        '-FileName',
        $targets[0].Out
    )
    $quotedAutosaverArgs = @($autosaverArgs | ForEach-Object {
        $value = [string]$_
        if ($value -match '[\s"]') {
            '"' + ($value -replace '"', '\"') + '"'
        } else {
            $value
        }
    })
    $autosaverProcess = Start-Process -FilePath 'powershell.exe' -ArgumentList ($quotedAutosaverArgs -join ' ') -WindowStyle Hidden -PassThru
    Write-RunLog "autosaver pid=$($autosaverProcess.Id)"
    Start-Sleep -Milliseconds 500
    if ($autosaverProcess.HasExited) {
        throw "Autosaver exited before the browse UI opened. Check $OutputDir\saveas_autosaver.log and the current export log."
    }

    Write-WallpaperProcessLog 'before open'
    $wallpaper32Running = [bool](Get-Process wallpaper32 -ErrorAction SilentlyContinue | Where-Object { -not $_.HasExited })
    $wallpaper64Running = [bool](Get-Process wallpaper64 -ErrorAction SilentlyContinue | Where-Object { -not $_.HasExited })
    $wallpaperUiRunning = [bool](Get-Process wallpaperui -ErrorAction SilentlyContinue | Where-Object { -not $_.HasExited })
    if (-not $wallpaper32Running) {
        Write-RunLog 'WARNING: wallpaper32 is not running; not starting it, because background must stay untouched'
    }
    if (-not $wallpaper64Running) {
        Write-RunLog 'wallpaper64 is not running; leaving it stopped'
    }
    Write-RunLog ("existing processes wallpaper32={0} wallpaper64={1} wallpaperui={2}" -f $wallpaper32Running, $wallpaper64Running, $wallpaperUiRunning)
    if (-not $SkipBrowseUiCacheClear) {
        Clear-BrowseUiCache $root
    } else {
        Write-RunLog 'Browse UI cache clear skipped by request'
    }
    Reset-StaleBrowseUi
    Open-BrowseUiWithoutKillingBackground
    $uiReadyAfterRestart = $false
    for ($wait = 0; $wait -lt 30; $wait += 2) {
        Start-Sleep -Seconds 2
        if (Get-WallpaperUiWindow) {
            $uiReadyAfterRestart = $true
            Write-RunLog "browse UI visible after $($wait + 2)s rect=$(Get-WindowRectText (Get-WallpaperUiWindow).Handle)"
            break
        }
        Write-RunLog "waiting for browse UI $($wait + 2)s"
    }
    if ($uiReadyAfterRestart) {
        Write-RunLog 'browse UI detected; leaving its original window size unchanged'
    }
    [void](Ensure-ExportWindowForeground)
    Write-WallpaperProcessLog 'after open'
    $uiReady = $false
    for ($wait = 0; $wait -lt 30; $wait += 2) {
        Start-Sleep -Seconds 2
        if (Ensure-ExportWindowForeground) {
            $uiReady = $true
            Write-RunLog "browse UI visible after $($wait + 2)s"
            break
        }
        Write-RunLog "waiting for browse UI $($wait + 2)s"
    }
    if (-not $uiReady) {
        Write-RunLog 'WARNING: Wallpaper UI was not raised after browse UI startup; continuing and retrying in the wait loop'
    }

    foreach ($index in 0..($targets.Count - 1)) {
        $target = $targets[$index]
        $output = $outputs[$index]
        $captureDir = Join-Path $captureRoot $target.Title
        $capturePath = Join-Path $captureDir 'wallpaper.mp4'
        $captureProcess = $null
        if (-not $WaitForMpkgOnly) {
            $captureMarker = $output
            New-Item -ItemType Directory -Path $captureDir -Force | Out-Null
            $captureArgs = @(
                '-NoProfile', '-ExecutionPolicy', 'Bypass',
                '-File', "`"$CaptureScriptPath`"",
                '-SourcePath', "`"$transcodePath`"",
                '-CapturePath', "`"$capturePath`"",
                '-ReadyMarker', "`"$captureMarker`"",
                '-TimeoutMinutes', $TimeoutMinutes
            )
            $captureProcess = Start-Process -FilePath 'powershell.exe' -ArgumentList $captureArgs -WindowStyle Hidden -PassThru
            $captureProcesses += $captureProcess
            Write-RunLog "capture pid=$($captureProcess.Id) target=$($target.Title) source=$transcodePath capture=$capturePath"
        } else {
            Write-RunLog "temporary MP4 capture skipped because WaitForMpkgOnly was requested"
        }

        $targetDeadline = (Get-Date).AddMinutes($TimeoutMinutes)
        do {
            if ($KeepWallpaperForeground) {
                if (-not (Ensure-ExportWindowForeground)) {
                    Write-RunLog "Wallpaper UI not opened yet for $($target.Title); retrying"
                }
            }
            $mpkgItem = Get-Item -LiteralPath $output -ErrorAction SilentlyContinue
            $mp4Item = Get-Item -LiteralPath $capturePath -ErrorAction SilentlyContinue
            if ($mpkgItem -and $mpkgItem.Length -gt 0 -and ($WaitForMpkgOnly -or ($mp4Item -and $mp4Item.Length -gt 0))) {
                Write-RunLog "output ready: $($mpkgItem.FullName) $($mpkgItem.Length) bytes"
                if ($mp4Item) {
                    Write-RunLog "captured mp4: $($mp4Item.FullName) $($mp4Item.Length) bytes"
                }
                break
            }
            if (-not $WaitForMpkgOnly -and $captureProcess.HasExited -and $captureProcess.ExitCode -ne 0 -and
                (-not $mp4Item -or $mp4Item.Length -le 0)) {
                throw "Temporary MP4 capture failed for $($target.Title). See $captureDir\capture.log"
            }
            Write-RunLog ("waiting target={0} mpkg={1} mp4={2}" -f $target.Title, [bool]$mpkgItem, [bool]$mp4Item)
            Start-Sleep -Seconds 2
        } while ((Get-Date) -lt $targetDeadline)

        $mpkgItem = Get-Item -LiteralPath $output -ErrorAction SilentlyContinue
        $mp4Item = Get-Item -LiteralPath $capturePath -ErrorAction SilentlyContinue
        if (-not $mpkgItem -or $mpkgItem.Length -le 0 -or (-not $WaitForMpkgOnly -and (-not $mp4Item -or $mp4Item.Length -le 0))) {
            throw "MPKG or temporary MP4 export timed out for $($target.Title)."
        }
    }
    $completed = $true
}
finally {
    if ($autosaverProcess -and -not $autosaverProcess.HasExited) {
        Stop-Process -Id $autosaverProcess.Id -Force -ErrorAction SilentlyContinue
        Write-RunLog "stopped autosaver pid=$($autosaverProcess.Id)"
    }
    foreach ($captureProcess in @($captureProcesses)) {
        if ($captureProcess -and -not $captureProcess.HasExited) {
            Stop-Process -Id $captureProcess.Id -Force -ErrorAction SilentlyContinue
            Write-RunLog "stopped capture pid=$($captureProcess.Id)"
        }
    }
    if (Test-Path -LiteralPath $scriptsPath) {
        try {
            [System.IO.File]::WriteAllBytes($scriptsPath, $originalBytes)
            Write-RunLog 'restored original scripts.js bytes'
        } catch {
            $restoreError = "SCRIPTS_RESTORE_FAILED: $($_.Exception.Message)"
            Write-RunLog $restoreError
        }
    }
    Write-WallpaperProcessLog 'finally'
    if (-not $completed) {
        Write-RunLog 'incomplete run: leaving wallpaper32/wallpaper64/wallpaperui running'
    }
    if ($restoreError) {
        throw $restoreError
    }
}
