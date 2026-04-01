"""
FT-991A Rig Control Widget — wird in die MainWindow geladen.
Enthält: Frequenzanzeige, Tuning, Modus-Buttons, DSP-Tools,
Regler (DNR/Notch/Power), S-Meter, TX-Meter, PTT.
"""

import os
import json
import platform
import subprocess
import threading
import numpy as np
import sounddevice as sd
import serial
import re
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QProgressBar, QSlider, QFrame,
)
from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtGui import QIcon, QFont

from core.theme import T, register_refresh, unregister_refresh

_ICONS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "..", "..", "assets", "icons")

# ── Style-Generatoren (lesen immer aktuelle Theme-Werte) ─────────────

def _btn_style(bg=None, fg=None, bd=None, hover=None):
    return f"""
    QPushButton {{ background-color: {bg or T['bg_button']}; color: {fg or T['text_muted']};
                   border: 2px solid {bd or T['border']};
                   border-radius: 5px; font-size: 12px; font-weight: bold;
                   padding: 4px 10px; min-height: 30px; }}
    QPushButton:hover {{ background-color: {hover or T['bg_button_hover']}; }}"""

def _get_BTN_DARK():
    return _btn_style()

def _get_BTN_ACTIVE():
    return _btn_style(fg=T['text'], bd=T['accent'])

def _get_BTN_PTT_RX():
    return _btn_style()

def _get_BTN_PTT_TX():
    return _btn_style(bg=T['ptt_tx_bg'], fg=T['text'], bd=T['ptt_tx_border'],
                      hover=T['ptt_tx_bg'])

def _get_BTN_SET():
    return _btn_style(fg=T['text'], bd=T['accent'])

def _get_LABEL(color=None, size=13):
    return f"color: {color or T['text']}; font-size: {size}px; font-weight: bold; border: none;"

def _get_COMBO():
    return f"""
    QComboBox {{ background-color: {T['bg_mid']}; color: {T['text_secondary']}; border: 1px solid {T['border']};
                border-radius: 5px; padding: 4px 8px; font-size: 12px; min-height: 26px; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{ background-color: {T['bg_mid']}; color: {T['text_secondary']};
                selection-background-color: {T['bg_light']}; border: 1px solid {T['border']}; }}"""

def _get_INPUT():
    return f"""
    QLineEdit {{ background-color: {T['bg_mid']}; color: {T['text_secondary']}; border: 1px solid {T['border']};
                border-radius: 5px; padding: 4px 8px; font-size: 13px; }}"""

def _get_SLIDER():
    return f"""
    QSlider {{ min-height: 24px; }}
    QSlider::groove:horizontal {{ background: {T['slider_groove']}; height: 6px; border-radius: 3px; }}
    QSlider::handle:horizontal {{ background: {T['slider_handle']}; width: 16px; height: 16px; margin: -6px 0;
                                  border-radius: 8px; }}
    QSlider::sub-page:horizontal {{ background: {T['slider_fill']}; border-radius: 3px; }}"""

def _get_METER():
    return f"""
    QProgressBar {{ background-color: {T['bg_dark']}; border: 1px solid {T['border']}; border-radius: 4px; }}
    QProgressBar::chunk {{ background-color: {T['smeter_bar']}; border-radius: 3px; }}"""

# Rückwärtskompatibilität: Modul-Level Variablen (initial gesetzt)
_BTN_DARK   = _get_BTN_DARK()
_BTN_ACTIVE = _get_BTN_ACTIVE()
_BTN_PTT_RX = _get_BTN_PTT_RX()
_BTN_PTT_TX = _get_BTN_PTT_TX()
_BTN_SET    = _get_BTN_SET()
_LABEL = "color: {color}; font-size: {size}px; font-weight: bold; border: none;"
_COMBO  = _get_COMBO()
_INPUT  = _get_INPUT()
_SLIDER = _get_SLIDER()


