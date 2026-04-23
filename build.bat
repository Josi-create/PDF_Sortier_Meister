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

REM Alte Build-Artefakte loeschen
echo Loesche alte Build-Dateien...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

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
    echo Optional: Installer bauen ^(benoetigt Inno Setup 6^)
    echo   "%%ProgramFiles(x86)%%\Inno Setup 6\ISCC.exe" installer.iss
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
