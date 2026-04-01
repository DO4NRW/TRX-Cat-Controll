"""
Auto-Updater — prüft GitHub auf neue Versionen.
Kein Git nötig! Lädt ZIP von GitHub, ersetzt Dateien, startet neu.
"""

import os
import sys
import json
import shutil
import tempfile
import platform
import subprocess
import threading
import zipfile
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QApplication
from PySide6.QtCore import Signal, QObject, Qt

# Aktuelle Version (wird bei jedem Update überschrieben)
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(_BASE_DIR, "configs", "version.json")

# GitHub Repo
REPO_OWNER = "DO4NRW"
REPO_NAME = "TRX-Cat-Controll"
API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/commits/main"
ZIP_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/archive/refs/heads/main.zip"

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Install-Verzeichnis ermitteln
def _get_install_dir():
    """Wo die App installiert ist (aus source_path.txt oder Fallback)."""
    marker = os.path.join(_PROJECT_DIR, "source_path.txt")
    if os.path.exists(marker):
        # Wir laufen aus dem Install-Ordner
        return _PROJECT_DIR
    # Wir laufen aus dem Source-Ordner
    if platform.system() == "Windows":
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "TRX_Cat_Control_V2")
    elif platform.system() == "Darwin":
        return os.path.join(os.path.expanduser("~"), "Applications", "TRX_Cat_Control_V2")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "TRX_Cat_Control_V2")

# Dateien/Ordner die NICHT überschrieben werden (User-Daten)
_KEEP = {"configs/user_themes.json", "configs/status_conf.json", "venv", "__pycache__",
         ".git", "dist", "build", "Screenshot.png", "source_path.txt"}


def get_local_version():
    """Lokale Version (commit hash) aus version.json lesen.
    Sucht im aktuellen Verzeichnis (wo die App läuft)."""
    try:
        with open(VERSION_FILE) as f:
            return json.load(f).get("commit", "unknown")
    except Exception:
        return "unknown"


def save_local_version(commit_hash):
    """Lokale Version in version.json speichern — überall wo nötig."""
    data = {"commit": commit_hash}
    # Im Source-Ordner
    try:
        with open(VERSION_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass
    # Im Install-Ordner (_internal/configs/)
    try:
        install_dir = _get_install_dir()
        install_vf = os.path.join(install_dir, "_internal", "configs", "version.json")
        if os.path.exists(os.path.dirname(install_vf)):
            with open(install_vf, "w") as f:
                json.dump(data, f, indent=4)
    except Exception:
        pass


class UpdateChecker(QObject):
    """Prüft im Hintergrund ob ein Update auf GitHub verfügbar ist."""

    update_available = Signal(str, str, str)  # (local_hash, remote_hash, commit_msg)
    no_update = Signal()
    check_failed = Signal(str)

    def check(self):
        """Starte Check im Hintergrund."""
        threading.Thread(target=self._check_remote, daemon=True).start()

    def _check_remote(self):
        try:
            local_hash = get_local_version()

            import urllib.request
            req = urllib.request.Request(API_URL)
            req.add_header("Accept", "application/vnd.github.v3+json")
            req.add_header("User-Agent", "TRX-Cat-Control-Updater")

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            remote_hash = data.get("sha", "")[:7]
            commit_msg = data.get("commit", {}).get("message", "").split("\n")[0]

            if local_hash != remote_hash:
                self.update_available.emit(local_hash, remote_hash, commit_msg)
            else:
                self.no_update.emit()

        except Exception as e:
            self.check_failed.emit(str(e))


def _download_and_install(parent):
    """ZIP von GitHub laden, entpacken, Dateien ersetzen."""
    import urllib.request

    tmp_dir = tempfile.mkdtemp(prefix="trx_update_")
    zip_path = os.path.join(tmp_dir, "update.zip")

    try:
        # 1. Download
        progress = QProgressDialog("Update wird heruntergeladen...", "Abbrechen", 0, 0, parent)
        progress.setWindowTitle("TRX Update")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        urllib.request.urlretrieve(ZIP_URL, zip_path)

        if progress.wasCanceled():
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return False, "Abgebrochen"

        # 2. Entpacken
        progress.setLabelText("Update wird installiert...")
        QApplication.processEvents()

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)

        # GitHub ZIP enthält Ordner "REPO-NAME-main/"
        extracted = None
        for name in os.listdir(tmp_dir):
            full = os.path.join(tmp_dir, name)
            if os.path.isdir(full) and name != "__MACOSX":
                extracted = full
                break

        if not extracted:
            return False, "ZIP-Inhalt nicht gefunden"

        # 3. Dateien ins Install-Verzeichnis kopieren (User-Daten behalten)
        install_dir = _get_install_dir()
        internal_dir = os.path.join(install_dir, "_internal")

        for item in os.listdir(extracted):
            if item in _KEEP:
                continue

            src = os.path.join(extracted, item)

            # In _internal des Install-Ordners kopieren (da liegen die App-Dateien)
            if os.path.exists(internal_dir):
                dst = os.path.join(internal_dir, item)
            else:
                dst = os.path.join(install_dir, item)

            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

        progress.close()

        # 4. Dependencies updaten
        progress.setLabelText("Dependencies werden aktualisiert...")
        QApplication.processEvents()
        pip_cmd = [sys.executable, "-m", "pip", "install", "--quiet",
                   "PySide6", "numpy", "sounddevice", "pyserial", "pyinstaller"]
        subprocess.run(pip_cmd, capture_output=True, timeout=120)

        # 5. Binary neu bauen
        build_script = os.path.join(_PROJECT_DIR, "build.py")
        if os.path.exists(build_script):
            progress.setLabelText("App wird neu gebaut...")
            QApplication.processEvents()
            subprocess.run(
                [sys.executable, build_script],
                capture_output=True, timeout=300,
                cwd=_PROJECT_DIR
            )

        return True, "OK"

    except Exception as e:
        return False, str(e)
    finally:
        # Temp aufräumen
        shutil.rmtree(tmp_dir, ignore_errors=True)


