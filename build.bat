@echo off
echo ========================================
echo   Barq Downloader - Packaging Engine
echo ========================================

:: Clean previous builds
if exist "dist" rd /s /q "dist"
if exist "build" rd /s /q "build"

echo [1/2] Building Executable with PyInstaller...
pyinstaller --clean build_executable.spec

if %errorlevel% equ 0 (
    echo.
    echo [2/2] Build Successful! 
    echo Executable is located in: %cd%\dist\BarqDownloader
    echo.
    echo Next Step: Run barq_installer.nsi script (NSIS) to create installer.
) else (
    echo.
    echo Error: Build Failed. Please check the logs above.
)
pause
