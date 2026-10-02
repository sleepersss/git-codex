param(
    [Parameter(Mandatory = $true)]
    [string]$SourcePath,

    [Parameter(Mandatory = $true)]
    [string]$CapturePath,

    [Parameter(Mandatory = $true)]
    [string]$ReadyMarker,

    [int]$TimeoutMinutes = 90,

    [int]$PollMilliseconds = 100
)

$ErrorActionPreference = 'Stop'

$SourcePath = [System.IO.Path]::GetFullPath($SourcePath)
$CapturePath = [System.IO.Path]::GetFullPath($CapturePath)
$ReadyMarker = [System.IO.Path]::GetFullPath($ReadyMarker)
$captureDir = Split-Path -Parent $CapturePath
$logPath = Join-Path $captureDir 'capture.log'
$partPath = "$CapturePath.part"

New-Item -ItemType Directory -Path $captureDir -Force | Out-Null

function Write-CaptureLog([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    Write-Host $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

function Get-Signature {
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        return $null
    }
    $item = Get-Item -LiteralPath $SourcePath
    return [pscustomobject]@{
        Length = $item.Length
        LastWriteTimeUtc = $item.LastWriteTimeUtc
    }
}

function Copy-SourceSnapshot {
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        return $false
    }

    try {
        if (Test-Path -LiteralPath $partPath) {
            Remove-Item -LiteralPath $partPath -Force -ErrorAction SilentlyContinue
        }
        Copy-Item -LiteralPath $SourcePath -Destination $partPath -Force
        $part = Get-Item -LiteralPath $partPath
        if ($part.Length -le 0) {
            Remove-Item -LiteralPath $partPath -Force -ErrorAction SilentlyContinue
            return $false
        }
        Move-Item -LiteralPath $partPath -Destination $CapturePath -Force
        return $true
    } catch {
        Write-CaptureLog "copy retry: $($_.Exception.Message)"
        Remove-Item -LiteralPath $partPath -Force -ErrorAction SilentlyContinue
        return $false
    }
}

Write-CaptureLog "capture started source=$SourcePath marker=$ReadyMarker"
$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
$baseline = Get-Signature
$captured = $false
$lastSignature = $null
$stableSince = $null

while ((Get-Date) -lt $deadline) {
    $current = Get-Signature
    $markerReady = Test-Path -LiteralPath $ReadyMarker -PathType Leaf

    if ($current) {
        $changed = (-not $baseline) -or
            ($current.Length -ne $baseline.Length) -or
            ($current.LastWriteTimeUtc -ne $baseline.LastWriteTimeUtc)

        if ($changed -or $markerReady -or $captured) {
            if (-not $lastSignature -or
                $current.Length -ne $lastSignature.Length -or
                $current.LastWriteTimeUtc -ne $lastSignature.LastWriteTimeUtc) {
                $lastSignature = $current
                $stableSince = Get-Date
                if (Copy-SourceSnapshot) {
                    $captured = $true
                    Write-CaptureLog "snapshot captured length=$($current.Length) write=$($current.LastWriteTimeUtc.ToString('o'))"
                }
            } elseif ($captured -and $stableSince -and ((Get-Date) - $stableSince).TotalMilliseconds -ge 800) {
                if ($markerReady) {
                    Write-CaptureLog "capture finalized"
                    exit 0
                }
            }
        }
    } elseif ($captured -and $markerReady) {
        Write-CaptureLog "source disappeared after capture; capture finalized"
        exit 0
    }

    Start-Sleep -Milliseconds $PollMilliseconds
}

if ($captured -and (Test-Path -LiteralPath $CapturePath -PathType Leaf)) {
    Write-CaptureLog "timeout after capture; retaining captured file"
    exit 0
}

Write-CaptureLog "capture failed: source MP4 was not captured"
exit 2
