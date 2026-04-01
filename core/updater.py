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
from PySide6.QtWidgets import (QMessageBox, QProgressDialog, QApplication,
                               QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QTextEdit)
from PySide6.QtCore import Signal, QObject, Qt

CURRENT_VERSION = "2.0.4"

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


def _themed_dialog_style():
    """Stylesheet für Update-Dialog im App-Theme."""
    from core.theme import T
    return f"""
        QDialog {{
            background-color: {T['bg_dark']};
            border: 1px solid {T['border']};
        }}
        QLabel {{
            color: {T['text']};
        }}
        QLabel#title {{
            font-size: 18px;
            font-weight: bold;
            color: {T['accent']};
        }}
        QLabel#versions {{
            font-size: 13px;
            color: {T['text_secondary']};
        }}
        QTextEdit {{
            background-color: {T['bg_mid']};
            color: {T['text_secondary']};
            border: 1px solid {T['border']};
            border-radius: 4px;
            font-size: 12px;
            padding: 6px;
        }}
        QPushButton {{
            background-color: {T['bg_button']};
            color: {T['text']};
            border: 1px solid {T['border']};
            border-radius: 5px;
            padding: 8px 20px;
            font-size: 13px;
        }}
        QPushButton:hover {{
            background-color: {T['bg_button_hover']};
            border: 1px solid {T['border_hover']};
        }}
        QPushButton#primary {{
            border: 2px solid {T['accent']};
        }}
        QPushButton#primary:hover {{
            border: 2px solid {T['accent']};
            background-color: {T['bg_light']};
        }}
    """


def show_update_dialog(parent, local_ver, remote_ver, changelog, zip_url):
    dlg = QDialog(parent)
    dlg.setWindowTitle("Update verfügbar")
    dlg.setFixedSize(420, 320)
    dlg.setStyleSheet(_themed_dialog_style())

    layout = QVBoxLayout(dlg)
    layout.setSpacing(12)
    layout.setContentsMargins(20, 20, 20, 20)

    # Titel
    lbl_title = QLabel("Update verfügbar")
    lbl_title.setObjectName("title")
    layout.addWidget(lbl_title)

    # Versionen
    lbl_ver = QLabel(f"Installiert: v{local_ver}  →  Neu: v{remote_ver}")
    lbl_ver.setObjectName("versions")
    layout.addWidget(lbl_ver)

    # Changelog
    if changelog:
        txt_log = QTextEdit()
        txt_log.setReadOnly(True)
        txt_log.setPlainText(changelog[:500])
        txt_log.setMaximumHeight(120)
        layout.addWidget(txt_log)

    layout.addStretch()

    # Buttons
    btn_row = QHBoxLayout()
    btn_row.addStretch()

    btn_skip = QPushButton("Später")
    btn_skip.clicked.connect(dlg.reject)
    btn_row.addWidget(btn_skip)

    btn_update = QPushButton("Jetzt updaten")
    btn_update.setObjectName("primary")
    btn_row.addWidget(btn_update)

    layout.addLayout(btn_row)

    def _do_update():
        dlg.accept()
        ok, output = _download_and_install(parent, zip_url)
        if ok:
            done = QDialog(parent)
            done.setWindowTitle("Update erfolgreich")
            done.setFixedSize(350, 150)
            done.setStyleSheet(_themed_dialog_style())
            dl = QVBoxLayout(done)
            dl.setContentsMargins(20, 20, 20, 20)
            dl.addWidget(QLabel(f"Update auf v{remote_ver} installiert!"))
            dl.addWidget(QLabel("App wird jetzt neu gestartet..."))
            dl.addStretch()
            btn_ok = QPushButton("OK")
            btn_ok.setObjectName("primary")
            btn_ok.clicked.connect(done.accept)
            dl.addWidget(btn_ok)
            done.exec()
            restart_app()
        else:
            err = QDialog(parent)
            err.setWindowTitle("Update fehlgeschlagen")
            err.setFixedSize(350, 150)
            err.setStyleSheet(_themed_dialog_style())
            el = QVBoxLayout(err)
            el.setContentsMargins(20, 20, 20, 20)
            el.addWidget(QLabel(f"Fehler beim Update:\n{output}"))
            el.addStretch()
            btn_ok = QPushButton("OK")
            btn_ok.clicked.connect(err.accept)
            el.addWidget(btn_ok)
            err.exec()

    btn_update.clicked.connect(_do_update)
    dlg.exec()
