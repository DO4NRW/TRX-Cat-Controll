#!/bin/bash
# TRX Cat Control V2 — Linux/macOS Setup
# Verwendung: chmod +x setup.sh && ./setup.sh

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

# Aktivieren
source venv/bin/activate

# Dependencies installieren
echo "Installiere Abhängigkeiten..."
pip install --quiet --upgrade pip
pip install --quiet PySide6 numpy sounddevice pyserial

echo ""
echo "Setup fertig!"
echo ""
echo "Starten mit:"
echo "  source venv/bin/activate"
echo "  python main.py"
echo ""
echo "Oder direkt:"
echo "  ./start.sh"
echo ""
