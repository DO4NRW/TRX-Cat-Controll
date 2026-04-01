#!/bin/bash
# TRX Cat Control V2 — Start (Linux/macOS)
# Baut automatisch die App wenn nötig, dann starten.

cd "$(dirname "$0")"
APP_NAME="TRX_Cat_Control_V2"

# 1. Python prüfen
if ! command -v python3 &>/dev/null; then
    echo ""
    echo "Python3 nicht gefunden!"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    echo "  macOS:         brew install python3"
    echo ""
    read -p "Drücke Enter zum Beenden..."
    exit 1
fi

# 2. venv erstellen wenn nötig
if [ ! -d "venv" ]; then
    echo "Erstelle Python-Umgebung (einmalig)..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --quiet --upgrade pip
    pip install --quiet PySide6 numpy sounddevice pyserial pyinstaller
else
    source venv/bin/activate
fi

# 3. Binary bauen wenn nötig oder Source neuer als Binary
BINARY="dist/$APP_NAME/$APP_NAME"
NEEDS_BUILD=0

if [ ! -f "$BINARY" ]; then
    NEEDS_BUILD=1
elif [ "main.py" -nt "$BINARY" ] || [ "main_ui.py" -nt "$BINARY" ] || [ "core/theme.py" -nt "$BINARY" ]; then
    NEEDS_BUILD=1
fi

if [ $NEEDS_BUILD -eq 1 ]; then
    echo "Baue App (kann beim ersten Mal etwas dauern)..."
    python build.py
    if [ $? -ne 0 ]; then
        echo "Build fehlgeschlagen! Starte aus Source..."
        python main.py
        exit $?
    fi
fi

# 4. App starten
echo "Starte TRX Cat Control V2..."
"./dist/$APP_NAME/$APP_NAME" &
disown
