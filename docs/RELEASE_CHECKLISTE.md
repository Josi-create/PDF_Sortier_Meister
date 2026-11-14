# Release-Checkliste

Ablauf fuer einen neuen Release von PDF Sortier Meister (`vX.Y.Z`).

## 1. Vorbereitung

- [ ] Alle Feature-PRs fuer den Release sind gemergt (main ist gruen: CI auf
      Windows und macOS laeuft durch).
- [ ] **LLM-Modell-Empfehlungen pruefen** (`src/utils/hardware.py`, `MODEL_TIERS`
      / `RAM_ONLY_MODEL` / `CLOUD_MODEL`): sind die empfohlenen Ollama-Modelle
      noch aktuell (Ollama-Library, Downloadgroessen), gibt es neuere/bessere
      Gemma-Generationen, ist `gpt-oss:120b` noch das sinnvolle Cloud-Default?
      `MODEL_TIERS_CHECKED_ON` in `hardware.py` auf das heutige Datum setzen.
      (Hintergrund: Issue #63 - Empfehlungen veralten schnell.)
- [ ] **Vergleich paperless-ngx pruefen** (`Vergleich paperless-ngx.md`): gibt es
      ein neues paperless-ngx-Release (<https://github.com/paperless-ngx/paperless-ngx/releases>),
      das die Tabellen aendert? Versionsnummer und "Stand" im Kopf des Dokuments
      aktualisieren; PDFSM-Features, die seit dem letzten Release dazukamen, in
      Abschnitt 2/3 nachtragen. (Hintergrund: Issue #112 - das Dokument vom
      Maerz 2026 war nach fuenf Monaten in sieben Punkten falsch.)

## 2. Release-Branch

- [ ] Branch `release/vX.Y.Z` von main abzweigen.
- [ ] Version bumpen:
  - `src/main.py` - `__version__ = "X.Y.Z"`
  - `pyproject.toml` - `version = "X.Y.Z"`
- [ ] `CHANGELOG.md`: neuen Abschnitt `## [X.Y.Z] - JJJJ-MM-TT` mit den
      Eintraegen aus `## [Unreleased]` fuellen (bestehende Unreleased-Eintraege
      dorthin verschieben), `## [Unreleased]` leer stehen lassen.
- [ ] PR `release/vX.Y.Z` -> `main` erstellen und mergen.

## 3. Tag und Build

- [ ] Annotierten Tag `vX.Y.Z` auf dem main-Merge-Commit setzen und pushen
      (`git tag -a vX.Y.Z -m "..." && git push origin vX.Y.Z`).
- [ ] `.github/workflows/release.yml` baut automatisch bei Tag-Push:
      Windows-Setup.exe, win64-Zip, macOS-DMGs (arm64 + x86_64) - als
      Draft-Release. Build in GitHub Actions abwarten.

## 4. Release veroeffentlichen

- [ ] Draft-Release pruefen, deutsche Release-Notes schreiben (Abschnitte
      **Neu**, **Behoben**, **Fuer Beta-Tester**), Download-Links im Format
      `releases/latest/download/...` verwenden.
- [ ] **Hinweis auf die SmartScreen-Warnung steht ganz oben** in der
      Release-Beschreibung (solange die Programme nicht signiert sind, #163).
      Der Workflow setzt den Kasten in den Draft; die Release-Notes kommen
      darunter, der Kasten bleibt stehen (nach einem zweiten Workflow-Lauf
      haengt er doppelt am Ende: dort loeschen). Wortlaut: `.github/workflows/release.yml`
      (Schritt „Draft-Release mit Assets erstellen“), gleich wie im README.
- [ ] **Fehlalarm-Meldung bei Microsoft** (solange die Programme nicht signiert
      sind, #163): `PDF_Sortier_Meister_Setup.exe` und `pdfsm-dienstw.exe` aus dem
      Draft-Release unter <https://www.microsoft.com/en-us/wdsi/filesubmission>
      einreichen (Rolle „Software developer“, „Incorrectly detected as
      malware/malicious“, Hinweis auf das GitHub-Repository). Hintergrund:
      Defender hat am 06.11.2026 `pdfsm-dienstw.exe` als
      *Behavior:Win32/Persistence.A!ml* entfernt.
- [ ] Draft veroeffentlichen.

## 5. Smoke-Test

- [ ] Gebaute EXE (bzw. DMG) mit isoliertem APPDATA/HOME starten (frisches
      Profil, kein bestehendes Config-/Datenbank-Verzeichnis) und den
      Einrichtungs-Assistenten inkl. Ollama-Erkennung/-Empfehlung, Sortierung
      und Beenden pruefen.
