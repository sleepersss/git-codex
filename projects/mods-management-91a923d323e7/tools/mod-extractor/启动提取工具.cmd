@echo off
setlocal
cd /d "%~dp0"
set "MOD_EXTRACTOR_APP=%~dp0..\..\outputs\mod-extractor-desktop-v3.3-r6\ModExtractor\ModExtractor.exe"
if exist "%MOD_EXTRACTOR_APP%" (
    start "" "%MOD_EXTRACTOR_APP%"
) else (
    echo ModExtractor package missing: "%MOD_EXTRACTOR_APP%"
    pause
    exit /b 1
)
