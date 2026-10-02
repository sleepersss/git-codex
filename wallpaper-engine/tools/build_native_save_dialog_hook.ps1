$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SourceDir = Join-Path $PSScriptRoot 'native_save_dialog_hook'
$BuildDir = Join-Path $ProjectRoot 'temp\logs\native_save_dialog_hook_build'
$VsRoot = 'D:\1_Software\40_Programming software\Visual Studio Build Tools 2022'
$VcVars = Join-Path $VsRoot 'VC\Auxiliary\Build\vcvars64.bat'
$Cl = Join-Path $VsRoot 'VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe'
$Link = Join-Path $VsRoot 'VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\link.exe'

foreach ($path in @($VcVars, $Cl, $Link)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Build tool not found: $path"
    }
}

New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null
$hookObj = Join-Path $BuildDir 'save_dialog_hook.obj'
$injectorObj = Join-Path $BuildDir 'save_dialog_injector.obj'
$hookDll = Join-Path $BuildDir 'save_dialog_hook.dll'
$injectorExe = Join-Path $BuildDir 'save_dialog_injector.exe'
$probeObj = Join-Path $BuildDir 'save_dialog_probe.obj'
$probeExe = Join-Path $BuildDir 'save_dialog_probe.exe'
$hookManifest = Join-Path $BuildDir 'current_hook_dll.txt'
$logPath = Join-Path $BuildDir 'build.log'

$hookDllForBuild = $hookDll
if (Test-Path -LiteralPath $hookDll) {
    Remove-Item -LiteralPath $hookDll -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $hookDll) {
        $version = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
        $hookDllForBuild = Join-Path $BuildDir "save_dialog_hook_$version.dll"
        Write-Output "Fixed hook DLL is locked; building versioned DLL: $hookDllForBuild"
    }
}

Remove-Item -LiteralPath $hookObj, $injectorObj, $injectorExe, $probeObj, $probeExe -Force -ErrorAction SilentlyContinue

$vcEnvironment = @(cmd.exe /d /s /c ('call "{0}" & set' -f $VcVars))
if ($LASTEXITCODE -ne 0) {
    throw "Could not initialize the Visual Studio environment."
}
$seenEnvironmentNames = @{}
foreach ($line in $vcEnvironment) {
    if ($line -match '^([^=]+)=(.*)$') {
        $name = [string]$Matches[1]
        $key = $name.ToUpperInvariant()
        if ($seenEnvironmentNames.ContainsKey($key)) {
            continue
        }
        $seenEnvironmentNames[$key] = $true
        Set-Item -LiteralPath ("Env:{0}" -f $name) -Value $Matches[2]
    }
}

& $Cl /nologo /std:c++17 /EHsc /LD /O2 /DUNICODE /D_UNICODE `
    "/I$SourceDir" /c "$SourceDir\save_dialog_hook.cpp" "/Fo$hookObj" 2>&1 |
    Tee-Object -FilePath $logPath
if ($LASTEXITCODE -ne 0) {
    throw "Hook DLL compilation failed. See $logPath"
}

& $Link /nologo /DLL "/OUT:$hookDllForBuild" "$hookObj" ole32.lib shell32.lib 2>&1 |
    Tee-Object -FilePath $logPath -Append
if ($LASTEXITCODE -ne 0) {
    throw "Hook DLL linking failed. See $logPath"
}

& $Cl /nologo /std:c++17 /EHsc /O2 /DUNICODE /D_UNICODE `
    /c "$SourceDir\save_dialog_injector.cpp" "/Fo$injectorObj" 2>&1 |
    Tee-Object -FilePath $logPath -Append
if ($LASTEXITCODE -ne 0) {
    throw "Injector compilation failed. See $logPath"
}

& $Link /nologo /SUBSYSTEM:CONSOLE "/OUT:$injectorExe" "$injectorObj" 2>&1 |
    Tee-Object -FilePath $logPath -Append
if ($LASTEXITCODE -ne 0) {
    throw "Injector linking failed. See $logPath"
}

& $Cl /nologo /std:c++17 /EHsc /O2 /DUNICODE /D_UNICODE `
    /c "$SourceDir\save_dialog_probe.cpp" "/Fo$probeObj" 2>&1 |
    Tee-Object -FilePath $logPath -Append
if ($LASTEXITCODE -ne 0) {
    throw "Probe compilation failed. See $logPath"
}

& $Link /nologo /SUBSYSTEM:CONSOLE "/OUT:$probeExe" "$probeObj" ole32.lib shell32.lib 2>&1 |
    Tee-Object -FilePath $logPath -Append
if ($LASTEXITCODE -ne 0) {
    throw "Probe linking failed. See $logPath"
}

Set-Content -LiteralPath $hookManifest -Value $hookDllForBuild -Encoding UTF8
Get-FileHash -LiteralPath $hookDllForBuild, $injectorExe, $probeExe -Algorithm SHA256 |
    Tee-Object -FilePath (Join-Path $BuildDir 'artifacts.sha256')
