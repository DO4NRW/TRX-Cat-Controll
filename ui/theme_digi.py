"""Digi-Mode Farben (FT8/FT4/RTTY etc.) — Tab-Widget für den Theme Editor."""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                                QPushButton, QScrollArea, QColorDialog)
from PySide6.QtGui import QColor
from PySide6.QtCore import QSize, Qt

from core.theme import T, themed_icon, rgba_parts
from ui._constants import _ICONS

# Digi-Mode Farb-Keys mit deutschem Label
_DIGI_FIELDS = [
    ("digi_cq",         "CQ Ruf"),
    ("digi_reply",      "Antwort auf CQ"),
    ("digi_own_call",   "Eigenes Rufzeichen"),
    ("digi_worked",     "Bereits gearbeitet"),
    ("digi_new_dxcc",   "Neues DXCC"),
    ("digi_new_grid",   "Neues Grid"),
    ("digi_new_call",   "Neues Rufzeichen"),
    ("digi_alert",      "Alert / Priorität"),
    ("digi_bg_even",    "Hintergrund gerade"),
    ("digi_bg_odd",     "Hintergrund ungerade"),
    ("digi_text",       "Standard Text"),
    ("digi_timestamp",  "Zeitstempel"),
    ("digi_freq",       "Frequenz-Marker"),
]

# Default-Farben (Digi-Mode Standard-Palette)
DIGI_DEFAULTS = {
    "digi_cq":         "rgba(0, 255, 0, 255)",
    "digi_reply":      "rgba(255, 0, 0, 255)",
    "digi_own_call":   "rgba(255, 0, 0, 255)",
    "digi_worked":     "rgba(180, 180, 180, 255)",
    "digi_new_dxcc":   "rgba(255, 0, 255, 255)",
    "digi_new_grid":   "rgba(255, 165, 0, 255)",
    "digi_new_call":   "rgba(0, 255, 255, 255)",
    "digi_alert":      "rgba(255, 255, 0, 255)",
    "digi_bg_even":    "rgba(30, 30, 30, 255)",
    "digi_bg_odd":     "rgba(40, 40, 40, 255)",
    "digi_text":       "rgba(220, 220, 220, 255)",
    "digi_timestamp":  "rgba(130, 130, 130, 255)",
    "digi_freq":       "rgba(6, 198, 164, 255)",
}


class DigiColorWidget(QWidget):
    """Digi-Mode Farb-Tab für den Theme Editor."""

    def __init__(self, theme_data: dict, parent=None):
        super().__init__(parent)
        self._theme_data = theme_data
        self._color_dots = {}
        self._color_rows = {}
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # Info-Label
        info = QLabel("FT8/FT4 Decode-Farben (wie WSJT-X)")
        info.setStyleSheet(f"color: {T['text_muted']}; font-size: 10px; border: none;")
        root.addWidget(info)

        # Farbliste
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { width: 6px; background: transparent; }
            QScrollBar::handle:vertical { background: rgba(128,128,128,60); border-radius: 3px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        """)
        scroll_widget = QWidget()
        color_list = QVBoxLayout(scroll_widget)
        color_list.setContentsMargins(4, 4, 4, 4)
        color_list.setSpacing(1)

        for key, label in _DIGI_FIELDS:
            row_widget = QWidget()
            row_widget.setFixedHeight(34)
            row_widget.setCursor(Qt.PointingHandCursor)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(6, 0, 6, 0)
            row_layout.setSpacing(6)

            # Farbpunkt
            dot = QLabel("")
            dot.setFixedSize(20, 20)
            color_val = self._theme_data.get(key, DIGI_DEFAULTS.get(key, "rgba(128,128,128,255)"))
            r, g, b, a = rgba_parts(color_val)
            dot.setStyleSheet(f"background: rgba({r},{g},{b},{a}); border: 2px solid {T['border']}; border-radius: 10px;")
            row_layout.addWidget(dot)
            self._color_dots[key] = dot

            # Label
            lbl = QPushButton(label)
            lbl.setCursor(Qt.PointingHandCursor)
            lbl.setStyleSheet(f"""
                QPushButton {{ background: transparent; border: none;
                    color: {T['text_secondary']}; font-size: 11px; text-align: left; padding: 0; }}
                QPushButton:hover {{ color: {T['text']}; }}
            """)
            lbl.clicked.connect(lambda checked, k=key: self._edit_color(k))
            row_layout.addWidget(lbl, stretch=1)

            # Edit Button
            btn_edit = QPushButton()
            btn_edit.setFixedSize(34, 34)
            btn_edit.setCursor(Qt.PointingHandCursor)
            btn_edit.setIcon(themed_icon(os.path.join(_ICONS, "build.svg")))
            btn_edit.setIconSize(QSize(24, 24))
            btn_edit.setStyleSheet(f"""
                QPushButton {{ background: transparent; border: none; }}
                QPushButton:hover {{ background: {T['bg_light']}; border-radius: 3px; }}
            """)
            btn_edit.clicked.connect(lambda checked, k=key: self._edit_color(k))
            row_layout.addWidget(btn_edit)

            color_list.addWidget(row_widget)
            self._color_rows[key] = (row_widget, lbl, btn_edit)

        color_list.addStretch()
        scroll.setWidget(scroll_widget)
        root.addWidget(scroll, stretch=1)

    def _edit_color(self, key):
        color_str = self._theme_data.get(key, DIGI_DEFAULTS.get(key, "rgba(0,0,0,255)"))
        r, g, b, a = rgba_parts(color_str)

        dlg = QColorDialog(QColor(r, g, b, a))
        dlg.setWindowTitle(dict(_DIGI_FIELDS).get(key, key))
        dlg.setOption(QColorDialog.ShowAlphaChannel, True)

        if dlg.exec() == QColorDialog.Accepted:
            c = dlg.selectedColor()
            rgba_str = f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()})"
            self._theme_data[key] = rgba_str
            self._update_dot(key)

    def _update_dot(self, key):
        if key in self._color_dots:
            color_val = self._theme_data.get(key, DIGI_DEFAULTS.get(key, "rgba(128,128,128,255)"))
            r, g, b, a = rgba_parts(color_val)
            self._color_dots[key].setStyleSheet(
                f"background: rgba({r},{g},{b},{a}); border: 2px solid {T['border']}; border-radius: 10px;")

    def refresh_theme(self):
        """Alle Dots und Labels mit aktuellen Theme-Farben updaten."""
        for key in self._color_rows:
            self._update_dot(key)
            row_data = self._color_rows[key]
            lbl = row_data[1]
            btn = row_data[2]
            lbl.setStyleSheet(f"""
                QPushButton {{ background: transparent; border: none;
                    color: {T['text_secondary']}; font-size: 11px; text-align: left; padding: 0; }}
                QPushButton:hover {{ color: {T['text']}; }}
            """)
            btn.setIcon(themed_icon(os.path.join(_ICONS, "build.svg")))
            btn.setStyleSheet(f"""
                QPushButton {{ background: transparent; border: none; }}
                QPushButton:hover {{ background: {T['bg_light']}; border-radius: 3px; }}
            """)

    def set_theme_data(self, data: dict):
        """Theme-Daten aktualisieren (beim Preset-Wechsel)."""
        self._theme_data = data
        # Defaults einfügen wenn Keys fehlen
        for key, default in DIGI_DEFAULTS.items():
            if key not in self._theme_data:
                self._theme_data[key] = default
        for key in self._color_dots:
            self._update_dot(key)


# os wird oben gebraucht
import os
