@echo off
REM ============================================
REM PDF Sortier Meister - Build Script
REM Erstellt eine Windows-Distribution (onedir)
REM ============================================

echo.
echo ========================================
echo PDF Sortier Meister - Build
echo ========================================
echo.

REM Pruefen ob PyInstaller installiert ist
python -c "import PyInstaller" 2>NUL
if errorlevel 1 (
    echo PyInstaller nicht gefunden. Installiere...
    pip install pyinstaller
)

REM Die LLM-Pakete sind in requirements.txt optional, muessen im Release aber
REM enthalten sein - sonst fehlt die Cloud-KI (OpenRouter/OpenAI/Claude) im Build.
python -c "import openai, anthropic" 2>NUL
if errorlevel 1 (
    echo LLM-Pakete nicht gefunden. Installiere openai + anthropic...
    pip install openai anthropic
)

REM Alte Build-Artefakte loeschen
echo Loesche alte Build-Dateien...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

REM Tesseract-Laufzeit fuer gebuendelte OCR bereitstellen (vendor\tesseract)
if not exist "vendor\tesseract\tesseract.exe" (
    echo Kopiere Tesseract nach vendor\tesseract ...
    python scripts\prepare_tesseract.py
    if errorlevel 1 goto :fail
)

REM Build starten
echo.
echo Starte Build (onedir, nativer Splash aus Bootloader)...
echo.
pyinstaller pdf_sortier_meister.spec --clean --noconfirm
if errorlevel 1 goto :fail

REM Pruefen ob erfolgreich
if exist "dist\PDF_Sortier_Meister\PDF_Sortier_Meister.exe" (
    echo.
    echo ========================================
    echo BUILD ERFOLGREICH!
    echo ========================================
    echo.
    echo Die Anwendung wurde erstellt unter:
    echo   dist\PDF_Sortier_Meister\PDF_Sortier_Meister.exe
    echo.
    echo Ordnergroesse:
    for /f "tokens=3" %%A in ('dir /s /-c "dist\PDF_Sortier_Meister" ^| findstr /C:"Datei(en)"') do echo   %%A Bytes
    echo.
    echo Installer bauen ^(benoetigt Inno Setup 6^)...
    python scripts\build_installer.py
    if errorlevel 1 (
        echo Installer uebersprungen - siehe Meldung oben.
    )
    echo.
    goto :eof
)

:fail
echo.
echo ========================================
echo BUILD FEHLGESCHLAGEN!
echo ========================================
echo.
echo Bitte Fehlermeldungen oben pruefen.
echo.
exit /b 1
