#!/bin/bash
# TRX Cat Control V2 — Einmal-Setup (Linux/macOS)
# Installiert alles und baut die App.

cd "$(dirname "$0")"

echo ""
echo "=================================="
echo "  TRX Cat Control V2 — Setup"
echo "=================================="
echo ""

# Python prüfen
if ! command -v python3 &>/dev/null; then
    echo "Python3 nicht gefunden!"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    echo "  macOS:         brew install python3"
    exit 1
fi

echo "Python: $(python3 --version)"

# venv erstellen
if [ ! -d "venv" ]; then
    echo "Erstelle virtuelle Umgebung..."
    python3 -m venv venv
fi

source venv/bin/activate

# Dependencies installieren
echo "Installiere Abhängigkeiten..."
pip install --quiet --upgrade pip
pip install --quiet PySide6 numpy sounddevice pyserial pyinstaller

# App bauen
echo ""
echo "Baue App (kann etwas dauern)..."
python build.py

echo ""
echo "=================================="
echo "  Setup fertig!"
echo "=================================="
echo ""
echo "  Starte die App mit:"
echo "  ./dist/TRX_Cat_Control_V2/TRX_Cat_Control_V2"
echo ""
