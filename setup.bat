@echo off
REM TRX Cat Control V2 — Einmal-Setup (Windows)
REM Installiert alles und baut die App.

cd /d "%~dp0"

echo.
echo ==================================
echo   TRX Cat Control V2 — Setup
echo ==================================
echo.

REM Python prüfen
python --version >nul 2>&1
if errorlevel 1 (
    echo Python nicht gefunden!
    echo Download: https://www.python.org/downloads/
    echo WICHTIG: Bei der Installation "Add to PATH" ankreuzen!
    pause
    exit /b 1
)

REM venv erstellen
if not exist "venv" (
    echo Erstelle virtuelle Umgebung...
    python -m venv venv
)

call venv\Scripts\activate.bat

REM Dependencies installieren
echo Installiere Abhängigkeiten...
pip install --quiet --upgrade pip
pip install --quiet PySide6 numpy sounddevice pyserial pyinstaller

REM App bauen
echo.
echo Baue App (kann etwas dauern)...
python build.py

echo.
echo ==================================
echo   Setup fertig!
echo ==================================
echo.
echo   Die App findest du unter:
echo   dist\TRX_Cat_Control_V2\TRX_Cat_Control_V2.exe
echo.
pause
