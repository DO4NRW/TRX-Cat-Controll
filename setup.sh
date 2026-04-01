#!/bin/bash
# TRX Cat Control V2 — Einmal-Setup (Linux/macOS)
# Installiert alles, baut die App, kopiert an festen Ort.

cd "$(dirname "$0")"
SOURCE_DIR="$(pwd)"
APP_NAME="TRX_Cat_Control_V2"

# Install-Verzeichnis
if [ "$(uname)" = "Darwin" ]; then
    INSTALL_DIR="$HOME/Applications/$APP_NAME"
else
    INSTALL_DIR="$HOME/.local/share/$APP_NAME"
fi

echo ""
echo "=================================="
echo "  TRX Cat Control V2 — Setup"
echo "=================================="
echo ""
echo "  Installiert nach: $INSTALL_DIR"
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

if [ $? -ne 0 ]; then
    echo "Build fehlgeschlagen!"
    exit 1
fi

# An festen Ort kopieren
echo "Installiere nach $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
rm -rf "$INSTALL_DIR"/*
cp -r "dist/$APP_NAME/"* "$INSTALL_DIR/"

# Source-Pfad merken (für Auto-Updater)
echo "$SOURCE_DIR" > "$INSTALL_DIR/_internal/source_path.txt"

# Desktop Shortcut erstellen (Linux)
if [ "$(uname)" != "Darwin" ]; then
    DESKTOP_FILE="$HOME/.local/share/applications/$APP_NAME.desktop"
    mkdir -p "$HOME/.local/share/applications"
    cat > "$DESKTOP_FILE" << DESKTOP
[Desktop Entry]
Name=TRX Cat Control V2
Comment=Amateurfunk TRX-Steuerung
Exec=$INSTALL_DIR/$APP_NAME
Icon=$SOURCE_DIR/Logo.png
Terminal=false
Type=Application
Categories=HamRadio;Audio;
DESKTOP
    chmod +x "$DESKTOP_FILE"
    echo "Desktop-Eintrag erstellt: $DESKTOP_FILE"
fi

# macOS: Alias auf Desktop
if [ "$(uname)" = "Darwin" ]; then
    ln -sf "$INSTALL_DIR/$APP_NAME" "$HOME/Desktop/$APP_NAME"
    echo "Desktop-Link erstellt"
fi

echo ""
echo "=================================="
echo "  Setup fertig!"
echo "=================================="
echo ""
echo "  App installiert: $INSTALL_DIR"
echo "  Starten: $APP_NAME (im App-Menü oder Desktop)"
echo ""
echo "  Diesen Ordner kannst du jetzt löschen."
echo "  (Für Updates behalten oder die App updated sich selbst)"
echo ""
