@echo off
REM TRX Cat Control V2 — Starten (Windows)
cd /d "%~dp0"
if not exist "venv" (
    echo Erst setup.bat ausführen!
    pause
    exit /b 1
)
call venv\Scripts\activate.bat
python main.py
