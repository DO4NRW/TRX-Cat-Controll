"""
RigLink — Digi-Modus Panel
FT8/FT4 Decode-Ansicht mit Demo-Daten, RTTY, PSK31, CW Platzhalter.
"""

import random
from datetime import datetime, timedelta

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QComboBox, QTextEdit, QSplitter,
                               QFrame, QProgressBar)
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QFont, QColor, QTextCharFormat, QTextCursor

from core.theme import T, register_refresh, themed_icon
from ui._constants import _ICONS


# ── FT8 Demo-Daten ────────────────────────────────────────────────────────────

_FT8_CALLS = [
    ("CQ DX DO4NRW JN49", -12, 0.3, 14074),
    ("DO4NRW DL2XYZ -08",  +3, 1.1, 14074),
    ("DL2XYZ DO4NRW RR73",  -8, 0.2, 14074),
    ("CQ EU SP5ABC KO02", +15, 0.8, 14075),
    ("CQ CONTEST OE3MWS JN78", -5, 0.4, 14076),
    ("DO4NRW PA3GRM -14",  -3, 0.6, 14077),
    ("PA3GRM DO4NRW R-09",  +7, 0.9, 14077),
    ("DO4NRW PA3GRM RR73", -10, 0.3, 14077),
    ("CQ DX F5RWT IN93",   +2, 0.5, 14073),
    ("F5RWT DO4NRW -06",   -6, 1.2, 14073),
    ("CQ VE3XAZ FN03",    -18, 0.1, 14072),
    ("DO4NRW DK5WL R-04",  -1, 0.7, 14079),
    ("CQ WWFF HA5CW JN97", +9, 0.4, 14071),
    ("CQ DX UR4EI KN88",  -15, 0.2, 14075),
    ("CQ EU IK4EST JN54",  +4, 0.8, 14078),
]


