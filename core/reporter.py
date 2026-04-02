"""
Crash-Reporter — sendet Session-Logs als GitHub Issue an DO4NRW/RigLink.
Token ist fest eingebaut, User braucht keinen Key.
Nach dem Senden bekommt er den Link zum Issue (kann Status verfolgen).
"""

import json
import urllib.request
import urllib.error
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QTextEdit, QApplication)
from PySide6.QtCore import Qt
from core.session_logger import get_session_log, get_system_info, clear_old_log

REPORT_REPO = "DO4NRW/RigLink"
REPORT_API = f"https://api.github.com/repos/{REPORT_REPO}/issues"

# Report-Token (nur Issues erstellen auf DO4NRW/RigLink, sonst keine Rechte)
import base64 as _b64
_TOKEN = _b64.b64decode("Z2l0aHViX3BhdF8xMUI3TUQyVVkwUWcwVmNSV0F6NzVNX2NYTklFaVY2MlVmQUJQNDdIaWQ5Y1hGVVYyaUFYZkNIOFhFekhKMUczczRFSFQyUVVMN1pvSnJWSmdY").decode()


def _themed_report_style():
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
        QLabel#subtitle {{
            font-size: 12px;
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
        QPushButton:disabled {{
            opacity: 0.5;
            color: {T['text_secondary']};
        }}
    """


def _send_issue(title, body):
    """GitHub Issue erstellen. Gibt (ok, message, url) zurück."""
    data = json.dumps({"title": title, "body": body, "labels": ["bug-report"]}).encode("utf-8")
    req = urllib.request.Request(REPORT_API, data=data, method="POST")
    req.add_header("Authorization", f"token {_TOKEN}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "RigLink-Reporter")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            url = result.get("html_url", "")
            return True, f"Report #{result.get('number', '?')} erstellt", url
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "Report-Token ungültig — bitte RigLink updaten.", ""
        elif e.code == 403:
            return False, "Zugriff verweigert — bitte RigLink updaten.", ""
        elif e.code == 404:
            return False, "Report-Server nicht erreichbar.", ""
        else:
            return False, f"Fehler: {e.code} {e.reason}", ""
    except Exception as e:
        return False, f"Verbindungsfehler: {e}", ""


def show_report_dialog(parent, is_crash=False):
    """Report-Dialog anzeigen. is_crash=True zeigt Crash-Hinweis."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Crash Report" if is_crash else "Bug Report")
    dlg.setFixedSize(520, 460)
    dlg.setStyleSheet(_themed_report_style())

    layout = QVBoxLayout(dlg)
    layout.setSpacing(10)
    layout.setContentsMargins(20, 20, 20, 20)

    # Titel
    lbl_title = QLabel("Crash Report senden" if is_crash else "Bug Report senden")
    lbl_title.setObjectName("title")
    layout.addWidget(lbl_title)

    if is_crash:
        lbl_info = QLabel("RigLink wurde nicht sauber beendet.\n"
                          "Sende den Session-Log damit wir den Fehler finden.")
        lbl_info.setObjectName("subtitle")
        lbl_info.setWordWrap(True)
        layout.addWidget(lbl_info)

    # Beschreibung
    lbl_desc = QLabel("Beschreibung (was hast du gemacht?):")
    layout.addWidget(lbl_desc)

    txt_desc = QTextEdit()
    txt_desc.setPlaceholderText("Kurze Beschreibung des Problems...")
    txt_desc.setMaximumHeight(80)
    layout.addWidget(txt_desc)

    # Session Log Vorschau
    lbl_log = QLabel("Session-Log:")
    layout.addWidget(lbl_log)

    txt_log = QTextEdit()
    txt_log.setReadOnly(True)
    session_log = get_session_log()
    txt_log.setPlainText(session_log if session_log else "(Kein Session-Log vorhanden)")
    layout.addWidget(txt_log)

    # Buttons
    btn_row = QHBoxLayout()
    btn_row.addStretch()

    btn_cancel = QPushButton("Abbrechen")
    btn_cancel.clicked.connect(dlg.reject)
    btn_row.addWidget(btn_cancel)

    btn_send = QPushButton("Report senden")
    btn_send.setObjectName("primary")
    btn_row.addWidget(btn_send)

    layout.addLayout(btn_row)

    def _do_send():
        desc = txt_desc.toPlainText().strip()
        log_content = txt_log.toPlainText()

        # Issue Title
        from core.updater import CURRENT_VERSION
        tag = "[CRASH]" if is_crash else "[BUG]"
        title = f"{tag} RigLink v{CURRENT_VERSION}"
        if desc:
            short = desc.split("\n")[0][:60]
            title += f" — {short}"

        # Issue Body
        body_parts = []
        if desc:
            body_parts.append(f"## Beschreibung\n{desc}")
        body_parts.append(f"## System\n```\n{get_system_info()}\n```")
        if log_content and log_content != "(Kein Session-Log vorhanden)":
            trimmed = log_content[-5000:] if len(log_content) > 5000 else log_content
            body_parts.append(f"## Session-Log\n```\n{trimmed}\n```")

        body = "\n\n".join(body_parts)

        btn_send.setEnabled(False)
        btn_send.setText("Sende...")
        btn_cancel.setEnabled(False)
        QApplication.processEvents()

        ok, msg, issue_url = _send_issue(title, body)
        _on_result(ok, msg, issue_url)

    def _on_result(ok, msg, issue_url=""):
        btn_send.setEnabled(True)
        btn_send.setText("Report senden")
        btn_cancel.setEnabled(True)

        if ok:
            if is_crash:
                clear_old_log()

            done = QDialog(dlg)
            done.setWindowTitle("Report gesendet")
            done.setFixedSize(420, 180)
            done.setStyleSheet(_themed_report_style())
            dl = QVBoxLayout(done)
            dl.setContentsMargins(20, 20, 20, 20)
            dl.addWidget(QLabel(f"Danke! {msg}"))

            if issue_url:
                from core.theme import T
                lbl_link = QLabel(f'<a href="{issue_url}" style="color: {T["accent"]};">'
                                  f'Status deines Reports ansehen</a>')
                lbl_link.setOpenExternalLinks(True)
                dl.addWidget(lbl_link)

            dl.addStretch()
            btn_ok = QPushButton("OK")
            btn_ok.setObjectName("primary")
            btn_ok.clicked.connect(done.accept)
            dl.addWidget(btn_ok)
            done.exec()
            dlg.accept()
        else:
            err = QDialog(dlg)
            err.setWindowTitle("Fehler")
            err.setFixedSize(380, 130)
            err.setStyleSheet(_themed_report_style())
            el = QVBoxLayout(err)
            el.setContentsMargins(20, 20, 20, 20)
            el.addWidget(QLabel(msg))
            el.addStretch()
            btn_ok = QPushButton("OK")
            btn_ok.clicked.connect(err.accept)
            el.addWidget(btn_ok)
            err.exec()

    btn_send.clicked.connect(_do_send)
    dlg.exec()


