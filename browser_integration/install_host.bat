@echo off
setlocal

:: Name of the native messaging host
set HOST_NAME=com.titan.downloader

:: Path to the manifest file
set MANIFEST_PATH=%~dp0host.json

:: Registry key for Chrome Native Messaging Hosts
set REG_KEY=HKCU\Software\Google\Chrome\NativeMessagingHosts\%HOST_NAME%

echo Installing Native Messaging Host: %HOST_NAME%
echo Manifest Path: %MANIFEST_PATH%

:: Add registry key
reg add "%REG_KEY%" /ve /t REG_SZ /d "%MANIFEST_PATH%" /f

if %errorlevel% equ 0 (
    echo successfully registered host.
    echo IMPORTANT: You must update 'host.json' with your actual Chrome Extension ID.
) else (
    echo Failed to register host. Try running as Administrator.
)

pause
