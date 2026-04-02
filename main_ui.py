import sys
import os
from PySide6.QtWidgets import (QLabel, QApplication, QMainWindow, QPushButton,
                             QWidget, QVBoxLayout, QHBoxLayout, QMenu, QProxyStyle,
                             QStyle, QComboBox, QFrame, QScrollArea, QButtonGroup,
                             QGridLayout, QProgressBar, QLineEdit, QSlider,
                             QColorDialog)
from PySide6.QtGui import QIcon, QAction, QPainter, QColor, QPalette
from PySide6.QtCore import QSize, QPoint, Qt, QEvent, QRect, QTimer, QThread, Signal
import json
import threading

from core.theme import T, load_theme, save_theme, apply_theme, hex_to_rgba, rgba_to_hex, \
    rgba_parts, with_alpha, PRESETS, PRESET_NAMES, register_refresh, unregister_refresh, \
    detect_preset, get_last_theme, themed_icon, \
    load_user_themes, save_user_theme, delete_user_theme, is_builtin_preset
from core.session_logger import log_action, log_event, log_error

_ICONS = os.path.join(os.path.dirname(__file__), "assets", "icons")
_RIG_DIR = os.path.join(os.path.dirname(__file__), "rig")


def _scan_rigs():
    """Scanne rig/ Ordner → flat list 'Hersteller Modell' (Kompatibilität)."""
    rig_map = _scan_rigs_map()
    rigs = []
    for maker, models in rig_map.items():
        for model in models:
            rigs.append(f"{maker} {model}")
    return rigs or ["(kein Rig gefunden)"]


def _scan_rigs_map():
    """Scanne rig/ Ordner → Dict: {'Yaesu': ['FT-991A'], 'Icom': ['IC-7300']}."""
    rig_map = {}
    if not os.path.isdir(_RIG_DIR):
        return rig_map
    for maker in sorted(os.listdir(_RIG_DIR)):
        maker_path = os.path.join(_RIG_DIR, maker)
        if not os.path.isdir(maker_path) or maker.startswith(("_", ".")):
            continue
        models = []
        for model in sorted(os.listdir(maker_path)):
            model_path = os.path.join(maker_path, model)
            if not os.path.isdir(model_path) or model.startswith(("_", ".")):
                continue
            if os.path.exists(os.path.join(model_path, "config.json")):
                display = model.upper().replace("FT", "FT-").replace("IC", "IC-").replace("TS", "TS-")
                models.append(display)
        if models:
            rig_map[maker.capitalize()] = models
    return rig_map


def _list_serial_ports():
    """Return only relevant serial ports for the current OS."""
    try:
        from serial.tools import list_ports
        import platform
        all_ports = [p.device for p in list_ports.comports()]
        os_name = platform.system()
        if os_name == "Linux":
            return [p for p in all_ports if "ttyUSB" in p or "ttyACM" in p] or ["(keine gefunden)"]
        elif os_name == "Darwin":
            return [p for p in all_ports if "cu." in p] or ["(keine gefunden)"]
        else:  # Windows
            return all_ports or ["COM1"]
    except Exception:
        return ["(pyserial fehlt)"]


# =====================================================================
# BLOCK: TOGGLE BUTTON & GROUP
# =====================================================================

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

# =====================================================================
# END OF BLOCK
# =====================================================================


# =====================================================================
# BLOCK: RADIO SETUP OVERLAY (Web-style modal popup)
# =====================================================================

def _section_label(text, icon=None):
    """Section label with optional icon left of the text."""
    row = QWidget()
    row.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 4, 0, 0)
    layout.setSpacing(6)
    if icon:
        ico = QLabel()
        ico.setPixmap(themed_icon(os.path.join(_ICONS, icon)).pixmap(QSize(14, 14)))
        ico.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(ico)
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {T['text_secondary']}; font-size: 12px; font-weight: bold; border: none;")
    layout.addWidget(lbl)
    layout.addStretch()
    return row


def _combo(values, current=""):
    cb = QComboBox()
    cb.addItems(values)
    if current and current in values:
        cb.setCurrentText(current)
    cb.setStyleSheet(f"""
        QComboBox {{
            background-color: {T['bg_mid']};
            color: {T['text_secondary']};
            border: 1px solid {T['border']};
            border-radius: 5px;
            padding: 4px 10px;
            font-size: 13px;
            min-height: 28px;
        }}
        QComboBox::drop-down {{ border: none; width: 24px; }}
        QComboBox QAbstractItemView {{
            background-color: {T['bg_mid']};
            color: {T['text_secondary']};
            selection-background-color: {T['bg_light']};
            border: 1px solid {T['border']};
        }}
    """)
    return cb


_card_counter = 0
def _card(title):
    """Returns (card_widget, inner_layout) — a bordered card with a bold title."""
    global _card_counter
    _card_counter += 1
    card = QWidget()
    obj_name = f"card_{_card_counter}"
    card.setObjectName(obj_name)
    card.setStyleSheet(f"""
        QWidget#{obj_name} {{
            background-color: {with_alpha(T['bg_mid'], 220)};
            border: 1px solid {T['bg_light']};
            border-radius: 8px;
        }}
    """)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 14)
    layout.setSpacing(10)
    hdr = QLabel(title)
    hdr.setStyleSheet(f"color: {T['text']}; font-size: 13px; font-weight: bold; border: none;")
    hdr.setAlignment(Qt.AlignCenter)
    layout.addWidget(hdr)
    return card, layout


class RadioSetupOverlay(QWidget):

    _cat_result_sig = Signal(bool)
    _ptt_result_sig = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.hide()
        if parent:
            parent.installEventFilter(self)
        # Connect save + rig change after widgets are built (deferred)

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

        cat_l.addWidget(_section_label("Serial Port:", "connection.svg"))
        self.combo_cat_port = _combo(_list_serial_ports())
        cat_l.addWidget(self.combo_cat_port)

        cat_l.addWidget(_section_label("Baud Rate:", "settings.svg"))
        self.combo_baud = _combo(["1200","2400","4800","9600","19200","38400","57600","115200"], "38400")
        cat_l.addWidget(self.combo_baud)

        cat_l.addWidget(_section_label("Data Bits", "build.svg"))
        self.tg_data_bits = ToggleGroup(["Default","Seven","Eight"], wrap_at=3)
        cat_l.addWidget(self.tg_data_bits)

        cat_l.addWidget(_section_label("Stop Bits", "build.svg"))
        self.tg_stop_bits = ToggleGroup(["Default","One","Two"], wrap_at=3)
        cat_l.addWidget(self.tg_stop_bits)

        cat_l.addWidget(_section_label("Handshake", "settings.svg"))
        self.tg_handshake = ToggleGroup(["Default","None","XON/XOFF","Hardware"], wrap_at=3)
        cat_l.addWidget(self.tg_handshake)

        cat_l.addStretch()
        cols.addWidget(self._cat_card, stretch=1)

        # ── RIGHT: PTT / Mode card (custom header with test buttons) ──
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

        # Header
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

        # Signals direkt verbinden — alle Widgets existieren jetzt
        self._connect_signals()

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
        # Protokoll aus aktuell gewähltem Rig lesen
        manufacturer = self.combo_manufacturer.currentText().lower()
        protocol_map = {"yaesu": "yaesu", "icom": "icom", "kenwood": "kenwood", "elecraft": "kenwood"}
        protocol = protocol_map.get(manufacturer, "yaesu")
        # Modell für Icom CI-V Adresse
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
                    # PTT via CAT: TX0; auf dem CAT-Port, RX; zum Loslassen
                    with serial.Serial(cat_port, cat_baud, timeout=0.5,
                                       rtscts=False, dsrdtr=False) as s:
                        s.write(b"TX0;")
                        time.sleep(0.5)
                        s.write(b"RX;")
                        time.sleep(0.1)
                        ok = True
                else:
                    # PTT via RTS/DTR auf dem PTT-Port
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
        """Alle Styles dynamisch aus T holen — kein doppelter Code."""
        self._apply_panel_style()
        self._update_btn_styles()
        self.btn_save.setStyleSheet(self._save_style_default)
        self.btn_test_cat.setStyleSheet(self._btn_style_grey)
        self.btn_test_ptt.setStyleSheet(self._btn_style_grey)
        self.btn_save.setIcon(themed_icon(os.path.join(_ICONS, "save.svg")))
        self.btn_test_cat.setIcon(themed_icon(os.path.join(_ICONS, "connection.svg")))
        self.btn_test_ptt.setIcon(themed_icon(os.path.join(_ICONS, "bigtop.svg")))

        # Alle Labels, Combos, Cards dynamisch aus T refreshen
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
                continue  # Icon-Labels nicht anfassen
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
                # Prüfe ob Click auf ein Popup/Dropdown geht
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

    # ── Config: Rig → Pfad ───────────────────────────────────────────

    _DATA_BITS_MAP  = {"Default": 8, "Seven": 7, "Eight": 8}
    _STOP_BITS_MAP  = {"Default": 1, "One": 1, "Two": 2}
    _DATA_BITS_INV  = {8: "Eight", 7: "Seven"}
    _STOP_BITS_INV  = {1: "One",   2: "Two"}

    def _config_path(self) -> str:
        """Config-Pfad dynamisch aus Rig-Name ableiten: 'Yaesu FT-991A' → rig/yaesu/ft991a/config.json"""
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

        # CAT port
        port = cat.get("port", "")
        if port and self.combo_cat_port.findText(port) == -1:
            self.combo_cat_port.insertItem(0, port)
        self.combo_cat_port.setCurrentText(port)

        # Baud
        baud = str(cat.get("baud", "38400"))
        self.combo_baud.setCurrentText(baud)

        # Data bits — None in config → alle Toggles aus
        db_raw = cat.get("data_bits")
        self.tg_data_bits.set_value(self._DATA_BITS_INV.get(db_raw) if db_raw is not None else None)

        # Stop bits — None in config → alle Toggles aus
        sb_raw = cat.get("stop_bits")
        self.tg_stop_bits.set_value(self._STOP_BITS_INV.get(sb_raw) if sb_raw is not None else None)

        # Handshake — None in config → alle Toggles aus
        self.tg_handshake.set_value(cat.get("handshake"))

        # PTT method — None in config → alle Toggles aus
        self.tg_ptt_method.set_value(ptt.get("method"))

        # PTT port
        ptt_port = ptt.get("port", "")
        if ptt_port and self.combo_ptt_port.findText(ptt_port) == -1:
            self.combo_ptt_port.insertItem(0, ptt_port)
        self.combo_ptt_port.setCurrentText(ptt_port)

        # PTT invert
        self.tg_ptt_invert.setChecked(bool(ptt.get("invert", False)))

        # Mode
        self.tg_mode.set_value(rig.get("mode", ""))

        # Split
        self.tg_split.set_value(rig.get("split", ""))

    def save_to_config(self):
        """Write GUI values to config.json, read back and verify before showing result."""
        path = self._config_path()
        ok = False
        try:
            # ── Build dict from GUI ──────────────────────────────────
            cfg = {}
            if os.path.exists(path):
                with open(path, "r") as f:
                    cfg = json.load(f)
            cfg.setdefault("cat", {})
            cfg.setdefault("ptt", {})
            cfg.setdefault("rig", {})

            # None wenn kein Toggle aktiv — wird als JSON null gespeichert
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

            # ── Write ────────────────────────────────────────────────
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(cfg, f, indent=4)

            # ── Verify: read back and compare ────────────────────────
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

        # Top-Bar Combo synchronisieren + Rig als konfiguriert markieren
        if ok:
            main_win = self.parent().window() if self.parent() else None
            if main_win and hasattr(main_win, "combo_rig_select"):
                new_rig = self.combo_rig.currentText()
                # Rig zur configured_rigs Liste hinzufügen
                if hasattr(main_win, "_add_configured_rig"):
                    main_win._add_configured_rig(new_rig)
                if main_win.combo_rig_select.currentText() != new_rig:
                    main_win.combo_rig_select.setCurrentText(new_rig)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))

    def resizeEvent(self, event):
        super().resizeEvent(event)