class DigiPanelOverlay(QDialog):
    """Freistehender Digi-Modus Dialog — FT8/FT4 Decode + Demo-Betrieb."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Digi-Modus")
        self.setMinimumSize(700, 500)
        self.setSizeGripEnabled(True)

        self._demo_timer = QTimer(self)
        self._demo_timer.timeout.connect(self._ft8_demo_tick)
        self._demo_counter = 0

        self._build_ui()
        register_refresh(self.refresh_theme)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        if not self._demo_timer.isActive():
            self._start_ft8_demo()

    def closeEvent(self, event):
        self._demo_timer.stop()
        super().closeEvent(event)

    # ── UI aufbauen ───────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(f"background-color: {T['bg_dark']};")
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        # ── Header ─────────────────────────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(8)

        title = QLabel("Digi-Modus")
        title.setFont(QFont("Roboto", 16, QFont.Bold))
        title.setStyleSheet(f"color: {T['accent']}; border: none;")
        header.addWidget(title)

        header.addStretch()

        # Modus-Auswahl
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["FT8", "FT4", "RTTY", "PSK31", "CW", "JS8Call", "OLIVIA"])
        self.combo_mode.setMinimumWidth(120)
        self._apply_combo_style()
        self.combo_mode.currentTextChanged.connect(self._on_mode_changed)
        header.addWidget(self.combo_mode)

        # Schließen-Button
        self.btn_close = QPushButton("Schließen")
        self.btn_close.setFixedHeight(36)
        self.btn_close.setStyleSheet(self._btn_style())
        self.btn_close.setFocusPolicy(Qt.NoFocus)
        self.btn_close.clicked.connect(self.close)
        header.addWidget(self.btn_close)

        root.addLayout(header)

        # ── Splitter: Decode-Liste oben, TX-Bereich unten ──────────
        splitter = QSplitter(Qt.Vertical)

        # Oberer Bereich: Decode-Liste
        decode_widget = QFrame()
        decode_layout = QVBoxLayout(decode_widget)
        decode_layout.setContentsMargins(0, 0, 0, 0)
        decode_layout.setSpacing(4)

        # Spalten-Header
        col_header = QHBoxLayout()
        for label, stretch in [("UTC", 2), ("dB", 1), ("DT", 1), ("Freq", 1), ("Message", 4)]:
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {T['text_muted']}; font-size: 10px; font-weight: bold; border: none;")
            col_header.addWidget(lbl, stretch=stretch)
        decode_layout.addLayout(col_header)

        # Decode-Textfeld
        self.decode_view = QTextEdit()
        self.decode_view.setReadOnly(True)
        self.decode_view.setFont(QFont("Consolas", 11))
        self.decode_view.setStyleSheet(f"""
            QTextEdit {{
                background-color: {T['bg_mid']};
                color: {T['text']};
                border: 1px solid {T['border']};
                border-radius: 4px;
            }}""")
        decode_layout.addWidget(self.decode_view)

        splitter.addWidget(decode_widget)

        # Unterer Bereich: TX-Eingabe + Buttons
        tx_widget = QFrame()
        tx_layout = QVBoxLayout(tx_widget)
        tx_layout.setContentsMargins(0, 0, 0, 0)
        tx_layout.setSpacing(6)

        # TX-Status-Zeile
        tx_status = QHBoxLayout()
        self.lbl_tx_status = QLabel("RX — Warte auf Decodes...")
        self.lbl_tx_status.setStyleSheet(f"color: {T['text_secondary']}; font-size: 12px; border: none;")
        tx_status.addWidget(self.lbl_tx_status)
        tx_status.addStretch()

        # Fortschrittsbalken (TX Timing)
        self.progress_tx = QProgressBar()
        self.progress_tx.setRange(0, 15)
        self.progress_tx.setValue(0)
        self.progress_tx.setFixedHeight(8)
        self.progress_tx.setFixedWidth(200)
        self.progress_tx.setTextVisible(False)
        self.progress_tx.setStyleSheet(f"""
            QProgressBar {{ background-color: {T['bg_dark']}; border: 1px solid {T['border']}; border-radius: 3px; }}
            QProgressBar::chunk {{ background-color: {T['accent']}; border-radius: 2px; }}""")
        tx_status.addWidget(self.progress_tx)
        tx_layout.addLayout(tx_status)

        # TX-Buttons
        tx_buttons = QHBoxLayout()
        tx_buttons.setSpacing(4)
        for label in ["Enable TX", "Halt TX", "Tune", "Log QSO"]:
            btn = QPushButton(label)
            btn.setFixedHeight(32)
            btn.setStyleSheet(self._btn_style())
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setEnabled(False)
            tx_buttons.addWidget(btn)
        tx_layout.addLayout(tx_buttons)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {T['border']};")
        tx_layout.addWidget(sep)

        info = QLabel("Demo-Modus: FT8-Decodes werden simuliert. TX erfordert TRX-Verbindung.")
        info.setStyleSheet(f"color: {T['text_muted']}; font-size: 11px; border: none;")
        info.setAlignment(Qt.AlignCenter)
        tx_layout.addWidget(info)

        splitter.addWidget(tx_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter)

        # Progress-Tick-Timer (1s)
        self._progress_timer = QTimer(self)
        self._progress_timer.timeout.connect(self._progress_tick)
        self._progress_value = 0
        self._progress_timer.start(1000)

    # ── FT8 Demo ─────────────────────────────────────────────────────────────

    def _start_ft8_demo(self):
        self.decode_view.clear()
        self.lbl_tx_status.setText("RX — FT8 Demo-Modus (kein TRX verbunden)")
        self._demo_counter = 0
        # Erste Zeile sofort
        self._ft8_demo_tick()
        # Danach alle 15 Sekunden
        self._demo_timer.start(15000)

    def _ft8_demo_tick(self):
        """Hängt eine simulierte FT8-Decode-Zeile an."""
        entry = _FT8_CALLS[self._demo_counter % len(_FT8_CALLS)]
        msg, snr, dt, freq = entry
        # Uhrzeit leicht variieren (immer richtiger 15s-Zyklus)
        base = datetime.now().replace(second=0, microsecond=0)
        utc = base.strftime("%H:%M:%S")
        snr_str = f"{snr:+4d}"
        line = f"{utc}  {snr_str}  {dt:.1f}  {freq:5d}  {msg}\n"

        # Farbe je nach Nachrichtstyp
        cursor = self.decode_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        if "CQ" in msg:
            fmt.setForeground(QColor(T["digi_cq"]))
        elif "DO4NRW" in msg and msg.startswith("DO4NRW"):
            fmt.setForeground(QColor(T["digi_own_call"]))
        elif "DO4NRW" in msg:
            fmt.setForeground(QColor(T["digi_reply"]))
        else:
            fmt.setForeground(QColor(T["text"]))
        cursor.insertText(line, fmt)
        self.decode_view.setTextCursor(cursor)
        self.decode_view.ensureCursorVisible()

        self._demo_counter += 1
        self._progress_value = 0

    def _progress_tick(self):
        self._progress_value = min(15, self._progress_value + 1)
        self.progress_tx.setValue(self._progress_value)

    # ── Modus-Wechsel ─────────────────────────────────────────────────────────

    def _on_mode_changed(self, mode: str):
        self.decode_view.clear()
        if mode == "FT8":
            self.lbl_tx_status.setText("RX — FT8 Demo-Modus (kein TRX verbunden)")
            if not self._demo_timer.isActive():
                self._start_ft8_demo()
        else:
            self._demo_timer.stop()
            self.lbl_tx_status.setText(f"RX — {mode} noch nicht implementiert")
            self.decode_view.setPlainText(
                f"— {mode} ist in dieser Version noch nicht verfügbar —\n\n"
                "Wird in einem zukünftigen Update implementiert."
            )

    # ── Styles ───────────────────────────────────────────────────────────────

    def _btn_style(self):
        return (f"QPushButton {{ background-color: {T['bg_mid']}; color: {T['text']}; "
                f"border: 1px solid {T['border']}; border-radius: 4px; padding: 4px 12px; font-size: 12px; }} "
                f"QPushButton:hover {{ border-color: {T['border_hover']}; background-color: {T['bg_light']}; }} "
                f"QPushButton:disabled {{ color: {T['text_disabled']}; }}")

    def _apply_combo_style(self):
        self.combo_mode.setStyleSheet(f"""
            QComboBox {{ background-color: {T['bg_mid']}; color: {T['text']};
                border: 1px solid {T['border']}; border-radius: 4px; padding: 6px; }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{ background-color: {T['bg_mid']}; color: {T['text']};
                selection-background-color: {T['bg_light']}; border: 1px solid {T['border']}; }}""")

    def refresh_theme(self):
        self.setStyleSheet(f"background-color: {T['bg_dark']};")
        self._apply_combo_style()
        self.btn_close.setStyleSheet(self._btn_style())
        self.decode_view.setStyleSheet(f"""
            QTextEdit {{
                background-color: {T['bg_mid']};
                color: {T['text']};
                border: 1px solid {T['border']};
                border-radius: 4px;
            }}""")
        self.progress_tx.setStyleSheet(f"""
            QProgressBar {{ background-color: {T['bg_dark']}; border: 1px solid {T['border']}; border-radius: 3px; }}
            QProgressBar::chunk {{ background-color: {T['accent']}; border-radius: 2px; }}""")
