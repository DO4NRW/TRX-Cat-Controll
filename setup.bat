@echo off
REM TRX Cat Control V2 — Windows Setup
REM Verwendung: Doppelklick oder setup.bat in CMD

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

echo Python gefunden.

REM venv erstellen
if not exist "venv" (
    echo Erstelle virtuelle Umgebung...
    python -m venv venv
)

REM Aktivieren + Dependencies
call venv\Scripts\activate.bat
echo Installiere Abhängigkeiten...
pip install --quiet --upgrade pip
pip install --quiet PySide6 numpy sounddevice pyserial

echo.
echo Setup fertig!
echo.
echo Starten mit: start.bat
echo.
pause
