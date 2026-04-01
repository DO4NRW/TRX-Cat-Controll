@echo off
REM TRX Cat Control V2 — Setup (Windows)
REM Einmal ausführen: Doppelklick auf setup.bat

cd /d "%~dp0"

echo.
echo ==================================
echo   TRX Cat Control V2 — Setup
echo ==================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python nicht gefunden!
    echo Download: https://www.python.org/downloads/
    echo WICHTIG: "Add to PATH" ankreuzen!
    pause
    exit /b 1
)

if not exist "venv" (
    echo Erstelle virtuelle Umgebung...
    python -m venv venv
)
call venv\Scripts\activate.bat
echo Installiere Abhängigkeiten...
pip install --quiet --upgrade pip
pip install --quiet PySide6 numpy sounddevice pyserial

REM Desktop-Verknüpfung
set SHORTCUT=%USERPROFILE%\Desktop\TRX Cat Control V2.lnk
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%~dp0start.bat'; $s.WorkingDirectory = '%~dp0'; $s.Description = 'TRX Cat Control V2'; $s.Save()" 2>nul
echo Desktop-Verknuepfung erstellt.

echo.
echo ==================================
echo   Setup fertig!
echo ==================================
echo.
echo   Starten: start.bat oder Desktop-Verknuepfung
echo.
pause
