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

[CustomMessages]
german.KiAssistentNeuStarten=Hinweis: Die Dokumentensuche für KI-Assistenten lief noch und wurde für die Aktualisierung beendet. Ist ein KI-Assistent (z. B. Claude) mit der Dokumentensuche verbunden, starten Sie ihn bitte einmal neu, damit er sie wieder findet.
english.KiAssistentNeuStarten=Note: The document search for AI assistants was still running and has been stopped for this update. If an AI assistant (such as Claude) is connected to the document search, please restart it once so that it reconnects.

[Code]
// Issue #229: Die Dienstprogramme der Dokumentensuche (pdfsm-dienst.exe mit Konsole,
// pdfsm-dienstw.exe ohne Fenster) laufen oft noch, wenn das Setup startet: als MCP-Server
// eines KI-Assistenten (je offener Sitzung ein Prozess), als Browser-Oberflaeche oder als
// Indexlauf. Sie haben kein Fenster und kein Symbol im Infobereich, der Nutzer kann sie
// nicht selbst schliessen, und solange sie laufen, scheitert das Ersetzen von _internal.
// Deshalb beendet das Setup sie selbst, und zwar nur die Prozesse, deren Programmdatei
// im Installationsordner liegt.
// Ein abgebrochener Indexlauf schadet nicht: Die Sperrdatei ist eine Sperre des
// Betriebssystems, die Datenbank ist SQLite, und Textebenen entstehen in einer
// Zwischendatei, die erst am Ende an die Stelle des Originals tritt.
// Bewusst ohne WMI: Die Abfrage scheitert, wenn der Knopf "Installieren" von einer
// Bedienungshilfe ausgeloest wird, und haengt an einem weiteren Windows-Dienst.

const
  DIENST_KONSOLE = 'pdfsm-dienst.exe';     // MCP-Server und Kommandozeile
  DIENST_FENSTERLOS = 'pdfsm-dienstw.exe'; // Indexlauf, Browser-Oberflaeche
  PROCESS_TERMINATE = $0001;
  PROCESS_QUERY_LIMITED_INFORMATION = $1000;
  SYNCHRONIZE_RECHT = $00100000;
  MAX_PROZESSE = 8192;

type
  TProzessNummern = array[0..MAX_PROZESSE - 1] of DWORD;

function K32EnumProcesses(var Nummern: TProzessNummern; Bytes: DWORD; var Benoetigt: DWORD): BOOL;
  external 'K32EnumProcesses@kernel32.dll stdcall';
function OpenProcess(Rechte: DWORD; Vererben: BOOL; Nummer: DWORD): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function QueryFullProcessImageName(Prozess: THandle; Flags: DWORD; Pfad: String; var Laenge: DWORD): BOOL;
  external 'QueryFullProcessImageNameW@kernel32.dll stdcall';
function TerminateProcess(Prozess: THandle; ExitCode: UINT): BOOL;
  external 'TerminateProcess@kernel32.dll stdcall';
function WaitForSingleObject(Objekt: THandle; Millisekunden: DWORD): DWORD;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function CloseHandle(Objekt: THandle): BOOL;
  external 'CloseHandle@kernel32.dll stdcall';

var
  KonsolendienstBeendet: Boolean;

// Dateiname (klein) des Prozesses, wenn er ein Dienstprogramm aus "Ordner" ist, sonst ''.
function DienstnameAus(Prozess: THandle; const Ordner: String; var Pfad: String): String;
var
  Laenge: DWORD;
begin
  Result := '';
  Laenge := 1024;
  Pfad := StringOfChar(#0, Laenge);
  if not QueryFullProcessImageName(Prozess, 0, Pfad, Laenge) then
    Exit;
  SetLength(Pfad, Laenge);
  if CompareText(ExtractFilePath(Pfad), AddBackslash(Ordner)) <> 0 then
    Exit;
  Result := Lowercase(ExtractFileName(Pfad));
  if (Result <> DIENST_KONSOLE) and (Result <> DIENST_FENSTERLOS) then
    Result := '';
end;

// Beendet alle Dienstprozesse, deren Programmdatei in "Ordner" liegt, und wartet je Prozess
// bis zu 5 Sekunden auf sein Ende (erst dann gibt Windows die Dateien frei). Gleichnamige
// Programme aus anderen Ordnern und Prozesse anderer Benutzer bleiben unberuehrt.
procedure DienstprozesseBeenden(const Ordner: String);
var
  Nummern: TProzessNummern;
  Benoetigt: DWORD;
  I: Integer;
  Prozess: THandle;
  Pfad, Name: String;
begin
  if not K32EnumProcesses(Nummern, MAX_PROZESSE * 4, Benoetigt) then
  begin
    Log('Laufende Prozesse konnten nicht ermittelt werden.');
    Exit;
  end;
  for I := 0 to Integer(Benoetigt div 4) - 1 do
  begin
    Prozess := OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION or PROCESS_TERMINATE or SYNCHRONIZE_RECHT,
      False, Nummern[I]);
    if Prozess = 0 then
      Continue;   // Systemprozess oder fremder Benutzer
    Name := DienstnameAus(Prozess, Ordner, Pfad);
    if Name <> '' then
    begin
      Log('Beende Dienstprozess ' + IntToStr(Nummern[I]) + ': ' + Pfad);
      if TerminateProcess(Prozess, 1) then
      begin
        WaitForSingleObject(Prozess, 5000);
        if Name = DIENST_KONSOLE then
          KonsolendienstBeendet := True;
      end
      else
        Log('Beenden fehlgeschlagen: ' + SysErrorMessage(DLLGetLastError));
    end;
    CloseHandle(Prozess);
  end;
end;

// Laeuft vor der Pruefung auf benutzte Dateien und vor dem Kopieren.
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  DienstprozesseBeenden(ExpandConstant('{app}'));
end;

// Wurde ein MCP-Server beendet, findet der KI-Assistent die Dokumentensuche erst nach
// seinem Neustart wieder: auf der letzten Seite darauf hinweisen.
procedure CurPageChanged(CurPageID: Integer);
var
  Vorher, Mehr: Integer;
begin
  if (CurPageID = wpFinished) and KonsolendienstBeendet then
  begin
    Vorher := WizardForm.FinishedLabel.Height;
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10 + #13#10 +
      CustomMessage('KiAssistentNeuStarten');
    WizardForm.AdjustLabelHeight(WizardForm.FinishedLabel);
    Mehr := WizardForm.FinishedLabel.Height - Vorher + ScaleY(8);
    WizardForm.RunList.Top := WizardForm.RunList.Top + Mehr;
    WizardForm.RunList.Height := WizardForm.RunList.Height - Mehr;
  end;
end;

// Deinstallation: Dienstprozesse beenden, bevor die Dateien geloescht werden.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    DienstprozesseBeenden(ExpandConstant('{app}'));
end;
