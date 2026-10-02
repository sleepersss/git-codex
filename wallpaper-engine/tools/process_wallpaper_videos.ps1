param(
    [switch]$DryRun,
    [string[]]$WorkshopId
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = 'D:\7_Video\20_Wallpaper Engine'
$SourceRoot = 'E:\1_Game\steam\steamapps\workshop\content\431960'
$DatabaseDir = Join-Path $ProjectRoot 'database'
$WallpaperDir = Join-Path $ProjectRoot 'wallpaper'
$VideoRoot = Join-Path $WallpaperDir 'video'
$LogDir = Join-Path $DatabaseDir 'logs'
$BackupRoot = Join-Path $DatabaseDir 'backups'
$LockPath = Join-Path $DatabaseDir '.lock'
$RunStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$RunIso = (Get-Date).ToUniversalTime().ToString('o')
$LogPath = Join-Path $LogDir "process_videos_$RunStamp.log"

function Write-Log {
    param([string]$Message)
    $line = "[$((Get-Date).ToString('s'))] $Message"
    Write-Host $line
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
}

function Sanitize-Name {
    param(
        [AllowNull()][string]$Value,
        [string]$Fallback
    )
    if ([string]::IsNullOrWhiteSpace($Value)) {
        $Value = $Fallback
    }
    $safe = $Value -replace '[\\/:*?"<>|]', '_'
    $safe = $safe -replace '[\x00-\x1f]', ''
    $safe = $safe.Trim().TrimEnd('.', ' ')
    if ([string]::IsNullOrWhiteSpace($safe)) {
        $safe = $Fallback
    }
    if ($safe.Length -gt 160) {
        $safe = $safe.Substring(0, 160).Trim().TrimEnd('.', ' ')
    }
    return $safe
}

function Get-VideoFile {
    param($Record)

    $videoExts = @('.mp4', '.m4v', '.mov', '.webm')
    $expectedFile = [string]$Record.raw_project_metadata.file
    if (-not [string]::IsNullOrWhiteSpace($expectedFile)) {
        $expectedPath = Join-Path ([string]$Record.source_workshop_path) $expectedFile
        if ((Test-Path -LiteralPath $expectedPath) -and ($videoExts -contains ([System.IO.Path]::GetExtension($expectedPath).ToLowerInvariant()))) {
            return [pscustomobject]@{
                Path = (Get-Item -LiteralPath $expectedPath).FullName
                Warning = $null
            }
        }
    }

    $candidates = @(Get-ChildItem -LiteralPath ([string]$Record.source_workshop_path) -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $videoExts -contains $_.Extension.ToLowerInvariant() } |
        Sort-Object Length -Descending)

    if ($candidates.Count -eq 1) {
        return [pscustomobject]@{
            Path = $candidates[0].FullName
            Warning = "PROJECT_FILE_MISSING_USED_ONLY_VIDEO expected=$expectedFile actual=$($candidates[0].Name)"
        }
    }

    if ($candidates.Count -gt 1) {
        return [pscustomobject]@{
            Path = $null
            Warning = "PROJECT_FILE_MISSING_MULTIPLE_VIDEO_CANDIDATES expected=$expectedFile candidates=$($candidates.Name -join ' | ')"
        }
    }

    return [pscustomobject]@{
        Path = $null
        Warning = "VIDEO_SOURCE_NOT_FOUND expected=$expectedFile"
    }
}

function Get-Fps {
    param([AllowNull()][string]$Rate)
    if ([string]::IsNullOrWhiteSpace($Rate) -or $Rate -eq '0/0') {
        return $null
    }
    if ($Rate -match '^(\d+)/(\d+)$') {
        $den = [double]$Matches[2]
        if ($den -eq 0) {
            return $null
        }
        return [math]::Round(([double]$Matches[1] / $den), 3)
    }
    $parsed = 0.0
    if ([double]::TryParse($Rate, [ref]$parsed)) {
        return [math]::Round($parsed, 3)
    }
    return $null
}

