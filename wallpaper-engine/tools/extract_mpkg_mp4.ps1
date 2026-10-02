param(
    [Parameter(Mandatory = $true)]
    [string]$MpkgPath,

    [string]$OutputDir,

    [string]$RePKGPath = 'D:\0_Vital document\tools\RePKG-GUI_v1.0.1\RePKG.exe',

    [string]$TempRoot = 'D:\7_Video\20_Wallpaper Engine\temp\repkg',

    [switch]$KeepExtracted,

    [switch]$Force
)

$ErrorActionPreference = 'Stop'

function Get-FullPath([string]$path) {
    return [System.IO.Path]::GetFullPath(($path -replace '/', '\'))
}

function ConvertTo-ProcessArguments([string[]]$arguments) {
    return (($arguments | ForEach-Object {
        $value = [string]$_
        if ($value -notmatch '[\s"]') {
            return $value
        }
        return '"' + ($value -replace '"', '\"') + '"'
    }) -join ' ')
}

function Invoke-ExternalCapture {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,

        [Parameter(Mandatory = $true)]
        [string]$LogPath
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.Arguments = ConvertTo-ProcessArguments $ArgumentList

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()

    @(
        "command: $FilePath $($ArgumentList -join ' ')"
        "exit_code: $($process.ExitCode)"
        "--- stdout ---"
        $stdout.TrimEnd()
        "--- stderr ---"
        $stderr.TrimEnd()
    ) | Set-Content -LiteralPath $LogPath -Encoding UTF8

    return [pscustomobject]@{
        ExitCode = $process.ExitCode
        StdOut = $stdout
        StdErr = $stderr
    }
}

function Get-VideoProbe([string]$ffprobePath, [string]$videoPath) {
    if (-not (Test-Path -LiteralPath $ffprobePath)) {
        return [pscustomobject]@{
            Available = $false
            Valid = $false
            Json = $null
            Error = "ffprobe not found: $ffprobePath"
        }
    }

    $probeArgs = @(
        '-v', 'error',
        '-print_format', 'json',
        '-show_format',
        '-show_streams',
        $videoPath
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $ffprobePath
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.Arguments = ConvertTo-ProcessArguments $probeArgs
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()

    if ($process.ExitCode -ne 0) {
        return [pscustomobject]@{
            Available = $true
            Valid = $false
            Json = $null
            Error = $stderr.Trim()
        }
    }

    try {
        $json = $stdout | ConvertFrom-Json
    } catch {
        return [pscustomobject]@{
            Available = $true
            Valid = $false
            Json = $null
            Error = "ffprobe returned invalid JSON: $($_.Exception.Message)"
        }
    }

    $videoStreams = @($json.streams | Where-Object { $_.codec_type -eq 'video' })
    if ($videoStreams.Count -eq 0) {
        return [pscustomobject]@{
            Available = $true
            Valid = $false
            Json = $json
            Error = 'No video stream found.'
        }
    }

    return [pscustomobject]@{
        Available = $true
        Valid = $true
        Json = $json
        Error = $null
    }
}

$MpkgPath = Get-FullPath $MpkgPath
$RePKGPath = Get-FullPath $RePKGPath
$TempRoot = Get-FullPath $TempRoot

if (-not (Test-Path -LiteralPath $MpkgPath -PathType Leaf)) {
    throw "MPKG not found: $MpkgPath"
}
if (-not (Test-Path -LiteralPath $RePKGPath -PathType Leaf)) {
    throw "RePKG not found: $RePKGPath"
}

$source = Get-Item -LiteralPath $MpkgPath
if ($source.Length -le 0) {
    throw "MPKG is empty: $MpkgPath"
}

$id = [System.IO.Path]::GetFileNameWithoutExtension($source.Name)
$runStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$runRoot = Join-Path $TempRoot "${id}_$runStamp"
$pkgPath = Join-Path $runRoot "$id.pkg"
$extractDir = Join-Path $runRoot 'extracted'
$repkgLog = Join-Path $runRoot 'repkg.log'
$resultPath = Join-Path $runRoot 'result.json'
$ffprobePath = $null

$ffprobeCandidates = @(
    'C:\Program Files\ffmpeg\bin\ffprobe.exe',
    'C:\Program Files (x86)\ffmpeg\bin\ffprobe.exe',
    'ffprobe.exe'
)
foreach ($candidate in $ffprobeCandidates) {
    if ($candidate -eq 'ffprobe.exe' -or (Test-Path -LiteralPath $candidate)) {
        $ffprobePath = $candidate
        break
    }
}

if (-not $OutputDir) {
    $OutputDir = Join-Path (Split-Path -Parent $MpkgPath) "${id}_mp4"
}
$OutputDir = Get-FullPath $OutputDir

New-Item -ItemType Directory -Path $runRoot, $extractDir, $OutputDir -Force | Out-Null

$sourceHash = (Get-FileHash -LiteralPath $MpkgPath -Algorithm SHA256).Hash
Copy-Item -LiteralPath $MpkgPath -Destination $pkgPath -Force
$copyHash = (Get-FileHash -LiteralPath $pkgPath -Algorithm SHA256).Hash
if ($sourceHash -ne $copyHash) {
    throw "Temporary .pkg copy hash mismatch. Source was not modified, but extraction was stopped."
}

$extractResult = Invoke-ExternalCapture `
    -FilePath $RePKGPath `
    -ArgumentList @('extract', $pkgPath, '-o', $extractDir, '--overwrite') `
    -LogPath $repkgLog

$mp4s = @(
    Get-ChildItem -LiteralPath $extractDir -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ieq 'wallpaper.mp4' }
)

if ($mp4s.Count -eq 0) {
    $allMedia = @(
        Get-ChildItem -LiteralPath $extractDir -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -match '^\.(mp4|m4v|mov|webm|mkv|avi)$' }
    )
    $result = [ordered]@{
        status = 'ERROR_NO_WALLPAPER_MP4'
        source_mpkg = $MpkgPath
        source_sha256 = $sourceHash
        temp_pkg = $pkgPath
        temp_pkg_sha256 = $copyHash
        repkg_exit_code = $extractResult.ExitCode
        extracted_dir = $extractDir
        media_candidates = @($allMedia | ForEach-Object { $_.FullName })
        repkg_log = $repkgLog
        message = 'RePKG completed, but wallpaper.mp4 was not found in the package.'
    }
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Host ($result | ConvertTo-Json -Depth 6)
    if (-not $KeepExtracted) {
        Write-Host "Kept failure evidence at $runRoot"
    }
    exit 2
}

if ($mp4s.Count -gt 1) {
    throw "Multiple wallpaper.mp4 entries found: $($mp4s.FullName -join ', ')"
}

$sourceVideo = $mp4s[0]
$outputPath = Join-Path $OutputDir "$id.mp4"
if ((Test-Path -LiteralPath $outputPath) -and -not $Force) {
    throw "Output exists: $outputPath. Use -Force to replace it."
}

Copy-Item -LiteralPath $sourceVideo.FullName -Destination $outputPath -Force
$outputItem = Get-Item -LiteralPath $outputPath
if ($outputItem.Length -le 0) {
    throw "Extracted MP4 is empty: $outputPath"
}

$probe = Get-VideoProbe -ffprobePath $ffprobePath -videoPath $outputPath
if (-not $probe.Valid) {
    $result = [ordered]@{
        status = 'ERROR_FFPROBE'
        source_mpkg = $MpkgPath
        source_sha256 = $sourceHash
        temp_pkg = $pkgPath
        temp_pkg_sha256 = $copyHash
        extracted_video = $sourceVideo.FullName
        output_mp4 = $outputPath
        output_size = $outputItem.Length
        ffprobe_error = $probe.Error
        repkg_log = $repkgLog
    }
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    throw "ffprobe validation failed for $outputPath. See $resultPath"
}

$videoStream = @($probe.Json.streams | Where-Object { $_.codec_type -eq 'video' })[0]
$audioStreams = @($probe.Json.streams | Where-Object { $_.codec_type -eq 'audio' })
$result = [ordered]@{
    status = 'SUCCESS'
    source_mpkg = $MpkgPath
    source_sha256 = $sourceHash
    temp_pkg = $pkgPath
    temp_pkg_sha256 = $copyHash
    extracted_video = $sourceVideo.FullName
    output_mp4 = $outputPath
    output_sha256 = (Get-FileHash -LiteralPath $outputPath -Algorithm SHA256).Hash
    output_size = $outputItem.Length
    codec = $videoStream.codec_name
    codec_long_name = $videoStream.codec_long_name
    width = $videoStream.width
    height = $videoStream.height
    frame_rate = $videoStream.r_frame_rate
    duration = $probe.Json.format.duration
    audio_stream_count = $audioStreams.Count
    repkg_exit_code = $extractResult.ExitCode
    repkg_log = $repkgLog
}
$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $resultPath -Encoding UTF8

if (-not $KeepExtracted) {
    Remove-Item -LiteralPath $extractDir -Recurse -Force
}

Write-Host ($result | ConvertTo-Json -Depth 8)