# =====================================================================
# BLOCK: AUDIO SETUP OVERLAY
# =====================================================================

def _pw_node_info(node_id):
    """Hole nick, bus-type und node.name für eine PipeWire Node-ID."""
    import subprocess, re
    nick = None
    node_name = None
    is_usb = False
    try:
        out = subprocess.run(
            ["pw-cli", "info", str(node_id)],
            capture_output=True, text=True, timeout=2
        ).stdout
        for line in out.splitlines():
            if "node.nick" in line or "device.nick" in line:
                m = re.search(r'"(.+?)"', line)
                if m and nick is None:
                    nick = m.group(1)
            if "node.name" in line and "node.nick" not in line:
                m = re.search(r'"(.+?)"', line)
                if m and node_name is None:
                    node_name = m.group(1)
            if "device.bus" in line and '"usb"' in line:
                is_usb = True
            if "api.alsa.card.name" in line and "usb" in line.lower():
                is_usb = True
    except Exception:
        pass
    return nick, is_usb, node_name


def _list_audio_devices_linux(kind="all", bus="all"):
    """Linux: PipeWire/PulseAudio Geräte via wpctl auslesen.
    bus='pc' → nur interne Geräte, bus='usb' → nur USB-Geräte, bus='all' → alle."""
    import subprocess, re
    result = []

    try:
        out = subprocess.run(["wpctl", "status"], capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return []

    if not out or "Audio" not in out:
        return []

    in_audio = False
    in_sinks = False
    in_sources = False

    for line in out.splitlines():
        if line.strip() == "Audio":
            in_audio = True; continue
        if line.strip() == "Video":
            in_audio = False; continue
        if not in_audio:
            continue

        clean = line.replace("│", "").strip()
        if "Sinks:" in clean and "endpoint" not in clean.lower():
            in_sinks = True; in_sources = False; continue
        elif "Sources:" in clean and "endpoint" not in clean.lower():
            in_sources = True; in_sinks = False; continue
        elif "endpoints:" in clean.lower() or "Streams:" in clean or "Devices:" in clean:
            in_sinks = False; in_sources = False; continue

        if not (in_sinks or in_sources):
            continue

        m = re.search(r"\*?\s*(\d+)\.\s+(.+?)(?:\s+\[vol:.*)?$", clean)
        if not m:
            continue
        dev_id = int(m.group(1))
        dev_name = m.group(2).strip()

        # Bus-Filter: pc = nur interne, usb = nur USB
        _, is_usb, node_name = _pw_node_info(dev_id)
        if bus != "all":
            if bus == "pc" and is_usb:
                continue
            if bus == "usb" and not is_usb:
                continue

        if in_sinks and kind in ("output", "all"):
            result.append((node_name or str(dev_id), dev_name, "out"))
        elif in_sources and kind in ("input", "all"):
            result.append((node_name or str(dev_id), dev_name, "in"))

    # Bei "all": gleiche Namen mit Richtung kennzeichnen
    name_count = {}
    for _, name, _ in result:
        name_count[name] = name_count.get(name, 0) + 1

    formatted = []
    for pw_name, name, direction in result:
        # Anzeige kürzen: "Analoges Stereo", "Digital Stereo" etc. entfernen
        display = re.sub(r"\s*(Analoges|Digital)\s*Stereo\s*", "", name).strip()
        formatted.append((display, f"[pw:{pw_name}] {name}"))

    return formatted


def _list_audio_devices(kind="all", bus="all"):
    """Return device strings, platform-aware.
    Linux: PipeWire/PulseAudio, Windows: WASAPI, macOS: CoreAudio.
    bus='pc' → nur interne, bus='usb' → nur USB, bus='all' → alle."""
    import platform
    os_name = platform.system()

    # ── Linux: PipeWire/PulseAudio bevorzugen ─────────────────────
    if os_name == "Linux":
        pw_devs = _list_audio_devices_linux(kind, bus)
        if pw_devs:
            return pw_devs

    # ── Fallback / Windows / macOS: sounddevice ───────────────────
    try:
        import sounddevice as sd
        devs_raw = sd.query_devices()
        hostapis = sd.query_hostapis()

        preferred = None
        for i, h in enumerate(hostapis):
            name = h["name"].lower()
            if os_name == "Windows" and "wasapi" in name:
                preferred = i; break
            elif os_name == "Darwin" and "core" in name:
                preferred = i; break
            elif os_name == "Linux" and "pulse" in name:
                preferred = i; break
        if preferred is None and os_name == "Linux":
            for i, h in enumerate(hostapis):
                if "alsa" in h["name"].lower():
                    preferred = i; break

        _BLACKLIST = ("midi", "through", "timer", "sequencer")

        # Windows Whitelist
        _MIC_HINTS = ("mikrofon", "microphone", "mic", "input", "capture",
                       "aufnahme", "recording", "line in", "scarlett", "codec",
                       "usb audio", "audio codec")
        _SPK_HINTS = ("lautsprecher", "speaker", "headphone", "kopfhörer",
                       "output", "playback", "wiedergabe", "realtek", "scarlett",
                       "codec", "usb audio", "audio codec", "headset",
                       "hdmi", "displayport", "spdif", "optical", "digital",
                       "monitor", "tv", "receiver")

        result = []
        for i, d in enumerate(devs_raw):
            if preferred is not None and d["hostapi"] != preferred:
                continue
            if kind == "input"  and d["max_input_channels"]  < 1: continue
            if kind == "output" and d["max_output_channels"] < 1: continue
            dname = d["name"].lower()
            if any(bl in dname for bl in _BLACKLIST):
                continue
            result.append((i, d["name"], dname))

        # Windows: zusätzlich Whitelist-Filter
        if os_name == "Windows":
            if kind == "input":
                filtered = [(i, n) for i, n, nl in result
                            if any(h in nl for h in _MIC_HINTS)]
            elif kind == "output":
                filtered = [(i, n) for i, n, nl in result
                            if any(h in nl for h in _SPK_HINTS)]
            else:
                filtered = [(i, n) for i, n, _ in result]
            if not filtered:
                filtered = [(i, n) for i, n, _ in result]
        else:
            filtered = [(i, n) for i, n, _ in result]

        formatted = [f"[{i}] {n}" for i, n in filtered]
        return formatted or ["(keine gefunden)"]
    except Exception:
        return ["(sounddevice fehlt)"]


def _pw_find_id_by_name(node_name):
    """Finde aktuelle PipeWire Node-ID anhand von node.name (stabil über Reboots)."""
    import subprocess, re
    try:
        out = subprocess.run(
            ["pw-cli", "list-objects", "Node"],
            capture_output=True, text=True, timeout=3
        ).stdout
        current_id = None
        for line in out.splitlines():
            id_m = re.search(r"id (\d+),", line)
            if id_m:
                current_id = id_m.group(1)
            if "node.name" in line and "node.nick" not in line:
                m = re.search(r'"(.+?)"', line)
                if m and m.group(1) == node_name and current_id:
                    return current_id
    except Exception:
        pass
    # Fallback: wenn node_name schon numerisch ist (Legacy)
    if node_name and node_name.isdigit():
        return node_name
    return None


def _device_max_channels(device_str: str, kind: str) -> int:
    """Return max channels for a device. Supports [pw:node.name] and [i] formats."""
    try:
        prefix = device_str.split("]")[0].replace("[", "").strip()
        if prefix.startswith("pw:"):
            pw_name = prefix.replace("pw:", "")
            node_id = _pw_find_id_by_name(pw_name)
            if node_id:
                import subprocess, re
                try:
                    out = subprocess.run(
                        ["pw-cli", "info", node_id],
                        capture_output=True, text=True, timeout=2
                    ).stdout
                    for line in out.splitlines():
                        if "audio.channels" in line or "channels" in line.lower():
                            m = re.search(r"(\d+)", line.split("=")[-1] if "=" in line else line.split(":")[-1])
                            if m:
                                return max(1, int(m.group(1)))
                except Exception:
                    pass
            return 2
        else:
            import sounddevice as sd
            idx = int(prefix)
            d = sd.query_devices(idx)
            return int(d["max_input_channels"] if kind == "input" else d["max_output_channels"])
    except Exception:
        return 2


class DropDownComboBox(QComboBox):
    """ComboBox die das Popup immer unterhalb öffnet."""
    def showPopup(self):
        super().showPopup()
        popup = self.view().window()
        pos = self.mapToGlobal(QPoint(0, self.height()))
        popup.move(pos)


class AudioSetupOverlay(QWidget):

    _save_sig  = Signal(bool)
    _rec_sig   = Signal(bool)   # True = aufnahme gestartet
    _wave_done = Signal()       # Wave Test fertig
    _rec_done  = Signal()       # Playback fertig
    _vu_level  = Signal(float)  # VU Meter Level 0.0–1.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.hide()
        self._recording = False
        if parent:
            parent.installEventFilter(self)

        # ── Panel ────────────────────────────────────────────────────
        self.panel = QWidget(self)
        self.panel.setFixedSize(700, 400)
        self.panel.setObjectName("audiopanel")
        self.panel.setStyleSheet(f"""
            QWidget#audiopanel {{
                background-color: {T['bg_dark']};
                border: 1px solid {T['border']};
                border-radius: 12px;
            }}
        """)

        root = QVBoxLayout(self.panel)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(8)

        # ── Title + Save button (oben rechts) ─────────────────────────
        title_row = QHBoxLayout()
        self._audio_title = QLabel("Audio Matrix")
        self._audio_title.setStyleSheet(f"color: {T['text']}; font-size: 16px; font-weight: bold; border: none;")
        title_row.addWidget(self._audio_title)
        title_row.addStretch()

        _icon_btn_style = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['border']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['border_hover']}; }}"""

        self.btn_wave = QPushButton()
        self.btn_wave.setFixedSize(40, 40)
        self.btn_wave.setIcon(themed_icon(os.path.join(_ICONS, "sound.svg")))
        self.btn_wave.setIconSize(QSize(22, 22))
        self.btn_wave.setCursor(Qt.PointingHandCursor)
        self.btn_wave.setToolTip("Wave Test")
        self.btn_wave.setStyleSheet(_icon_btn_style)
        title_row.addWidget(self.btn_wave)

        self.btn_rec = QPushButton()
        self.btn_rec.setFixedSize(40, 40)
        self.btn_rec.setIcon(themed_icon(os.path.join(_ICONS, "mic.svg")))
        self.btn_rec.setIconSize(QSize(22, 22))
        self.btn_rec.setCursor(Qt.PointingHandCursor)
        self.btn_rec.setToolTip("Aufnahme Test")
        self._rec_style_idle = _icon_btn_style
        self._rec_style_active = f"""
            QPushButton {{ background-color: rgba(139, 0, 0, 255); border: 2px solid {T['error']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: rgba(160, 0, 0, 255); }}"""
        self.btn_rec.setStyleSheet(self._rec_style_idle)
        title_row.addWidget(self.btn_rec)

        self.btn_save = QPushButton()
        self.btn_save.setFixedSize(40, 40)
        self.btn_save.setIcon(themed_icon(os.path.join(_ICONS, "save.svg")))
        self.btn_save.setIconSize(QSize(22, 22))
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setToolTip("Audio-Matrix speichern")
        self._save_style_default = _icon_btn_style
        self._save_style_ok  = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['accent']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['accent']}; }}"""
        self._save_style_err = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['error']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['error']}; }}"""
        self.btn_save.setStyleSheet(self._save_style_default)
        title_row.addWidget(self.btn_save)
        root.addLayout(title_row)

        # ── 4 Device rows ─────────────────────────────────────────────
        rows_cfg = [
            ("1. PC MIKROFON",      "input"),
            ("2. TRX MIKROFON",     "input"),
            ("3. TRX LAUTSPRECHER", "output"),
            ("4. PC LAUTSPRECHER",  "output"),
        ]

        _combo_style = f"""
            QComboBox {{ background-color: {T['bg_mid']}; color: {T['text_secondary']}; border: 1px solid {T['border']};
                        border-radius: 5px; padding: 4px 8px; font-size: 12px; min-height: 26px; }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{ background-color: {T['bg_mid']}; color: {T['text_secondary']};
                        selection-background-color: {T['bg_light']}; border: 1px solid {T['border']}; }}"""

        self.device_combos = []
        self.rate_combos   = []
        self.chan_combos   = []
        self._row_kinds    = []
        self._row_labels   = []

        for label_text, kind in rows_cfg:
            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"color: {T['accent']}; font-size: 11px; font-weight: bold; border: none;")
            root.addWidget(lbl)
            self._row_labels.append(lbl)

            row = QHBoxLayout()
            row.setSpacing(8)

            dev_cb = DropDownComboBox()
            devs = _list_audio_devices(kind)
            for item in devs:
                if isinstance(item, tuple):
                    display, internal = item
                    dev_cb.addItem(display, userData=internal)
                else:
                    dev_cb.addItem(item, userData=item)
            dev_cb.setStyleSheet(_combo_style)
            row.addWidget(dev_cb, stretch=1)

            rate_cb = DropDownComboBox()
            rate_cb.addItems(["44100", "48000", "96000", "192000"])
            rate_cb.setFixedWidth(90)
            rate_cb.setStyleSheet(_combo_style)
            row.addWidget(rate_cb)

            chan_cb = DropDownComboBox()
            chan_cb.setFixedWidth(55)
            chan_cb.setStyleSheet(_combo_style)
            row.addWidget(chan_cb)

            root.addLayout(row)
            self.device_combos.append(dev_cb)
            self.rate_combos.append(rate_cb)
            self.chan_combos.append(chan_cb)
            self._row_kinds.append(kind)

            # Kanäle dynamisch beim Gerätewechsel aktualisieren
            idx = len(self.device_combos) - 1
            dev_cb.currentTextChanged.connect(
                lambda txt, i=idx, k=kind: self._update_channels(i, txt, k)
            )
            # Initial befüllen
            self._update_channels(idx, dev_cb.currentText(), kind)

        # ── VU Meter ─────────────────────────────────────────────────
        self.vu_bar = QProgressBar()
        self.vu_bar.setFixedHeight(10)
        self.vu_bar.setRange(0, 100)
        self.vu_bar.setValue(0)
        self.vu_bar.setTextVisible(False)
        root.addWidget(self.vu_bar)

        # ── Signals ───────────────────────────────────────────────────
        self.btn_save.clicked.connect(self.save_to_config)
        self.btn_wave.clicked.connect(self._wave_test)
        self.btn_rec.clicked.connect(self._toggle_rec)
        self._save_sig.connect(self._on_save_result)
        self._wave_done.connect(self._wave_test_reset)
        self._rec_done.connect(self._on_rec_done)
        self._vu_level.connect(self._update_vu)

    def _update_vu(self, level):
        val = int(level * 100)
        self.vu_bar.setValue(val)
        if val < 60:
            color = T['vu_green']
        elif val < 85:
            color = T['vu_yellow']
        else:
            color = T['vu_red']
        self.vu_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {T['bg_dark']}; border: 1px solid {T['border']};
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                border-radius: 3px;
                background-color: {color};
            }}
        """)

    def _on_rec_done(self):
        self.btn_rec.setEnabled(True)
        self.vu_bar.setValue(0)
        self.btn_rec.setStyleSheet(self._icon_btn_ok)
        QTimer.singleShot(2000, lambda: self.btn_rec.setStyleSheet(self._rec_style_idle))

    def _update_channels(self, row_idx: int, device_str: str, kind: str):
        """Populate channel combo based on actual device max channels."""
        cb = self.chan_combos[row_idx]
        current = cb.currentText()
        max_ch = _device_max_channels(device_str, kind)
        cb.blockSignals(True)
        cb.clear()
        cb.addItems([str(i) for i in range(1, max_ch + 1)])
        if current and cb.findText(current) != -1:
            cb.setCurrentText(current)
        cb.blockSignals(False)

    # ── Config: speichert in die Rig-Config des ausgewählten Rigs ────

    _ROW_KEYS = ["pc_mic", "trx_mic", "trx_speaker", "pc_speaker"]

    def _rig_config_path(self) -> str:
        """Get the config.json path of the currently selected rig from RadioSetupOverlay."""
        parent = self.parent()
        if parent is None:
            return ""
        # MainWindow → central_widget ist parent, RadioSetupOverlay hängt dort
        main_win = parent.window()
        if hasattr(main_win, "radio_setup_overlay"):
            return main_win.radio_setup_overlay._config_path()
        return ""

    def load_from_config(self):
        path = self._rig_config_path()
        if not path or not os.path.exists(path):
            return
        try:
            with open(path) as f:
                full_cfg = json.load(f)
        except Exception:
            return
        cfg = full_cfg.get("audio", {})
        if not cfg:
            return
        for i, key in enumerate(self._ROW_KEYS):
            row = cfg.get(key, {})
            dev  = row.get("device", "")
            rate = str(row.get("rate", "44100"))
            chan = str(row.get("channels", "1"))
            # Device aus Config matchen (über userData oder Display-Name)
            cb = self.device_combos[i]
            matched = False
            if dev:
                for idx in range(cb.count()):
                    if cb.itemData(idx) == dev:
                        cb.setCurrentIndex(idx)
                        matched = True
                        break
                if not matched:
                    # Display-Name aus dem Config-String extrahieren
                    import re as _re
                    display = _re.sub(r"^\[.*?\]\s*", "", dev).strip()
                    for idx in range(cb.count()):
                        if cb.itemText(idx) == display:
                            cb.setCurrentIndex(idx)
                            matched = True
                            break
                if not matched and dev:
                    # Fallback: raw einfügen
                    display = _re.sub(r"^\[.*?\]\s*", "", dev).strip()
                    cb.addItem(display, userData=dev)
                    cb.setCurrentIndex(cb.count() - 1)
            self.rate_combos[i].setCurrentText(rate)
            self.chan_combos[i].setCurrentText(chan)

    def save_to_config(self):
        path = self._rig_config_path()
        if not path:
            print("Audio save fehler: kein Rig ausgewählt")
            self._save_sig.emit(False)
            return
        try:
            # Bestehende Rig-Config laden
            if os.path.exists(path):
                with open(path) as f:
                    full_cfg = json.load(f)
            else:
                full_cfg = {}

            # Audio-Block erstellen
            audio_cfg = {}
            for i, key in enumerate(self._ROW_KEYS):
                audio_cfg[key] = {
                    "device":   self.device_combos[i].currentData() or self.device_combos[i].currentText(),
                    "rate":     int(self.rate_combos[i].currentText()),
                    "channels": int(self.chan_combos[i].currentText()),
                }

            # In Rig-Config einfügen und speichern
            full_cfg["audio"] = audio_cfg
            with open(path, "w") as f:
                json.dump(full_cfg, f, indent=4)

            # Verify
            with open(path) as f:
                check = json.load(f)
            ok = all(
                check["audio"][k]["device"] == audio_cfg[k]["device"] and
                check["audio"][k]["rate"]   == audio_cfg[k]["rate"]
                for k in self._ROW_KEYS
            )
        except Exception as e:
            print(f"Audio save fehler: {e}")
            ok = False
        self._save_sig.emit(ok)

    def _on_save_result(self, ok: bool):
        self.btn_save.setStyleSheet(self._save_style_ok if ok else self._save_style_err)
        QTimer.singleShot(2000, lambda: self.btn_save.setStyleSheet(self._save_style_default))
        # Audio-Streams neu starten wenn verbunden
        if ok:
            main_win = self.parent().window() if self.parent() else None
            if main_win and hasattr(main_win, "_restart_audio"):
                main_win._restart_audio()

    # ── Wave Test ────────────────────────────────────────────────────

    _WAV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "audio", "VOXScrm_Wilhelm_scream.wav")
    _TEMP_REC  = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "audio", "temp_rec.wav")

    def _find_sd_device(self, combo_index, need_input=False, need_output=False):
        """Finde den sounddevice Device-Index anhand des Namens im Combo."""
        import sounddevice as sd
        txt = self.device_combos[combo_index].currentText()
        # Name extrahieren: "[pw:33] Scarlett 2i2 USB (Eingang)" → "Scarlett 2i2 USB"
        import re
        name = re.sub(r"^\[.*?\]\s*", "", txt).strip()
        name = re.sub(r"\s*\((Eingang|Ausgabe)\)\s*$", "", name).strip().lower()

        for i, d in enumerate(sd.query_devices()):
            if need_input and d["max_input_channels"] < 1:
                continue
            if need_output and d["max_output_channels"] < 1:
                continue
            if name in d["name"].lower():
                return i
        return None

    def _pw_node_name_for(self, combo_index):
        """PipeWire node.name direkt aus Combo-Text lesen.
        Format: '[pw:alsa_output.usb-...] Display Name' → 'alsa_output.usb-...'
        Legacy: '[pw:57]' → Fallback pw-cli lookup."""
        import subprocess, re
        txt = self.device_combos[combo_index].currentData() or self.device_combos[combo_index].currentText()
        m = re.search(r"\[pw:([^\]]+)\]", txt)
        if not m:
            return None
        pw_val = m.group(1)
        if not pw_val.isdigit():
            return pw_val
        # Legacy: numerische ID → node.name auflösen
        try:
            out = subprocess.run(["pw-cli", "info", pw_val],
                capture_output=True, text=True, timeout=2).stdout
            for line in out.splitlines():
                if "node.name" in line and "node.nick" not in line:
                    nm = re.search(r'"(.+?)"', line)
                    if nm:
                        return nm.group(1)
        except Exception:
            pass
        return pw_val

    def _wave_test(self):
        """WAV auf PC LAUTSPRECHER (Zeile 4, Index 3) abspielen."""
        self.btn_wave.setEnabled(False)
        import platform
        pw_target = self._pw_node_name_for(3) if platform.system() == "Linux" else None

        def run():
            try:
                if pw_target:
                    import subprocess
                    subprocess.run(
                        ["pw-play", "--target", pw_target, self._WAV_PATH],
                        timeout=15
                    )
                else:
                    import sounddevice as sd, numpy as np, wave
                    with wave.open(self._WAV_PATH, "rb") as wf:
                        rate = wf.getframerate()
                        frames = wf.readframes(wf.getnframes())
                        dtype = np.int16 if wf.getsampwidth() == 2 else np.uint8
                        data = np.frombuffer(frames, dtype=dtype).astype(np.float32)
                        data /= np.iinfo(dtype).max
                        if wf.getnchannels() > 1:
                            data = data.reshape(-1, wf.getnchannels())
                    sd.play(data, rate)
                    sd.wait()
            except Exception as e:
                print(f"Wave Test Fehler: {e}")
            self._wave_done.emit()
        threading.Thread(target=run, daemon=True).start()

    @property
    def _icon_btn_ok(self):
        return f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['accent']};
                          border-radius: 5px; padding: 5px; }}"""

    def _wave_test_reset(self):
        self.btn_wave.setEnabled(True)
        self.btn_wave.setStyleSheet(self._icon_btn_ok)
        QTimer.singleShot(2000, lambda: self.btn_wave.setStyleSheet(self._rec_style_idle))

    # ── Record ───────────────────────────────────────────────────────

    def _toggle_rec(self):
        """Aufnahme von PC MIKROFON (Zeile 1, Index 0),
        Wiedergabe auf PC LAUTSPRECHER (Zeile 4, Index 3).
        Nutzt immer die aktuellen Dropdown-Werte, nicht die gespeicherte Config."""
        import platform

        if not self._recording:
            try:
                if os.path.exists(self._TEMP_REC):
                    os.remove(self._TEMP_REC)
            except Exception:
                pass

            rate = int(self.rate_combos[0].currentText())
            ch = int(self.chan_combos[0].currentText())
            self._recording = True
            self._rec_frames = []
            self._rec_rate = rate
            self._rec_ch = ch
            self.btn_rec.setStyleSheet(self._rec_style_active)

            if platform.system() == "Linux":
                pw_mic = self._pw_node_name_for(0)  # Aktueller PC Mic Dropdown
                if not pw_mic:
                    print("PC Mikrofon nicht gefunden!")
                    self._recording = False
                    self.btn_rec.setStyleSheet(self._rec_style_idle)
                    return
                import subprocess
                self._rec_process = subprocess.Popen(
                    ["pw-cat", "--record", "--target", pw_mic,
                     "--format", "s16", "--rate", str(rate), "--channels", str(ch), "-"],
                    stdout=subprocess.PIPE)

                def read_audio():
                    import numpy as np
                    chunk_size = 1024 * ch * 2
                    while self._recording and self._rec_process:
                        data = self._rec_process.stdout.read(chunk_size)
                        if not data:
                            break
                        self._rec_frames.append(data)
                        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                        rms = np.sqrt(np.mean(samples ** 2)) / 32768.0
                        self._vu_level.emit(min(1.0, rms * 5.0))

                self._rec_thread = threading.Thread(target=read_audio, daemon=True)
                self._rec_thread.start()
                print(f"Aufnahme: pw-cat --target {pw_mic} | {rate}Hz | {ch}ch")
            else:
                import sounddevice as sd, numpy as np
                mic_idx = self._find_sd_device(0, need_input=True)
                if mic_idx is None:
                    print("PC Mikrofon nicht gefunden!")
                    self._recording = False
                    self.btn_rec.setStyleSheet(self._rec_style_idle)
                    return
                def callback(indata, frames, time_info, status):
                    if self._recording:
                        self._rec_frames.append(indata.copy())
                        rms = float(np.sqrt(np.mean(indata ** 2)))
                        self._vu_level.emit(min(1.0, rms * 5.0))
                self._rec_stream = sd.InputStream(
                    device=mic_idx, samplerate=rate, channels=ch,
                    dtype="float32", blocksize=1024, callback=callback)
                self._rec_stream.start()
        else:
            # ── Stop & Play ───────────────────────────────────────
            self._recording = False
            self.btn_rec.setStyleSheet(self._rec_style_idle)
            self.btn_rec.setEnabled(False)
            self._vu_level.emit(0.0)

            pw_spk = self._pw_node_name_for(3) if platform.system() == "Linux" else None

            if platform.system() == "Linux":
                if hasattr(self, "_rec_process") and self._rec_process:
                    self._rec_process.terminate()
                    try: self._rec_process.wait(timeout=3)
                    except Exception: pass
                    self._rec_process = None
                if hasattr(self, "_rec_thread"):
                    self._rec_thread.join(timeout=2)

                frames_raw = self._rec_frames
                rate = self._rec_rate
                ch = self._rec_ch
                self._rec_frames = []

                def save_and_play():
                    try:
                        if not frames_raw:
                            print("Keine Daten!")
                            self._rec_done.emit()
                            return
                        import wave as wavmod
                        raw = b"".join(frames_raw)
                        with wavmod.open(self._TEMP_REC, "wb") as wf:
                            wf.setnchannels(ch)
                            wf.setsampwidth(2)
                            wf.setframerate(rate)
                            wf.writeframes(raw)
                        if pw_spk:
                            import subprocess
                            subprocess.run(
                                ["pw-play", "--target", pw_spk, self._TEMP_REC],
                                timeout=30)
                        print("Playback fertig")
                    except Exception as e:
                        print(f"Playback Fehler: {e}")
                    self._rec_done.emit()
                threading.Thread(target=save_and_play, daemon=True).start()
            else:
                import sounddevice as sd, numpy as np
                if hasattr(self, "_rec_stream") and self._rec_stream:
                    self._rec_stream.stop()
                    self._rec_stream.close()
                    self._rec_stream = None
                if self._rec_frames:
                    audio = np.concatenate(self._rec_frames, axis=0)
                    rate = self._rec_rate
                    self._rec_frames = []
                    def playback():
                        sd.play(audio, rate)
                        sd.wait()
                        self._rec_done.emit()
                    threading.Thread(target=playback, daemon=True).start()
                else:
                    self._rec_done.emit()

    # ── Overlay mechanics ────────────────────────────────────────────

    def _refresh_styles(self):
        """Styles mit aktuellen Theme-Werten neu setzen."""
        self.panel.setStyleSheet(f"""
            QWidget#audiopanel {{
                background-color: {T['bg_dark']};
                border: 1px solid {T['border']};
                border-radius: 12px;
            }}
        """)
        self._audio_title.setStyleSheet(f"color: {T['text']}; font-size: 16px; font-weight: bold; border: none;")

        _icon_btn_style = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['border']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['border_hover']}; }}"""
        self._rec_style_idle = _icon_btn_style
        self._save_style_default = _icon_btn_style
        self._save_style_ok = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['accent']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['accent']}; }}"""
        self._save_style_err = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['error']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['error']}; }}"""

        self.btn_wave.setStyleSheet(_icon_btn_style)
        self.btn_rec.setStyleSheet(self._rec_style_idle)
        self.btn_save.setStyleSheet(self._save_style_default)
        self.btn_wave.setIcon(themed_icon(os.path.join(_ICONS, "sound.svg")))
        self.btn_rec.setIcon(themed_icon(os.path.join(_ICONS, "mic.svg")))
        self.btn_save.setIcon(themed_icon(os.path.join(_ICONS, "save.svg")))

        _combo_style = f"""
            QComboBox {{ background-color: {T['bg_mid']}; color: {T['text_secondary']}; border: 1px solid {T['border']};
                        border-radius: 5px; padding: 4px 8px; font-size: 12px; min-height: 26px; }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{ background-color: {T['bg_mid']}; color: {T['text_secondary']};
                        selection-background-color: {T['bg_light']}; border: 1px solid {T['border']}; }}"""

        for lbl in self._row_labels:
            lbl.setStyleSheet(f"color: {T['accent']}; font-size: 11px; font-weight: bold; border: none;")
        for cb in self.device_combos + self.rate_combos + self.chan_combos:
            cb.setStyleSheet(_combo_style)

    def show_overlay(self):
        self._refresh_styles()
        parent = self.parent()
        self.setGeometry(parent.rect())
        pw = min(700, int(parent.width() * 0.85))
        ph = min(400, int(parent.height() * 0.85))
        self.panel.setFixedSize(pw, ph)
        self.panel.move((self.width() - pw) // 2, (self.height() - ph) // 2)
        self.load_from_config()
        self.show()
        self.raise_()
        QApplication.instance().installEventFilter(self)

    def hide(self):
        try:
            QApplication.instance().removeEventFilter(self)
        except Exception:
            pass
        super().hide()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            global_pos = event.globalPosition().toPoint()
            panel_rect = QRect(self.panel.mapToGlobal(QPoint(0, 0)), self.panel.size())
            if not panel_rect.contains(global_pos):
                # Prüfe ob der Click auf ein Popup/Dropdown geht (ComboBox etc.)
                widget_at = QApplication.widgetAt(global_pos)
                if widget_at is not None:
                    # Ist das Widget ein Kind des Panels oder ein Popup davon?
                    parent = widget_at
                    while parent is not None:
                        if parent is self.panel:
                            return False  # Click gehört zum Panel
                        parent = parent.parent()
                    # Prüfe ob es ein Popup-Window ist (ComboBox Dropdown)
                    top = widget_at.window()
                    if top is not None and top is not self.parent().window():
                        return False  # Click auf ein separates Popup-Fenster
                self.hide()
        elif event.type() == QEvent.Type.Resize and obj is self.parent() and self.isVisible():
            parent = self.parent()
            self.setGeometry(parent.rect())
            pw = min(700, int(parent.width() * 0.85))
            ph = min(400, int(parent.height() * 0.85))
            self.panel.setFixedSize(pw, ph)
            self.panel.move((self.width() - pw) // 2, (self.height() - ph) // 2)
        return False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))

