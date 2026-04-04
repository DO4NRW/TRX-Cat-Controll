import os
import sys
import json
import threading
import subprocess
import importlib

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                                QLabel, QPushButton, QSlider, QMenu, QProxyStyle,
                                QStyle, QLineEdit, QApplication)
from PySide6.QtGui import QIcon, QAction, QPainter, QColor, QPalette
from PySide6.QtCore import QSize, QPoint, Qt, QTimer
import PySide6.QtWidgets as _qtw

from core.theme import T, themed_icon, rgba_parts, register_refresh, apply_theme
from core.session_logger import log_action, log_event, log_error
from ui._constants import _ICONS, _RIG_DIR, _PROJECT_DIR

_UI_STATE_PATH = os.path.join(_PROJECT_DIR, "configs", "ui_state.json")
from ui._helpers import _scan_rigs, _scan_rigs_map
from ui.toggle import ToggleButton, ToggleGroup
from ui.radio_setup import RadioSetupOverlay
from ui.audio_setup import AudioSetupOverlay, DropDownComboBox
from ui.theme_editor import ThemeEditorOverlay
from ui.digi_panel import DigiPanelOverlay
from ui.logbook_panel import LogbookOverlay
from ui.eq_panel import EQOverlay


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

        logo_svg = os.path.join(_PROJECT_DIR, "PandaLogo.svg")
        logo_png = os.path.join(_PROJECT_DIR, "Logo.png")
        if os.path.exists(logo_png):
            self.setWindowIcon(QIcon(logo_png))
        elif os.path.exists(logo_svg):
            self.setWindowIcon(themed_icon(logo_svg))

        self._apply_window_bg()

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        self.top_layout = QHBoxLayout()
        self.top_layout.setSpacing(0)
        self.main_layout.addLayout(self.top_layout)

        # ── Main Menu ─────────────────────────────────────────────────
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

        self.action_digi = QAction("Digi-Modus", self)
        self.action_digi.setIcon(themed_icon(os.path.join(_ICONS, "radio.svg")))

        self.action_logbook = QAction("Logbuch", self)
        self.action_logbook.setIcon(themed_icon(os.path.join(_ICONS, "build.svg")))

        self.action_eq = QAction("EQ", self)
        self.action_eq.setIcon(themed_icon(os.path.join(_ICONS, "sound.svg")))

        self.main_menu.addAction(self.action_settings)
        self.main_menu.addAction(self.action_audio)
        self.main_menu.addAction(self.action_eq)
        self.main_menu.addAction(self.action_digi)
        self.main_menu.addAction(self.action_logbook)
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

        # Overlays
        self.radio_setup_overlay = RadioSetupOverlay(self.central_widget)
        self.action_settings.triggered.connect(lambda: (self.radio_setup_overlay.show_overlay(), self._check_gauge_visibility()))
        self.radio_setup_overlay.remote_connect_sig.connect(self._connect_cat_network)
        self.radio_setup_overlay.remote_disconnect_sig.connect(self._disconnect_cat)

        self.audio_setup_overlay = AudioSetupOverlay(self.central_widget)
        self.action_audio.triggered.connect(lambda: (self.audio_setup_overlay.show_overlay(), self._check_gauge_visibility()))

        self.theme_editor_overlay = ThemeEditorOverlay(self.central_widget)
        self.action_theme.triggered.connect(lambda: (self.theme_editor_overlay.show_overlay(), self._check_gauge_visibility()))

        # Digi + EQ: freistehende QDialog-Fenster (kein Vollbild-Overlay)
        self.digi_panel_overlay = DigiPanelOverlay(self)
        self.action_digi.triggered.connect(self.digi_panel_overlay.show)

        self.logbook_overlay = LogbookOverlay(self.central_widget)
        self.action_logbook.triggered.connect(lambda: (self.logbook_overlay.show_overlay(), self._check_gauge_visibility()))

        self.eq_overlay = EQOverlay(self)
        self.action_eq.triggered.connect(self.eq_overlay.show)

        # Gauge wieder zeigen wenn Overlay geschlossen wird (nur für Vollbild-Overlays)
        for overlay in [self.radio_setup_overlay, self.audio_setup_overlay, self.theme_editor_overlay, self.logbook_overlay]:
            orig_hide = overlay.hide
            def make_hide(oh):
                def patched_hide():
                    oh()
                    QTimer.singleShot(50, lambda: (self._update_top_smeter(), self._check_gauge_visibility()))
                return patched_hide
            overlay.hide = make_hide(orig_hide)

        def _open_report():
            log_action("Menü → Bug Report")
            from core.reporter import show_report_dialog
            show_report_dialog(self)
        self.action_report.triggered.connect(_open_report)

        self.top_layout.addStretch()

        # ── REC Button ───────────────────────────────────────────────
        self.tgl_demo_rec = ToggleButton("REC")
        self.tgl_demo_rec.toggled.connect(self._toggle_demo_rec)
        self.top_layout.addWidget(self.tgl_demo_rec)

        # ── VOX Controls ─────────────────────────────────────────────
        self.tgl_vox = ToggleButton("VOX")
        self.tgl_vox.toggled.connect(self._toggle_vox)
        self.top_layout.addWidget(self.tgl_vox)

        self.lbl_vox_thr = QLabel("THR:-25")
        self.lbl_vox_thr.setStyleSheet(f"color: {T['text']}; font-size: 10px; font-weight: bold;")
        self.lbl_vox_thr.setFixedWidth(44)
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
            self.lbl_vox_thr.setText(f"THR:{v}dB"), self._save_vox()))
        self.top_layout.addWidget(self.slider_vox_thr)

        self.lbl_vox_hold = QLabel("H:700")
        self.lbl_vox_hold.setStyleSheet(f"color: {T['text']}; font-size: 10px; font-weight: bold;")
        self.lbl_vox_hold.setFixedWidth(40)
        self.top_layout.addWidget(self.lbl_vox_hold)

        self.slider_vox_hold = QSlider(Qt.Horizontal)
        self.slider_vox_hold.setRange(1, 20)
        self.slider_vox_hold.setValue(7)
        self.slider_vox_hold.setFixedWidth(60)
        self.slider_vox_hold.setFixedHeight(24)
        self.slider_vox_hold.setFocusPolicy(Qt.NoFocus)
        self.slider_vox_hold.setToolTip("VOX Hold ms")
        self._apply_top_slider_style(self.slider_vox_hold, small=True)
        self.slider_vox_hold.valueChanged.connect(lambda v: (
            self.lbl_vox_hold.setText(f"H:{v * 100}ms"), self._save_vox()))
        self.top_layout.addWidget(self.slider_vox_hold)

        # ── RX Volume + Mute ─────────────────────────────────────────
        lbl_vol = QLabel("VOL")
        lbl_vol.setStyleSheet(f"color: {T['text']}; font-size: 11px; font-weight: bold;")
        self.lbl_vol = lbl_vol
        self.top_layout.addWidget(lbl_vol)

        self.slider_vol = QSlider(Qt.Horizontal)
        self.slider_vol.setRange(0, 20)
        _saved_vol = 1
        try:
            with open(_UI_STATE_PATH) as f:
                _saved_vol = json.load(f).get("sliders", {}).get("volume", 1)
        except Exception:
            pass
        self.slider_vol.setValue(_saved_vol)
        self.slider_vol.setFixedWidth(80)
        self.slider_vol.setFixedHeight(30)
        self.slider_vol.setFocusPolicy(Qt.NoFocus)
        self._apply_top_slider_style(self.slider_vol)
        self.slider_vol.valueChanged.connect(self._apply_volume)
        self.top_layout.addWidget(self.slider_vol)

        self._muted = False
        self._vol_before_mute = 5
        self._icon_vol_on = themed_icon(os.path.join(_ICONS, "volume_up.svg"))
        self._icon_vol_off = themed_icon(os.path.join(_ICONS, "volume_off.svg"))
        self.btn_mute = QPushButton()
        self.btn_mute.setFixedSize(32, 32)
        self.btn_mute.setIcon(self._icon_vol_on)
        self.btn_mute.setIconSize(QSize(20, 20))
        self.btn_mute.setFocusPolicy(Qt.NoFocus)
        self.btn_mute.setCursor(Qt.PointingHandCursor)
        self.btn_mute.setToolTip("Mute/Unmute")
        self._update_mute_styles()
        self.btn_mute.setStyleSheet(self._mute_style_on)
        self.btn_mute.clicked.connect(self._toggle_mute)
        self.top_layout.addWidget(self.btn_mute)

        self.top_layout.addSpacing(6)

        # ── Rig-Auswahl ──────────────────────────────────────────────
        self.combo_rig_select = DropDownComboBox()
        self.combo_rig_select.addItems(self._get_configured_rigs())
        self.combo_rig_select.setFixedHeight(40)
        self.combo_rig_select.setMinimumWidth(160)
        self.combo_rig_select.setFocusPolicy(Qt.NoFocus)
        self._apply_rig_combo_style()
        self.combo_rig_select.currentTextChanged.connect(self._on_rig_combo_changed)
        self.top_layout.addWidget(self.combo_rig_select)

        self._top_smeter = None

        self.top_layout.addSpacing(4)

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

        # ── Letztes Rig laden ────────────────────────────────────────
        self._status_conf_path = os.path.join(_PROJECT_DIR, "configs", "status_conf.json")
        self._rig_switching = False
        try:
            with open(self._status_conf_path) as f:
                status_cfg = json.load(f)
            last_rig = status_cfg.get("last_rig", "")
            if last_rig and self.combo_rig_select.findText(last_rig) != -1:
                self._rig_switching = True
                self.combo_rig_select.setCurrentText(last_rig)
                self.radio_setup_overlay.combo_rig.setCurrentText(last_rig)
                self._rig_switching = False
        except Exception:
            self._rig_switching = False

        # ── Rig Widget ───────────────────────────────────────────────
        self.rig_widget = None
        self._load_rig_widget()

        self.main_layout.addStretch()

        # ── Status-Bar ───────────────────────────────────────────────
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

        # NoFocus für alle interaktiven Widgets
        for cls in [_qtw.QAbstractButton, _qtw.QComboBox, _qtw.QAbstractSlider]:
            for w in self.findChildren(cls):
                w.setFocusPolicy(Qt.NoFocus)

    # ── Style-Methoden ───────────────────────────────────────────────

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

    def _apply_window_bg(self):
        r, g, b, a = rgba_parts(T['bg_dark'])
        tr, tg, tb, _ = rgba_parts(T['text'])
        bg_color = QColor(r, g, b, a)
        text_color = QColor(tr, tg, tb)

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

        self.setStyleSheet(f"QMainWindow {{ background-color: {T['bg_dark']}; }}")

    # ── Theme Refresh ────────────────────────────────────────────────

    def refresh_theme(self):
        self._apply_window_bg()
        self._apply_menu_btn_style()
        self._apply_menu_style()
        self._apply_rig_combo_style()
        self._update_cat_styles()
        self._update_status_styles()
        self._update_mute_styles()

        self.btn_menu.setIcon(themed_icon(os.path.join(_ICONS, "menu.svg")))
        self._icon_vol_on = themed_icon(os.path.join(_ICONS, "volume_up.svg"))
        self._icon_vol_off = themed_icon(os.path.join(_ICONS, "volume_off.svg"))
        self.btn_mute.setIcon(self._icon_vol_off if self._muted else self._icon_vol_on)
        self.btn_cat_con.setIcon(themed_icon(os.path.join(_ICONS, "connection.svg")))

        self.action_settings.setIcon(themed_icon(os.path.join(_ICONS, "radio.svg")))
        self.action_audio.setIcon(themed_icon(os.path.join(_ICONS, "sound.svg")))
        self.action_theme.setIcon(themed_icon(os.path.join(_ICONS, "settings.svg")))

        self.lbl_vox_thr.setStyleSheet(f"color: {T['text']}; font-size: 10px;")
        self.lbl_vox_hold.setStyleSheet(f"color: {T['text']}; font-size: 10px;")
        self.lbl_vol.setStyleSheet(f"color: {T['text']}; font-size: 11px; font-weight: bold;")
        self._apply_top_slider_style(self.slider_vox_thr, small=True)
        self._apply_top_slider_style(self.slider_vox_hold, small=True)
        self._apply_top_slider_style(self.slider_vol)

        if self._cat_connected:
            self.btn_cat_con.setStyleSheet(self._CAT_BTN_ON)
        else:
            self.btn_cat_con.setStyleSheet(self._CAT_BTN_OFF)

        if self._muted:
            self.btn_mute.setStyleSheet(self._mute_style_off)
        else:
            self.btn_mute.setStyleSheet(self._mute_style_on)

        self.status_bar_widget.setStyleSheet(self._STATUS_ON if self._cat_connected else self._STATUS_OFF)

        self.status_label.setStyleSheet(f"color: {T['text']}; padding-left: 10px; font-family: Consolas;")
        self.lbl_version.setStyleSheet(f"color: {T['text_secondary']}; font-size: 11px; padding-right: 8px;")

        self.action_report.setIcon(themed_icon(os.path.join(_ICONS, "bug_report.svg")))

        for tb in self.findChildren(ToggleButton):
            tb._load_icons()
            tb._update_icon(tb.isChecked())
            tb._apply_style()

        if self.rig_widget and hasattr(self.rig_widget, "refresh_theme"):
            self.rig_widget.refresh_theme()

        # Gauge erst updaten wenn kein Overlay offen ist
        any_open = (self.radio_setup_overlay.isVisible() or
                    self.audio_setup_overlay.isVisible() or
                    self.theme_editor_overlay.isVisible())
        if not any_open:
            self._update_top_smeter()

    # ── Keyboard (PTT) ───────────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            focus = QApplication.focusWidget()
            if isinstance(focus, QLineEdit):
                super().keyPressEvent(event)
                return
            if not event.isAutoRepeat() and self.rig_widget and hasattr(self.rig_widget, "_ptt_on"):
                if getattr(self.rig_widget, '_current_mode', '') == 'AM':
                    return
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
        rig_name = "Yaesu FT-991A"
        if hasattr(self, "combo_rig_select"):
            rig_name = self.combo_rig_select.currentText()
        if hasattr(self, "radio_setup_overlay") and hasattr(self.radio_setup_overlay, "combo_rig"):
            self.radio_setup_overlay.combo_rig.setCurrentText(rig_name)

        parts = rig_name.split(" ", 1)
        if len(parts) == 2:
            maker = parts[0].lower()
            model = parts[1].lower().replace("-", "")
            config_path = os.path.join(_RIG_DIR, maker, model, "config.json")
        else:
            config_path = ""
        log_event(f"Connect: {rig_name} → {config_path}")

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
        port = cat_cfg.get("port", "/dev/ttyUSB0")
        baud = int(cat_cfg.get("baud", 38400))

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

                if self.rig_widget and hasattr(self.rig_widget, "set_cat_handler"):
                    self.rig_widget.set_cat_handler(self._cat_handler)

                if self.rig_widget and hasattr(self.rig_widget, "start_audio"):
                    if self.rig_widget.start_audio(config_path):
                        self.status_label.setText(f" CAT+Audio: Verbunden ({port} @ {baud})")
                        self.slider_vox_thr.setValue(int(self.rig_widget._vox_threshold))
                        self.slider_vox_hold.setValue(int(self.rig_widget._vox_hold_ms) // 100)
                        self._apply_volume(self.slider_vol.value())
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
        log_event("CAT Disconnect")
        old_handler = self._cat_handler   # lokale Referenz sichern
        self._cat_handler = None          # sofort freigeben — kein Zugriff mehr vom Thread
        if old_handler:
            old_handler.connected = False

        if self.rig_widget:
            if hasattr(self.rig_widget, "stop_polling"):
                self.rig_widget.stop_polling()
            if hasattr(self.rig_widget, "stop_audio"):
                self.rig_widget.stop_audio()
        try:
            subprocess.run(["pkill", "-9", "-f", "pw-cat"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

        def close_handler(handler):      # handler als Parameter — kein self-Zugriff
            if handler:
                try:
                    handler.disconnect()
                except Exception:
                    pass

        threading.Thread(target=close_handler, args=(old_handler,), daemon=True).start()

        self._cat_connected = False
        self.btn_cat_con.setStyleSheet(self._CAT_BTN_OFF)
        self.status_label.setText(" CAT: Getrennt")
        self.status_bar_widget.setStyleSheet(self._STATUS_OFF)
        self.tgl_vox.setChecked(False)

    def _connect_cat_network(self, host: str, port: int):
        """Verbindet via TCP-CAT (NetworkCat / Hamlib rigctld)."""
        if self._cat_connected:
            self._disconnect_cat()

        log_event(f"Remote-Connect: {host}:{port}")
        try:
            from core.cat import create_cat_handler
            self._cat_handler = create_cat_handler("network", host=host, port=port)
            ok = self._cat_handler.connect()
        except Exception as e:
            ok = False
            log_error(f"NetworkCat Exception: {e}")

        overlay = getattr(self, "radio_setup_overlay", None)
        if ok:
            self._cat_connected = True
            self.btn_cat_con.setStyleSheet(self._CAT_BTN_ON)
            msg = f" CAT: Remote {host}:{port}"
            self.status_label.setText(msg)
            self.status_bar_widget.setStyleSheet(self._STATUS_ON)
            log_event(msg)
            if self.rig_widget and hasattr(self.rig_widget, "set_cat_handler"):
                self.rig_widget.set_cat_handler(self._cat_handler)
            if overlay:
                overlay.set_remote_status(True, f"Verbunden — {host}:{port}")
        else:
            self._cat_handler = None
            self.btn_cat_con.setStyleSheet(self._CAT_BTN_ERR)
            msg = f" CAT: Remote fehlgeschlagen ({host}:{port})"
            self.status_label.setText(msg)
            self.status_bar_widget.setStyleSheet(self._STATUS_ERR)
            log_error(msg)
            if overlay:
                overlay.set_remote_status(False, f"Verbindung fehlgeschlagen ({host}:{port})")
            QTimer.singleShot(3000, lambda: (
                self.btn_cat_con.setStyleSheet(self._CAT_BTN_OFF),
                self.status_bar_widget.setStyleSheet(self._STATUS_OFF)))

    def _on_rig_combo_changed(self, rig_name):
        if self._rig_switching or not rig_name:
            return
        if self._cat_connected:
            self._disconnect_cat()
        if self.rig_widget:
            if hasattr(self.rig_widget, "stop_polling"):
                self.rig_widget.stop_polling()
            if hasattr(self.rig_widget, "stop_audio"):
                self.rig_widget.stop_audio()
        if hasattr(self, 'radio_setup_overlay'):
            self._rig_switching = True
            self.radio_setup_overlay.combo_rig.setCurrentText(rig_name)
            self._rig_switching = False
        self._load_rig_widget()
        try:
            cfg = {}
            if os.path.exists(self._status_conf_path):
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
            self.btn_mute.setIcon(self._icon_vol_off)
            self.btn_mute.setStyleSheet(self._mute_style_off)
        else:
            self._muted = False
            self.slider_vol.setValue(self._vol_before_mute)
            self.btn_mute.setIcon(self._icon_vol_on)
            self.btn_mute.setStyleSheet(self._mute_style_on)

    def _restart_audio(self):
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
        if self.rig_widget:
            if hasattr(self.rig_widget, "stop_polling"):
                self.rig_widget.stop_polling()
            if hasattr(self.rig_widget, "stop_audio"):
                self.rig_widget.stop_audio()
            self.main_layout.removeWidget(self.rig_widget)
            self.rig_widget.deleteLater()
            self.rig_widget = None

        rig_name = ""
        if hasattr(self, "combo_rig_select"):
            rig_name = self.combo_rig_select.currentText()
        if not rig_name:
            return

        parts = rig_name.split(" ", 1)
        if len(parts) != 2:
            return
        maker = parts[0].lower()
        model = parts[1].lower().replace("-", "")

        ui_file = os.path.join(_RIG_DIR, maker, model, f"{model}_ui.py")
        if not os.path.exists(ui_file):
            print(f"Kein UI für {rig_name}: {ui_file}")
            return

        module_path = f"rig.{maker}.{model}.{model}_ui"
        class_name = f"{parts[1].replace('-', '').upper()}Widget"

        try:
            mod = importlib.import_module(module_path)
            widget_class = getattr(mod, class_name)
            self.rig_widget = widget_class(self.central_widget)
            self.main_layout.insertWidget(1, self.rig_widget, stretch=1)
            print(f"Rig-Widget geladen: {class_name}")
            try:
                with open(_UI_STATE_PATH) as f:
                    sliders = json.load(f).get("sliders", {})
                if hasattr(self.rig_widget, 'slider_signal') and "signal_gain" in sliders:
                    self.rig_widget.slider_signal.setValue(sliders["signal_gain"])
                if hasattr(self.rig_widget, 'slider_noise') and "noise_floor" in sliders:
                    self.rig_widget.slider_noise.setValue(sliders["noise_floor"])
            except Exception:
                pass
        except Exception as e:
            print(f"Rig-Widget laden fehlgeschlagen: {e}")

        self._update_top_smeter()

    def _update_top_smeter(self):
        """Gauge-Style S-Meter zwischen Top-Bar und Rig-Widget platzieren."""
        # Altes Top-SMeter entfernen
        if self._top_smeter:
            self.main_layout.removeWidget(self._top_smeter)
            self._top_smeter = None

        if not self.rig_widget or not hasattr(self.rig_widget, 'smeter_widget'):
            return

        style = T.get("smeter_style", "segment")
        if style in ("gauge", "classic", "dual", "rings"):
            rw = self.rig_widget
            # Gauge aus dem Rig-Widget Layout nehmen
            rw_layout = rw.layout()
            if rw_layout and rw_layout.indexOf(rw.smeter_widget) >= 0:
                rw_layout.removeWidget(rw.smeter_widget)
            rw.smeter_widget.setParent(self.central_widget)
            # Rechts bündig — Gauge wächst dynamisch mit dem Fenster
            gauge_row = QHBoxLayout()
            gauge_row.setContentsMargins(0, 0, 0, 0)
            gauge_row.addStretch(60)
            gauge_row.addWidget(rw.smeter_widget, stretch=40)
            self._gauge_container = QWidget(self.central_widget)
            self._gauge_container.setStyleSheet("background: transparent;")
            self._gauge_container.setLayout(gauge_row)
            self.main_layout.insertWidget(1, self._gauge_container)
            self._scale_gauge()
            self._top_smeter = self._gauge_container

    def _check_gauge_visibility(self):
        """Gauge aus/ein basierend auf Overlay-Status."""
        if not self._top_smeter:
            return
        any_open = (self.radio_setup_overlay.isVisible() or
                    self.audio_setup_overlay.isVisible() or
                    self.theme_editor_overlay.isVisible())
        if any_open:
            self._top_smeter.hide()
        else:
            self._top_smeter.show()

    def _scale_gauge(self):
        """Gauge-Höhe proportional zur Fensterhöhe skalieren."""
        if not self._top_smeter or not hasattr(self, '_gauge_container'):
            return
        win_h = self.height()
        # Skalierung: 640px Fenster → 80px Gauge, 1080px → 130px
        gauge_h = max(80, min(130, int(win_h * 0.12)))
        self._gauge_container.setFixedHeight(gauge_h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_gauge()

    # ── Configured Rigs ──────────────────────────────────────────────

    def _get_configured_rigs(self):
        try:
            path = os.path.join(_PROJECT_DIR, "configs", "status_conf.json")
            with open(path) as f:
                cfg = json.load(f)
            rigs = cfg.get("configured_rigs", [])
            if rigs:
                return rigs
        except Exception:
            pass
        return _scan_rigs()

    def _add_configured_rig(self, rig_name):
        try:
            path = os.path.join(_PROJECT_DIR, "configs", "status_conf.json")
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
                if self.combo_rig_select.findText(rig_name) == -1:
                    self.combo_rig_select.addItem(rig_name)
        except Exception as e:
            print(f"configured_rigs update fehlgeschlagen: {e}")

    def closeEvent(self, event):
        from core.session_logger import mark_clean_exit
        log_event("Fenster geschlossen (X-Button)")

        try:
            ui_state = {}
            if os.path.exists(_UI_STATE_PATH):
                with open(_UI_STATE_PATH) as f:
                    ui_state = json.load(f)
            ui_state["sliders"] = {
                "volume": self.slider_vol.value(),
            }
            if self.rig_widget:
                if hasattr(self.rig_widget, 'slider_signal'):
                    ui_state["sliders"]["signal_gain"] = self.rig_widget.slider_signal.value()
                if hasattr(self.rig_widget, 'slider_noise'):
                    ui_state["sliders"]["noise_floor"] = self.rig_widget.slider_noise.value()
            with open(_UI_STATE_PATH, "w") as f:
                json.dump(ui_state, f, indent=4)
        except Exception:
            pass

        mark_clean_exit()
        super().closeEvent(event)