def restart_app():
    """App komplett neu starten — exe oder Source."""
    install_dir = _get_install_dir()
    app_name = "TRX_Cat_Control_V2"

    if platform.system() == "Windows":
        exe = os.path.join(install_dir, f"{app_name}.exe")
    else:
        exe = os.path.join(install_dir, app_name)

    if os.path.exists(exe):
        subprocess.Popen([exe])
    else:
        # Fallback: aus Source starten
        script = os.path.join(_PROJECT_DIR, "main.py")
        subprocess.Popen([sys.executable, script])

    # Aktuelle App beenden
    QApplication.instance().quit()
    sys.exit(0)


def show_update_dialog(parent, local_hash, remote_hash, commit_msg):
    """Zeigt Update-Dialog mit Ja/Nein."""
    msg = QMessageBox(parent)
    msg.setWindowTitle("Update verfügbar")
    msg.setText(f"Eine neue Version ist verfügbar!\n\n"
                f"Aktuell:  {local_hash}\n"
                f"Neu:      {remote_hash}\n"
                f"Änderung: {commit_msg}\n\n"
                f"Jetzt herunterladen und installieren?")
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    msg.setDefaultButton(QMessageBox.No)
    msg.button(QMessageBox.Yes).setText("Ja, updaten")
    msg.button(QMessageBox.No).setText("Nein, später")

    if msg.exec() == QMessageBox.Yes:
        ok, output = _download_and_install(parent)
        if ok:
            # Version speichern
            save_local_version(remote_hash)

            restart_msg = QMessageBox(parent)
            restart_msg.setWindowTitle("Update erfolgreich")
            restart_msg.setText("Update installiert!\n\n"
                               "App wird jetzt neu gestartet...")
            restart_msg.setStandardButtons(QMessageBox.Ok)
            restart_msg.exec()
            restart_app()
        else:
            err_msg = QMessageBox(parent)
            err_msg.setWindowTitle("Update fehlgeschlagen")
            err_msg.setText(f"Fehler beim Update:\n\n{output}")
            err_msg.setStandardButtons(QMessageBox.Ok)
            err_msg.exec()
