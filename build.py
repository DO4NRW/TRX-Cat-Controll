"""
TRX Cat Control V2 — Build Script
Erstellt Binaries für Linux, Windows und macOS.

Verwendung:
    python build.py

Voraussetzungen:
    pip install pyinstaller PySide6 numpy sounddevice pyserial
"""

import os
import sys
import platform
import subprocess
import shutil
import zipfile

APP_NAME = "TRX_Cat_Control_V2"
SCRIPT = "main.py"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Trennzeichen für --add-data: Windows = ";", Linux/Mac = ":"
SEP = ";" if platform.system() == "Windows" else ":"


def get_platform_name():
    s = platform.system()
    if s == "Linux":
        return "Linux"
    elif s == "Darwin":
        return "macOS"
    elif s == "Windows":
        return "Windows"
    return s


REQUIREMENTS = [
    "PySide6",
    "numpy",
    "sounddevice",
    "pyserial",
    "pyinstaller",
]


def install_deps():
    """Alle Abhängigkeiten installieren."""
    print("  Installiere Abhängigkeiten...\n")
    for pkg in REQUIREMENTS:
        print(f"    → {pkg}")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
            check=False
        )
    print()


def build():
    plat = get_platform_name()
    print(f"\n{'='*60}")
    print(f"  TRX Cat Control V2 — Build für {plat}")
    print(f"{'='*60}\n")

    # Abhängigkeiten installieren
    install_deps()

    # PyInstaller prüfen
    try:
        import PyInstaller
        print(f"  PyInstaller {PyInstaller.__version__} gefunden")
    except ImportError:
        print("  FEHLER: PyInstaller konnte nicht installiert werden!")
        sys.exit(1)

    # Alte Builds aufräumen
    dist_dir = os.path.join(BASE_DIR, "dist")
    build_dir = os.path.join(BASE_DIR, "build")
    spec_file = os.path.join(BASE_DIR, f"{APP_NAME}.spec")

    for d in [os.path.join(dist_dir, APP_NAME), build_dir]:
        if os.path.exists(d):
            print(f"  Räume auf: {d}")
            shutil.rmtree(d)

    # PyInstaller ausführen
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onedir",
        "--windowed",
        "--add-data", f"assets{SEP}assets",
        "--add-data", f"configs{SEP}configs",
        "--add-data", f"rig{SEP}rig",
        "--add-data", f"core{SEP}core",
        "--hidden-import", "PySide6.QtSvg",
        "--hidden-import", "numpy",
        "--hidden-import", "sounddevice",
        "--hidden-import", "serial",
        "--hidden-import", "serial.tools.list_ports",
        "--noconfirm",
        SCRIPT,
    ]

    # macOS: Icon hinzufügen wenn vorhanden
    icon_icns = os.path.join(BASE_DIR, "assets", "icons", "app.icns")
    icon_ico = os.path.join(BASE_DIR, "assets", "icons", "app.ico")
    if platform.system() == "Darwin" and os.path.exists(icon_icns):
        cmd.extend(["--icon", icon_icns])
    elif platform.system() == "Windows" and os.path.exists(icon_ico):
        cmd.extend(["--icon", icon_ico])

    print(f"\n  Starte Build...\n")
    result = subprocess.run(cmd, cwd=BASE_DIR)

    if result.returncode != 0:
        print(f"\n  BUILD FEHLGESCHLAGEN (Exit Code {result.returncode})")
        sys.exit(1)

    # ZIP erstellen
    app_dir = os.path.join(dist_dir, APP_NAME)
    if not os.path.exists(app_dir):
        print(f"\n  FEHLER: Build-Ordner nicht gefunden: {app_dir}")
        sys.exit(1)

    zip_name = f"{APP_NAME}_{plat}.zip"
    zip_path = os.path.join(dist_dir, zip_name)

    print(f"\n  Erstelle {zip_name}...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(app_dir):
            for f in files:
                file_path = os.path.join(root, f)
                arc_name = os.path.relpath(file_path, dist_dir)
                zf.write(file_path, arc_name)

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)

    print(f"\n{'='*60}")
    print(f"  BUILD ERFOLGREICH!")
    print(f"  Plattform: {plat}")
    print(f"  Output:    dist/{zip_name} ({size_mb:.1f} MB)")
    print(f"{'='*60}\n")
    print(f"  Upload zum Release:")
    print(f"  gh release upload v2.0-pyside6 dist/{zip_name}")
    print()


if __name__ == "__main__":
    build()
