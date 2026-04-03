"""
RigLink — Digi-Modus Panel (Platzhalter)
Zeigt die UI-Struktur für den zukünftigen Digi-Modus (FT8/FT4/RTTY etc.).
Noch keine Funktionalität — nur Layout.
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QComboBox, QTextEdit, QSplitter,
                               QFrame, QProgressBar)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont

from core.theme import T, register_refresh, themed_icon
from ui._constants import _ICONS

import os


class DigiPanelOverlay(QWidget):
    """Overlay für den Digi-Modus — Platzhalter-UI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self._build_ui()
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
        header.addWidget(self.combo_mode)

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
