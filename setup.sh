#!/bin/bash
# RigLink — Setup (Linux/macOS)
# Einmal ausführen: chmod +x setup.sh && ./setup.sh

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

# Installationsordner (getrennt vom Git-Repo)
if [ "$(uname)" = "Darwin" ]; then
    INSTALL_DIR="$HOME/Library/Application Support/RigLink"
else
    INSTALL_DIR="$HOME/.local/share/RigLink"
fi

echo ""
echo "=================================="
echo "  RigLink — Setup"
echo "=================================="
echo ""
echo "  Source:  $SRC_DIR"
echo "  Install: $INSTALL_DIR"
echo ""

# Python prüfen
if ! command -v python3 &>/dev/null; then
    echo "Python3 nicht gefunden!"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    echo "  macOS:         brew install python3"
    exit 1
fi
echo "Python: $(python3 --version)"

# Installationsordner erstellen
mkdir -p "$INSTALL_DIR"

# Dateien kopieren (configs nur wenn neu)
echo "Kopiere Dateien..."
for item in "$SRC_DIR"/*; do
    name="$(basename "$item")"
    # Git/Dev-Dateien überspringen
    case "$name" in
        .git|venv|__pycache__|dist|build|*.pyc|test_*.py|CLAUDE.md) continue ;;
    esac
    # configs: nur kopieren wenn Ziel nicht existiert (User-Daten behalten)
    if [ "$name" = "configs" ] && [ -d "$INSTALL_DIR/configs" ]; then
        for cfg in "$item"/*; do
            cfg_name="$(basename "$cfg")"
            case "$cfg_name" in
                status_conf.json|user_themes.json) continue ;;  # User-Daten
            esac
            cp -f "$cfg" "$INSTALL_DIR/configs/$cfg_name"
        done
        continue
    fi
    if [ -d "$item" ]; then
        cp -rf "$item" "$INSTALL_DIR/"
    else
        cp -f "$item" "$INSTALL_DIR/"
    fi
done

# venv im Installationsordner
cd "$INSTALL_DIR"
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
    cat > "$HOME/Desktop/RigLink.command" << EOF
#!/bin/bash
cd "$INSTALL_DIR"
source venv/bin/activate
python main.py
EOF
    chmod +x "$HOME/Desktop/RigLink.command"
    echo "Desktop-Starter erstellt (macOS)"
else
    mkdir -p "$HOME/.local/share/applications"
    cat > "$HOME/.local/share/applications/RigLink.desktop" << EOF
[Desktop Entry]
Name=RigLink
Comment=Amateurfunk TRX-Steuerung
Exec=bash -c 'cd "$INSTALL_DIR" && source venv/bin/activate && python main.py'
Icon=$INSTALL_DIR/Logo.png
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
echo "  Installiert in: $INSTALL_DIR"
echo "  Starten: über das App-Menü oder:"
echo "    cd $INSTALL_DIR && ./start.sh"
echo ""