function Read-VideoMetadata {
    param([string]$Path)

    $ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
    if (-not $ffprobe) {
        return [pscustomobject]@{
            Width = $null; Height = $null; Resolution = $null; Duration = $null
            Fps = $null; Codec = $null; Bitrate = $null
            Warning = 'FFPROBE_NOT_FOUND'
        }
    }

    try {
        $json = & $ffprobe.Source -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate,avg_frame_rate,codec_name,bit_rate -show_entries format=duration,bit_rate -of json -- $Path
        $meta = ($json -join "`n") | ConvertFrom-Json
        $stream = @($meta.streams | Select-Object -First 1)[0]
        $format = $meta.format
        $width = if ($stream.width) { [int]$stream.width } else { $null }
        $height = if ($stream.height) { [int]$stream.height } else { $null }
        $duration = if ($format.duration) { [math]::Round([double]$format.duration, 3) } else { $null }
        $fps = Get-Fps -Rate ([string]$stream.avg_frame_rate)
        if ($null -eq $fps) {
            $fps = Get-Fps -Rate ([string]$stream.r_frame_rate)
        }
        $bitrate = $null
        if ($format.bit_rate) {
            $bitrate = [int64]$format.bit_rate
        } elseif ($stream.bit_rate) {
            $bitrate = [int64]$stream.bit_rate
        }
        return [pscustomobject]@{
            Width = $width
            Height = $height
            Resolution = if ($width -and $height) { "${width}x${height}" } else { $null }
            Duration = $duration
            Fps = $fps
            Codec = if ($stream.codec_name) { [string]$stream.codec_name } else { $null }
            Bitrate = $bitrate
            Warning = $null
        }
    } catch {
        return [pscustomobject]@{
            Width = $null; Height = $null; Resolution = $null; Duration = $null
            Fps = $null; Codec = $null; Bitrate = $null
            Warning = "FFPROBE_FAILED $($_.Exception.Message)"
        }
    }
}

