"""
RigLink — Digi-Modus Panel
FT8/FT4 Decode-Ansicht.
- WSJT-X UDP-Listener (Port 2237): echte Decodes wenn WSJT-X läuft
- Ohne WSJT-X: Hinweistext statt Demo-Betrieb
"""

import time

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QToolButton, QComboBox, QTextEdit,
                               QSplitter, QFrame, QProgressBar)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor, QTextCharFormat, QTextCursor, QIcon, QPixmap

from core.theme import T, register_refresh
from core.digi.wsjtx_listener import WsjtxListener

_LIVE_TIMEOUT = 30.0   # Sekunden ohne Decode → Status-Hinweis

# SVG für weißes X (Close-Icon)
_CLOSE_SVG = b'''<svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 0 24 24" width="24">
  <path d="M0 0h24v24H0V0z" fill="none"/>
  <path fill="#ffffff" d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
</svg>'''


class DigiPanelOverlay(QDialog):
    """Freistehender Digi-Modus Dialog — FT8/FT4 Decode + Demo-Betrieb."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Digi-Modus")
        self.setMinimumSize(700, 500)
        self.setSizeGripEnabled(True)

        self._listener: WsjtxListener | None = None
        self._live_mode      = False
        self._last_real_ts   = 0.0   # Unix-Timestamp letzter echter Decode

        # Watchdog: alle 5s prüfen ob WSJT-X noch Daten liefert
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(5000)
        self._watchdog.timeout.connect(self._live_watchdog)

        self._build_ui()
        register_refresh(self.refresh_theme)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._start_listener()
        if not self._live_mode:
            self._show_no_wsjtx_hint()
        self._watchdog.start()

    def closeEvent(self, event):
        self._progress_timer.stop()
        self._watchdog.stop()
        self._stop_listener()
        self._live_mode = False
        super().closeEvent(event)

    # ── WSJT-X Listener ───────────────────────────────────────────────────────

    def _start_listener(self):
        if self._listener is not None:
            return
        self._listener = WsjtxListener(parent=self)
        self._listener.decoded.connect(self._on_wsjtx_decode)
        self._listener.error.connect(self._on_listener_error)
        if not self._listener.start():
            self._listener = None  # Fehler wurde per error-Signal gemeldet

    def _stop_listener(self):
        if self._listener:
            self._listener.stop()
            self._listener = None

    def _on_wsjtx_decode(self, utc: str, snr: int, dt: float,
                         freq_hz: int, message: str, mode: str):
        """Slot im Main-Thread — Qt-Signal vom UDP-Thread."""
        if not self._live_mode:
            # Erster echter Decode: Hinweis ersetzen
            self._live_mode = True
            self.decode_view.clear()
            self.lbl_tx_status.setText(f"RX — WSJT-X Live ({mode})")
            self.lbl_info.setText(f"WSJT-X Live — {mode} Decodes (Port 2237)")

        self._last_real_ts = time.monotonic()
        self._append_decode(utc, snr, dt, freq_hz, message)
        self._progress_value = 0

    def _on_listener_error(self, msg: str):
        self.lbl_tx_status.setText(f"⚠ {msg}")
        self._listener = None  # kein Stop-Versuch beim close

    def _live_watchdog(self):
        """Alle 5s: Status aktualisieren wenn keine echten Daten kommen."""
        if self._live_mode:
            age = time.monotonic() - self._last_real_ts
            if age > _LIVE_TIMEOUT:
                self.lbl_tx_status.setText(
                    f"RX — Warte auf WSJT-X… (kein Decode seit {int(age)}s)")

    # ── Decode ausgeben ───────────────────────────────────────────────────────

    def _append_decode(self, utc: str, snr: int, dt: float,
                       freq_hz: int, message: str):
        """Zeile in decode_view einhängen — mit Theme-Farbe."""
        snr_str = f"{snr:+4d}"
        line    = f"{utc}  {snr_str}  {dt:.1f}  {freq_hz:5d}  {message}\n"

        cursor = self.decode_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        if "CQ" in message:
            fmt.setForeground(QColor(T["digi_cq"]))
        elif message.startswith("DO4NRW"):
            fmt.setForeground(QColor(T["digi_own_call"]))
        elif "DO4NRW" in message:
            fmt.setForeground(QColor(T["digi_reply"]))
        else:
            fmt.setForeground(QColor(T["text"]))
        cursor.insertText(line, fmt)
        self.decode_view.setTextCursor(cursor)
        self.decode_view.ensureCursorVisible()

    # ── Hinweis ohne WSJT-X ─────────────────────────────────────────────────

    def _show_no_wsjtx_hint(self):
        """Zeigt Hinweistext wenn kein WSJT-X verbunden ist."""
        self.decode_view.clear()
        self.decode_view.setPlainText(
            "\u2014 Kein WSJT-X verbunden (Port 2237) \u2014\n\n"
            "WSJT-X starten f\u00fcr Live-Decodes.")
        self.lbl_tx_status.setText("RX \u2014 Warte auf WSJT-X\u2026")
        self.lbl_info.setText("WSJT-X starten f\u00fcr Live-Decodes (UDP Port 2237).")

    def _progress_tick(self):
        self._progress_value = min(15, self._progress_value + 1)
        self.progress_tx.setValue(self._progress_value)

    # ── Modus-Wechsel ─────────────────────────────────────────────────────────

    def _on_mode_changed(self, mode: str):
        self.decode_view.clear()
        if mode == "FT8":
            if self._live_mode:
                self.lbl_tx_status.setText(f"RX \u2014 WSJT-X Live ({mode})")
            else:
                self._show_no_wsjtx_hint()
        else:
            self.lbl_tx_status.setText(f"RX \u2014 {mode} noch nicht implementiert")
            self.decode_view.setPlainText(
                f"\u2014 {mode} ist in dieser Version noch nicht verf\u00fcgbar \u2014\n\n"
                "Wird in einem zuk\u00fcnftigen Update implementiert."
            )

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

        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["FT8", "FT4", "RTTY", "PSK31", "CW", "JS8Call", "OLIVIA"])
        self.combo_mode.setMinimumWidth(120)
        self._apply_combo_style()
        self.combo_mode.currentTextChanged.connect(self._on_mode_changed)
        header.addWidget(self.combo_mode)

        self.btn_close = QToolButton()
        self.btn_close.setFixedSize(28, 28)
        px = QPixmap()
        px.loadFromData(_CLOSE_SVG)
        self.btn_close.setIcon(QIcon(px))
        self.btn_close.setFocusPolicy(Qt.NoFocus)
        self.btn_close.setStyleSheet(
            f"QToolButton {{ background: transparent; border: none; padding: 2px; }}"
            f"QToolButton:hover {{ border: 1px solid {T['border_hover']}; border-radius: 3px; }}")
        self.btn_close.clicked.connect(self.close)
        header.addWidget(self.btn_close)

        root.addLayout(header)

        # ── Splitter ───────────────────────────────────────────────
        splitter = QSplitter(Qt.Vertical)

        # Decode-Liste
        decode_widget = QFrame()
        decode_layout = QVBoxLayout(decode_widget)
        decode_layout.setContentsMargins(0, 0, 0, 0)
        decode_layout.setSpacing(4)

        col_header = QHBoxLayout()
        for label, stretch in [("UTC", 2), ("dB", 1), ("DT", 1), ("Freq", 1), ("Message", 4)]:
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {T['text_muted']}; font-size: 10px; font-weight: bold; border: none;")
            col_header.addWidget(lbl, stretch=stretch)
        decode_layout.addLayout(col_header)

        self.decode_view = QTextEdit()
        self.decode_view.setReadOnly(True)
        self.decode_view.setFont(QFont("Consolas", 11))
        self.decode_view.setStyleSheet(self._decode_style())
        decode_layout.addWidget(self.decode_view)

        splitter.addWidget(decode_widget)

        # TX-Bereich
        tx_widget = QFrame()
        tx_layout = QVBoxLayout(tx_widget)
        tx_layout.setContentsMargins(0, 0, 0, 0)
        tx_layout.setSpacing(6)

        tx_status = QHBoxLayout()
        self.lbl_tx_status = QLabel("RX — Warte auf Decodes…")
        self.lbl_tx_status.setStyleSheet(f"color: {T['text_secondary']}; font-size: 12px; border: none;")
        tx_status.addWidget(self.lbl_tx_status)
        tx_status.addStretch()

        self.progress_tx = QProgressBar()
        self.progress_tx.setRange(0, 15)
        self.progress_tx.setValue(0)
        self.progress_tx.setFixedHeight(8)
        self.progress_tx.setFixedWidth(200)
        self.progress_tx.setTextVisible(False)
        self.progress_tx.setStyleSheet(self._progress_style())
        tx_status.addWidget(self.progress_tx)
        tx_layout.addLayout(tx_status)

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

        self.lbl_info = QLabel("WSJT-X starten f\u00fcr Live-Decodes (UDP Port 2237).")
        self.lbl_info.setStyleSheet(f"color: {T['text_muted']}; font-size: 11px; border: none;")
        self.lbl_info.setAlignment(Qt.AlignCenter)
        tx_layout.addWidget(self.lbl_info)

        splitter.addWidget(tx_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter)

        # Progress-Tick-Timer (1s)
        self._progress_timer = QTimer(self)
        self._progress_timer.timeout.connect(self._progress_tick)
        self._progress_value = 0
        self._progress_timer.start(1000)

    # ── Styles ────────────────────────────────────────────────────────────────

    def _btn_style(self):
        return (f"QPushButton {{ background-color: {T['bg_mid']}; color: {T['text']}; "
                f"border: 1px solid {T['border']}; border-radius: 4px; padding: 4px 12px; font-size: 12px; }} "
                f"QPushButton:hover {{ border-color: {T['border_hover']}; background-color: {T['bg_light']}; }} "
                f"QPushButton:disabled {{ color: {T['text_disabled']}; }}")

    def _decode_style(self):
        return (f"QTextEdit {{ background-color: {T['bg_mid']}; color: {T['text']}; "
                f"border: 1px solid {T['border']}; border-radius: 4px; }}")

    def _progress_style(self):
        return (f"QProgressBar {{ background-color: {T['bg_dark']}; border: 1px solid {T['border']}; border-radius: 3px; }}"
                f"QProgressBar::chunk {{ background-color: {T['accent']}; border-radius: 2px; }}")

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
        self.btn_close.setStyleSheet(
            f"QToolButton {{ background: transparent; border: none; padding: 2px; }}"
            f"QToolButton:hover {{ border: 1px solid {T['border_hover']}; border-radius: 3px; }}")
        self.decode_view.setStyleSheet(self._decode_style())
        self.progress_tx.setStyleSheet(self._progress_style())