# =====================================================================
# END OF BLOCK
# =====================================================================


# Helper class to force larger icons in QMenu since it lacks a direct setIconSize method
# =====================================================================
# BLOCK: THEME EDITOR OVERLAY
# =====================================================================

_THEME_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs", "theme.json")

# Editierbare Farben mit deutschem Label
_THEME_FIELDS = [
    ("accent",              "Akzentfarbe"),
    ("accent_dark",         "Akzent dunkel"),
    ("error",               "Fehler"),
    ("bg_dark",             "Hintergrund dunkel"),
    ("bg_mid",              "Hintergrund mittel"),
    ("bg_light",            "Hintergrund hell"),
    ("bg_button",           "Button Hintergrund"),
    ("bg_button_hover",     "Button Hover"),
    ("border",              "Rahmen"),
    ("border_hover",        "Rahmen Hover"),
    ("border_active",       "Rahmen aktiv"),
    ("text",                "Text"),
    ("text_secondary",      "Text sekundär"),
    ("text_muted",          "Text gedimmt"),
    ("slider_handle",       "Slider Punkt"),
    ("slider_fill",         "Slider Spur"),
    ("smeter_bar",          "S-Meter Balken"),
    ("smeter_label_active", "S-Meter Label aktiv"),
    ("tx_bar",              "TX-Meter Balken"),
    ("ptt_tx_bg",           "PTT TX Hintergrund"),
    ("ptt_tx_border",       "PTT TX Rahmen"),
    ("vu_green",            "VU Grün"),
    ("vu_yellow",           "VU Gelb"),
    ("vu_red",              "VU Rot"),
]


