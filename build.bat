@echo off
REM ============================================
REM PDF Sortier Meister - Build Script
REM Erstellt eine Windows .exe Distribution
REM ============================================

echo.
echo ========================================
echo PDF Sortier Meister - Build
echo ========================================
echo.

REM Prüfen ob PyInstaller installiert ist
python -c "import PyInstaller" 2>NUL
if errorlevel 1 (
    echo PyInstaller nicht gefunden. Installiere...
    pip install pyinstaller
)

REM Alte Build-Artefakte löschen
echo Loesche alte Build-Dateien...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

REM Build starten
echo.
echo Starte Build...
echo.
pyinstaller pdf_sortier_meister.spec --clean

REM Prüfen ob erfolgreich
if exist "dist\PDF_Sortier_Meister.exe" (
    echo.
    echo ========================================
    echo BUILD ERFOLGREICH!
    echo ========================================
    echo.
    echo Die Anwendung wurde erstellt unter:
    echo   dist\PDF_Sortier_Meister.exe
    echo.
    echo Groesse:
    for %%A in ("dist\PDF_Sortier_Meister.exe") do echo   %%~zA Bytes
    echo.
) else (
    echo.
    echo ========================================
    echo BUILD FEHLGESCHLAGEN!
    echo ========================================
    echo.
    echo Bitte Fehlermeldungen oben pruefen.
    echo.
)

pause
