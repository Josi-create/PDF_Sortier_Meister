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
- [ ] Draft veroeffentlichen.

## 5. Smoke-Test

- [ ] Gebaute EXE (bzw. DMG) mit isoliertem APPDATA/HOME starten (frisches
      Profil, kein bestehendes Config-/Datenbank-Verzeichnis) und den
      Einrichtungs-Assistenten inkl. Ollama-Erkennung/-Empfehlung, Sortierung
      und Beenden pruefen.
