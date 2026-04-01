@echo off
REM TRX Cat Control V2 — Einmal-Setup (Windows)
REM Installiert alles, baut die App, kopiert an festen Ort.

cd /d "%~dp0"
set APP_NAME=TRX_Cat_Control_V2
set INSTALL_DIR=%LOCALAPPDATA%\%APP_NAME%

echo.
echo ==================================
echo   TRX Cat Control V2 — Setup
echo ==================================
echo.
echo   Installiert nach: %INSTALL_DIR%
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

if errorlevel 1 (
    echo Build fehlgeschlagen!
    pause
    exit /b 1
)

REM An festen Ort kopieren
echo Installiere nach %INSTALL_DIR%...
if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"
mkdir "%INSTALL_DIR%"
xcopy /s /e /q "dist\%APP_NAME%\*" "%INSTALL_DIR%\" >nul

REM Source-Pfad merken (für Auto-Updater)
echo %~dp0> "%INSTALL_DIR%\_internal\source_path.txt"

REM Desktop Shortcut erstellen
set SHORTCUT=%USERPROFILE%\Desktop\TRX Cat Control V2.lnk
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%INSTALL_DIR%\%APP_NAME%.exe'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.Description = 'TRX Cat Control V2'; $s.Save()"
echo Desktop-Verknüpfung erstellt.

echo.
echo ==================================
echo   Setup fertig!
echo ==================================
echo.
echo   App installiert: %INSTALL_DIR%
echo   Desktop-Verknüpfung: TRX Cat Control V2
echo.
echo   Diesen Ordner kannst du jetzt loeschen.
echo   (Fuer Updates behalten oder die App updated sich selbst)
echo.
pause
