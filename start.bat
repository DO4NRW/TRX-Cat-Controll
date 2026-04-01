@echo off
REM RigLink — Start (Windows)
cd /d "%~dp0"
if not exist "venv" (
    echo Erst setup.bat ausführen!
    pause
    exit /b 1
)
call venv\Scripts\activate.bat
python main.py