function Get-ProjectRelativePath {
    param(
        [string]$BasePath,
        [string]$FullPath
    )
    $baseFull = [System.IO.Path]::GetFullPath($BasePath).TrimEnd('\') + '\'
    $targetFull = [System.IO.Path]::GetFullPath($FullPath)
    if (-not $targetFull.StartsWith($baseFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside project root: $targetFull"
    }
    return $targetFull.Substring($baseFull.Length)
}

function ConvertTo-CsvRows {
    param($Records)

    foreach ($record in $Records) {
        [pscustomobject]@{
            title = $record.title
            type = $record.type
            scene_class = $record.scene_class
            tags = if ($record.tags -is [array]) { $record.tags -join ';' } else { [string]$record.tags }
            primary_tag = $record.primary_tag
            workshopid = $record.workshopid
            workshopurl = $record.workshopurl
            relative_path = $record.relative_path
            filename = $record.filename
            width = $record.width
            height = $record.height
            resolution = $record.resolution
            file_size = $record.file_size
            duration = $record.duration
            fps = $record.fps
            codec = $record.codec
            bitrate = $record.bitrate
            file_created_time = $record.file_created_time
            file_modified_time = $record.file_modified_time
            source_hash = $record.source_hash
            output_hash = $record.output_hash
            archive_state = $record.archive_state
            processing_status = $record.processing_status
            archive_location = $record.archive_location
        }
    }
}

function Write-JsonAtomic {
    param(
        [string]$Path,
        $Value,
        [int]$Depth = 100
    )
    $tmp = "$Path.tmp"
    $Value | ConvertTo-Json -Depth $Depth | Set-Content -LiteralPath $tmp -Encoding UTF8
    $null = Get-Content -LiteralPath $tmp -Raw -Encoding UTF8 | ConvertFrom-Json
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Write-CsvAtomic {
    param(
        [string]$Path,
        $Rows
    )
    $tmp = "$Path.tmp"
    @($Rows) | Export-Csv -LiteralPath $tmp -NoTypeInformation -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

New-Item -ItemType Directory -Force -Path $LogDir, $BackupRoot, $VideoRoot | Out-Null
New-Item -ItemType File -Force -Path $LogPath | Out-Null

if (Test-Path -LiteralPath $LockPath) {
    throw "Database lock exists: $LockPath"
}

try {
    if (-not $DryRun) {
        Set-Content -LiteralPath $LockPath -Value "process_wallpaper_videos $RunIso" -Encoding UTF8
    }

    $dbPath = Join-Path $DatabaseDir 'wallpapers.json'
    $csvPath = Join-Path $DatabaseDir 'wallpapers.csv'
    $historyPath = Join-Path $DatabaseDir 'history.json'

    $db = Get-Content -LiteralPath $dbPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $history = Get-Content -LiteralPath $historyPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$db.source_root -ne $SourceRoot) {
        throw "Unexpected source_root: $($db.source_root)"
    }

    $records = @($db.wallpapers.PSObject.Properties | ForEach-Object { $_.Value })
    $videos = @($records | Where-Object { $_.type -eq 'video' } | Sort-Object workshopid)
    if ($WorkshopId -and $WorkshopId.Count -gt 0) {
        $requestedIds = @($WorkshopId | ForEach-Object { ([string]$_ -split ',') } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        $unknownIds = @($requestedIds | Where-Object { -not $db.wallpapers.PSObject.Properties[$_] })
        if ($unknownIds.Count -gt 0) {
            throw "Workshop IDs are missing from the database: $($unknownIds -join ', ')"
        }
        $videos = @($videos | Where-Object { $requestedIds -contains [string]$_.workshopid })
        if ($videos.Count -ne $requestedIds.Count) {
            throw "One or more requested Workshop IDs are not video records."
        }
    }
    Write-Log "Video records: $($videos.Count)"

    if (-not $DryRun) {
        $backupDir = Join-Path $BackupRoot $RunStamp
        New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
        Copy-Item -LiteralPath $dbPath -Destination (Join-Path $backupDir 'wallpapers.json') -Force
        Copy-Item -LiteralPath $csvPath -Destination (Join-Path $backupDir 'wallpapers.csv') -Force
        Copy-Item -LiteralPath $historyPath -Destination (Join-Path $backupDir 'history.json') -Force
        Write-Log "Database backup: $backupDir"
    }

    $processed = 0
    $skipped = 0
    $errors = 0
    $warnings = 0
    $duplicates = @()

    foreach ($record in $videos) {
        $id = [string]$record.workshopid
        $oldStatus = [string]$record.processing_status
        $sourceResult = Get-VideoFile -Record $record
        if ($sourceResult.Warning) {
            $warnings++
            if (-not $record.warnings) {
                $record | Add-Member -NotePropertyName warnings -NotePropertyValue @() -Force
            }
            $record.warnings = @($record.warnings) + $sourceResult.Warning
            if (-not $DryRun) {
                $history.events += [pscustomobject]@{
                    timestamp = $RunIso
                    workshopid = $id
                    event = 'WARNING'
                    old_state = $oldStatus
                    new_state = $oldStatus
                    details = $sourceResult.Warning
                }
            }
            Write-Log "WARNING $id $($sourceResult.Warning)"
        }

        if (-not $sourceResult.Path) {
            $errors++
            $record.processing_status = 'ERROR'
            $record.conversion_status = 'ERROR'
            if (-not $DryRun) {
                $history.events += [pscustomobject]@{
                    timestamp = $RunIso
                    workshopid = $id
                    event = 'ERROR'
                    old_state = $oldStatus
                    new_state = 'ERROR'
                    details = 'Video source not found or ambiguous'
                }
            }
            continue
        }

        $sourceItem = Get-Item -LiteralPath $sourceResult.Path
        $tag = Sanitize-Name -Value ([string]$record.primary_tag) -Fallback '_NoTag'
        $title = Sanitize-Name -Value ([string]$record.title) -Fallback $id
        $ext = $sourceItem.Extension
        if ([string]::IsNullOrWhiteSpace($ext)) {
            $ext = '.mp4'
        }
        $targetDir = Join-Path $VideoRoot $tag
        $targetName = "$title$ext"
        $targetPath = Join-Path $targetDir $targetName

        if ((Test-Path -LiteralPath $targetPath) -and ([string]$record.relative_path)) {
            $existingPath = Join-Path $ProjectRoot ([string]$record.relative_path)
            if ((Test-Path -LiteralPath $existingPath) -and ((Get-Item -LiteralPath $existingPath).Length -gt 0)) {
                $skipped++
                Write-Log "SKIP existing output $id $existingPath"
                continue
            }
        }

        if (Test-Path -LiteralPath $targetPath) {
            $targetName = "$title [$id]$ext"
            $targetPath = Join-Path $targetDir $targetName
        }

        $relativePath = Get-ProjectRelativePath -BasePath $ProjectRoot -FullPath $targetPath
        Write-Log "COPY $id -> $relativePath"

        if ($DryRun) {
            $processed++
            continue
        }

        New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
        Copy-Item -LiteralPath $sourceItem.FullName -Destination $targetPath -Force
        $targetItem = Get-Item -LiteralPath $targetPath
        if ($targetItem.Length -le 0 -or $targetItem.Length -ne $sourceItem.Length) {
            throw "Output verification failed for $id"
        }

        $metadata = Read-VideoMetadata -Path $targetPath
        if ($metadata.Warning) {
            $warnings++
            $record.warnings = @($record.warnings) + $metadata.Warning
            $history.events += [pscustomobject]@{
                timestamp = $RunIso
                workshopid = $id
                event = 'WARNING'
                old_state = $oldStatus
                new_state = $oldStatus
                details = $metadata.Warning
            }
        }

        $outputHash = (Get-FileHash -LiteralPath $targetPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $sameHash = @($records | Where-Object {
            $_.workshopid -ne $id -and
            -not [string]::IsNullOrWhiteSpace([string]$_.output_hash) -and
            ([string]$_.output_hash).ToLowerInvariant() -eq $outputHash
        })
        foreach ($dup in $sameHash) {
            $duplicates += [pscustomobject]@{
                workshopid = $id
                duplicate_of = $dup.workshopid
                title = $record.title
                duplicate_title = $dup.title
                output_hash = $outputHash
            }
            $history.events += [pscustomobject]@{
                timestamp = $RunIso
                workshopid = $id
                event = 'DUPLICATE_FOUND'
                old_state = $oldStatus
                new_state = 'PROCESSED'
                details = "Duplicate output hash with $($dup.workshopid)"
            }
        }

        $record.relative_path = $relativePath
        $record.filename = $targetName
        $record.file_size = $targetItem.Length
        $record.file_created_time = $targetItem.CreationTimeUtc.ToString('o')
        $record.file_modified_time = $targetItem.LastWriteTimeUtc.ToString('o')
        $record.width = $metadata.Width
        $record.height = $metadata.Height
        $record.resolution = $metadata.Resolution
        $record.duration = $metadata.Duration
        $record.fps = $metadata.Fps
        $record.codec = $metadata.Codec
        $record.bitrate = $metadata.Bitrate
        $record.output_hash = $outputHash
        $record.archive_state = 'LOCAL'
        $record.processing_status = 'PROCESSED'
        $record.conversion_status = 'NOT_NEEDED_VIDEO_COPY'
        $record.conversion_time = $RunIso
        $record.archive_location = $null
        $record.last_processed = $RunIso
        $record.last_seen = $RunIso
        $record.artifacts = @([pscustomobject]@{
            kind = 'video'
            relative_path = $relativePath
            filename = $targetName
            width = $metadata.Width
            height = $metadata.Height
            resolution = $metadata.Resolution
            duration = $metadata.Duration
            fps = $metadata.Fps
            codec = $metadata.Codec
            bitrate = $metadata.Bitrate
            file_size = $targetItem.Length
            output_hash = $outputHash
        })

        $history.events += [pscustomobject]@{
            timestamp = $RunIso
            workshopid = $id
            event = 'COPIED'
            old_state = $oldStatus
            new_state = 'PROCESSED'
            details = "Copied source video to $relativePath"
        }
        $history.events += [pscustomobject]@{
            timestamp = $RunIso
            workshopid = $id
            event = 'VERIFIED'
            old_state = 'PROCESSING'
            new_state = 'PROCESSED'
            details = "Verified copied video: size=$($targetItem.Length) sha256=$outputHash"
        }

        $processed++
    }

    if (-not $DryRun) {
        $db.updated_at = $RunIso
        $history.updated_at = $RunIso

        $allRows = ConvertTo-CsvRows -Records $records
        Write-JsonAtomic -Path $dbPath -Value $db
        Write-CsvAtomic -Path $csvPath -Rows $allRows
        Write-JsonAtomic -Path $historyPath -Value $history

        $processedVideoRows = ConvertTo-CsvRows -Records (@($records | Where-Object { $_.type -eq 'video' -and $_.processing_status -eq 'PROCESSED' }))
        Write-CsvAtomic -Path (Join-Path $VideoRoot 'metadata.csv') -Rows $processedVideoRows
        Write-CsvAtomic -Path (Join-Path $WallpaperDir 'metadata.csv') -Rows $processedVideoRows

        $tagGroups = @($records | Where-Object { $_.type -eq 'video' -and $_.processing_status -eq 'PROCESSED' } | Group-Object primary_tag)
        foreach ($group in $tagGroups) {
            $safeTag = Sanitize-Name -Value ([string]$group.Name) -Fallback '_NoTag'
            $dir = Join-Path $VideoRoot $safeTag
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
            Write-CsvAtomic -Path (Join-Path $dir 'metadata.csv') -Rows (ConvertTo-CsvRows -Records @($group.Group))
        }
    }

    $summaryPath = Join-Path $LogDir "process_videos_summary_$RunStamp.json"
    $summary = [pscustomobject]@{
        timestamp = $RunIso
        dry_run = [bool]$DryRun
        source_root = $SourceRoot
        video_records = $videos.Count
        processed = $processed
        skipped = $skipped
        errors = $errors
        warnings = $warnings
        duplicates = $duplicates
        log = $LogPath
    }
    if (-not $DryRun) {
        Write-JsonAtomic -Path $summaryPath -Value $summary
    } else {
        $summary | ConvertTo-Json -Depth 20
    }

    Write-Log "SUMMARY processed=$processed skipped=$skipped errors=$errors warnings=$warnings duplicates=$($duplicates.Count)"
    if ($duplicates.Count -gt 0) {
        Write-Log "DUPLICATES $($duplicates | ConvertTo-Json -Compress)"
    }
} finally {
    if (-not $DryRun -and (Test-Path -LiteralPath $LockPath)) {
        Remove-Item -LiteralPath $LockPath -Force
    }
}
