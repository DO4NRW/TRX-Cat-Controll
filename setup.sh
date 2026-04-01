#!/bin/bash
# RigLink — Setup (Linux/macOS)
# Einmal ausführen: chmod +x setup.sh && ./setup.sh

cd "$(dirname "$0")"
APP_DIR="$(pwd)"

echo ""
echo "=================================="
echo "  RigLink — Setup"
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

# venv erstellen + Dependencies
if [ ! -d "venv" ]; then
    echo "Erstelle virtuelle Umgebung..."
    python3 -m venv venv
fi
source venv/bin/activate
echo "Installiere Abhängigkeiten..."
pip install --quiet --upgrade pip
pip install --quiet PySide6 numpy sounddevice pyserial

# Desktop-Eintrag
if [ "$(uname)" = "Darwin" ]; then
    # macOS: .command Datei auf Desktop
    cat > "$HOME/Desktop/RigLink.command" << EOF
#!/bin/bash
cd "$APP_DIR"
source venv/bin/activate
python main.py
EOF
    chmod +x "$HOME/Desktop/RigLink.command"
    echo "Desktop-Starter erstellt (macOS)"
else
    # Linux: .desktop Eintrag im App-Menü
    mkdir -p "$HOME/.local/share/applications"
    cat > "$HOME/.local/share/applications/RigLink.desktop" << EOF
[Desktop Entry]
Name=RigLink
Comment=Amateurfunk TRX-Steuerung
Exec=bash -c 'cd "$APP_DIR" && source venv/bin/activate && python main.py'
Icon=$APP_DIR/Logo.png
Terminal=false
Type=Application
Categories=HamRadio;Audio;
EOF
    chmod +x "$HOME/.local/share/applications/RigLink.desktop"
    echo "App-Menü Eintrag erstellt (Linux)"
fi

echo ""
echo "=================================="
echo "  Setup fertig!"
echo "=================================="
echo ""
echo "  Starten: ./start.sh oder über das App-Menü"
echo ""
