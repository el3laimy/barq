; Barq Download Manager Installer Script
; Requires NSIS (http://nsis.sourceforge.net)

!define APP_NAME "Barq Download Manager"
!define EXE_NAME "Barq.exe"
!define PUBLISHER "Barq Project"
!define VERSION "1.0.0"

Name "${APP_NAME}"
OutFile "BarqSetup_v${VERSION}.exe"
InstallDir "$PROGRAMFILES64\Barq"
SetCompressor lzma

; --- UI Settings ---
!include "MUI2.nsh"
!define MUI_ABORTWARNING
!define MUI_ICON "assets\icons\barq.ico"

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
    File "dist\Barq.exe"
    
    ; Bundle the icon for shortcuts
    SetOutPath "$INSTDIR\assets\icons"
    File "assets\icons\barq.ico"
    SetOutPath "$INSTDIR"

    ; Remove the unsafe bridge left by older Barq installers during upgrade.
    RMDir /r "$INSTDIR\browser_integration"
    DeleteRegKey HKCU "Software\Google\Chrome\NativeMessagingHosts\com.barq.downloader"
    DeleteRegKey HKCU "Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\com.barq.downloader"
    DeleteRegKey HKCU "Software\Microsoft\Edge\NativeMessagingHosts\com.barq.downloader"
    DeleteRegKey HKCU "Software\Mozilla\NativeMessagingHosts\com.barq.downloader"

    ; Create Shortcuts with explicit icon
    CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${EXE_NAME}" "" "$INSTDIR\assets\icons\barq.ico"
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${EXE_NAME}" "" "$INSTDIR\assets\icons\barq.ico"
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk" "$INSTDIR\uninstall.exe"

    ; Write Uninstaller
    WriteUninstaller "$INSTDIR\uninstall.exe"
    
    ; Add to Add/Remove Programs
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Barq" "DisplayName" "${APP_NAME}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Barq" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Barq" "DisplayIcon" "$INSTDIR\assets\icons\barq.ico"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Barq" "Publisher" "${PUBLISHER}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Barq" "DisplayVersion" "${VERSION}"
SectionEnd

Section "Uninstall"
    ; Delete Files
    Delete "$DESKTOP\${APP_NAME}.lnk"
    RMDir /r "$SMPROGRAMS\${APP_NAME}"
    RMDir /r "$INSTDIR"

    ; Remove Registry Keys
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Barq"
SectionEnd