class ThemeEditorOverlay(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.hide()
        if parent:
            parent.installEventFilter(self)

        # Früh initialisieren — werden von _refresh_own_styles / _detect_current_preset gebraucht
        self.btn_delete = QPushButton()
        self.btn_delete.setFixedSize(0, 0)
        self.btn_delete.setVisible(False)
        self._user_edited_name = False
        self._name_block_signal = False

        self.panel = QWidget(self)
        self.panel.setFixedSize(500, 580)
        self.panel.setObjectName("themepanel")
        self._apply_panel_style()

        root = QVBoxLayout(self.panel)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(6)

        # ── Title Row ─────────────────────────────────────────────────
        title_row = QHBoxLayout()
        self._title_lbl = QLabel("Theme Editor")
        self._title_lbl.setStyleSheet(f"color: {T['text']}; font-size: 16px; font-weight: bold; border: none;")
        title_row.addWidget(self._title_lbl)
        title_row.addStretch()
        root.addLayout(title_row)

        # ── Preset Dropdown (öffnet nach unten) ──────────────────────
        preset_row = QHBoxLayout()
        self._preset_lbl = QLabel("Vorlage:")
        self._preset_lbl.setStyleSheet(f"color: {T['text_secondary']}; font-size: 12px; border: none;")
        preset_row.addWidget(self._preset_lbl)

        self.combo_preset = DropDownComboBox()
        # Wird dynamisch befüllt via _rebuild_preset_combo()
        self.combo_preset.setStyleSheet(f"""
            QComboBox {{
                background-color: {T['bg_mid']};
                color: {T['text_secondary']};
                border: 1px solid {T['border']};
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 12px;
                min-height: 28px;
            }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox QAbstractItemView {{
                background-color: {T['bg_mid']};
                color: {T['text_secondary']};
                selection-background-color: {T['bg_light']};
                border: 1px solid {T['border']};
            }}
        """)
        self.combo_preset.currentIndexChanged.connect(self._on_preset_selected)
        preset_row.addWidget(self.combo_preset, stretch=1)
        root.addLayout(preset_row)

        # ── Scrollbare Farbfelder ────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { width: 8px; background: transparent; border: none; }
            QScrollBar::handle:vertical { background: rgba(128,128,128,80); border-radius: 4px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        """)
        scroll_widget = QWidget()
        self._grid = QGridLayout(scroll_widget)
        self._grid.setSpacing(4)

        self._color_buttons = {}
        self._theme_data = {}

        for row, (key, label) in enumerate(_THEME_FIELDS):
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {T['text_secondary']}; font-size: 11px; border: none;")
            self._grid.addWidget(lbl, row, 0)

            btn = QPushButton()
            btn.setFixedSize(60, 24)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, k=key: self._pick_color(k))
            self._grid.addWidget(btn, row, 1)

            val = QLabel("")
            val.setStyleSheet(f"color: {T['text_muted']}; font-size: 10px; border: none;")
            self._grid.addWidget(val, row, 2)

            self._color_buttons[key] = (btn, val)

        scroll.setWidget(scroll_widget)
        root.addWidget(scroll, stretch=1)

        # ── Save Row: Name-Eingabe + Delete + Save ────────────────────
        save_row = QHBoxLayout()
        save_row.setSpacing(6)

        self.input_theme_name = QLineEdit()
        self.input_theme_name.setPlaceholderText("Theme-Name eingeben...")
        self.input_theme_name.setStyleSheet(f"""
            QLineEdit {{ background-color: {T['bg_mid']}; color: {T['text_secondary']};
                        border: 1px solid {T['border']}; border-radius: 5px;
                        padding: 4px 8px; font-size: 12px; }}
        """)
        self.input_theme_name.setFocusPolicy(Qt.ClickFocus)
        self.input_theme_name.textEdited.connect(self._on_name_edited)
        save_row.addWidget(self.input_theme_name, stretch=1)

        # Delete Button (nur für User-Themes sichtbar)
        self.btn_delete = QPushButton()
        self.btn_delete.setFixedSize(40, 40)
        self.btn_delete.setText("X")
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.setToolTip("User-Theme löschen")
        self._delete_style = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['error']};
                          border-radius: 5px; padding: 5px; color: {T['error']};
                          font-weight: bold; font-size: 14px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; }}"""
        self.btn_delete.setStyleSheet(self._delete_style)
        self.btn_delete.clicked.connect(self._delete_theme)
        save_row.addWidget(self.btn_delete)
        self._hide_delete_btn()

        # Save Button
        btn_save = QPushButton()
        btn_save.setFixedSize(40, 40)
        btn_save.setIcon(themed_icon(os.path.join(_ICONS, "save.svg")))
        btn_save.setIconSize(QSize(22, 22))
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setToolTip("Theme speichern & anwenden")
        self._save_default = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['border']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['border_hover']}; }}"""
        self._save_ok = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['accent']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['accent']}; }}"""
        btn_save.setStyleSheet(self._save_default)
        btn_save.clicked.connect(self._save_theme)
        self._btn_save = btn_save
        save_row.addWidget(btn_save)

        root.addLayout(save_row)
        self._init_done = True

    def _hide_delete_btn(self):
        self.btn_delete.setFixedSize(0, 0)
        self.btn_delete.setVisible(False)

    def _show_delete_btn(self):
        self.btn_delete.setFixedSize(40, 40)
        self.btn_delete.setVisible(True)

    def _on_name_edited(self):
        if not self._name_block_signal:
            self._user_edited_name = True

    def _set_name_silent(self, text):
        """Name-Feld setzen ohne _user_edited_name zu triggern."""
        self._name_block_signal = True
        self.input_theme_name.setText(text)
        self._name_block_signal = False

    def _clear_name_silent(self):
        """Name-Feld leeren ohne _user_edited_name zu triggern."""
        self._name_block_signal = True
        self.input_theme_name.clear()
        self._name_block_signal = False

    def _apply_panel_style(self):
        self.panel.setStyleSheet(f"""
            QWidget#themepanel {{
                background-color: {T['bg_dark']};
                border: 1px solid {T['border']};
                border-radius: 12px;
            }}
        """)

    def _load_theme(self):
        try:
            with open(_THEME_PATH) as f:
                raw = json.load(f)
            self._theme_data = {k: v for k, v in raw.items() if not k.startswith("_")}
        except Exception:
            self._theme_data = {}

        for key, (btn, val) in self._color_buttons.items():
            color_str = self._theme_data.get(key, "rgba(0, 0, 0, 255)")
            # Für Button-Hintergrund: hex konvertieren für CSS
            hex_color = rgba_to_hex(color_str) if color_str.startswith("rgba") else color_str
            btn.setStyleSheet(f"background-color: {color_str}; border: 1px solid {T['border']}; border-radius: 4px;")
            val.setText(color_str)

    def _pick_color(self, key):
        color_str = self._theme_data.get(key, "rgba(0, 0, 0, 255)")
        r, g, b, a = rgba_parts(color_str)
        current = QColor(r, g, b, a)
        # Alpha-Kanal im Dialog aktivieren
        color = QColorDialog.getColor(current, self, f"Farbe: {key}",
                                       QColorDialog.ShowAlphaChannel)
        if color.isValid():
            rgba_str = f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"
            self._theme_data[key] = rgba_str
            btn, val = self._color_buttons[key]
            btn.setStyleSheet(f"background-color: {rgba_str}; border: 1px solid {T['border']}; border-radius: 4px;")
            val.setText(rgba_str)

    def _rebuild_preset_combo(self):
        """Dropdown neu füllen: Builtin-Presets + User-Themes."""
        self.combo_preset.blockSignals(True)
        self.combo_preset.clear()
        self.combo_preset.addItem("— Benutzerdefiniert —", None)
        # Builtin Presets
        for key, name in PRESET_NAMES.items():
            self.combo_preset.addItem(f"  {name}", f"builtin:{key}")
        # User Themes
        user_themes = load_user_themes()
        if user_themes:
            for name in sorted(user_themes.keys()):
                self.combo_preset.addItem(f"  {name}", f"user:{name}")
        self.combo_preset.blockSignals(False)

    def _on_preset_selected(self, index):
        if index <= 0:
            self._hide_delete_btn()
            self._clear_name_silent()
            self.input_theme_name.setReadOnly(False)
            self.input_theme_name.setPlaceholderText("Theme-Name eingeben...")
            self._user_edited_name = False
            return

        data_key = self.combo_preset.itemData(index)
        if not data_key:
            return

        import copy
        if data_key.startswith("builtin:"):
            # Builtin Preset — read-only, direkt anwenden
            preset_key = data_key.replace("builtin:", "")
            if preset_key in PRESETS:
                self._theme_data = copy.deepcopy(PRESETS[preset_key])
                self._clear_name_silent()
                self.input_theme_name.setReadOnly(True)
                self.input_theme_name.setPlaceholderText("Preset (read-only)")
                self._user_edited_name = False
                self._hide_delete_btn()
        elif data_key.startswith("user:"):
            # User Theme — kann überschrieben/gelöscht werden
            theme_name = data_key.replace("user:", "")
            user_themes = load_user_themes()
            if theme_name in user_themes:
                self._theme_data = copy.deepcopy(user_themes[theme_name])
                self._set_name_silent(theme_name)
                self.input_theme_name.setReadOnly(False)
                self.input_theme_name.setPlaceholderText("Theme-Name eingeben...")
                self._user_edited_name = True
                self._show_delete_btn()

        # Farbfelder aktualisieren
        for key, (btn, val) in self._color_buttons.items():
            color_str = self._theme_data.get(key, "rgba(0, 0, 0, 255)")
            btn.setStyleSheet(f"background-color: {color_str}; border: 1px solid {T['border']}; border-radius: 4px;")
            val.setText(color_str)

    def _detect_current_preset(self):
        """Preset-Dropdown auf das aktuell geladene Theme setzen."""
        self.combo_preset.blockSignals(True)
        self._hide_delete_btn()

        # Builtin Preset?
        current = detect_preset()
        if current:
            for i in range(self.combo_preset.count()):
                if self.combo_preset.itemData(i) == f"builtin:{current}":
                    self.combo_preset.setCurrentIndex(i)
                    self._clear_name_silent()
                    self._user_edited_name = False
                    self.combo_preset.blockSignals(False)
                    return

        # User Theme?
        user_themes = load_user_themes()
        for name, theme_data in user_themes.items():
            if all(T.get(k) == v for k, v in theme_data.items()):
                for i in range(self.combo_preset.count()):
                    if self.combo_preset.itemData(i) == f"user:{name}":
                        self.combo_preset.setCurrentIndex(i)
                        self._set_name_silent(name)
                        self._user_edited_name = True
                        self._show_delete_btn()
                        self.combo_preset.blockSignals(False)
                        return

        # Nichts erkannt → Benutzerdefiniert
        self.combo_preset.setCurrentIndex(0)
        self._clear_name_silent()
        self._user_edited_name = False
        self.combo_preset.blockSignals(False)

    def _save_theme(self):
        try:
            theme_name = self.input_theme_name.text().strip()

            # Nur als User-Theme speichern wenn:
            # 1. Ein Name eingegeben wurde UND
            # 2. Es kein Builtin-Preset-Name ist UND
            # 3. Es kein "Mein ..."-Vorschlag ist der nicht geändert wurde
            is_user_theme = (theme_name
                             and not is_builtin_preset(theme_name)
                             and self._user_edited_name)
            if is_user_theme:
                save_user_theme(theme_name, self._theme_data)

            # Erst T aktualisieren (damit detect_preset() korrekt arbeitet)
            T.clear()
            T.update(self._theme_data)

            # Dann in theme.json speichern + last_theme in status_conf
            save_theme()

            self._btn_save.setStyleSheet(self._save_ok)
            QTimer.singleShot(2000, lambda: self._btn_save.setStyleSheet(self._save_default))

            # Live anwenden!
            main_win = self.parent().window() if self.parent() else None
            if main_win and hasattr(main_win, "refresh_theme"):
                main_win.refresh_theme()

            # Alle registrierten Callbacks (Rig-UIs etc.)
            from core.theme import _refresh_callbacks
            for cb in _refresh_callbacks[:]:
                try:
                    cb()
                except Exception:
                    pass

            # Theme Editor selbst refreshen + Dropdown aktualisieren
            self._refresh_own_styles()
            self._rebuild_preset_combo()
            self._detect_current_preset()

        except Exception as e:
            print(f"Theme save Fehler: {e}")

    def _delete_theme(self):
        """User-Theme löschen mit Bestätigungs-Dialog."""
        from PySide6.QtWidgets import QMessageBox
        theme_name = self.input_theme_name.text().strip()
        if not theme_name or is_builtin_preset(theme_name):
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Theme löschen")
        msg.setText(f'Theme "{theme_name}" wirklich löschen?')
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        msg.button(QMessageBox.Yes).setText("Ja, löschen")
        msg.button(QMessageBox.No).setText("Nein")

        if msg.exec() == QMessageBox.Yes:
            delete_user_theme(theme_name)
            self._clear_name_silent()
            self._user_edited_name = False
            self._hide_delete_btn()
            self._rebuild_preset_combo()
            self.combo_preset.setCurrentIndex(0)

    def _refresh_own_styles(self):
        """Theme Editor Panel + Labels mit neuen Farben aktualisieren."""
        self._apply_panel_style()
        if not getattr(self, '_init_done', False):
            return  # Init noch nicht fertig
        self._title_lbl.setStyleSheet(f"color: {T['text']}; font-size: 16px; font-weight: bold; border: none;")
        self._preset_lbl.setStyleSheet(f"color: {T['text_secondary']}; font-size: 12px; border: none;")
        # Labels in der Farbgrid aktualisieren
        for key, (btn, val) in self._color_buttons.items():
            val.setStyleSheet(f"color: {T['text_muted']}; font-size: 10px; border: none;")
        # Grid-Labels (Farbnamen)
        for i in range(self._grid.rowCount()):
            item = self._grid.itemAtPosition(i, 0)
            if item and item.widget():
                item.widget().setStyleSheet(f"color: {T['text_secondary']}; font-size: 11px; border: none;")
        # Input-Feld + Delete Button
        self.input_theme_name.setStyleSheet(f"""
            QLineEdit {{ background-color: {T['bg_mid']}; color: {T['text_secondary']};
                        border: 1px solid {T['border']}; border-radius: 5px;
                        padding: 4px 8px; font-size: 12px; }}
        """)
        self._delete_style = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['error']};
                          border-radius: 5px; padding: 5px; color: {T['error']};
                          font-weight: bold; font-size: 14px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; }}"""
        self.btn_delete.setStyleSheet(self._delete_style)
        self._save_default = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['border']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['border_hover']}; }}"""
        self._save_ok = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['accent']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['accent']}; }}"""
        self._btn_save.setStyleSheet(self._save_default)
        self._btn_save.setIcon(themed_icon(os.path.join(_ICONS, "save.svg")))
        # Preset-Label + Combo
        self.combo_preset.setStyleSheet(f"""
            QComboBox {{
                background-color: {T['bg_mid']};
                color: {T['text_secondary']};
                border: 1px solid {T['border']};
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 12px;
                min-height: 28px;
            }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox QAbstractItemView {{
                background-color: {T['bg_mid']};
                color: {T['text_secondary']};
                selection-background-color: {T['bg_light']};
                border: 1px solid {T['border']};
            }}
        """)

    def show_overlay(self):
        if not getattr(self, '_init_done', False):
            print("ThemeEditor: show_overlay abgebrochen — Init nicht fertig!")
            return
        parent = self.parent()
        self.setGeometry(parent.rect())
        pw = min(500, int(parent.width() * 0.6))
        ph = min(580, int(parent.height() * 0.9))
        self.panel.setFixedSize(pw, ph)
        self.panel.move((self.width() - pw) // 2, (self.height() - ph) // 2)
        self._refresh_own_styles()
        self._load_theme()
        # Dropdown mit Presets + User-Themes füllen
        self._rebuild_preset_combo()
        self._detect_current_preset()
        self.show()
        self.raise_()
        QApplication.instance().installEventFilter(self)

    def hide(self):
        try:
            QApplication.instance().removeEventFilter(self)
        except Exception:
            pass
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
            parent = self.parent()
            self.setGeometry(parent.rect())
            pw = min(500, int(parent.width() * 0.6))
            ph = min(580, int(parent.height() * 0.9))
            self.panel.setFixedSize(pw, ph)
            self.panel.move((self.width() - pw) // 2, (self.height() - ph) // 2)
        return False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))

# =====================================================================
# END THEME EDITOR
# =====================================================================


class MenuIconProxyStyle(QProxyStyle):
    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PixelMetric.PM_SmallIconSize:
            return 26
        return super().pixelMetric(metric, option, widget)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("RigLink")
        self.resize(1000, 700)
        self.setMinimumSize(900, 640)

        # Fenster-Icon setzen
        # SVG Logo für Fenster-Icon (PNG Fallback wenn vorhanden)
        logo_svg = os.path.join(os.path.dirname(__file__), "PandaLogo.svg")
        logo_png = os.path.join(os.path.dirname(__file__), "Logo.png")
        if os.path.exists(logo_png):
            self.setWindowIcon(QIcon(logo_png))
        elif os.path.exists(logo_svg):
            self.setWindowIcon(themed_icon(logo_svg))

        # Fenster-Background entkoppeln vom System-Theme
        self._apply_window_bg()

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        self.top_layout = QHBoxLayout()
        self.main_layout.addLayout(self.top_layout)

        # =====================================================================
        # BLOCK: MAIN MENU (Button, Dropdown, Icons, Styling & Logic)
        # =====================================================================

        self.btn_menu = QPushButton()
        self.btn_menu.setFixedSize(40, 40)
        self.btn_menu.setIcon(themed_icon(os.path.join(_ICONS, "menu.svg")))
        self.btn_menu.setIconSize(QSize(24, 24))
        self._apply_menu_btn_style()

        self.main_menu = QMenu(self)
        self.main_menu.setStyle(MenuIconProxyStyle())
        self._apply_menu_style()

        self.action_settings = QAction("Radio Setup", self)
        self.action_settings.setIcon(themed_icon(os.path.join(_ICONS, "radio.svg")))

        self.action_audio = QAction("Audio Setup", self)
        self.action_audio.setIcon(themed_icon(os.path.join(_ICONS, "sound.svg")))

        self.action_theme = QAction("Theme", self)
        self.action_theme.setIcon(themed_icon(os.path.join(_ICONS, "settings.svg")))

        self.action_report = QAction("Bug Report", self)
        self.action_report.setIcon(themed_icon(os.path.join(_ICONS, "bug_report.svg")))

        self.main_menu.addAction(self.action_settings)
        self.main_menu.addAction(self.action_audio)
        self.main_menu.addAction(self.action_theme)
        self.main_menu.addSeparator()
        self.main_menu.addAction(self.action_report)

        def show_custom_menu():
            button_pos = self.btn_menu.mapToGlobal(QPoint(0, 0))
            self.main_menu.exec(QPoint(button_pos.x(),
                                      button_pos.y() + self.btn_menu.height() + 5))

        self.btn_menu.setFocusPolicy(Qt.NoFocus)
        self.btn_menu.clicked.connect(show_custom_menu)
        self.top_layout.addWidget(self.btn_menu)

        # Radio Setup Overlay
        self.radio_setup_overlay = RadioSetupOverlay(self.central_widget)
        self.action_settings.triggered.connect(self.radio_setup_overlay.show_overlay)

        # Audio Setup Overlay
        self.audio_setup_overlay = AudioSetupOverlay(self.central_widget)
        self.action_audio.triggered.connect(self.audio_setup_overlay.show_overlay)

        # Theme Editor Overlay
        self.theme_editor_overlay = ThemeEditorOverlay(self.central_widget)
        self.action_theme.triggered.connect(self.theme_editor_overlay.show_overlay)

        # Bug Report
        def _open_report():
            log_action("Menü → Bug Report")
            from core.reporter import show_report_dialog
            show_report_dialog(self)
        self.action_report.triggered.connect(_open_report)

        # =====================================================================
        # END OF BLOCK
        # =====================================================================

        self.top_layout.addStretch()

        # ── REC Button (Demo-Aufnahme) ───────────────────────────────
        self.tgl_demo_rec = ToggleButton("REC")
        self.tgl_demo_rec.toggled.connect(self._toggle_demo_rec)
        self.top_layout.addWidget(self.tgl_demo_rec)

        # ── VOX Controls ─────────────────────────────────────────────
        self.tgl_vox = ToggleButton("VOX")
        self.tgl_vox.toggled.connect(self._toggle_vox)
        self.top_layout.addWidget(self.tgl_vox)

        self.lbl_vox_thr = QLabel("THR:-25")
        self.lbl_vox_thr.setStyleSheet(f"color: {T['text']}; font-size: 10px;")
        self.lbl_vox_thr.setFixedWidth(42)
        self.top_layout.addWidget(self.lbl_vox_thr)

        self.slider_vox_thr = QSlider(Qt.Horizontal)
        self.slider_vox_thr.setRange(-60, -5)
        self.slider_vox_thr.setValue(-25)
        self.slider_vox_thr.setSingleStep(5)
        self.slider_vox_thr.setPageStep(10)
        self.slider_vox_thr.setFixedWidth(60)
        self.slider_vox_thr.setFixedHeight(24)
        self.slider_vox_thr.setFocusPolicy(Qt.NoFocus)
        self.slider_vox_thr.setToolTip("VOX Schwelle dBFS")
        self._apply_top_slider_style(self.slider_vox_thr, small=True)
        self.slider_vox_thr.valueChanged.connect(lambda v: (
            self.lbl_vox_thr.setText(f"THR:{v}"), self._save_vox()))
        self.top_layout.addWidget(self.slider_vox_thr)

        self.lbl_vox_hold = QLabel("H:700")
        self.lbl_vox_hold.setStyleSheet(f"color: {T['text']}; font-size: 10px;")
        self.lbl_vox_hold.setFixedWidth(38)
        self.top_layout.addWidget(self.lbl_vox_hold)

        self.slider_vox_hold = QSlider(Qt.Horizontal)
        self.slider_vox_hold.setRange(1, 20)  # x100 = 100-2000ms
        self.slider_vox_hold.setValue(7)
        self.slider_vox_hold.setFixedWidth(60)
        self.slider_vox_hold.setFixedHeight(24)
        self.slider_vox_hold.setFocusPolicy(Qt.NoFocus)
        self.slider_vox_hold.setToolTip("VOX Hold ms")
        self._apply_top_slider_style(self.slider_vox_hold, small=True)
        self.slider_vox_hold.valueChanged.connect(lambda v: (
            self.lbl_vox_hold.setText(f"H:{v * 100}"), self._save_vox()))
        self.top_layout.addWidget(self.slider_vox_hold)

        # ── RX Volume + Mute ─────────────────────────────────────────
        lbl_vol = QLabel("VOL")
        lbl_vol.setStyleSheet(f"color: {T['text']}; font-size: 11px; font-weight: bold;")
        self.lbl_vol = lbl_vol
        self.top_layout.addWidget(lbl_vol)

        self.slider_vol = QSlider(Qt.Horizontal)
        self.slider_vol.setRange(0, 20)
        # Gespeicherten Wert laden oder Default 1 (5%)
        _saved_vol = 1
        try:
            _sc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs", "status_conf.json")
            with open(_sc) as f:
                _saved_vol = json.load(f).get("sliders", {}).get("volume", 1)
        except Exception:
            pass
        self.slider_vol.setValue(_saved_vol)
        self.slider_vol.setFixedWidth(100)
        self.slider_vol.setFixedHeight(30)
        self.slider_vol.setFocusPolicy(Qt.NoFocus)
        self._apply_top_slider_style(self.slider_vol)
        self.slider_vol.valueChanged.connect(self._apply_volume)
        self.top_layout.addWidget(self.slider_vol)

        self._muted = False
        self._vol_before_mute = 5
        self.btn_mute = QPushButton()
        self.btn_mute.setFixedSize(40, 40)
        self.btn_mute.setIcon(themed_icon(os.path.join(_ICONS, "sound.svg")))
        self.btn_mute.setIconSize(QSize(22, 22))
        self.btn_mute.setFocusPolicy(Qt.NoFocus)
        self.btn_mute.setCursor(Qt.PointingHandCursor)
        self.btn_mute.setToolTip("Mute/Unmute")
        self._update_mute_styles()
        self.btn_mute.setStyleSheet(self._mute_style_on)
        self.btn_mute.clicked.connect(self._toggle_mute)
        self.top_layout.addWidget(self.btn_mute)

        # ── Rig-Auswahl Combo in der Top-Bar ─────────────────────────
        # Zeigt nur konfigurierte Rigs (aus status_conf.json), nicht alle gescannten
        self.combo_rig_select = DropDownComboBox()
        self.combo_rig_select.addItems(self._get_configured_rigs())
        self.combo_rig_select.setFixedHeight(40)
        self.combo_rig_select.setMinimumWidth(160)
        self.combo_rig_select.setFocusPolicy(Qt.NoFocus)
        self._apply_rig_combo_style()
        self.combo_rig_select.currentTextChanged.connect(self._on_rig_combo_changed)
        self.top_layout.addWidget(self.combo_rig_select)

        self.btn_cat_con = QPushButton()
        self.btn_cat_con.setFixedSize(40, 40)
        self.btn_cat_con.setIcon(themed_icon(os.path.join(_ICONS, "connection.svg")))
        self.btn_cat_con.setIconSize(QSize(24, 24))
        self._update_cat_styles()
        self.btn_cat_con.setStyleSheet(self._CAT_BTN_OFF)
        self.btn_cat_con.setFocusPolicy(Qt.NoFocus)
        self.btn_cat_con.clicked.connect(self._toggle_cat_connection)
        self.top_layout.addWidget(self.btn_cat_con)

        self._cat_connected = False
        self._cat_handler = None

        # ── Letztes Rig aus Config laden ──────────────────────────────
        self._status_conf_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "configs", "status_conf.json")
        self._rig_switching = False  # Verhindert doppeltes Laden beim Init
        try:
            with open(self._status_conf_path) as f:
                status_cfg = json.load(f)
            last_rig = status_cfg.get("last_rig", "")
            if last_rig and self.combo_rig_select.findText(last_rig) != -1:
                self._rig_switching = True
                self.combo_rig_select.setCurrentText(last_rig)
                # Radio Setup Combo synchronisieren
                self.radio_setup_overlay.combo_rig.setCurrentText(last_rig)
                self._rig_switching = False
        except Exception:
            self._rig_switching = False

        # ── Rig Widget laden ──────────────────────────────────────────
        self.rig_widget = None
        self._load_rig_widget()

        self.main_layout.addStretch()

        # Status-Bar Container (durchgehender Balken)
        self.status_bar_widget = QWidget()
        self.status_bar_widget.setFixedHeight(30)
        status_row = QHBoxLayout(self.status_bar_widget)
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(0)

        self.status_label = QLabel(" Status: Ready")
        self.status_label.setStyleSheet(f"color: {T['text']}; padding-left: 10px;")
        status_row.addWidget(self.status_label)

        from core.updater import CURRENT_VERSION
        self.lbl_version = QLabel(f"v{CURRENT_VERSION}")
        self.lbl_version.setStyleSheet(f"color: {T['text_secondary']}; font-size: 11px; padding-right: 8px;")
        self.lbl_version.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_row.addWidget(self.lbl_version)

        self._update_status_styles()
        self.status_bar_widget.setStyleSheet(self._STATUS_OFF)
        self.main_layout.addWidget(self.status_bar_widget)

        # ALLE interaktiven Widgets auf NoFocus — Leertaste nur für PTT
        import PySide6.QtWidgets as _qtw
        for cls in [_qtw.QAbstractButton, _qtw.QComboBox, _qtw.QAbstractSlider]:
            for w in self.findChildren(cls):
                w.setFocusPolicy(Qt.NoFocus)

    # ── Style-Methoden für Theme-Refresh ─────────────────────────────

    def _apply_menu_btn_style(self):
        self.btn_menu.setStyleSheet(f"""
            QPushButton {{
                background-color: {T['bg_mid']};
                border: 2px solid {T['border']};
                border-radius: 5px;
                padding: 5px;
            }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border: 2px solid {T['accent']}; }}
            QPushButton::menu-indicator {{ image: none; border: none; width: 0px; height: 0px; }}
        """)

    def _apply_menu_style(self):
        self.main_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {T['bg_mid']};
                border: 1px solid {T['border']};
                border-radius: 12px;
                padding: 5px;
            }}
            QMenu::item {{
                background-color: transparent;
                padding: 10px 40px 10px 10px;
                color: {T['text_muted']};
                border-radius: 6px;
                margin: 2px;
            }}
            QMenu::item:selected {{ background-color: {T['bg_light']}; color: {T['text']}; }}
        """)

    def _apply_top_slider_style(self, slider, small=False):
        h = 4 if small else 6
        w = 12 if small else 14
        m = 4 if small else 4
        br = w // 2
        slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{ background: {T['slider_groove']}; height: {h}px; border-radius: {h//2}px; }}
            QSlider::handle:horizontal {{ background: {T['slider_handle']}; width: {w}px; margin: -{m}px 0; border-radius: {br}px; }}
            QSlider::sub-page:horizontal {{ background: {T['slider_fill']}; border-radius: {h//2}px; }}""")

    def _update_mute_styles(self):
        self._mute_style_on = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['border']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['border_hover']}; }}"""
        self._mute_style_off = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['error']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['error']}; }}"""

    def _apply_rig_combo_style(self):
        self.combo_rig_select.setStyleSheet(f"""
            QComboBox {{ background-color: {T['bg_mid']}; color: {T['text_secondary']}; border: 2px solid {T['border']};
                        border-radius: 5px; padding: 4px 10px; font-size: 12px; font-weight: bold; }}
            QComboBox:hover {{ border-color: {T['border_hover']}; }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{ background-color: {T['bg_mid']}; color: {T['text_secondary']};
                        selection-background-color: {T['bg_light']}; border: 1px solid {T['border']}; }}
        """)

    def _update_cat_styles(self):
        self._CAT_BTN_OFF = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['border']}; border-radius: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border: 2px solid {T['border_hover']}; }}"""
        self._CAT_BTN_ON = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['accent']}; border-radius: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border: 2px solid {T['accent']}; }}"""
        self._CAT_BTN_ERR = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['error']}; border-radius: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border: 2px solid {T['error']}; }}"""

    def _update_status_styles(self):
        self._STATUS_OFF = f"background-color: {T['bg_dark']}; border-top: 1px solid {T['border']};"
        self._STATUS_ON  = f"background-color: {T['bg_dark']}; border-top: 2px solid {T['accent']};"
        self._STATUS_ERR = f"background-color: {T['bg_dark']}; border-top: 2px solid {T['error']};"

    # ── Fenster-Hintergrund (entkoppelt vom System-Theme) ────────────

    def _apply_window_bg(self):
        """Fenster-BG über QApplication Palette + Stylesheet setzen.
        Überschreibt Linux/System-Theme komplett."""
        r, g, b, a = rgba_parts(T['bg_dark'])
        tr, tg, tb, _ = rgba_parts(T['text'])
        bg_color = QColor(r, g, b, a)
        text_color = QColor(tr, tg, tb)

        # App-Level Palette (überschreibt System-Theme global)
        app = QApplication.instance()
        pal = app.palette()
        pal.setColor(QPalette.Window, bg_color)
        pal.setColor(QPalette.Base, bg_color)
        pal.setColor(QPalette.AlternateBase, bg_color)
        pal.setColor(QPalette.WindowText, text_color)
        pal.setColor(QPalette.Text, text_color)
        pal.setColor(QPalette.ButtonText, text_color)
        pal.setColor(QPalette.Button, bg_color)
        app.setPalette(pal)

        # Zusätzlich Stylesheet auf MainWindow für Sicherheit
        self.setStyleSheet(f"QMainWindow {{ background-color: {T['bg_dark']}; }}")

    # ── Theme Live-Refresh ───────────────────────────────────────────

    def refresh_theme(self):
        """Alle Styles mit aktuellen Theme-Werten neu setzen."""
        self._apply_window_bg()
        self._apply_menu_btn_style()
        self._apply_menu_style()
        self._apply_rig_combo_style()
        self._update_cat_styles()
        self._update_status_styles()
        self._update_mute_styles()

        # Icons neu laden (Farbe passt sich ans Theme an)
        self.btn_menu.setIcon(themed_icon(os.path.join(_ICONS, "menu.svg")))
        self.btn_mute.setIcon(themed_icon(os.path.join(_ICONS, "sound.svg")))
        self.btn_cat_con.setIcon(themed_icon(os.path.join(_ICONS, "connection.svg")))

        # Menu-Action Icons
        self.action_settings.setIcon(themed_icon(os.path.join(_ICONS, "radio.svg")))
        self.action_audio.setIcon(themed_icon(os.path.join(_ICONS, "sound.svg")))
        self.action_theme.setIcon(themed_icon(os.path.join(_ICONS, "settings.svg")))

        # Top-Bar Widgets
        self.lbl_vox_thr.setStyleSheet(f"color: {T['text']}; font-size: 10px;")
        self.lbl_vox_hold.setStyleSheet(f"color: {T['text']}; font-size: 10px;")
        self.lbl_vol.setStyleSheet(f"color: {T['text']}; font-size: 11px; font-weight: bold;")
        self._apply_top_slider_style(self.slider_vox_thr, small=True)
        self._apply_top_slider_style(self.slider_vox_hold, small=True)
        self._apply_top_slider_style(self.slider_vol)

        # CAT + Status basierend auf aktuellem Zustand
        if self._cat_connected:
            self.btn_cat_con.setStyleSheet(self._CAT_BTN_ON)
        else:
            self.btn_cat_con.setStyleSheet(self._CAT_BTN_OFF)

        if self._muted:
            self.btn_mute.setStyleSheet(self._mute_style_off)
        else:
            self.btn_mute.setStyleSheet(self._mute_style_on)

        self.status_bar_widget.setStyleSheet(self._STATUS_ON if self._cat_connected else self._STATUS_OFF)

        # Status-Bar Labels
        self.status_label.setStyleSheet(f"color: {T['text']}; padding-left: 10px; font-family: Consolas;")
        self.lbl_version.setStyleSheet(f"color: {T['text_secondary']}; font-size: 11px; padding-right: 8px;")

        # Report-Action Icon
        self.action_report.setIcon(themed_icon(os.path.join(_ICONS, "bug_report.svg")))

        # Alle ToggleButtons: Icons + Style neu laden
        for tb in self.findChildren(ToggleButton):
            tb._load_icons()
            tb._update_icon(tb.isChecked())
            tb._apply_style()

        # Rig-Widget refreshen (falls es refresh_theme hat)
        if self.rig_widget and hasattr(self.rig_widget, "refresh_theme"):
            self.rig_widget.refresh_theme()

    # ── Keyboard (PTT via Leertaste) ─────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            focus = QApplication.focusWidget()
            if isinstance(focus, QLineEdit):
                super().keyPressEvent(event)
                return
            if not event.isAutoRepeat() and self.rig_widget and hasattr(self.rig_widget, "_ptt_on"):
                self.rig_widget._ptt_on()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space:
            focus = QApplication.focusWidget()
            if isinstance(focus, QLineEdit):
                super().keyReleaseEvent(event)
                return
            if not event.isAutoRepeat() and self.rig_widget and hasattr(self.rig_widget, "_ptt_off"):
                self.rig_widget._ptt_off()
            event.accept()
            return
        super().keyReleaseEvent(event)

    # ── CAT Connection ────────────────────────────────────────────────

    def _toggle_cat_connection(self):
        if self._cat_connected:
            self._disconnect_cat()
        else:
            self._connect_cat()

    def _connect_cat(self):
        """CAT-Verbindung herstellen mit Config aus Radio Setup."""
        # Config laden
        rig_name = "Yaesu FT-991A"
        if hasattr(self, "radio_setup_overlay") and hasattr(self.radio_setup_overlay, "combo_rig"):
            rig_name = self.radio_setup_overlay.combo_rig.currentText()

        config_path = ""
        if hasattr(self, "radio_setup_overlay"):
            config_path = self.radio_setup_overlay._config_path()

        if not config_path or not os.path.exists(config_path):
            self.btn_cat_con.setStyleSheet(self._CAT_BTN_ERR)
            self.status_label.setText(" CAT: Keine Config gefunden")
            self.status_bar_widget.setStyleSheet(self._STATUS_ERR)
            QTimer.singleShot(2000, lambda: (
                self.btn_cat_con.setStyleSheet(self._CAT_BTN_OFF),
                self.status_bar_widget.setStyleSheet(self._STATUS_OFF)))
            return

        try:
            with open(config_path) as f:
                cfg = json.load(f)
        except Exception:
            self.btn_cat_con.setStyleSheet(self._CAT_BTN_ERR)
            self.status_bar_widget.setStyleSheet(self._STATUS_ERR)
            return

        cat_cfg = cfg.get("cat", {})
        protocol = cat_cfg.get("protocol", "yaesu")

        # Live-Werte aus Radio Settings Dropdowns lesen (nicht gespeicherte Config)
        rs = self.radio_setup_overlay
        port = rs.combo_cat_port.currentText() if hasattr(rs, "combo_cat_port") else cat_cfg.get("port", "/dev/ttyUSB0")
        baud = int(rs.combo_baud.currentText()) if hasattr(rs, "combo_baud") else cat_cfg.get("baud", 38400)

        # Globalen CAT-Handler nach Protokoll erstellen
        try:
            from core.cat import create_cat_handler
            handler_kwargs = {
                "port": port,
                "baud": baud,
                "data_bits": cat_cfg.get("data_bits", 8),
                "stop_bits": cat_cfg.get("stop_bits", 1),
                "parity": cat_cfg.get("parity", "N"),
                "timeout": cat_cfg.get("timeout", 0.5),
                "handshake": cat_cfg.get("handshake"),
            }
            # Icom CI-V Adresse aus Modell ableiten
            if protocol == "icom":
                from core.cat.icom import RIG_ADDRESSES
                parts = rig_name.split(" ", 1)
                model_key = parts[1].lower().replace("-", "") if len(parts) == 2 else ""
                handler_kwargs["civ_address"] = RIG_ADDRESSES.get(model_key, 0x94)

            self._cat_handler = create_cat_handler(protocol, **handler_kwargs)
            ok = self._cat_handler.connect()

            if ok:
                self._cat_connected = True
                self.btn_cat_con.setStyleSheet(self._CAT_BTN_ON)
                self.status_label.setText(f" CAT: Verbunden ({port} @ {baud})")
                log_event(f"CAT verbunden: {rig_name} auf {port} @ {baud}")
                self.status_bar_widget.setStyleSheet(self._STATUS_ON)

                # Rig-Widget mit CatHandler verbinden
                if self.rig_widget and hasattr(self.rig_widget, "set_cat_handler"):
                    self.rig_widget.set_cat_handler(self._cat_handler)

                # Audio-Streams starten
                if self.rig_widget and hasattr(self.rig_widget, "start_audio"):
                    if self.rig_widget.start_audio(config_path):
                        self.status_label.setText(f" CAT+Audio: Verbunden ({port} @ {baud})")
                        # VOX-Werte aus Rig in Top-Bar Slider laden
                        self.slider_vox_thr.setValue(int(self.rig_widget._vox_threshold))
                        self.slider_vox_hold.setValue(int(self.rig_widget._vox_hold_ms) // 100)
                    else:
                        self.status_label.setText(f" CAT: Verbunden, Audio FEHLT ({port})")
            else:
                self._cat_handler = None
                self.btn_cat_con.setStyleSheet(self._CAT_BTN_ERR)
                self.status_label.setText(f" CAT: Verbindung fehlgeschlagen ({port})")
                log_error(f"CAT Verbindung fehlgeschlagen: {port} @ {baud}")
                self.status_bar_widget.setStyleSheet(self._STATUS_ERR)
                QTimer.singleShot(3000, lambda: (
                    self.btn_cat_con.setStyleSheet(self._CAT_BTN_OFF),
                    self.status_bar_widget.setStyleSheet(self._STATUS_OFF)))

        except Exception as e:
            self.btn_cat_con.setStyleSheet(self._CAT_BTN_ERR)
            self.status_label.setText(f" CAT Fehler: {e}")
            log_error(f"CAT Exception: {e}")
            self.status_bar_widget.setStyleSheet(self._STATUS_ERR)
            QTimer.singleShot(3000, lambda: (
                self.btn_cat_con.setStyleSheet(self._CAT_BTN_OFF),
                self.status_bar_widget.setStyleSheet(self._STATUS_OFF)))

    def _disconnect_cat(self):
        """CAT-Verbindung trennen — sofort connected=False, Polling stop, dann Serial close."""
        log_event("CAT Disconnect")
        # 1. CatHandler sofort als disconnected markieren (stoppt laufende Queries)
        if self._cat_handler:
            self._cat_handler.connected = False

        # 2. Polling sofort stoppen + GUI zurücksetzen
        if self.rig_widget and hasattr(self.rig_widget, "stop_polling"):
            self.rig_widget.stop_polling()

        # 3. Serial schließen im Hintergrund (falls Lock blockiert)
        def close_serial():
            if self._cat_handler:
                try:
                    if self._cat_handler._ser and self._cat_handler._ser.is_open:
                        self._cat_handler._ser.close()
                except Exception:
                    pass
                self._cat_handler._ser = None
                self._cat_handler = None

        threading.Thread(target=close_serial, daemon=True).start()

        self._cat_connected = False
        self.btn_cat_con.setStyleSheet(self._CAT_BTN_OFF)
        self.status_label.setText(" CAT: Getrennt")
        self.status_bar_widget.setStyleSheet(self._STATUS_OFF)
        self.tgl_vox.setChecked(False)

    def _on_rig_combo_changed(self, rig_name):
        """Rig-Wechsel über Top-Bar Combo."""
        if self._rig_switching:
            return
        # Radio Setup Combo synchronisieren
        self.radio_setup_overlay.combo_rig.setCurrentText(rig_name)
        self._on_rig_changed()

    def _on_rig_changed(self):
        """Rig-Widget neu laden nach Rig-Wechsel."""
        # Wenn verbunden, erst disconnecten
        if self._cat_connected:
            self._disconnect_cat()
        self._load_rig_widget()

        # last_rig in status_conf.json speichern
        rig_name = self.combo_rig_select.currentText()
        try:
            with open(self._status_conf_path) as f:
                cfg = json.load(f)
            cfg["last_rig"] = rig_name
            with open(self._status_conf_path, "w") as f:
                json.dump(cfg, f, indent=4)
        except Exception:
            pass

    def _toggle_demo_rec(self, checked):
        if not self.rig_widget or not hasattr(self.rig_widget, '_demo_recording'):
            return
        if checked:
            self.rig_widget.start_demo_recording()
        else:
            self.rig_widget.stop_demo_recording()

    def _toggle_vox(self, checked):
        log_action(f"VOX {'aktiviert' if checked else 'deaktiviert'}")
        if self.rig_widget and hasattr(self.rig_widget, "set_vox_enabled"):
            self.rig_widget.set_vox_enabled(checked)

    def _save_vox(self):
        thr = float(self.slider_vox_thr.value())
        hold = int(self.slider_vox_hold.value()) * 100
        if self.rig_widget and hasattr(self.rig_widget, "set_vox_params"):
            self.rig_widget.set_vox_params(thr, hold)

    def _apply_volume(self, val):
        """RX Volume an das Rig-Widget weiterleiten."""
        if self.rig_widget and hasattr(self.rig_widget, "_RX_GAIN"):
            self.rig_widget._RX_GAIN = float(val)
        if self._muted and val > 0:
            self._muted = False
            self.btn_mute.setStyleSheet(self._mute_style_on)

    def _toggle_mute(self):
        if not self._muted:
            self._muted = True
            self._vol_before_mute = self.slider_vol.value()
            self.slider_vol.setValue(0)
            if self.rig_widget and hasattr(self.rig_widget, "_RX_GAIN"):
                self.rig_widget._RX_GAIN = 0.0
            self.btn_mute.setStyleSheet(self._mute_style_off)
        else:
            self._muted = False
            self.slider_vol.setValue(self._vol_before_mute)
            self.btn_mute.setStyleSheet(self._mute_style_on)

    def _restart_audio(self):
        """Audio-Streams neu starten nach Config-Änderung."""
        if not self._cat_connected or not self.rig_widget:
            return
        if hasattr(self.rig_widget, "stop_audio"):
            self.rig_widget.stop_audio()
        config_path = ""
        if hasattr(self, "radio_setup_overlay"):
            config_path = self.radio_setup_overlay._config_path()
        if config_path and hasattr(self.rig_widget, "start_audio"):
            if self.rig_widget.start_audio(config_path):
                self.status_label.setText(" Audio neu gestartet")
            else:
                self.status_label.setText(" Audio Restart fehlgeschlagen")

    # ── Rig Widget laden ─────────────────────────────────────────────

    def _load_rig_widget(self):
        """Lade Rig-Widget: rig-spezifisch wenn vorhanden, sonst generisch."""
        # Altes Widget sauber entfernen
        if self.rig_widget:
            if hasattr(self.rig_widget, "stop_polling"):
                self.rig_widget.stop_polling()
            if hasattr(self.rig_widget, "stop_audio"):
                self.rig_widget.stop_audio()
            self.main_layout.removeWidget(self.rig_widget)
            self.rig_widget.deleteLater()
            self.rig_widget = None

        # Rig-Name aus Top-Bar Combo
        rig_name = ""
        if hasattr(self, "combo_rig_select"):
            rig_name = self.combo_rig_select.currentText()
        if not rig_name:
            return

        # "Yaesu FT-991A" → maker="yaesu", model="ft991a"
        parts = rig_name.split(" ", 1)
        if len(parts) != 2:
            return
        maker = parts[0].lower()
        model = parts[1].lower().replace("-", "")

        # UI-Datei laden: rig/yaesu/ft991a/ft991a_ui.py → FT991AWidget
        ui_file = os.path.join(_RIG_DIR, maker, model, f"{model}_ui.py")
        if not os.path.exists(ui_file):
            print(f"Kein UI für {rig_name}: {ui_file}")
            return

        module_path = f"rig.{maker}.{model}.{model}_ui"
        class_name = f"{parts[1].replace('-', '').upper()}Widget"

        try:
            import importlib
            mod = importlib.import_module(module_path)
            widget_class = getattr(mod, class_name)
            self.rig_widget = widget_class(self.central_widget)
            self.main_layout.insertWidget(1, self.rig_widget, stretch=1)
            print(f"Rig-Widget geladen: {class_name}")
            # Gespeicherte Slider-Werte wiederherstellen
            try:
                with open(self._status_conf_path) as f:
                    sliders = json.load(f).get("sliders", {})
                if hasattr(self.rig_widget, 'slider_signal') and "signal_gain" in sliders:
                    self.rig_widget.slider_signal.setValue(sliders["signal_gain"])
                if hasattr(self.rig_widget, 'slider_noise') and "noise_floor" in sliders:
                    self.rig_widget.slider_noise.setValue(sliders["noise_floor"])
            except Exception:
                pass
        except Exception as e:
            print(f"Rig-Widget laden fehlgeschlagen: {e}")


    # ── Configured Rigs ─────────────────────────────────────────────

    def _get_configured_rigs(self):
        """Liest configured_rigs aus status_conf.json. Fallback: alle gescannten Rigs."""
        try:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "configs", "status_conf.json")
            with open(path) as f:
                cfg = json.load(f)
            rigs = cfg.get("configured_rigs", [])
            if rigs:
                return rigs
        except Exception:
            pass
        return _scan_rigs()

    def _add_configured_rig(self, rig_name):
        """Fügt ein Rig zur configured_rigs Liste hinzu (nach Save im Radio Setup)."""
        try:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "configs", "status_conf.json")
            cfg = {}
            if os.path.exists(path):
                with open(path) as f:
                    cfg = json.load(f)
            rigs = cfg.get("configured_rigs", [])
            if rig_name not in rigs:
                rigs.append(rig_name)
                cfg["configured_rigs"] = rigs
                with open(path, "w") as f:
                    json.dump(cfg, f, indent=4)
                # Top-Bar Combo aktualisieren
                if self.combo_rig_select.findText(rig_name) == -1:
                    self.combo_rig_select.addItem(rig_name)
        except Exception as e:
            print(f"configured_rigs update fehlgeschlagen: {e}")

    def closeEvent(self, event):
        """Sauberen Exit markieren + Slider-Positionen speichern."""
        from core.session_logger import mark_clean_exit
        log_event("Fenster geschlossen (X-Button)")

        # Slider-Werte in status_conf.json speichern
        try:
            cfg = {}
            if os.path.exists(self._status_conf_path):
                with open(self._status_conf_path) as f:
                    cfg = json.load(f)
            cfg["sliders"] = {
                "volume": self.slider_vol.value(),
            }
            # Rig-Widget Slider
            if self.rig_widget:
                if hasattr(self.rig_widget, 'slider_signal'):
                    cfg["sliders"]["signal_gain"] = self.rig_widget.slider_signal.value()
                if hasattr(self.rig_widget, 'slider_noise'):
                    cfg["sliders"]["noise_floor"] = self.rig_widget.slider_noise.value()
            with open(self._status_conf_path, "w") as f:
                json.dump(cfg, f, indent=4)
        except Exception:
            pass

        mark_clean_exit()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
