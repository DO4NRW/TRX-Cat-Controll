import os

from PySide6.QtWidgets import QPushButton, QWidget, QGridLayout
from PySide6.QtCore import QSize, Qt

from core.theme import T, themed_icon
from ui._constants import _ICONS


class ToggleButton(QPushButton):
    """Single on/off toggle button using toggle_off / toggle_on SVG icons."""

    def __init__(self, label, parent=None):
        super().__init__(parent)
        self._label = label
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)

        self._load_icons()

        self.setIcon(self._icon_off)
        self.setIconSize(QSize(52, 32))
        self.setText(f"  {label}")
        self.setLayoutDirection(Qt.LeftToRight)
        self._apply_style()
        self.toggled.connect(self._update_icon)

    def _load_icons(self):
        self._icon_off = themed_icon(os.path.join(_ICONS, "toggle_off.svg"))
        self._icon_on  = themed_icon(os.path.join(_ICONS, "toggle_on.svg"))

    def _apply_style(self):
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                color: {T['text_secondary']};
                font-size: 13px;
                text-align: left;
                padding: 4px 6px;
            }}
            QPushButton:checked {{ color: {T['text']}; }}
            QPushButton:hover   {{ color: {T['text']}; }}
        """)

    def _update_icon(self, checked):
        self.setIcon(self._icon_on if checked else self._icon_off)


class ToggleGroup(QWidget):
    """Toggle group: click to select, click again to deselect (all-off allowed).
    Default: all OFF unless set_value() is called explicitly."""

    def __init__(self, options, wrap_at=3, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._buttons = []
        self._lock = False  # prevent re-entrancy during deselect

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        for i, opt in enumerate(options):
            btn = ToggleButton(opt)
            btn.toggled.connect(lambda checked, b=btn: self._on_toggled(b, checked))
            layout.addWidget(btn, i // wrap_at, i % wrap_at)
            self._buttons.append(btn)

    def _on_toggled(self, source, checked):
        if self._lock:
            return
        if checked:
            self._lock = True
            for btn in self._buttons:
                if btn is not source:
                    btn.setChecked(False)
            self._lock = False

    def value(self):
        for btn in self._buttons:
            if btn.isChecked():
                return btn._label
        return None

    def set_value(self, val):
        self._lock = True
        for btn in self._buttons:
            btn.setChecked(btn._label == val)
        self._lock = False
