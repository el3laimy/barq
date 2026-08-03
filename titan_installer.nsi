; Titan Download Manager Installer Script
; Requires NSIS (http://nsis.sourceforge.net)

!define APP_NAME "Titan Download Manager"
!define EXE_NAME "TitanDownloader.exe"
!define PUBLISHER "Titan Labs"
!define VERSION "1.0.0"

Name "${APP_NAME}"
OutFile "TitanSetup_v${VERSION}.exe"
InstallDir "$PROGRAMFILES64\TitanDownloader"
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
    File /r "dist\TitanDownloader\*.*"
    
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
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\TitanDownloader" "DisplayName" "${APP_NAME}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\TitanDownloader" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\TitanDownloader" "DisplayIcon" "$INSTDIR\${EXE_NAME}"
SectionEnd

Section "Uninstall"
    ; Kill app if running? 
    ; (Add logic here if needed)

    ; Delete Files
    Delete "$DESKTOP\${APP_NAME}.lnk"
    RMDir /r "$SMPROGRAMS\${APP_NAME}"
    RMDir /r "$INSTDIR"

    ; Remove Registry Keys
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\TitanDownloader"
SectionEnd
