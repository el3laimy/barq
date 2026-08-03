; Barq Download Manager Installer Script
; Requires NSIS (http://nsis.sourceforge.net)

!define APP_NAME "Barq Download Manager"
!define EXE_NAME "BarqDownloader.exe"
!define PUBLISHER "Barq Project"
!define VERSION "1.0.0"

Name "${APP_NAME}"
OutFile "BarqSetup_v${VERSION}.exe"
InstallDir "$PROGRAMFILES64\BarqDownloader"
SetCompressor lzma

; --- UI Settings ---
!include "MUI2.nsh"
!define MUI_ABORTWARNING
!define MUI_ICON "icon.ico" ; Ensure you have an icon.ico in the root

; --- Pages ---
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; --- Languages ---
!insertmacro MUI_LANGUAGE "English"

Section "MainSection" SEC01
    SetOutPath "$INSTDIR"
    File /r "dist\BarqDownloader\*.*"
    
    ; Create Shortcuts
    CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${EXE_NAME}"
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${EXE_NAME}"
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk" "$INSTDIR\uninstall.exe"

    ; Browser Integration (Run the registration script)
    DetailPrint "Registering Browser Integration..."
    nsExec::Exec '"$INSTDIR\browser_integration\install_host.bat"'

    ; Write Uninstaller
    WriteUninstaller "$INSTDIR\uninstall.exe"
    
    ; Add to Add/Remove Programs
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\BarqDownloader" "DisplayName" "${APP_NAME}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\BarqDownloader" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\BarqDownloader" "DisplayIcon" "$INSTDIR\${EXE_NAME}"
SectionEnd

Section "Uninstall"
    ; Delete Files
    Delete "$DESKTOP\${APP_NAME}.lnk"
    RMDir /r "$SMPROGRAMS\${APP_NAME}"
    RMDir /r "$INSTDIR"

    ; Remove Registry Keys
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\BarqDownloader"
SectionEnd
