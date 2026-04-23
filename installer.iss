; ============================================================
; PDF Sortier Meister - Inno Setup Installer Script
;
; Kompilieren mit:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;
; Inno Setup 6 kostenlos: https://jrsoftware.org/isinfo.php
;
; Voraussetzung: build.bat wurde zuvor erfolgreich ausgefuehrt,
; sodass dist\PDF_Sortier_Meister\ existiert.
; ============================================================

#define MyAppName "PDF Sortier Meister"
#define MyAppVersion "0.9.0"
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
OutputBaseFilename=PDF_Sortier_Meister_Setup_{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Kompletten PyInstaller-onedir-Ordner mitnehmen
Source: "dist\PDF_Sortier_Meister\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
