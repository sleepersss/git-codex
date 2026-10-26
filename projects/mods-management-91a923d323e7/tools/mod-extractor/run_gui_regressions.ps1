param([string[]]$Samples = @('augusta','carlotta','evanescia','yaoguang','denia','iuno'))
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$sampleRuns = @{
    augusta = 'mod-extraction-auto-00c8b82beaf6-20261010-8d9da808'
    carlotta = 'mod-extraction-auto-50f876cab282-20261010-ca1927f1'
    evanescia = 'mod-extraction-auto-e5a4a639fc7f-20261010-be52b133'
    yaoguang = 'mod-extraction-auto-2653a2e3a922-20261010-17526eda'
    denia = 'mod-extraction-denia-20261010-f3af91d0'
    iuno = 'mod-extraction-auto-7845a914ddd8-20261010-5fdfe976'
}
$exePath = (Resolve-Path (Join-Path $taskRoot 'outputs/mod-extractor-desktop-v3/ModExtractor/ModExtractor.exe')).Path
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONUTF8 = '1'
foreach ($sample in $Samples) {
    $jobPath = Join-Path $taskRoot ('work/'+$sampleRuns[$sample]+'/job.json')
    $job = Get-Content -LiteralPath $jobPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $reportPath = Join-Path $taskRoot ('outputs/mod-extractor-qa/v3-'+$sample+'-result.json')
    $process = Start-Process -FilePath $exePath -ArgumentList @('--smoke-source',('"'+$job.source+'"'),('"'+$reportPath+'"')) -WindowStyle Hidden -PassThru
    $process.WaitForExit()
    if (-not (Test-Path -LiteralPath $reportPath)) { throw ($sample+': report missing') }
    $result = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Output ($sample+': exit='+$process.ExitCode+', status='+$result.status+', body='+$result.body_status+', run='+$result.run)
    if ($process.ExitCode -ne 0 -or $result.status -ne 'passed') { throw ($sample+': '+$result.error) }
    $expectedBody = if ($sample -eq 'iuno') {'abandoned'} else {'available'}
    if ($result.body_status -ne $expectedBody) { throw ($sample+': unexpected body outcome '+$result.body_status) }
}
