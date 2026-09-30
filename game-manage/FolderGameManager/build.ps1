param(
    [string]$PlayniteInstallDir = 'D:\1_Software\20_Functional tools\Playnite',
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release'
)

$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$outputDir = Join-Path $projectDir "bin\$Configuration"
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
$sdk = Join-Path $PlayniteInstallDir 'Playnite.SDK.dll'
$wpfDir = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\WPF'

if (-not (Test-Path -LiteralPath $compiler)) {
    throw "C# compiler not found: $compiler"
}

if (-not (Test-Path -LiteralPath $sdk)) {
    throw "Playnite SDK not found: $sdk"
}

New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

$sourceFiles = @(
    (Join-Path $projectDir 'FolderGameManager.cs'),
    (Join-Path $projectDir 'FolderGameScanner.cs'),
    (Join-Path $projectDir 'FolderGameManagerSettings.cs'),
    (Join-Path $projectDir 'Properties\AssemblyInfo.cs')
)

$compilerArguments = @(
    '/nologo',
    '/target:library',
    '/platform:anycpu',
    "/out:$(Join-Path $outputDir 'FolderGameManager.dll')",
    "/reference:$sdk",
    '/reference:System.dll',
    '/reference:System.Core.dll',
    "/reference:$(Join-Path $wpfDir 'PresentationFramework.dll')",
    "/reference:$(Join-Path $wpfDir 'WindowsBase.dll')"
)

if ($Configuration -eq 'Release') {
    $compilerArguments += '/optimize+'
}
else {
    $compilerArguments += '/debug:full'
}

& $compiler @compilerArguments @sourceFiles
if ($LASTEXITCODE -ne 0) {
    throw "Plugin build failed. Compiler exit code: $LASTEXITCODE"
}

Copy-Item -LiteralPath (Join-Path $projectDir 'extension.yaml') -Destination $outputDir -Force
Copy-Item -LiteralPath (Join-Path $projectDir 'icon.png') -Destination $outputDir -Force
Copy-Item -LiteralPath (Join-Path $projectDir 'README.md') -Destination $outputDir -Force

Write-Host "Build completed: $outputDir"
