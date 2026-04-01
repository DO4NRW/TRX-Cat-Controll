"""
Auto-Updater — prüft GitHub Releases auf neue Versionen.
Lädt Source-Code, ersetzt .py Dateien, startet App neu.
Kein PyInstaller nötig — App läuft direkt aus Source.
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

CURRENT_VERSION = "2.0.3"

REPO_OWNER = "DO4NRW"
REPO_NAME = "RigLink"
RELEASES_API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Dateien/Ordner die NICHT überschrieben werden
_KEEP = {"venv", "__pycache__", ".git", "dist", "build", "Screenshot.png",
         "configs/user_themes.json", "configs/status_conf.json"}


def _version_tuple(v):
    try:
        return tuple(int(x) for x in v.strip().lstrip("v").split("."))
    except Exception:
        return (0, 0, 0)


class UpdateChecker(QObject):
    update_available = Signal(str, str, str, str)  # local_ver, remote_ver, changelog, zip_url
    no_update = Signal()
    check_failed = Signal(str)

    def check(self):
        threading.Thread(target=self._check_remote, daemon=True).start()

    def _check_remote(self):
        try:
            import urllib.request
            req = urllib.request.Request(RELEASES_API)
            req.add_header("Accept", "application/vnd.github.v3+json")
            req.add_header("User-Agent", "RigLink-Updater")

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            remote_tag = data.get("tag_name", "")
            remote_ver = remote_tag.lstrip("v")
            changelog = data.get("body", "").strip()[:300]
            zip_url = data.get("zipball_url", "")

            if _version_tuple(remote_ver) > _version_tuple(CURRENT_VERSION):
                self.update_available.emit(CURRENT_VERSION, remote_ver, changelog, zip_url)
            else:
                self.no_update.emit()

        except Exception as e:
            self.check_failed.emit(str(e))


def _download_and_install(parent, zip_url):
    """ZIP von GitHub laden, entpacken, Dateien im Projektordner ersetzen."""
    import urllib.request

    tmp_dir = tempfile.mkdtemp(prefix="trx_update_")
    zip_path = os.path.join(tmp_dir, "update.zip")

    try:
        progress = QProgressDialog("Update wird heruntergeladen...", "Abbrechen", 0, 0, parent)
        progress.setWindowTitle("TRX Update")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        urllib.request.urlretrieve(zip_url, zip_path)

        if progress.wasCanceled():
            return False, "Abgebrochen"

        progress.setLabelText("Update wird installiert...")
        QApplication.processEvents()

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)

        # GitHub ZIP enthält Ordner "REPO-main/"
        extracted = None
        for name in os.listdir(tmp_dir):
            full = os.path.join(tmp_dir, name)
            if os.path.isdir(full) and name != "__MACOSX":
                extracted = full
                break

        if not extracted:
            return False, "ZIP-Inhalt nicht gefunden"

        # Dateien im Projektordner ersetzen (User-Daten behalten)
        for item in os.listdir(extracted):
            if item in _KEEP or item.startswith("."):
                continue

            src = os.path.join(extracted, item)
            dst = os.path.join(_PROJECT_DIR, item)

            # configs/ Ordner: nur neue Dateien, bestehende nicht überschreiben
            if item == "configs" and os.path.isdir(src):
                for cfg_file in os.listdir(src):
                    cfg_src = os.path.join(src, cfg_file)
                    cfg_dst = os.path.join(dst, cfg_file)
                    # User-Daten nicht überschreiben
                    if cfg_file in ("user_themes.json", "status_conf.json"):
                        continue
                    shutil.copy2(cfg_src, cfg_dst)
                continue

            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

        progress.close()

        # Dependencies updaten (falls neue dazu kamen)
        progress = QProgressDialog("Dependencies werden aktualisiert...", None, 0, 0, parent)
        progress.setWindowTitle("TRX Update")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        QApplication.processEvents()

        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "PySide6", "numpy", "sounddevice", "pyserial"],
            capture_output=True, timeout=120
        )
        progress.close()

        return True, "OK"

    except Exception as e:
        return False, str(e)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def restart_app():
    """App neu starten aus Source."""
    script = os.path.join(_PROJECT_DIR, "main.py")
    subprocess.Popen([sys.executable, script], cwd=_PROJECT_DIR)
    QApplication.instance().quit()
    sys.exit(0)


def show_update_dialog(parent, local_ver, remote_ver, changelog, zip_url):
    msg = QMessageBox(parent)
    msg.setWindowTitle("Update verfügbar")
    text = (f"Neue Version verfügbar!\n\n"
            f"Aktuell: v{local_ver}\n"
            f"Neu:     v{remote_ver}\n")
    if changelog:
        text += f"\n{changelog[:200]}\n"
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
