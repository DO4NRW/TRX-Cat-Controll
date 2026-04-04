import os
import json
import threading

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                                QPushButton, QComboBox, QApplication,
                                QStackedWidget, QLineEdit)
from PySide6.QtGui import QPainter, QColor
from PySide6.QtCore import QSize, QPoint, Qt, QEvent, QRect, QTimer, Signal

from core.theme import T, themed_icon, with_alpha
from core.session_logger import log_action, log_event, log_error
from ui._constants import _ICONS, _RIG_DIR
from ui._helpers import _scan_rigs_map, _list_serial_ports, _section_label, _combo, _card
from ui.toggle import ToggleButton, ToggleGroup


class RadioSetupOverlay(QWidget):

    _cat_result_sig    = Signal(bool)
    _ptt_result_sig    = Signal(bool)
    remote_connect_sig = Signal(str, int)   # (host, port) → main_window verbindet
    remote_disconnect_sig = Signal()        # → main_window trennt

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.hide()
        if parent:
            parent.installEventFilter(self)

        # ── Outer panel ──────────────────────────────────────────────
        self.panel = QWidget(self)
        self.panel.setFixedSize(860, 600)
        self.panel.setObjectName("panel")
        self._apply_panel_style()

        root = QVBoxLayout(self.panel)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(14)

        # ── Rig row: Hersteller + Modell + Buttons ─────────────────────
        self._rig_map = _scan_rigs_map()
        rig_row = QHBoxLayout()

        maker_lbl = QLabel("Hersteller:")
        maker_lbl.setStyleSheet(f"color: {T['text_muted']}; font-size: 13px; border: none;")
        rig_row.addWidget(maker_lbl)
        self.combo_manufacturer = _combo(sorted(self._rig_map.keys()))
        rig_row.addWidget(self.combo_manufacturer, stretch=1)

        model_lbl = QLabel("Modell:")
        model_lbl.setStyleSheet(f"color: {T['text_muted']}; font-size: 13px; border: none;")
        rig_row.addWidget(model_lbl)
        self.combo_model = _combo([])
        rig_row.addWidget(self.combo_model, stretch=1)

        # Kompatibilität: combo_rig gibt "Hersteller Modell" zurück
        class _RigProxy:
            """Proxy der combo_manufacturer + combo_model als 'Hersteller Modell' zusammenfasst."""
            def __init__(self, manufacturer, model):
                self._mfr = manufacturer
                self._mdl = model
            def currentText(self):
                m = self._mfr.currentText()
                d = self._mdl.currentText()
                return f"{m} {d}" if m and d else ""
            def setCurrentText(self, txt):
                parts = txt.split(" ", 1)
                if len(parts) == 2:
                    self._mfr.setCurrentText(parts[0])
                    self._mdl.setCurrentText(parts[1])
            def findText(self, txt):
                parts = txt.split(" ", 1)
                if len(parts) == 2:
                    return self._mfr.findText(parts[0])
                return -1
        self.combo_rig = _RigProxy(self.combo_manufacturer, self.combo_model)

        self.btn_save = QPushButton()
        self.btn_save.setFixedSize(40, 40)
        self.btn_save.setIcon(themed_icon(os.path.join(_ICONS, "save.svg")))
        self.btn_save.setIconSize(QSize(22, 22))
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setToolTip("Einstellungen speichern")
        self._update_btn_styles()
        self.btn_save.setStyleSheet(self._save_style_default)

        self.btn_test_cat = QPushButton()
        self.btn_test_cat.setFixedSize(40, 40)
        self.btn_test_cat.setIcon(themed_icon(os.path.join(_ICONS, "connection.svg")))
        self.btn_test_cat.setIconSize(QSize(22, 22))
        self.btn_test_cat.setCursor(Qt.PointingHandCursor)
        self.btn_test_cat.setToolTip("Test CAT")
        self.btn_test_cat.setStyleSheet(self._btn_style_grey)

        self.btn_test_ptt = QPushButton()
        self.btn_test_ptt.setFixedSize(40, 40)
        self.btn_test_ptt.setIcon(themed_icon(os.path.join(_ICONS, "bigtop.svg")))
        self.btn_test_ptt.setIconSize(QSize(22, 22))
        self.btn_test_ptt.setCursor(Qt.PointingHandCursor)
        self.btn_test_ptt.setToolTip("Test PTT")
        self.btn_test_ptt.setStyleSheet(self._btn_style_grey)

        rig_row.addWidget(self.btn_test_cat)
        rig_row.addWidget(self.btn_test_ptt)
        rig_row.addWidget(self.btn_save)
        root.addLayout(rig_row)

        # ── Two columns ───────────────────────────────────────────────
        cols = QHBoxLayout()
        cols.setSpacing(12)

        # ── LEFT: CAT Control card ────────────────────────────────────
        self._cat_card, cat_l = _card("CAT Control")

        # ── Tab-Leiste: Lokal / Remote ────────────────────────────
        self._cat_tab_buttons = []
        self._cat_current_tab = 0
        cat_tab_row = QHBoxLayout()
        cat_tab_row.setSpacing(0)
        for i, name in enumerate(["Lokal", "Remote"]):
            btn = QPushButton(name)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.clicked.connect(lambda checked, idx=i: self._switch_cat_tab(idx))
            cat_tab_row.addWidget(btn)
            self._cat_tab_buttons.append(btn)
        cat_tab_row.addStretch()
        cat_l.addLayout(cat_tab_row)
        self._apply_cat_tab_styles()

        self._cat_tab_stack = QStackedWidget()
        self._cat_tab_stack.setStyleSheet("background: transparent;")

        # ── TAB 0: Lokal ──────────────────────────────────────────
        _tab_lokal = QWidget()
        lokal_l = QVBoxLayout(_tab_lokal)
        lokal_l.setContentsMargins(0, 4, 0, 0)
        lokal_l.setSpacing(4)

        lokal_l.addWidget(_section_label("Serial Port:", "connection.svg"))
        self.combo_cat_port = _combo(_list_serial_ports())
        lokal_l.addWidget(self.combo_cat_port)

        lokal_l.addWidget(_section_label("Baud Rate:", "settings.svg"))
        self.combo_baud = _combo(["1200","2400","4800","9600","19200","38400","57600","115200"], "38400")
        lokal_l.addWidget(self.combo_baud)

        lokal_l.addWidget(_section_label("Data Bits", "build.svg"))
        self.tg_data_bits = ToggleGroup(["Default","Seven","Eight"], wrap_at=3)
        lokal_l.addWidget(self.tg_data_bits)

        lokal_l.addWidget(_section_label("Stop Bits", "build.svg"))
        self.tg_stop_bits = ToggleGroup(["Default","One","Two"], wrap_at=3)
        lokal_l.addWidget(self.tg_stop_bits)

        lokal_l.addWidget(_section_label("Handshake", "settings.svg"))
        self.tg_handshake = ToggleGroup(["Default","None","XON/XOFF","Hardware"], wrap_at=3)
        lokal_l.addWidget(self.tg_handshake)

        lokal_l.addStretch()
        self._cat_tab_stack.addWidget(_tab_lokal)

        # ── TAB 1: Remote ─────────────────────────────────────────
        _tab_remote = QWidget()
        remote_l = QVBoxLayout(_tab_remote)
        remote_l.setContentsMargins(0, 8, 0, 0)
        remote_l.setSpacing(8)

        remote_l.addWidget(_section_label("IP / URL (rigctld)", "connection.svg"))

        self.input_remote_host = QLineEdit()
        self.input_remote_host.setPlaceholderText("192.168.1.167  oder  192.168.1.167:4532")
        self.input_remote_host.setFocusPolicy(Qt.ClickFocus)
        self.input_remote_host.setStyleSheet(self._remote_input_style())
        self.input_remote_host.returnPressed.connect(self._on_remote_connect)
        remote_l.addWidget(self.input_remote_host)

        remote_btn_row = QHBoxLayout()
        remote_btn_row.setSpacing(8)

        self.btn_remote_connect = QPushButton("Verbinden")
        self.btn_remote_connect.setFixedHeight(34)
        self.btn_remote_connect.setFocusPolicy(Qt.NoFocus)
        self.btn_remote_connect.setStyleSheet(self._remote_btn_style())
        self.btn_remote_connect.clicked.connect(self._on_remote_connect)
        remote_btn_row.addWidget(self.btn_remote_connect)

        self.btn_remote_disconnect = QPushButton("Trennen")
        self.btn_remote_disconnect.setFixedHeight(34)
        self.btn_remote_disconnect.setFocusPolicy(Qt.NoFocus)
        self.btn_remote_disconnect.setStyleSheet(self._remote_btn_style())
        self.btn_remote_disconnect.clicked.connect(self._on_remote_disconnect)
        remote_btn_row.addWidget(self.btn_remote_disconnect)

        remote_l.addLayout(remote_btn_row)

        self.lbl_remote_status = QLabel("")
        self.lbl_remote_status.setStyleSheet(f"color: {T['text_muted']}; font-size: 11px; border: none;")
        self.lbl_remote_status.setWordWrap(True)
        remote_l.addWidget(self.lbl_remote_status)

        remote_l.addStretch()
        self._cat_tab_stack.addWidget(_tab_remote)

        cat_l.addWidget(self._cat_tab_stack)
        cols.addWidget(self._cat_card, stretch=1)

        # ── RIGHT: PTT / Mode card ──────────────────────────────────
        self._ptt_card = QWidget()
        self._ptt_card.setObjectName("pttCard")
        self._ptt_card.setStyleSheet(f"""
            QWidget#pttCard {{
                background-color: {with_alpha(T['bg_mid'], 220)};
                border: 1px solid {T['bg_light']};
                border-radius: 8px;
            }}
        """)
        ptt_l = QVBoxLayout(self._ptt_card)
        ptt_l.setContentsMargins(14, 12, 14, 14)
        ptt_l.setSpacing(10)

        ptt_header = QHBoxLayout()
        ptt_title = QLabel("PTT Method")
        ptt_title.setStyleSheet(f"color: {T['text']}; font-size: 13px; font-weight: bold; border: none;")
        ptt_header.addWidget(ptt_title)
        ptt_l.addLayout(ptt_header)

        self.tg_ptt_method = ToggleGroup(["VOX","DTR","CAT","RTS"], wrap_at=2)
        ptt_l.addWidget(self.tg_ptt_method)

        ptt_l.addWidget(_section_label("Port:", "connection.svg"))
        self.combo_ptt_port = _combo(_list_serial_ports())
        ptt_l.addWidget(self.combo_ptt_port)

        self.tg_ptt_invert = ToggleButton("PTT invertieren (+V)")
        ptt_l.addWidget(self.tg_ptt_invert)

        ptt_l.addWidget(_section_label("Mode", "radio.svg"))
        self.tg_mode = ToggleGroup(["None","USB","Data/Pkt"], wrap_at=3)
        ptt_l.addWidget(self.tg_mode)

        ptt_l.addWidget(_section_label("Split Operation", "settings.svg"))
        self.tg_split = ToggleGroup(["None","Rig","Fake It"], wrap_at=3)
        ptt_l.addWidget(self.tg_split)

        ptt_l.addStretch()

        cols.addWidget(self._ptt_card, stretch=1)
        root.addLayout(cols)

        # Erstes Modell laden
        if self.combo_manufacturer.count() > 0:
            first_maker = self.combo_manufacturer.currentText()
            models = self._rig_map.get(first_maker, [])
            self.combo_model.addItems(models)

        # Signals direkt verbinden
        self._connect_signals()

    # ── Remote-Tab Logik ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_remote_input(text: str) -> tuple[str, int]:
        """Parst '192.168.1.167' oder 'http://host:4532' → (host, port)."""
        text = text.strip()
        # http(s)-Präfix entfernen
        for prefix in ("https://", "http://"):
            if text.lower().startswith(prefix):
                text = text[len(prefix):]
        # host:port trennen
        if ":" in text:
            host, _, port_str = text.rpartition(":")
            try:
                return host.strip(), int(port_str.strip())
            except ValueError:
                pass
        return text, 4532

    def _on_remote_connect(self):
        raw = self.input_remote_host.text().strip()
        if not raw:
            self.lbl_remote_status.setText("Bitte IP-Adresse eingeben.")
            self.lbl_remote_status.setStyleSheet(f"color: {T['error']}; font-size: 11px; border: none;")
            return
        host, port = self._parse_remote_input(raw)
        self.lbl_remote_status.setText(f"Verbinde mit {host}:{port} …")
        self.lbl_remote_status.setStyleSheet(f"color: {T['text_muted']}; font-size: 11px; border: none;")
        self.remote_connect_sig.emit(host, port)

    def _on_remote_disconnect(self):
        self.lbl_remote_status.setText("")
        self.remote_disconnect_sig.emit()

    def set_remote_status(self, ok: bool, message: str):
        """Wird aus main_window nach Connect-Versuch aufgerufen."""
        color = T['accent'] if ok else T['error']
        self.lbl_remote_status.setText(message)
        self.lbl_remote_status.setStyleSheet(f"color: {color}; font-size: 11px; border: none;")

    def _remote_input_style(self) -> str:
        return (f"QLineEdit {{ background-color: {T['bg_mid']}; color: {T['text']}; "
                f"border: 1px solid {T['border']}; border-radius: 4px; "
                f"padding: 6px 10px; font-size: 13px; }}"
                f"QLineEdit:focus {{ border-color: {T['accent']}; }}")

    def _remote_btn_style(self) -> str:
        return (f"QPushButton {{ background-color: {T['bg_mid']}; color: {T['text']}; "
                f"border: 1px solid {T['border']}; border-radius: 4px; padding: 4px 14px; font-size: 12px; }} "
                f"QPushButton:hover {{ border-color: {T['border_hover']}; background-color: {T['bg_light']}; }}")

    # ── CAT-Tab-System ────────────────────────────────────────────────────────

    def _switch_cat_tab(self, idx: int):
        self._cat_current_tab = idx
        self._cat_tab_stack.setCurrentIndex(idx)
        self._apply_cat_tab_styles()

    def _apply_cat_tab_styles(self):
        """Tab-Buttons der CAT-Card stylen — aktiver Tab hervorgehoben."""
        for i, btn in enumerate(self._cat_tab_buttons):
            if i == self._cat_current_tab:
                btn.setStyleSheet(f"""
                    QPushButton {{ background: {T['bg_mid']}; color: {T['text']};
                        border: 1px solid {T['border']}; border-bottom: none;
                        border-radius: 6px 6px 0 0; padding: 4px 12px;
                        font-size: 11px; font-weight: bold; }}""")
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{ background: transparent; color: {T['text_muted']};
                        border: none; border-bottom: 1px solid {T['border']};
                        border-radius: 0; padding: 4px 12px; font-size: 11px; }}
                    QPushButton:hover {{ color: {T['text']}; }}""")

    def _apply_panel_style(self):
        self.panel.setStyleSheet(f"""
            QWidget#panel {{
                background-color: {T['bg_dark']};
                border: 1px solid {T['border']};
                border-radius: 12px;
            }}
        """)

    def _update_btn_styles(self):
        self._btn_style_grey = f"""
            QPushButton {{
                background-color: {T['bg_mid']};
                border: 2px solid {T['border']};
                border-radius: 5px;
                padding: 5px;
            }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['border_hover']}; }}
        """
        self._btn_style_ok = f"""
            QPushButton {{
                background-color: {T['bg_mid']};
                border: 2px solid {T['accent']};
                border-radius: 5px;
                padding: 5px;
            }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['accent']}; }}
        """
        self._btn_style_err = f"""
            QPushButton {{
                background-color: {T['bg_mid']};
                border: 2px solid {T['error']};
                border-radius: 5px;
                padding: 5px;
            }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['error']}; }}
        """
        self._save_style_default = self._btn_style_grey
        self._save_style_ok      = self._btn_style_ok
        self._save_style_error   = self._btn_style_err
        self._cat_style_grey = self._btn_style_grey
        self._cat_style_ok   = self._btn_style_ok
        self._cat_style_err  = self._btn_style_err
        self._ptt_style_grey = self._btn_style_grey
        self._ptt_style_ok   = self._btn_style_ok
        self._ptt_style_err  = self._btn_style_err

    def _connect_signals(self):
        self.btn_save.clicked.connect(self.save_to_config)
        self.combo_manufacturer.currentTextChanged.connect(self._on_manufacturer_changed)
        self.combo_model.currentTextChanged.connect(lambda _: self.load_from_config())
        self.btn_test_cat.clicked.connect(self._test_cat)
        self.btn_test_ptt.clicked.connect(self._test_ptt)
        self._cat_result_sig.connect(self._cat_result)
        self._ptt_result_sig.connect(self._ptt_result)

    def _on_manufacturer_changed(self, manufacturer):
        """Modell-Dropdown updaten wenn Hersteller wechselt."""
        self.combo_model.blockSignals(True)
        self.combo_model.clear()
        models = self._rig_map.get(manufacturer, [])
        self.combo_model.addItems(models)
        self.combo_model.blockSignals(False)
        if models:
            self.load_from_config()

    # ── Test CAT ──────────────────────────────────────────────────────

    def _test_cat(self):
        port = self.combo_cat_port.currentText()
        baud = int(self.combo_baud.currentText())
        manufacturer = self.combo_manufacturer.currentText().lower()
        protocol_map = {"yaesu": "yaesu", "icom": "icom", "kenwood": "kenwood", "elecraft": "kenwood"}
        protocol = protocol_map.get(manufacturer, "yaesu")
        model_key = self.combo_model.currentText().lower().replace("-", "") if hasattr(self, "combo_model") else ""
        self.btn_test_cat.setEnabled(False)

        def run():
            ok = False
            try:
                from core.cat import create_cat_handler
                kwargs = {"port": port, "baud": baud, "timeout": 1.0}
                if protocol == "icom":
                    from core.cat.icom import RIG_ADDRESSES
                    kwargs["civ_address"] = RIG_ADDRESSES.get(model_key, 0x94)
                handler = create_cat_handler(protocol, **kwargs)
                if handler.connect():
                    freq = handler.get_frequency()
                    ok = freq is not None
                    handler.disconnect()
            except Exception:
                pass
            self._cat_result_sig.emit(ok)

        threading.Thread(target=run, daemon=True).start()

    def _cat_result(self, ok: bool):
        self.btn_test_cat.setStyleSheet(self._cat_style_ok if ok else self._cat_style_err)
        self.btn_test_cat.setEnabled(True)
        QTimer.singleShot(3000, lambda: self.btn_test_cat.setStyleSheet(self._cat_style_grey))

    # ── Test PTT ──────────────────────────────────────────────────────

    def _test_ptt(self):
        cat_port = self.combo_cat_port.currentText()
        cat_baud = int(self.combo_baud.currentText())
        ptt_port = self.combo_ptt_port.currentText()
        method = (self.tg_ptt_method.value() or "CAT").upper()
        invert = self.tg_ptt_invert.isChecked()
        self.btn_test_ptt.setEnabled(False)

        def run():
            ok = False
            try:
                import serial, time
                if method == "CAT":
                    with serial.Serial(cat_port, cat_baud, timeout=0.5,
                                       rtscts=False, dsrdtr=False) as s:
                        s.write(b"TX0;")
                        time.sleep(0.5)
                        s.write(b"RX;")
                        time.sleep(0.1)
                        ok = True
                else:
                    with serial.Serial(ptt_port, 38400, timeout=0.5,
                                       rtscts=False, dsrdtr=False) as s:
                        safe = invert
                        s.setRTS(safe)
                        s.setDTR(safe)
                        time.sleep(0.05)
                        if method == "RTS":
                            s.setRTS(not safe)
                            time.sleep(0.3)
                            s.setRTS(safe)
                        elif method == "DTR":
                            s.setDTR(not safe)
                            time.sleep(0.3)
                            s.setDTR(safe)
                        ok = True
            except Exception as e:
                print(f"Test PTT Fehler: {e}")
            self._ptt_result_sig.emit(ok)

        threading.Thread(target=run, daemon=True).start()

    def _ptt_result(self, ok: bool):
        self.btn_test_ptt.setStyleSheet(self._ptt_style_ok if ok else self._ptt_style_err)
        self.btn_test_ptt.setEnabled(True)
        QTimer.singleShot(3000, lambda: self.btn_test_ptt.setStyleSheet(self._ptt_style_grey))

    # ── Overlay mechanics ─────────────────────────────────────────────

    def _refresh_styles(self):
        """Alle Styles dynamisch aus T holen."""
        self._apply_panel_style()
        self._update_btn_styles()
        self.btn_save.setStyleSheet(self._save_style_default)
        self.btn_test_cat.setStyleSheet(self._btn_style_grey)
        self.btn_test_ptt.setStyleSheet(self._btn_style_grey)
        self.btn_save.setIcon(themed_icon(os.path.join(_ICONS, "save.svg")))
        self.btn_test_cat.setIcon(themed_icon(os.path.join(_ICONS, "connection.svg")))
        self.btn_test_ptt.setIcon(themed_icon(os.path.join(_ICONS, "bigtop.svg")))

        _combo_style = f"""
            QComboBox {{
                background-color: {T['bg_mid']}; color: {T['text_secondary']};
                border: 1px solid {T['border']}; border-radius: 5px;
                padding: 4px 10px; font-size: 13px; min-height: 28px;
            }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox QAbstractItemView {{
                background-color: {T['bg_mid']}; color: {T['text_secondary']};
                selection-background-color: {T['bg_light']}; border: 1px solid {T['border']};
            }}"""
        if hasattr(self, '_cat_tab_buttons'):
            self._apply_cat_tab_styles()
        if hasattr(self, 'input_remote_host'):
            self.input_remote_host.setStyleSheet(self._remote_input_style())
            self.btn_remote_connect.setStyleSheet(self._remote_btn_style())
            self.btn_remote_disconnect.setStyleSheet(self._remote_btn_style())
        self._cat_card.setObjectName("catCard")
        self._ptt_card.setObjectName("pttCard")
        _card_style_cat = f"""
            QWidget#catCard {{
                background-color: {with_alpha(T['bg_mid'], 220)};
                border: 1px solid {T['bg_light']}; border-radius: 8px;
            }}"""
        _card_style_ptt = f"""
            QWidget#pttCard {{
                background-color: {with_alpha(T['bg_mid'], 220)};
                border: 1px solid {T['bg_light']}; border-radius: 8px;
            }}"""
        self._cat_card.setStyleSheet(_card_style_cat)
        self._ptt_card.setStyleSheet(_card_style_ptt)
        for cb in self.panel.findChildren(QComboBox):
            cb.setStyleSheet(_combo_style)
        for lbl in self.panel.findChildren(QLabel):
            txt = lbl.text()
            if lbl.pixmap() and not lbl.pixmap().isNull():
                continue
            if any(k in txt for k in ["CAT", "PTT", "Rig"]):
                lbl.setStyleSheet(f"color: {T['text']}; font-size: 13px; font-weight: bold; border: none;")
            else:
                lbl.setStyleSheet(f"color: {T['text_secondary']}; font-size: 12px; font-weight: bold; border: none;")
        for tb in self.panel.findChildren(ToggleButton):
            tb._load_icons()
            tb._update_icon(tb.isChecked())
            tb._apply_style()

    def show_overlay(self):
        self._refresh_styles()
        self._refit()
        self.load_from_config()
        self.show()
        self.raise_()
        QApplication.instance().installEventFilter(self)

    def hide(self):
        QApplication.instance().removeEventFilter(self)
        super().hide()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            global_pos = event.globalPosition().toPoint()
            panel_rect = QRect(self.panel.mapToGlobal(QPoint(0, 0)), self.panel.size())
            if not panel_rect.contains(global_pos):
                widget_at = QApplication.widgetAt(global_pos)
                if widget_at is not None:
                    parent = widget_at
                    while parent is not None:
                        if parent is self.panel:
                            return False
                        parent = parent.parent()
                    top = widget_at.window()
                    if top is not None and top is not self.parent().window():
                        return False
                self.hide()
        elif event.type() == QEvent.Type.Resize and obj is self.parent() and self.isVisible():
            self._refit()
        return False

    def _refit(self):
        parent = self.parent()
        self.setGeometry(parent.rect())
        pw = min(860, int(parent.width() * 0.88))
        ph = min(600, int(parent.height() * 0.88))
        self.panel.setFixedSize(pw, ph)
        self.panel.move((self.width() - pw) // 2, (self.height() - ph) // 2)

    # ── Config ───────────────────────────────────────────────────────

    _DATA_BITS_MAP  = {"Default": 8, "Seven": 7, "Eight": 8}
    _STOP_BITS_MAP  = {"Default": 1, "One": 1, "Two": 2}
    _DATA_BITS_INV  = {8: "Eight", 7: "Seven"}
    _STOP_BITS_INV  = {1: "One",   2: "Two"}

    def _config_path(self) -> str:
        """Config-Pfad dynamisch aus Rig-Name ableiten."""
        rig_name = self.combo_rig.currentText()
        parts = rig_name.split(" ", 1)
        if len(parts) != 2:
            return ""
        maker = parts[0].lower()
        model = parts[1].lower().replace("-", "")
        return os.path.join(_RIG_DIR, maker, model, "config.json")

    def load_from_config(self):
        """Load values from rig config.json into GUI widgets."""
        path = self._config_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r") as f:
                cfg = json.load(f)
        except Exception:
            return

        cat = cfg.get("cat", {})
        ptt = cfg.get("ptt", {})
        rig = cfg.get("rig", {})

        port = cat.get("port", "")
        if port and self.combo_cat_port.findText(port) == -1:
            self.combo_cat_port.insertItem(0, port)
        self.combo_cat_port.setCurrentText(port)

        baud = str(cat.get("baud", "38400"))
        self.combo_baud.setCurrentText(baud)

        db_raw = cat.get("data_bits")
        self.tg_data_bits.set_value(self._DATA_BITS_INV.get(db_raw) if db_raw is not None else None)

        sb_raw = cat.get("stop_bits")
        self.tg_stop_bits.set_value(self._STOP_BITS_INV.get(sb_raw) if sb_raw is not None else None)

        self.tg_handshake.set_value(cat.get("handshake"))
        self.tg_ptt_method.set_value(ptt.get("method"))

        ptt_port = ptt.get("port", "")
        if ptt_port and self.combo_ptt_port.findText(ptt_port) == -1:
            self.combo_ptt_port.insertItem(0, ptt_port)
        self.combo_ptt_port.setCurrentText(ptt_port)

        self.tg_ptt_invert.setChecked(bool(ptt.get("invert", False)))
        self.tg_mode.set_value(rig.get("mode", ""))
        self.tg_split.set_value(rig.get("split", ""))

    def save_to_config(self):
        """Write GUI values to config.json."""
        path = self._config_path()
        ok = False
        try:
            cfg = {}
            if os.path.exists(path):
                with open(path, "r") as f:
                    cfg = json.load(f)
            cfg.setdefault("cat", {})
            cfg.setdefault("ptt", {})
            cfg.setdefault("rig", {})

            wanted = {
                "cat_port":      self.combo_cat_port.currentText(),
                "cat_baud":      int(self.combo_baud.currentText()),
                "cat_data_bits": self._DATA_BITS_MAP.get(self.tg_data_bits.value()),
                "cat_stop_bits": self._STOP_BITS_MAP.get(self.tg_stop_bits.value()),
                "cat_handshake": self.tg_handshake.value(),
                "ptt_method":    self.tg_ptt_method.value(),
                "ptt_port":      self.combo_ptt_port.currentText(),
                "ptt_invert":    self.tg_ptt_invert.isChecked(),
                "rig_mode":      self.tg_mode.value(),
                "rig_split":     self.tg_split.value(),
            }

            cfg["cat"]["port"]      = wanted["cat_port"]
            cfg["cat"]["baud"]      = wanted["cat_baud"]
            cfg["cat"]["data_bits"] = wanted["cat_data_bits"]
            cfg["cat"]["stop_bits"] = wanted["cat_stop_bits"]
            cfg["cat"]["handshake"] = wanted["cat_handshake"]
            cfg["ptt"]["method"]    = wanted["ptt_method"]
            cfg["ptt"]["port"]      = wanted["ptt_port"]
            cfg["ptt"]["invert"]    = wanted["ptt_invert"]
            cfg["rig"]["mode"]      = wanted["rig_mode"]
            cfg["rig"]["split"]     = wanted["rig_split"]

            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(cfg, f, indent=4)

            with open(path, "r") as f:
                check = json.load(f)

            ok = (
                check["cat"]["port"]      == wanted["cat_port"]      and
                check["cat"]["baud"]      == wanted["cat_baud"]      and
                check["cat"]["data_bits"] == wanted["cat_data_bits"] and
                check["cat"]["stop_bits"] == wanted["cat_stop_bits"] and
                check["cat"]["handshake"] == wanted["cat_handshake"] and
                check["ptt"]["method"]    == wanted["ptt_method"]    and
                check["ptt"]["port"]      == wanted["ptt_port"]      and
                check["ptt"]["invert"]    == wanted["ptt_invert"]
            )

        except Exception as e:
            print(f"Speichern fehlgeschlagen: {e}")
            ok = False

        style = self._save_style_ok if ok else self._save_style_error
        self.btn_save.setStyleSheet(style)
        QTimer.singleShot(2000, lambda: self.btn_save.setStyleSheet(self._save_style_default))

        if ok:
            main_win = self.parent().window() if self.parent() else None
            if main_win and hasattr(main_win, "combo_rig_select"):
                new_rig = self.combo_rig.currentText()
                if hasattr(main_win, "_add_configured_rig"):
                    main_win._add_configured_rig(new_rig)
                if main_win.combo_rig_select.currentText() != new_rig:
                    main_win.combo_rig_select.setCurrentText(new_rig)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))

    def resizeEvent(self, event):
        super().resizeEvent(event)
