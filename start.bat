@echo off
REM TRX Cat Control V2 — Start (Windows)
REM Baut automatisch die App wenn nötig, dann starten.

cd /d "%~dp0"
set APP_NAME=TRX_Cat_Control_V2

REM 1. Python prüfen
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo Python nicht gefunden!
    echo Download: https://www.python.org/downloads/
    echo WICHTIG: Bei der Installation "Add to PATH" ankreuzen!
    echo.
    pause
    exit /b 1
)

REM 2. venv erstellen wenn nötig
if not exist "venv" (
    echo Erstelle Python-Umgebung (einmalig, bitte warten^)...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install --quiet --upgrade pip
    pip install --quiet PySide6 numpy sounddevice pyserial pyinstaller
) else (
    call venv\Scripts\activate.bat
)

REM 3. Binary bauen wenn nötig
set BINARY=dist\%APP_NAME%\%APP_NAME%.exe
set NEEDS_BUILD=0

if not exist "%BINARY%" set NEEDS_BUILD=1

REM Prüfe ob Source neuer als Binary
if exist "%BINARY%" (
    for %%F in (main.py main_ui.py core\theme.py) do (
        for %%A in ("%%F") do for %%B in ("%BINARY%") do (
            if "%%~tA" GTR "%%~tB" set NEEDS_BUILD=1
        )
    )
)

if %NEEDS_BUILD%==1 (
    echo Baue App (kann beim ersten Mal etwas dauern^)...
    python build.py
    if errorlevel 1 (
        echo Build fehlgeschlagen! Starte aus Source...
        python main.py
        exit /b
    )
)

REM 4. App starten
echo Starte TRX Cat Control V2...
start "" "dist\%APP_NAME%\%APP_NAME%.exe"
