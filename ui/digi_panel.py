"""
RigLink — Digi-Modus Panel
FT8/FT4 Platzhalter + RTTY Decode (RTTYDecoder).
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QComboBox, QTextEdit, QSplitter,
                               QFrame, QProgressBar, QStackedWidget)
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QFont

from core.theme import T, register_refresh, themed_icon
from core.digi.rtty import RTTYDecoder, RTTYConfig
from ui._constants import _ICONS

import os
import random


class DigiPanelOverlay(QWidget):
    """Overlay für den Digi-Modus (FT8/FT4 Platzhalter + RTTY aktiv)."""

    _RTTY_DEMO_LINES = [
        "CQ CQ DE DO4NRW DO4NRW JN49 K\r\n",
        "DL1ABC DE DO4NRW 599 NR 001 K\r\n",
        "CQ DX DE DO4NRW JN49 PSE K\r\n",
        "DO4NRW DE DL2XYZ 579 NR 042 BK\r\n",
        "QSL 73 DE DO4NRW SK\r\n",
        "CQ CQ DE OE3MWS OE3MWS JN78 K\r\n",
        "DO4NRW DE PA3ABC 599 NR 007 K\r\n",
        "CQ CONTEST DE DK5WL JO31 K\r\n",
        "DO4NRW DE F5RWT 599 599 BK\r\n",
        "QRZ? DE DO4NRW K\r\n",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setVisible(False)
        self._rtty_decoder = RTTYDecoder(RTTYConfig())
        self._rtty_active  = False
        self._rtty_demo_timer = QTimer(self)
        self._rtty_demo_timer.timeout.connect(self._rtty_demo_tick)
        self._build_ui()
        self._rtty_decoder.decoded.connect(self._on_rtty_decoded)
        register_refresh(self.refresh_theme)

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

        # RTTY Start/Stop (nur sichtbar wenn RTTY aktiv)
        self.btn_rtty = QPushButton("▶ RTTY Start")
        self.btn_rtty.setFixedHeight(36)
        self.btn_rtty.setStyleSheet(self._btn_style())
        self.btn_rtty.setFocusPolicy(Qt.NoFocus)
        self.btn_rtty.setVisible(False)
        self.btn_rtty.clicked.connect(self._on_rtty_toggle)
        header.addWidget(self.btn_rtty)

        # Schließen-Button
        self.btn_close = QPushButton("Schließen")
        self.btn_close.setFixedHeight(36)
        self.btn_close.setStyleSheet(self._btn_style())
        self.btn_close.setFocusPolicy(Qt.NoFocus)
        self.btn_close.clicked.connect(self.hide)
        header.addWidget(self.btn_close)

        root.addLayout(header)

        # ── Splitter: Decode-Liste oben, Wasserfall-Bereich unten ──
        splitter = QSplitter(Qt.Vertical)

        # Oberer Bereich: Decode-Liste (Platzhalter)
        decode_widget = QWidget()
        decode_layout = QVBoxLayout(decode_widget)
        decode_layout.setContentsMargins(0, 0, 0, 0)
        decode_layout.setSpacing(4)

        # Spalten-Header
        col_header = QHBoxLayout()
        for label in ["UTC", "dB", "DT", "Freq", "Message"]:
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {T['text_muted']}; font-size: 10px; font-weight: bold; border: none;")
            if label == "Message":
                col_header.addWidget(lbl, stretch=3)
            else:
                col_header.addWidget(lbl, stretch=1)
        decode_layout.addLayout(col_header)

        # Decode-Textfeld (Platzhalter)
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
        # Platzhalter-Daten
        self.decode_view.setPlainText(
            "— Digi-Modus ist noch nicht implementiert —\n\n"
            "Hier werden zukünftig FT8/FT4 Decodes angezeigt:\n\n"
            "  UTC    dB   DT   Freq   Message\n"
            "  12:30  -5  0.3  1234   CQ DL1ABC JO31\n"
            "  12:30  -8  0.1  1567   CQ DO4NRW JO31\n"
            "  12:30 -12  0.5   890   DL1ABC DO4NRW -05\n"
            "  12:31  -3  0.2  1234   DO4NRW DL1ABC R-08\n"
            "  12:31  -6  0.4  1567   DL1ABC DO4NRW RR73\n"
        )
        decode_layout.addWidget(self.decode_view)

        splitter.addWidget(decode_widget)

        # Unterer Bereich: TX-Eingabe + Buttons
        tx_widget = QWidget()
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
        self.progress_tx.setRange(0, 100)
        self.progress_tx.setValue(0)
        self.progress_tx.setFixedHeight(8)
        self.progress_tx.setFixedWidth(200)
        self.progress_tx.setTextVisible(False)
        self.progress_tx.setStyleSheet(f"""
            QProgressBar {{ background-color: {T['bg_dark']}; border: 1px solid {T['border']}; border-radius: 3px; }}
            QProgressBar::chunk {{ background-color: {T['accent']}; border-radius: 2px; }}""")
        tx_status.addWidget(self.progress_tx)
        tx_layout.addLayout(tx_status)

        # TX-Buttons-Reihe
        tx_buttons = QHBoxLayout()
        tx_buttons.setSpacing(4)

        for label in ["Enable TX", "Halt TX", "Tune", "Log QSO"]:
            btn = QPushButton(label)
            btn.setFixedHeight(32)
            btn.setStyleSheet(self._btn_style())
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setEnabled(False)  # Platzhalter — noch nicht aktiv
            tx_buttons.addWidget(btn)

        tx_layout.addLayout(tx_buttons)

        # Info-Zeile
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {T['border']};")
        tx_layout.addWidget(sep)

        info = QLabel("Digi-Modus wird in einem zukünftigen Update verfügbar sein.")
        info.setStyleSheet(f"color: {T['text_muted']}; font-size: 11px; border: none;")
        info.setAlignment(Qt.AlignCenter)
        tx_layout.addWidget(info)

        splitter.addWidget(tx_widget)
        splitter.setStretchFactor(0, 3)  # Decode-Liste größer
        splitter.setStretchFactor(1, 1)  # TX-Bereich kleiner

        root.addWidget(splitter)

    # ── Modus-Wechsel ─────────────────────────────────────────────────────────

    def _on_mode_changed(self, mode: str):
        is_rtty = (mode == "RTTY")
        self.btn_rtty.setVisible(is_rtty)
        if not is_rtty and self._rtty_active:
            self._stop_rtty()
        if is_rtty:
            self.decode_view.setPlainText("— RTTY-Decoder bereit. Start drücken —\n")
        else:
            self.decode_view.setPlainText(
                "— Digi-Modus ist noch nicht implementiert —\n\n"
                "Hier werden zukünftig FT8/FT4 Decodes angezeigt:\n\n"
                "  UTC    dB   DT   Freq   Message\n"
                "  12:30  -5  0.3  1234   CQ DL1ABC JO31\n"
            )

    def _on_rtty_toggle(self):
        if self._rtty_active:
            self._stop_rtty()
        else:
            self._start_rtty()

    def _start_rtty(self):
        self._rtty_decoder.reset()
        self._rtty_active = True
        self.btn_rtty.setText("■ RTTY Stop")
        self.decode_view.setPlainText("— RTTY läuft — Demo-Modus (kein TRX) —\n")
        self.lbl_tx_status.setText("RTTY RX aktiv [Demo]")
        self._rtty_demo_timer.start(random.randint(2000, 5000))

    def _stop_rtty(self):
        self._rtty_active = False
        self._rtty_demo_timer.stop()
        self.btn_rtty.setText("▶ RTTY Start")
        self.lbl_tx_status.setText("RX — Warte auf Decodes...")

    def _rtty_demo_tick(self):
        """Simuliert eine zufällige RTTY-Decode-Zeile im Demo-Modus."""
        if not self._rtty_active:
            return
        line = random.choice(self._RTTY_DEMO_LINES)
        self._on_rtty_decoded(line)
        self._rtty_demo_timer.start(random.randint(2000, 5000))

    def _on_rtty_decoded(self, text: str):
        """Dekodierten RTTY-Text in decode_view anhängen."""
        cursor = self.decode_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self.decode_view.setTextCursor(cursor)
        self.decode_view.ensureCursorVisible()

    def _btn_style(self):
        return f"""QPushButton {{ background-color: {T['bg_mid']}; color: {T['text']};
            border: 1px solid {T['border']}; border-radius: 4px; padding: 4px 12px; font-size: 12px; }}
            QPushButton:hover {{ border-color: {T['border_hover']}; background-color: {T['bg_light']}; }}
            QPushButton:disabled {{ color: {T['text_disabled']}; }}"""

    def _apply_combo_style(self):
        self.combo_mode.setStyleSheet(f"""
            QComboBox {{ background-color: {T['bg_mid']}; color: {T['text']};
                border: 1px solid {T['border']}; border-radius: 4px; padding: 6px; }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{ background-color: {T['bg_mid']}; color: {T['text']};
                selection-background-color: {T['bg_light']}; border: 1px solid {T['border']}; }}""")

    def show_overlay(self):
        self.setGeometry(self.parent().rect())
        self.setVisible(True)
        self.raise_()

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
