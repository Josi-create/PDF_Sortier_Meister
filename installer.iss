; ============================================================
; PDF Sortier Meister - Inno Setup Installer Script
;
; Kompilieren mit (Version wird aus src/main.py gelesen):
;   venv\Scripts\python.exe scripts\build_installer.py
; oder direkt:
;   ISCC.exe /DMyAppVersion=0.15.1 installer.iss
;
; Inno Setup 6 kostenlos: https://jrsoftware.org/isinfo.php
;
; Voraussetzung: build.bat wurde zuvor erfolgreich ausgefuehrt,
; sodass dist\PDF_Sortier_Meister\ existiert (mit PDF_Sortier_Meister.exe,
; pdfsm-dienst.exe und pdfsm-dienstw.exe der Dokumentensuche).
; ============================================================

#define MyAppName "PDF Sortier Meister"
#ifndef MyAppVersion
  #error MyAppVersion fehlt - bitte /DMyAppVersion=x.y.z uebergeben oder scripts/build_installer.py verwenden
#endif
#define MyAppPublisher "PDF Sortier Meister"
#define MyAppExeName "PDF_Sortier_Meister.exe"

[Setup]
AppId={{7A1E4B2C-9F3D-4E6A-B1C2-3D4E5F6A7B8C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PDF Sortier Meister
DefaultGroupName=PDF Sortier Meister
DisableProgramGroupPage=yes
OutputDir=dist\installer
; Fester Dateiname (ohne Version), damit der GitHub-Link
; releases/latest/download/PDF_Sortier_Meister_Setup.exe immer auf die
; neueste Version zeigt (Issue #49). Die Version steckt in AppVersion.
OutputBaseFilename=PDF_Sortier_Meister_Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=icon.ico

[InstallDelete]
; Beim Drueber-Installieren die PyInstaller-Dateien der Vorversion
; entfernen, damit keine veralteten DLLs/Module zurueckbleiben (Issue #48).
; Nutzerdaten liegen in %APPDATA%\PDF_Sortier_Meister und bleiben unberuehrt.
Type: filesandordirs; Name: "{app}\_internal"

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Kompletten PyInstaller-onedir-Ordner mitnehmen
Source: "dist\PDF_Sortier_Meister\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Lizenztext (GPL-3.0-or-later) gut sichtbar neben der EXE
Source: "LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Zeitplan der Dokumentensuche nach den Einstellungen einrichten (Aufgabenplanung,
; Ordner "\PDF Sortier Meister\"), z. B. nach einer Neuinstallation an anderem Ort.
; Ist die Hintergrundindexierung nicht eingeschaltet, passiert nichts.
Filename: "{app}\pdfsm-dienstw.exe"; Parameters: "zeitplan --einrichten"; Flags: runhidden runasoriginaluser waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Aufgaben der Dokumentensuche entfernen (beendet auch die Browser-Oberflaeche).
; Einstellungen, Suchindex und Sicherungskopien in %APPDATA% bleiben erhalten.
Filename: "{app}\pdfsm-dienstw.exe"; Parameters: "zeitplan --entfernen"; Flags: runhidden waituntilterminated; RunOnceId: "ZeitplanEntfernen"
