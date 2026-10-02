$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $PSScriptRoot 'save_dialog_controller.cs'
$buildDir = Join-Path $projectRoot 'temp\logs\save_dialog_controller_build'
$exe = Join-Path $buildDir 'save_dialog_controller.exe'
$csc = 'D:\1_Software\40_Programming software\Visual Studio Build Tools 2022\MSBuild\Current\Bin\Roslyn\csc.exe'
$uiaClient = Join-Path $env:windir 'Microsoft.NET\Framework64\v4.0.30319\WPF\UIAutomationClient.dll'
$uiaTypes = Join-Path $env:windir 'Microsoft.NET\Framework64\v4.0.30319\WPF\UIAutomationTypes.dll'

foreach ($path in @($source, $csc, $uiaClient, $uiaTypes)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required path not found: $path"
    }
}

New-Item -ItemType Directory -Path $buildDir -Force | Out-Null
& $csc /nologo /target:exe /out:$exe /optimize+ /debug- `
    /reference:$uiaClient /reference:$uiaTypes `
    /reference:System.dll /reference:System.Core.dll `
    $source 2>&1 | Tee-Object -FilePath (Join-Path $buildDir 'build.log')
if ($LASTEXITCODE -ne 0) {
    throw "save_dialog_controller build failed"
}

Get-FileHash -LiteralPath $exe -Algorithm SHA256 |
    Tee-Object -FilePath (Join-Path $buildDir 'controller.sha256')