class FT991AWidget(QWidget):
    """Rig-Control-Widget für Yaesu FT-991A."""

    # Signals für MainWindow
    ptt_changed = Signal(bool)  # True = TX

    # S-Meter Skala
    _S_LABELS = ["S0","S1","S2","S3","S4","S5","S6","S7","S8","S9",
                 "+10","+20","+40","+60"]

    # Kalibrierungstabelle: Raw-CAT-Wert → (S-Stufe, dBm)
    # Pro Preamp-Modus da die Empfindlichkeit anders ist
    # dBm-Werte basierend auf Standard S-Meter Kalibrierung (50 Ohm):
    # S1=-121, S2=-115, S3=-109, S4=-103, S5=-97, S6=-91, S7=-85, S8=-79, S9=-73
    # S9+10=-63, S9+20=-53, S9+40=-33, S9+60=-13
    _SMETER_CAL = {
        # ── IPO ──────────────────────────────────────────────────
        "IPO": [
            (0,   "S0",    -130),
            (12,  "S1",    -121),
            (28,  "S2",    -115),
            (48,  "S3",    -109),
            (70,  "S4",    -103),
            (95,  "S5",    -97),
            (118, "S6",    -91),
            (140, "S7",    -85),
            (160, "S8",    -79),
            (180, "S9",    -73),
            (200, "S9+10", -63),
            (220, "S9+20", -53),
            (238, "S9+40", -33),
            (255, "S9+60", -13),
        ],
        # ── AMP1 FM ──────────────────────────────────────────────
        "AMP1_FM": [
            (0,   "S0",    -130),
            (8,   "S1",    -121),
            (18,  "S2",    -115),
            (32,  "S3",    -109),
            (50,  "S4",    -103),
            (68,  "S5",    -97),
            (90,  "S6",    -91),
            (112, "S7",    -85),
            (138, "S8",    -79),
            (165, "S9",    -73),
            (195, "S9+10", -63),
            (222, "S9+20", -53),
            (242, "S9+40", -33),
            (255, "S9+60", -13),
        ],
        # ── AMP1 USB/LSB/CW/AM (SSB-Modi) ───────────────────────
        "AMP1": [
            (0,   "S0",    -130),
            (8,   "S1",    -121),
            (20,  "S2",    -115),
            (38,  "S3",    -109),
            (52,  "S4",    -103),
            (66,  "S5",    -97),
            (82,  "S6",    -91),
            (100, "S7",    -85),
            (122, "S8",    -79),
            (148, "S9",    -73),
            (182, "S9+10", -63),
            (212, "S9+20", -53),
            (240, "S9+40", -33),
            (255, "S9+60", -13),
        ],
        "AMP2": [
            (0,   "S0",    -150),
            (6,   "S1",    -141),
            (14,  "S2",    -135),
            (26,  "S3",    -129),
            (40,  "S4",    -123),
            (55,  "S5",    -117),
            (72,  "S6",    -111),
            (90,  "S7",    -105),
            (112, "S8",    -99),
            (128, "S9",    -93),
            (152, "S9+10", -83),
            (174, "S9+20", -73),
            (200, "S9+40", -53),
            (255, "S9+60", -33),
        ],
    }

    # Modes die als Buttons angezeigt werden
    _MODES = ["LSB", "USB", "CW", "FM", "AM"]
    _DIGI_MODES = ["DATA", "RTTY"]

    # Tuning Steps in Hz
    _STEPS = ["10","50","100","500","1000","2500","5000","6250",
              "8333","9000","10000","12500","25000","100000","1000000"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cat = None
        self._current_mode = ""
        self._current_freq = 0
        self._ptt_active = False
        self._disconnecting = False
        self._smeter_smooth = 0.0
        self._current_preamp = "IPO"
        self._poll_timer = None
        self._poll_count = 0

        # Audio streams
        self._st_rx_in = None   # TRX Mic → rx_input_cb
        self._st_rx_out = None  # → PC Speaker
        self._st_tx_in = None   # PC Mic → tx_input_cb
        self._st_tx_out = None  # → TRX Speaker
        self._tx_rms_db = -60.0

        # PTT Hardware
        self._ptt_method = "CAT"
        self._ptt_port = None
        self._ptt_ser = None
        self._ptt_invert = False

        self._build_ui()
        # Buttons/Combos/Slider auf NoFocus — QLineEdit bleibt fokussierbar für Eingabe
        for cls in [QPushButton, QComboBox, QSlider]:
            for w in self.findChildren(cls):
                w.setFocusPolicy(Qt.NoFocus)

        # Theme-Refresh registrieren
        register_refresh(self.refresh_theme)

    # ══════════════════════════════════════════════════════════════════
    # UI BUILD
    # ══════════════════════════════════════════════════════════════════

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(15, 10, 15, 10)
        root.setSpacing(8)

        # ── 1. Frequency Display ──────────────────────────────────────
        self.lbl_freq = QLabel("---.------ MHz")
        self.lbl_freq.setAlignment(Qt.AlignCenter)
        self.lbl_freq.setFont(QFont("Roboto", 32, QFont.Bold))
        self.lbl_freq.setStyleSheet(_get_LABEL(T['text'], 32))
        root.addWidget(self.lbl_freq)

        # ── 2. Tuning Row ────────────────────────────────────────────
        tune_row = QHBoxLayout()
        tune_row.setSpacing(6)

        self.btn_step_down = QPushButton("STEP <")
        self.btn_step_down.setStyleSheet(_BTN_DARK)
        self.btn_step_down.setMinimumHeight(32)
        self.btn_step_down.clicked.connect(lambda: self._step_freq(-1))
        tune_row.addWidget(self.btn_step_down, stretch=1)


        self.combo_step = QComboBox()
        self.combo_step.addItems(self._STEPS)
        self.combo_step.setCurrentText("100")
        self.combo_step.setMinimumWidth(80)
        self.combo_step.setStyleSheet(_COMBO)
        tune_row.addWidget(self.combo_step, stretch=1)

        self.btn_step_up = QPushButton("STEP >")
        self.btn_step_up.setStyleSheet(_BTN_DARK)
        self.btn_step_up.setMinimumHeight(32)
        self.btn_step_up.clicked.connect(lambda: self._step_freq(1))
        tune_row.addWidget(self.btn_step_up, stretch=1)

        tune_row.addStretch(1)

        self.input_freq = QLineEdit()
        self.input_freq.setPlaceholderText("Freq MHz")
        self.input_freq.setMinimumWidth(100)
        self.input_freq.setStyleSheet(_INPUT)
        self.input_freq.setAlignment(Qt.AlignRight)
        self.input_freq.setFocusPolicy(Qt.ClickFocus)
        self.input_freq.returnPressed.connect(self._set_freq_from_input)
        tune_row.addWidget(self.input_freq, stretch=1)

        self.btn_set_freq = QPushButton("SET")
        self.btn_set_freq.setStyleSheet(_BTN_SET)
        self.btn_set_freq.setMinimumHeight(32)
        self.btn_set_freq.clicked.connect(self._set_freq_from_input)
        tune_row.addWidget(self.btn_set_freq, stretch=1)

        root.addLayout(tune_row)

        # ── 3. Mode Row (Analog + Digital Modifier) ────────────────
        self.mode_buttons = {}
        self._digi_modifier = None  # "DATA" oder "RTTY" wenn aktiv

        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        for mode in self._MODES:
            btn = QPushButton(mode)
            btn.setMinimumHeight(28)
            btn.setStyleSheet(_BTN_DARK)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, m=mode: self._set_mode(m))
            mode_row.addWidget(btn, stretch=1)
            self.mode_buttons[mode] = btn

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(2)
        mode_row.addWidget(sep)

        # Digital Modifier Buttons
        for digi in self._DIGI_MODES:
            btn = QPushButton(digi)
            btn.setMinimumHeight(28)
            btn.setStyleSheet(_BTN_DARK)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, d=digi: self._toggle_digi_mode(d))
            mode_row.addWidget(btn, stretch=1)
            self.mode_buttons[digi] = btn

        root.addLayout(mode_row)

        # ── 4. DSP Tools Row ─────────────────────────────────────────
        dsp_row = QHBoxLayout()
        dsp_row.setSpacing(4)

        self.dsp_buttons = {}
        for name in ["ATT", "NB", "DNR", "DNF", "NOTCH"]:
            btn = QPushButton(name)
            btn.setMinimumHeight(28)
            btn.setStyleSheet(_BTN_DARK)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, n=name: self._toggle_dsp(n))
            dsp_row.addWidget(btn, stretch=1)
            self.dsp_buttons[name] = btn

        self.btn_preamp = QPushButton("AMP: IPO")
        self.btn_preamp.setMinimumHeight(32)
        self.btn_preamp.setStyleSheet(_BTN_DARK)
        self.btn_preamp.clicked.connect(self._cycle_preamp)
        dsp_row.addWidget(self.btn_preamp, stretch=1)

        root.addLayout(dsp_row)

        # ── 5. Sliders Row (DNR Level, Notch Freq, Power) ────────────
        slider_row = QHBoxLayout()
        slider_row.setSpacing(20)

        # DNR Level
        dnr_grp = QVBoxLayout()
        dnr_grp.setSpacing(2)
        self.lbl_dnr = QLabel("DNR: 5")
        self.lbl_dnr.setStyleSheet(_get_LABEL(T['text'], 10))
        dnr_grp.addWidget(self.lbl_dnr)
        self.slider_dnr = QSlider(Qt.Horizontal)
        self.slider_dnr.setRange(1, 15)
        self.slider_dnr.setValue(5)
        self.slider_dnr.setMinimumWidth(120)
        self.slider_dnr.setStyleSheet(_SLIDER)
        self.slider_dnr.valueChanged.connect(
            lambda v: self.lbl_dnr.setText(f"DNR: {v}"))
        self.slider_dnr.sliderReleased.connect(self._apply_dnr_level)
        dnr_grp.addWidget(self.slider_dnr)
        slider_row.addLayout(dnr_grp, stretch=1)

        # Notch Freq
        notch_grp = QVBoxLayout()
        notch_grp.setSpacing(2)
        self.lbl_notch = QLabel("NOTCH: 1000 Hz")
        self.lbl_notch.setStyleSheet(_get_LABEL(T['text'], 10))
        notch_grp.addWidget(self.lbl_notch)
        self.slider_notch = QSlider(Qt.Horizontal)
        self.slider_notch.setRange(10, 3200)
        self.slider_notch.setValue(1000)
        self.slider_notch.setMinimumWidth(120)
        self.slider_notch.setStyleSheet(_SLIDER)
        self.slider_notch.valueChanged.connect(
            lambda v: self.lbl_notch.setText(f"NOTCH: {v} Hz"))
        self.slider_notch.sliderReleased.connect(self._apply_notch_freq)
        notch_grp.addWidget(self.slider_notch)
        slider_row.addLayout(notch_grp, stretch=1)

        # Power
        pwr_grp = QVBoxLayout()
        pwr_grp.setSpacing(2)
        self.lbl_pwr = QLabel("PWR: 50")
        self.lbl_pwr.setStyleSheet(_get_LABEL(T['text'], 10))
        pwr_grp.addWidget(self.lbl_pwr)
        self.slider_pwr = QSlider(Qt.Horizontal)
        self.slider_pwr.setRange(5, 100)
        self.slider_pwr.setValue(50)
        self.slider_pwr.setMinimumWidth(120)
        self.slider_pwr.setStyleSheet(_SLIDER)
        self.slider_pwr.valueChanged.connect(
            lambda v: self.lbl_pwr.setText(f"PWR: {v}"))
        self.slider_pwr.sliderReleased.connect(self._apply_power)
        pwr_grp.addWidget(self.slider_pwr)
        slider_row.addLayout(pwr_grp, stretch=1)

        root.addLayout(slider_row)

        # ── 6. S-Meter ───────────────────────────────────────────────
        self.lbl_smeter_info = QLabel("S-METER: --- (S0 | IPO)")
        self.lbl_smeter_info.setStyleSheet(_get_LABEL(T['text'], 13))
        root.addWidget(self.lbl_smeter_info)

        # S-Meter Scale Labels
        scale_row = QHBoxLayout()
        scale_row.setSpacing(0)
        self.s_labels = []
        for s in self._S_LABELS:
            lbl = QLabel(s)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(f"color: {T['smeter_label_inactive']}; font-size: 10px; font-weight: bold; border: none;")
            scale_row.addWidget(lbl, stretch=1)
            self.s_labels.append(lbl)
        root.addLayout(scale_row)

        # S-Meter Bar — Range 0-1000 (Promille für feine Auflösung)
        self.smeter_bar = QProgressBar()
        self.smeter_bar.setFixedHeight(18)
        self.smeter_bar.setRange(0, 1000)
        self.smeter_bar.setValue(0)
        self.smeter_bar.setTextVisible(False)
        self.smeter_bar.setStyleSheet(_get_METER())
        root.addWidget(self.smeter_bar)

        # ── 7. TX Meter ──────────────────────────────────────────────
        self.lbl_tx_info = QLabel("TX: --- dBFS")
        self.lbl_tx_info.setStyleSheet(_get_LABEL(T['text'], 13))
        root.addWidget(self.lbl_tx_info)

        self.tx_bar = QProgressBar()
        self.tx_bar.setFixedHeight(18)
        self.tx_bar.setRange(0, 100)
        self.tx_bar.setValue(0)
        self.tx_bar.setTextVisible(False)
        self.tx_bar.setStyleSheet(f"""
            QProgressBar {{ background-color: {T['bg_dark']}; border: 1px solid {T['border']}; border-radius: 4px; }}
            QProgressBar::chunk {{ background-color: {T['tx_bar']}; border-radius: 3px; }}
        """)
        root.addWidget(self.tx_bar)

        # VOX State (UI wird in MainWindow Top-Bar gebaut)
        self._vox_enabled = False
        self._vox_mute = False
        self._vox_threshold = -25.0
        self._vox_hold_ms = 700
        self._vox_hold_timer = 0
        self._vox_active = False
        self._vox_debounce = 0
        self._vox_debounce_ms = 150
        self._vox_lockout = 0
        self._vox_lockout_ms = 500
        self._config_path = None

        # ── 9. PTT Button ───────────────────────────────────────────
        root.addStretch()

        self.btn_ptt = QPushButton("RX (SPACE)")
        self.btn_ptt.setFixedHeight(50)
        self.btn_ptt.setFont(QFont("Roboto", 20, QFont.Bold))
        self.btn_ptt.setStyleSheet(_BTN_PTT_RX)
        self.btn_ptt.pressed.connect(self._ptt_on)
        self.btn_ptt.released.connect(self._ptt_off)
        root.addWidget(self.btn_ptt)

    # ══════════════════════════════════════════════════════════════════
    # CAT ANBINDUNG
    # ══════════════════════════════════════════════════════════════════

    def set_cat_handler(self, cat):
        """CatHandler-Instanz setzen und Polling starten."""
        self._cat = cat
        self._poll_count = 0
        # Sofort ersten vollen Sync machen
        self._sync_rig_state()
        if self._poll_timer is None:
            self._poll_timer = QTimer(self)
            self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(150)

    def stop_polling(self):
        if self._poll_timer:
            self._poll_timer.stop()
        self._cat = None
        self.stop_audio()
        self._reset_display()

    def _reset_display(self):
        """Alle Anzeigen auf Default zurücksetzen."""
        self.lbl_freq.setText("---.------ MHz")
        # Mode Labels werden über Button-Styles angezeigt
        self.lbl_smeter_info.setText("S-METER: --- (S0 | IPO)")
        self.lbl_tx_info.setText("TX: --- dBFS")
        self.smeter_bar.setValue(0)
        self.tx_bar.setValue(0)
        self._smeter_smooth = 0.0
        self._current_freq = 0
        self._current_mode = ""
        self._ptt_active = False
        self.btn_ptt.setText("RX (SPACE)")
        self.btn_ptt.setStyleSheet(_get_BTN_PTT_RX())
        self.btn_preamp.setText("AMP: IPO")
        self._vox_enabled = False
        self._vox_active = False
        for btn in self.mode_buttons.values():
            btn.setStyleSheet(_get_BTN_DARK())
        for btn in self.dsp_buttons.values():
            btn.setChecked(False)
            btn.setStyleSheet(_get_BTN_DARK())
        for lbl in self.s_labels:
            lbl.setStyleSheet(f"color: {T['smeter_label_inactive']}; font-size: 10px; font-weight: bold; border: none;")

    # ══════════════════════════════════════════════════════════════════
    # AUDIO ROUTING
    # ══════════════════════════════════════════════════════════════════

    def _find_sd_index(self, device_name, need_input=False, need_output=False):
        """Finde sounddevice Device-Index anhand Name (aus Audio-Config).
        Versucht PipeWire-Name, dann Nick (ALSA-Name)."""
        if not device_name:
            return None

        # "[pw:33] Family 17h/19h ... (Ausgabe)" → clean name + pw_id
        pw_id = None
        m = re.search(r"\[pw:(\d+)\]", device_name)
        if m:
            pw_id = m.group(1)
        clean = re.sub(r"^\[.*?\]\s*", "", device_name).strip()
        clean = re.sub(r"\s*\((Eingang|Ausgabe)\)\s*$", "", clean).strip().lower()

        # Versuch 1: direkt matchen
        for i, d in enumerate(sd.query_devices()):
            if need_input and d["max_input_channels"] < 1: continue
            if need_output and d["max_output_channels"] < 1: continue
            if clean in d["name"].lower():
                return i

        # Versuch 2: PipeWire Nick (ALSA-Name) holen und matchen
        if pw_id:
            try:
                import subprocess
                out = subprocess.run(["pw-cli", "info", pw_id],
                    capture_output=True, text=True, timeout=2).stdout
                nick = None
                for line in out.splitlines():
                    if "node.nick" in line or "device.nick" in line:
                        nm = re.search(r'"(.+?)"', line)
                        if nm:
                            nick = nm.group(1)
                            break
                if nick:
                    nick_lower = nick.lower()
                    for i, d in enumerate(sd.query_devices()):
                        if need_input and d["max_input_channels"] < 1: continue
                        if need_output and d["max_output_channels"] < 1: continue
                        if nick_lower in d["name"].lower():
                            return i
            except Exception:
                pass

        # Versuch 3: Fallback auf "pulse" (PipeWire/PulseAudio Default)
        for i, d in enumerate(sd.query_devices()):
            if d["name"] == "pulse":
                if need_input and d["max_input_channels"] < 1: continue
                if need_output and d["max_output_channels"] < 1: continue
                print(f"Audio Fallback: '{device_name}' → pulse [{i}]")
                return i

        return None

    def _get_pw_id(self, device_str):
        """PipeWire Node-ID aus Config-String extrahieren."""
        m = re.search(r"\[pw:(\d+)\]", device_str)
        return m.group(1) if m else None

    def _get_pw_node_name(self, device_str):
        """PipeWire node.name für --target holen (node.name statt ID nötig)."""
        pw_id = self._get_pw_id(device_str)
        if not pw_id:
            return None
        try:
            out = subprocess.run(["pw-cli", "info", pw_id],
                capture_output=True, text=True, timeout=2).stdout
            for line in out.splitlines():
                if "node.name" in line:
                    m = re.search(r'"(.+?)"', line)
                    if m:
                        return m.group(1)
        except Exception:
            pass
        return pw_id  # Fallback auf ID

    def start_audio(self, config_path):
        """Audio-Streams öffnen basierend auf der Rig-Config."""
        self._disconnecting = False
        self._config_path = config_path

        if not config_path or not os.path.exists(config_path):
            print("Audio: Keine Config gefunden")
            return False

        try:
            with open(config_path) as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"Audio Config Fehler: {e}")
            return False

        # VOX Config laden
        vox_cfg = cfg.get("vox", {})
        self._vox_threshold = float(vox_cfg.get("threshold", -25))
        self._vox_hold_ms = int(vox_cfg.get("hold_ms", 700))

        # PTT Config laden
        ptt_cfg = cfg.get("ptt", {})
        self._ptt_method = ptt_cfg.get("method", "CAT").upper()
        self._ptt_invert = bool(ptt_cfg.get("invert", False))
        ptt_port = ptt_cfg.get("port", "")

        if self._ptt_method in ("RTS", "DTR") and ptt_port:
            try:
                self._ptt_ser = serial.Serial(
                    ptt_port, 38400, timeout=0.5,
                    rtscts=False, dsrdtr=False)
                safe = self._ptt_invert
                self._ptt_ser.setRTS(safe)
                self._ptt_ser.setDTR(safe)
                print(f"PTT Port geöffnet: {ptt_port} ({self._ptt_method}, invert={self._ptt_invert})")
            except Exception as e:
                print(f"PTT Port Fehler: {e}")
                self._ptt_ser = None

        audio = cfg.get("audio")
        if not audio:
            print("Audio: Kein audio-Block in Config")
            return False

        pc_mic  = audio.get("pc_mic", {})
        trx_mic = audio.get("trx_mic", {})
        trx_spk = audio.get("trx_speaker", {})
        pc_spk  = audio.get("pc_speaker", {})

        pc_mic_sr  = int(pc_mic.get("rate", 44100))
        trx_mic_sr = int(trx_mic.get("rate", 44100))
        trx_spk_sr = int(trx_spk.get("rate", 44100))
        pc_spk_sr  = int(pc_spk.get("rate", 44100))
        pc_mic_ch  = int(pc_mic.get("channels", 1))
        trx_mic_ch = int(trx_mic.get("channels", 1))
        trx_spk_ch = int(trx_spk.get("channels", 1))
        pc_spk_ch  = int(pc_spk.get("channels", 1))

        self._rx_out_ch = pc_spk_ch
        self._tx_out_ch = trx_spk_ch

        try:
            if platform.system() == "Linux":
                # PipeWire: alle 4 Streams via pw-cat (node.name für --target)
                pw_pc_mic  = self._get_pw_node_name(pc_mic.get("device", ""))
                pw_trx_mic = self._get_pw_node_name(trx_mic.get("device", ""))
                pw_trx_spk = self._get_pw_node_name(trx_spk.get("device", ""))
                pw_pc_spk  = self._get_pw_node_name(pc_spk.get("device", ""))

                missing = []
                if not pw_pc_mic:  missing.append(f"PC Mic ({pc_mic.get('device','')})")
                if not pw_trx_mic: missing.append(f"TRX Mic ({trx_mic.get('device','')})")
                if not pw_trx_spk: missing.append(f"TRX Spk ({trx_spk.get('device','')})")
                if not pw_pc_spk:  missing.append(f"PC Spk ({pc_spk.get('device','')})")
                if missing:
                    print(f"Audio: PipeWire-IDs fehlen: {', '.join(missing)}")
                    return False

                # RX: TRX Mic → PC Speaker
                self._pw_rx_rec = subprocess.Popen(
                    ["pw-cat", "--record", "--target", pw_trx_mic,
                     "--format", "s16", "--rate", str(trx_mic_sr), "--channels", str(trx_mic_ch), "-"],
                    stdout=subprocess.PIPE)
                self._pw_rx_play = subprocess.Popen(
                    ["pw-cat", "--playback", "--target", pw_pc_spk,
                     "--format", "s16", "--rate", str(pc_spk_sr), "--channels", str(pc_spk_ch), "-"],
                    stdin=subprocess.PIPE)

                # TX: PC Mic → TRX Speaker
                self._pw_tx_rec = subprocess.Popen(
                    ["pw-cat", "--record", "--target", pw_pc_mic,
                     "--format", "s16", "--rate", str(pc_mic_sr), "--channels", str(pc_mic_ch), "-"],
                    stdout=subprocess.PIPE)
                self._pw_tx_play = subprocess.Popen(
                    ["pw-cat", "--playback", "--target", pw_trx_spk,
                     "--format", "s16", "--rate", str(trx_spk_sr), "--channels", str(trx_spk_ch), "-"],
                    stdin=subprocess.PIPE)

                # Routing Threads
                self._rx_thread = threading.Thread(target=self._rx_routing_loop, daemon=True)
                self._rx_thread.start()
                self._tx_thread = threading.Thread(target=self._tx_routing_loop, daemon=True)
                self._tx_thread.start()

                print(f"Audio gestartet (PipeWire):")
                print(f"  TX: PC Mic [pw:{pw_pc_mic}] → TRX Spk [pw:{pw_trx_spk}]")
                print(f"  RX: TRX Mic [pw:{pw_trx_mic}] → PC Spk [pw:{pw_pc_spk}]")
            else:
                # Windows/Mac: sounddevice direkt
                idx_pc_mic  = self._find_sd_index(pc_mic.get("device", ""),  need_input=True)
                idx_trx_mic = self._find_sd_index(trx_mic.get("device", ""), need_input=True)
                idx_trx_spk = self._find_sd_index(trx_spk.get("device", ""), need_output=True)
                idx_pc_spk  = self._find_sd_index(pc_spk.get("device", ""),  need_output=True)

                if any(x is None for x in [idx_pc_mic, idx_trx_mic, idx_trx_spk, idx_pc_spk]):
                    print("Audio: Geräte nicht gefunden")
                    return False

                self._st_rx_out = sd.OutputStream(device=idx_pc_spk, samplerate=pc_spk_sr,
                    channels=pc_spk_ch, dtype="float32", blocksize=1024)
                self._st_rx_in = sd.InputStream(device=idx_trx_mic, samplerate=trx_mic_sr,
                    channels=trx_mic_ch, dtype="float32", blocksize=1024, callback=self._rx_input_cb)
                self._st_tx_out = sd.OutputStream(device=idx_trx_spk, samplerate=trx_spk_sr,
                    channels=trx_spk_ch, dtype="float32", blocksize=1024)
                self._st_tx_in = sd.InputStream(device=idx_pc_mic, samplerate=pc_mic_sr,
                    channels=pc_mic_ch, dtype="float32", blocksize=1024, callback=self._tx_input_cb)

                for s in [self._st_rx_out, self._st_rx_in, self._st_tx_out, self._st_tx_in]:
                    s.start()
                print("Audio gestartet (sounddevice)")

            return True

        except Exception as e:
            print(f"Audio Stream Fehler: {e}")
            import traceback; traceback.print_exc()
            self.stop_audio()
            return False

    _RX_GAIN = 5.0  # Verstärkung für RX Audio (TRX → PC Speaker)

    def _rx_routing_loop(self):
        """Thread: TRX Mic → PC Speaker (nur wenn nicht PTT)."""
        chunk = 1024 * 2  # s16 mono = 2 bytes/sample
        while not self._disconnecting:
            try:
                data = self._pw_rx_rec.stdout.read(chunk)
                if not data:
                    break
                if not self._ptt_active and self._RX_GAIN > 0 and self._pw_rx_play and self._pw_rx_play.stdin:
                    # Gain anwenden
                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                    samples *= self._RX_GAIN
                    samples = np.clip(samples, -32768, 32767)
                    amplified = samples.astype(np.int16).tobytes()
                    self._pw_rx_play.stdin.write(amplified)
                    self._pw_rx_play.stdin.flush()
            except Exception:
                break

    def _tx_routing_loop(self):
        """Thread: PC Mic → TRX Speaker (nur wenn PTT aktiv)."""
        chunk = 1024 * 2  # s16 mono = 2 bytes/sample
        while not self._disconnecting:
            try:
                data = self._pw_tx_rec.stdout.read(chunk)
                if not data:
                    break

                # TX-Meter berechnen
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(samples ** 2))) / 32768.0
                self._tx_rms_db = max(-60.0, 20 * np.log10(max(rms, 1e-7)))

                # Nur senden wenn PTT aktiv
                if self._ptt_active and self._pw_tx_play and self._pw_tx_play.stdin:
                    self._pw_tx_play.stdin.write(data)
                    self._pw_tx_play.stdin.flush()
            except Exception:
                break

    def stop_audio(self):
        """Alle Audio-Streams/Prozesse stoppen."""
        self._disconnecting = True

        # sounddevice Streams
        for s in [self._st_tx_in, self._st_tx_out, self._st_rx_in, self._st_rx_out]:
            if s is None: continue
            try: s.stop()
            except Exception: pass
            try: s.close()
            except Exception: pass
        self._st_tx_in = self._st_tx_out = self._st_rx_in = self._st_rx_out = None

        # pw-cat Prozesse
        for p in ["_pw_rx_rec", "_pw_rx_play", "_pw_tx_rec", "_pw_tx_play"]:
            proc = getattr(self, p, None)
            if proc:
                try: proc.terminate()
                except Exception: pass
                setattr(self, p, None)

        # PTT Port
        if self._ptt_ser:
            try:
                safe = self._ptt_invert
                self._ptt_ser.setRTS(safe)
                self._ptt_ser.setDTR(safe)
                self._ptt_ser.close()
            except Exception: pass
            self._ptt_ser = None
        print("Audio+PTT gestoppt")

    def _tx_input_cb(self, indata, frames, time_info, status):
        """PC Mic → TRX Speaker (Windows/Mac only, Linux uses _tx_routing_loop)."""
        if self._disconnecting:
            return
        try:
            mono = indata[:, [0]] if indata.shape[1] > 1 else indata
            rms = float(np.sqrt(np.mean(np.square(mono))))
            self._tx_rms_db = max(-60.0, 20 * np.log10(max(rms, 1e-7)))

            if self._ptt_active and self._st_tx_out is not None:
                out = np.column_stack((mono, mono)) if self._tx_out_ch == 2 else mono
                try: self._st_tx_out.write(out)
                except Exception: pass
        except Exception:
            pass

    def _rx_input_cb(self, indata, frames, time_info, status):
        """TRX Mic → PC Speaker (Windows/Mac only, Linux uses _rx_routing_loop)."""
        if self._disconnecting:
            return
        try:
            if not self._ptt_active and self._st_rx_out is not None:
                mono = indata[:, [0]] if indata.shape[1] > 1 else indata
                out = np.column_stack((mono, mono)) if self._rx_out_ch == 2 else mono
                try: self._st_rx_out.write(out)
                except Exception: pass
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════
    # POLLING / UPDATE
    # ══════════════════════════════════════════════════════════════════

    def _poll(self):
        """Wird alle 120ms aufgerufen — liest Rig-Status."""
        if not self._cat or not self._cat.connected:
            return

        # Frequenz jedes Mal abfragen
        freq = self._cat.get_frequency()
        if freq is not None and freq != self._current_freq:
            self._current_freq = freq
            mhz = freq / 1_000_000
            self.lbl_freq.setText(f"{mhz:.6f} MHz")

        # S-Meter jedes Mal
        raw = self._cat.get_smeter()
        if raw is not None:
            # Fast direkt, nur minimal geglättet
            self._smeter_smooth = 0.8 * raw + 0.2 * self._smeter_smooth
            val = int(self._smeter_smooth)
            preamp = self._current_preamp or "IPO"
            s_str, dbm, active_idx = self._raw_to_s_dbm(val, preamp)
            cal = self._get_cal(preamp)
            # Interpoliere zwischen den Labels
            frac = 0.0
            if active_idx < len(cal) - 1:
                r0 = cal[active_idx][0]
                r1 = cal[active_idx + 1][0]
                if r1 > r0:
                    frac = min(1.0, (val - r0) / (r1 - r0))
            bar_val = int((active_idx + frac) / 13 * 1000)
            self.smeter_bar.setValue(min(1000, bar_val))
            self.lbl_smeter_info.setText(f"S-METER: {s_str} | {dbm:.0f} dBm | {preamp}")
            self._update_s_labels(active_idx)

        # TX-Meter aktualisieren + VOX
        self.update_tx_meter(self._tx_rms_db)
        self._vox_tick()

    def _sync_rig_state(self):
        """Liest Frequenz, Mode, Preamp und DSP-Status vom Rig."""
        if not self._cat:
            return

        mode = self._cat.get_mode()
        if mode is not None:
            # Digi-Modes auf Base-Mode + Modifier aufteilen
            if mode in ("D-L", "DATA-L"):
                self._current_mode = "LSB"
                self._digi_modifier = "DATA"
            elif mode in ("D-U", "DATA-U"):
                self._current_mode = "USB"
                self._digi_modifier = "DATA"
            elif mode in ("RTTY", "RTTY-L"):
                self._current_mode = "LSB"
                self._digi_modifier = "RTTY"
            elif mode == "RTTY-U":
                self._current_mode = "USB"
                self._digi_modifier = "RTTY"
            else:
                self._current_mode = mode
                self._digi_modifier = None
            self._update_mode_buttons()
            # Digi-Modifier Buttons updaten
            for d in self._DIGI_MODES:
                if d == self._digi_modifier:
                    self.mode_buttons[d].setStyleSheet(_get_BTN_ACTIVE())
                    self.mode_buttons[d].setChecked(True)
                else:
                    self.mode_buttons[d].setStyleSheet(_get_BTN_DARK())
                    self.mode_buttons[d].setChecked(False)

        preamp = self._cat.get_preamp()
        if preamp is not None:
            self._current_preamp = preamp
            self.btn_preamp.setText(f"AMP: {preamp}")

        att = self._cat.get_att()
        if att is not None:
            self.dsp_buttons["ATT"].setStyleSheet(_get_BTN_ACTIVE() if att else _get_BTN_DARK())

        pwr = self._cat.get_power()
        if pwr is not None:
            self.slider_pwr.blockSignals(True)
            self.slider_pwr.setValue(pwr)
            self.slider_pwr.blockSignals(False)
            self.lbl_pwr.setText(f"PWR: {pwr}")

        dnr_lvl = self._cat.get_dnr_level()
        if dnr_lvl is not None:
            self.slider_dnr.blockSignals(True)
            self.slider_dnr.setValue(dnr_lvl)
            self.slider_dnr.blockSignals(False)
            self.lbl_dnr.setText(f"DNR: {dnr_lvl}")

    def _get_cal(self, preamp):
        """Kalibrierungstabelle: erst preamp_mode versuchen, dann preamp allein."""
        mode = self._current_mode or ""
        key = f"{preamp}_{mode}"
        if key in self._SMETER_CAL:
            return self._SMETER_CAL[key]
        return self._SMETER_CAL.get(preamp, self._SMETER_CAL["IPO"])

    def _raw_to_s_dbm(self, raw, preamp="IPO"):
        """Raw CAT-Wert → (S-String, dBm, Index) mit linearer Interpolation."""
        cal = self._get_cal(preamp)

        # Unter Minimum
        if raw <= cal[0][0]:
            return cal[0][1], cal[0][2], 0

        # Zwischen zwei Kalibrierungspunkten interpolieren
        for i in range(1, len(cal)):
            if raw <= cal[i][0]:
                r0, s0, d0 = cal[i-1]
                r1, s1, d1 = cal[i]
                frac = (raw - r0) / max(1, r1 - r0)
                dbm = d0 + frac * (d1 - d0)
                idx = i if frac >= 0.8 else i - 1
                s_str = s1 if frac >= 0.8 else s0
                return s_str, round(dbm, 1), idx

        # Über Maximum
        return cal[-1][1], cal[-1][2], len(cal) - 1

    def _update_s_labels(self, active_idx):
        """S-Meter Skala-Labels hervorheben bis active_idx."""
        for i, lbl in enumerate(self.s_labels):
            if i <= active_idx:
                lbl.setStyleSheet(f"color: {T['smeter_label_active']}; font-size: 10px; font-weight: bold; border: none;")
            else:
                lbl.setStyleSheet(f"color: {T['smeter_label_inactive']}; font-size: 10px; font-weight: bold; border: none;")

    # ══════════════════════════════════════════════════════════════════
    # ACTIONS
    # ══════════════════════════════════════════════════════════════════

    def _step_freq(self, direction):
        if not self._cat or not self._cat.connected:
            return
        step = int(self.combo_step.currentText()) * direction
        self._cat.step_frequency(step)

    def _set_freq_from_input(self):
        if not self._cat or not self._cat.connected:
            return
        try:
            mhz = float(self.input_freq.text().replace(",", "."))
            hz = int(mhz * 1_000_000)
            self._cat.set_frequency(hz)
            self.input_freq.clear()
        except ValueError:
            pass
        # Focus rausnehmen damit Leertaste wieder PTT ist
        self.input_freq.clearFocus()
        self.setFocus()

    def _set_mode(self, mode):
        if not self._cat or not self._cat.connected:
            return
        # Wenn Digi-Modifier aktiv: kombinieren
        if self._digi_modifier and mode in ("LSB", "USB"):
            if self._digi_modifier == "DATA":
                combined = "D-L" if mode == "LSB" else "D-U"
            else:  # RTTY
                combined = "RTTY" if mode == "LSB" else "RTTY"
                # RTTY-L = LSB, RTTY-U = USB
                combined = "RTTY-L" if mode == "LSB" else "RTTY-U"
            self._cat.set_mode(combined)
        elif self._digi_modifier and mode not in ("LSB", "USB"):
            # CW/FM/AM: Digi-Modifier deaktivieren
            self._digi_modifier = None
            for d in self._DIGI_MODES:
                self.mode_buttons[d].setStyleSheet(_get_BTN_DARK())
                self.mode_buttons[d].setChecked(False)
            self._cat.set_mode(mode)
        else:
            self._cat.set_mode(mode)
        self._sync_rig_state()
        self._update_mode_buttons()

    def _toggle_digi_mode(self, digi):
        """DATA oder RTTY Modifier an/aus schalten."""
        if self._digi_modifier == digi:
            # Ausschalten → zurück auf reinen Mode
            self._digi_modifier = None
            self.mode_buttons[digi].setStyleSheet(_get_BTN_DARK())
            self.mode_buttons[digi].setChecked(False)
            # Aktuellen Base-Mode neu setzen (LSB/USB)
            base = self._current_mode
            if base in ("LSB", "USB") and self._cat and self._cat.connected:
                self._cat.set_mode(base)
        else:
            # Anderer Digi aus, diesen an
            for d in self._DIGI_MODES:
                self.mode_buttons[d].setStyleSheet(_get_BTN_DARK())
                self.mode_buttons[d].setChecked(False)
            self._digi_modifier = digi
            self.mode_buttons[digi].setStyleSheet(_get_BTN_ACTIVE())
            self.mode_buttons[digi].setChecked(True)
            # Wenn LSB oder USB aktiv: sofort kombiniert senden
            if self._current_mode in ("LSB", "USB") and self._cat and self._cat.connected:
                self._set_mode(self._current_mode)
                return
            # Sonst: auf USB wechseln als Standard
            if self._cat and self._cat.connected:
                self._set_mode("USB")
                return
        self._update_mode_buttons()

    def _update_mode_buttons(self):
        """Mode-Buttons visuell aktualisieren."""
        for m, btn in self.mode_buttons.items():
            if m in self._DIGI_MODES:
                continue  # Digi-Buttons separat
            if m == self._current_mode:
                btn.setStyleSheet(_get_BTN_ACTIVE())
            else:
                btn.setStyleSheet(_get_BTN_DARK())
            # Bei Digi-Modifier: nur LSB/USB klickbar, sonst alles frei
            if self._digi_modifier:
                btn.setEnabled(m in ("LSB", "USB"))
            else:
                btn.setEnabled(True)

    def _toggle_dsp(self, name):
        if not self._cat or not self._cat.connected:
            return
        btn = self.dsp_buttons[name]
        on = btn.isChecked()
        btn.setStyleSheet(_get_BTN_ACTIVE() if on else _get_BTN_DARK())

        if name == "ATT":
            self._cat.set_att(on)
        elif name == "NB":
            self._cat.set_nb(on)
        elif name == "DNR":
            self._cat.set_dnr(on)
        elif name == "DNF":
            self._cat.set_dnf(on)
        elif name == "NOTCH":
            # Notch On/Off
            if self._cat._ser:
                with self._cat._lock:
                    self._cat._raw_send(f"BP0000{'1' if on else '0'};")

    def _cycle_preamp(self):
        if not self._cat or not self._cat.connected:
            return
        current = self.btn_preamp.text().replace("AMP: ", "")
        cycle = {"IPO": "AMP1", "AMP1": "AMP2", "AMP2": "IPO"}
        new_mode = cycle.get(current, "IPO")
        self._cat.set_preamp(new_mode)
        self._current_preamp = new_mode
        self.btn_preamp.setText(f"AMP: {new_mode}")

    def _apply_dnr_level(self):
        if not self._cat or not self._cat.connected:
            return
        level = self.slider_dnr.value()
        self._cat.set_dnr_level(level)

    def _apply_notch_freq(self):
        if not self._cat or not self._cat.connected:
            return
        freq = self.slider_notch.value()
        val = freq // 10
        if self._cat._ser:
            with self._cat._lock:
                self._cat._raw_send(f"BP01{val:03d};")

    def set_vox_enabled(self, checked):
        """Wird von MainWindow aufgerufen."""
        self._vox_enabled = checked
        if not self._vox_enabled and self._vox_active:
            self._vox_active = False
            self._ptt_off()

    def set_vox_params(self, threshold, hold_ms):
        """Wird von MainWindow aufgerufen wenn THR/HOLD geändert werden."""
        self._vox_threshold = threshold
        self._vox_hold_ms = hold_ms
        # Auto-Save in Rig-Config
        if self._config_path and os.path.exists(self._config_path):
            try:
                with open(self._config_path) as f:
                    cfg = json.load(f)
                cfg["vox"] = {
                    "threshold": self._vox_threshold,
                    "hold_ms": self._vox_hold_ms,
                }
                with open(self._config_path, "w") as f:
                    json.dump(cfg, f, indent=4)
            except Exception as e:
                print(f"VOX save Fehler: {e}")

    def _vox_tick(self):
        """VOX Logik mit Debounce + Lockout — wird im Poll aufgerufen."""
        if not self._vox_enabled:
            return
        poll_ms = 150

        # Sperrzeit nach VOX-Release (RX-Audio kommt rein, darf nicht re-triggern)
        if self._vox_lockout > 0:
            self._vox_lockout -= poll_ms
            return

        if self._tx_rms_db >= self._vox_threshold:
            self._vox_debounce += poll_ms
            self._vox_hold_timer = self._vox_hold_ms

            if not self._vox_active and self._vox_debounce >= self._vox_debounce_ms:
                self._vox_active = True
                self._ptt_on()
        else:
            self._vox_debounce = 0
            if self._vox_active and self._vox_hold_timer > 0:
                self._vox_hold_timer -= poll_ms
                if self._vox_hold_timer <= 0:
                    self._vox_active = False
                    self._ptt_off()
                    self._vox_lockout = self._vox_lockout_ms  # Sperrzeit starten

    def _apply_power(self):
        if not self._cat or not self._cat.connected:
            return
        self._cat.set_power(self.slider_pwr.value())


    def _ptt_on(self):
        if not self._cat or not self._cat.connected:
            return
        self._ptt_active = True
        self.btn_ptt.setText("TX (SPACE)")
        self.btn_ptt.setStyleSheet(_get_BTN_PTT_TX())
        self._set_ptt_hardware(True)
        self.ptt_changed.emit(True)

    def _ptt_off(self):
        if not self._cat or not self._cat.connected:
            return
        self._ptt_active = False
        self.btn_ptt.setText("RX (SPACE)")
        self.btn_ptt.setStyleSheet(_get_BTN_PTT_RX())
        self._set_ptt_hardware(False)
        self.ptt_changed.emit(False)

    def _set_ptt_hardware(self, tx: bool):
        """PTT schalten nach konfigurierter Methode (RTS/DTR/CAT/VOX)."""
        safe = self._ptt_invert
        active = not safe

        if self._ptt_method == "CAT":
            if tx:
                self._cat.ptt_on()
            else:
                self._cat.ptt_off()
        elif self._ptt_method == "RTS" and self._ptt_ser:
            try:
                self._ptt_ser.setRTS(active if tx else safe)
            except Exception as e:
                print(f"PTT RTS Fehler: {e}")
        elif self._ptt_method == "DTR" and self._ptt_ser:
            try:
                self._ptt_ser.setDTR(active if tx else safe)
            except Exception as e:
                print(f"PTT DTR Fehler: {e}")
        # VOX: nichts tun, Audio-Level steuert den TRX

    # ══════════════════════════════════════════════════════════════════
    # TX METER (wird von Audio-Engine aufgerufen)
    # ══════════════════════════════════════════════════════════════════

    def update_tx_meter(self, dbfs: float):
        """TX-Meter aktualisieren. dbfs: -60..0"""
        level = max(0, min(100, int((dbfs + 60) / 60 * 100)))
        self.tx_bar.setValue(level)
        self.lbl_tx_info.setText(f"TX: {dbfs:.1f} dBFS")

    # ══════════════════════════════════════════════════════════════════
    # THEME REFRESH
    # ══════════════════════════════════════════════════════════════════

    def refresh_theme(self):
        """Alle Styles mit aktuellen Theme-Werten neu setzen (vom Mittelsmann aufgerufen)."""
        # Freq Display
        self.lbl_freq.setStyleSheet(_get_LABEL(T['text'], 32))

        # Tuning Buttons
        self.btn_step_down.setStyleSheet(_get_BTN_DARK())
        self.btn_step_up.setStyleSheet(_get_BTN_DARK())
        self.btn_set_freq.setStyleSheet(_get_BTN_SET())
        self.combo_step.setStyleSheet(_get_COMBO())
        self.input_freq.setStyleSheet(_get_INPUT())

        # Mode Buttons
        for m, btn in self.mode_buttons.items():
            if m == self._current_mode:
                btn.setStyleSheet(_get_BTN_ACTIVE())
            else:
                btn.setStyleSheet(_get_BTN_DARK())

        # DSP Buttons
        for name, btn in self.dsp_buttons.items():
            btn.setStyleSheet(_get_BTN_ACTIVE() if btn.isChecked() else _get_BTN_DARK())
        self.btn_preamp.setStyleSheet(_get_BTN_DARK())

        # Sliders
        for slider in [self.slider_dnr, self.slider_notch, self.slider_pwr]:
            slider.setStyleSheet(_get_SLIDER())

        # Labels
        self.lbl_dnr.setStyleSheet(_get_LABEL(T['text'], 10))
        self.lbl_notch.setStyleSheet(_get_LABEL(T['text'], 10))
        self.lbl_pwr.setStyleSheet(_get_LABEL(T['text'], 10))
        self.lbl_smeter_info.setStyleSheet(_get_LABEL(T['text'], 13))
        self.lbl_tx_info.setStyleSheet(_get_LABEL(T['text'], 13))

        # Meters
        self.smeter_bar.setStyleSheet(_get_METER())
        self.tx_bar.setStyleSheet(f"""
            QProgressBar {{ background-color: {T['bg_dark']}; border: 1px solid {T['border']}; border-radius: 4px; }}
            QProgressBar::chunk {{ background-color: {T['tx_bar']}; border-radius: 3px; }}
        """)

        # S-Labels
        for lbl in self.s_labels:
            lbl.setStyleSheet(f"color: {T['smeter_label_inactive']}; font-size: 10px; font-weight: bold; border: none;")

        # PTT Button
        if self._ptt_active:
            self.btn_ptt.setStyleSheet(_get_BTN_PTT_TX())
        else:
            self.btn_ptt.setStyleSheet(_get_BTN_PTT_RX())

    def destroy(self, *args, **kwargs):
        unregister_refresh(self.refresh_theme)
        super().destroy(*args, **kwargs)

    # ══════════════════════════════════════════════════════════════════
    # KEYBOARD
    # ══════════════════════════════════════════════════════════════════

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._ptt_on()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._ptt_off()
        else:
            super().keyReleaseEvent(event)