def show_crash_dialog(parent):
    """Beim Start zeigen wenn Crash erkannt wurde. Fragt ob Report gesendet werden soll."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("RigLink — Absturz erkannt")
    dlg.setFixedSize(420, 180)
    dlg.setStyleSheet(_themed_report_style())

    layout = QVBoxLayout(dlg)
    layout.setSpacing(12)
    layout.setContentsMargins(20, 20, 20, 20)

    lbl_title = QLabel("Absturz erkannt")
    lbl_title.setObjectName("title")
    layout.addWidget(lbl_title)

    lbl_info = QLabel("RigLink wurde beim letzten Mal nicht sauber beendet.\n"
                      "Möchtest du einen Crash-Report senden?")
    lbl_info.setObjectName("subtitle")
    lbl_info.setWordWrap(True)
    layout.addWidget(lbl_info)

    layout.addStretch()

    btn_row = QHBoxLayout()
    btn_row.addStretch()

    btn_skip = QPushButton("Nein, löschen")
    btn_row.addWidget(btn_skip)

    btn_send = QPushButton("Report senden")
    btn_send.setObjectName("primary")
    btn_row.addWidget(btn_send)

    layout.addLayout(btn_row)

    def _skip():
        clear_old_log()
        dlg.reject()

    def _send():
        dlg.accept()
        show_report_dialog(parent, is_crash=True)

    btn_skip.clicked.connect(_skip)
    btn_send.clicked.connect(_send)
    dlg.exec()
