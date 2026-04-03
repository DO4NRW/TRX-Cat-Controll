"""
RigLink — EQ-Panel
10-Band Grafik-Equalizer (EQWidget aus core/audio/eq.py).
Werte werden in der Rig-Config gespeichert.
"""

import os
import json

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from core.theme import T, register_refresh
from core.audio.eq import EQWidget, EQProcessor
from ui._constants import _PROJECT_DIR


_CONFIG_PATH = os.path.join(_PROJECT_DIR, "configs", "eq_state.json")


class EQOverlay(QWidget):
    """Overlay-Panel für den 10-Band EQ."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self._build_ui()
        self._load_state()
        register_refresh(self.refresh_theme)

    # ── UI aufbauen ───────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(f"background-color: {T['bg_dark']};")
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        # Header
        header = QHBoxLayout()
        title = QLabel("TX Equalizer")
        title.setFont(QFont("Roboto", 16, QFont.Bold))
        title.setStyleSheet(f"color: {T['accent']}; border: none;")
        header.addWidget(title)
        header.addStretch()

        self.btn_save = QPushButton("Speichern")
        self.btn_save.setFixedHeight(34)
        self.btn_save.setFocusPolicy(Qt.NoFocus)
        self.btn_save.setStyleSheet(self._btn_style())
        self.btn_save.clicked.connect(self._save_state)
        header.addWidget(self.btn_save)

        self.btn_close = QPushButton("Schließen")
        self.btn_close.setFixedHeight(34)
        self.btn_close.setFocusPolicy(Qt.NoFocus)
        self.btn_close.setStyleSheet(self._btn_style())
        self.btn_close.clicked.connect(self.hide)
        header.addWidget(self.btn_close)

        root.addLayout(header)

        # EQ-Widget
        self.eq_widget = EQWidget()
        self.eq_widget.changed.connect(self._on_eq_changed)
        root.addWidget(self.eq_widget)

        # Info
        info = QLabel("Werte werden gespeichert und bei der nächsten TX-Sitzung angewendet.")
        info.setStyleSheet(f"color: {T['text_muted']}; font-size: 11px; border: none;")
        info.setAlignment(Qt.AlignCenter)
        root.addWidget(info)

    # ── State speichern / laden ───────────────────────────────────────────────

    def _on_eq_changed(self, gains: list):
        """Gains bei jeder Änderung live speichern."""
        self._save_state()

    def _save_state(self):
        gains = self.eq_widget.processor.get_gains()
        try:
            with open(_CONFIG_PATH, "w") as f:
                json.dump({"eq_gains": gains}, f)
        except OSError:
            pass

    def _load_state(self):
        if not os.path.exists(_CONFIG_PATH):
            return
        try:
            with open(_CONFIG_PATH) as f:
                data = json.load(f)
            gains = data.get("eq_gains", [])
            if len(gains) == 10:
                self.eq_widget.set_gains(gains)
        except (OSError, json.JSONDecodeError, KeyError):
            pass

    # ── Overlay-Verwaltung ────────────────────────────────────────────────────

    def show_overlay(self):
        self.setGeometry(self.parent().rect())
        self.setVisible(True)
        self.raise_()

    # ── Theme ─────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        self.setStyleSheet(f"background-color: {T['bg_dark']};")
        for btn in [self.btn_save, self.btn_close]:
            btn.setStyleSheet(self._btn_style())
        self.eq_widget._apply_theme()

    def _btn_style(self):
        return (f"QPushButton {{ background-color: {T['bg_mid']}; color: {T['text']}; "
                f"border: 1px solid {T['border']}; border-radius: 4px; padding: 4px 12px; font-size: 12px; }} "
                f"QPushButton:hover {{ border-color: {T['border_hover']}; background-color: {T['bg_light']}; }}")
