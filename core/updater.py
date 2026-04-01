"""
Auto-Updater — prüft GitHub auf neue Versionen.
Zeigt Popup wenn Update verfügbar, User entscheidet.
"""

import os
import json
import subprocess
import threading
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Signal, QObject

# Aktuelle Version
CURRENT_VERSION = "2.0.0"

# GitHub Repo
REPO_OWNER = "DO4NRW"
REPO_NAME = "TRX-Cat-Controll"
API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/commits/main"

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class UpdateChecker(QObject):
    """Prüft im Hintergrund ob ein Update auf GitHub verfügbar ist."""

    update_available = Signal(str, str)  # (local_hash, remote_hash)
    no_update = Signal()
    check_failed = Signal(str)  # error message

    def check(self):
        """Starte Check im Hintergrund."""
        threading.Thread(target=self._check_remote, daemon=True).start()

    def _check_remote(self):
        try:
            # Lokalen Git-Hash holen
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=_PROJECT_DIR
            )
            if result.returncode != 0:
                self.check_failed.emit("Kein Git-Repository")
                return
            local_hash = result.stdout.strip()[:7]

            # Remote Hash von GitHub holen (ohne Token, public repo)
            import urllib.request
            req = urllib.request.Request(API_URL)
            req.add_header("Accept", "application/vnd.github.v3+json")
            req.add_header("User-Agent", "TRX-Cat-Control-Updater")

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            remote_hash = data.get("sha", "")[:7]
            commit_msg = data.get("commit", {}).get("message", "").split("\n")[0]

            if local_hash != remote_hash:
                self.update_available.emit(local_hash, f"{remote_hash} — {commit_msg}")
            else:
                self.no_update.emit()

        except Exception as e:
            self.check_failed.emit(str(e))

    @staticmethod
    def do_update():
        """Git pull ausführen."""
        try:
            result = subprocess.run(
                ["git", "pull", "origin", "main"],
                capture_output=True, text=True, timeout=30,
                cwd=_PROJECT_DIR
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, str(e)


def show_update_dialog(parent, local_hash, remote_info):
    """Zeigt Update-Dialog. Gibt True zurück wenn User updaten will."""
    msg = QMessageBox(parent)
    msg.setWindowTitle("Update verfügbar")
    msg.setText(f"Eine neue Version ist auf GitHub verfügbar!\n\n"
                f"Lokal:  {local_hash}\n"
                f"Remote: {remote_info}\n\n"
                f"Jetzt aktualisieren?")
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    msg.setDefaultButton(QMessageBox.No)
    msg.button(QMessageBox.Yes).setText("Ja, updaten")
    msg.button(QMessageBox.No).setText("Nein, später")

    if msg.exec() == QMessageBox.Yes:
        ok, output = UpdateChecker.do_update()
        if ok:
            # Neustart-Dialog
            restart_msg = QMessageBox(parent)
            restart_msg.setWindowTitle("Update erfolgreich")
            restart_msg.setText("Update installiert!\n\n"
                               "Die App muss neu gestartet werden.\n"
                               "Bitte schließe und starte die App erneut.")
            restart_msg.setStandardButtons(QMessageBox.Ok)
            restart_msg.exec()
        else:
            err_msg = QMessageBox(parent)
            err_msg.setWindowTitle("Update fehlgeschlagen")
            err_msg.setText(f"Update konnte nicht installiert werden:\n\n{output}")
            err_msg.setStandardButtons(QMessageBox.Ok)
            err_msg.exec()
