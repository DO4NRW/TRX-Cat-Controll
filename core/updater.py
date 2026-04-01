"""
Auto-Updater — prüft GitHub Releases auf neue Versionen.
Vergleicht Versionsnummern (z.B. 2.0.0 vs 2.1.0).
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

# Aktuelle Version der App
CURRENT_VERSION = "2.0.1"

# GitHub Repo
REPO_OWNER = "DO4NRW"
REPO_NAME = "TRX-Cat-Controll"
RELEASES_API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Dateien die NICHT überschrieben werden (User-Daten)
_KEEP = {"configs/user_themes.json", "configs/status_conf.json", "venv", "__pycache__",
         ".git", "dist", "build", "Screenshot.png", "source_path.txt"}


def _get_install_dir():
    """Wo die App installiert ist."""
    marker = os.path.join(_PROJECT_DIR, "source_path.txt")
    if os.path.exists(marker):
        return _PROJECT_DIR
    if platform.system() == "Windows":
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "TRX_Cat_Control_V2")
    elif platform.system() == "Darwin":
        return os.path.join(os.path.expanduser("~"), "Applications", "TRX_Cat_Control_V2")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "TRX_Cat_Control_V2")


def _version_tuple(v):
    """'2.1.0' → (2, 1, 0) für Vergleich."""
    try:
        return tuple(int(x) for x in v.strip().lstrip("v").split("."))
    except Exception:
        return (0, 0, 0)


class UpdateChecker(QObject):
    """Prüft im Hintergrund ob ein neues Release auf GitHub verfügbar ist."""

    update_available = Signal(str, str, str, str)  # (local_ver, remote_ver, changelog, zip_url)
    no_update = Signal()
    check_failed = Signal(str)

    def check(self):
        threading.Thread(target=self._check_remote, daemon=True).start()

    def _check_remote(self):
        try:
            import urllib.request
            req = urllib.request.Request(RELEASES_API)
            req.add_header("Accept", "application/vnd.github.v3+json")
            req.add_header("User-Agent", "TRX-Cat-Control-Updater")

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            remote_tag = data.get("tag_name", "")
            remote_ver = remote_tag.lstrip("v")
            changelog = data.get("body", "").strip()[:200]

            # ZIP URL aus dem Release (Source code)
            zip_url = data.get("zipball_url", "")

            if _version_tuple(remote_ver) > _version_tuple(CURRENT_VERSION):
                self.update_available.emit(CURRENT_VERSION, remote_ver, changelog, zip_url)
            else:
                self.no_update.emit()

        except Exception as e:
            self.check_failed.emit(str(e))


def _download_and_install(parent, zip_url):
    """ZIP von GitHub Release laden, entpacken, Dateien ersetzen."""
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

        urllib.request.urlretrieve(zip_url, zip_path)

        if progress.wasCanceled():
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return False, "Abgebrochen"

        # 2. Entpacken
        progress.setLabelText("Update wird installiert...")
        QApplication.processEvents()

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)

        # GitHub ZIP enthält Ordner "REPO-main/" o.ä.
        extracted = None
        for name in os.listdir(tmp_dir):
            full = os.path.join(tmp_dir, name)
            if os.path.isdir(full) and name != "__MACOSX":
                extracted = full
                break

        if not extracted:
            return False, "ZIP-Inhalt nicht gefunden"

        # 3. Dateien ins Install-Verzeichnis kopieren
        install_dir = _get_install_dir()
        internal_dir = os.path.join(install_dir, "_internal")

        for item in os.listdir(extracted):
            if item in _KEEP:
                continue

            src = os.path.join(extracted, item)
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
        return True, "OK"

    except Exception as e:
        return False, str(e)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def restart_app():
    """App neu starten."""
    install_dir = _get_install_dir()
    app_name = "TRX_Cat_Control_V2"

    if platform.system() == "Windows":
        exe = os.path.join(install_dir, f"{app_name}.exe")
    else:
        exe = os.path.join(install_dir, app_name)

    if os.path.exists(exe):
        subprocess.Popen([exe])
    else:
        script = os.path.join(_PROJECT_DIR, "main.py")
        subprocess.Popen([sys.executable, script])

    QApplication.instance().quit()
    sys.exit(0)


def show_update_dialog(parent, local_ver, remote_ver, changelog, zip_url):
    """Zeigt Update-Dialog."""
    msg = QMessageBox(parent)
    msg.setWindowTitle("Update verfügbar")
    text = (f"Neue Version verfügbar!\n\n"
            f"Aktuell: v{local_ver}\n"
            f"Neu:     v{remote_ver}\n")
    if changelog:
        text += f"\nÄnderungen:\n{changelog}\n"
    text += "\nJetzt herunterladen und installieren?"
    msg.setText(text)
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    msg.setDefaultButton(QMessageBox.No)
    msg.button(QMessageBox.Yes).setText("Ja, updaten")
    msg.button(QMessageBox.No).setText("Nein, später")

    if msg.exec() == QMessageBox.Yes:
        ok, output = _download_and_install(parent, zip_url)
        if ok:
            restart_msg = QMessageBox(parent)
            restart_msg.setWindowTitle("Update erfolgreich")
            restart_msg.setText(f"Update auf v{remote_ver} installiert!\n\n"
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
