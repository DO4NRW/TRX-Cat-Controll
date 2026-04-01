"""
Kenwood TS890S Rig-Widget — funktioniert mit jedem CAT-Backend.
Zeigt Frequenz, Mode, S-Meter, PTT, Power, DSP.
"""

import os
import re
import json
import platform
import subprocess
import threading
import numpy as np
import serial

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QComboBox, QSlider, QLineEdit,
                               QProgressBar, QFrame)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from core.theme import T, register_refresh

# ── Style Helpers ─────────────────────────────────────────────────────

def _BTN_DARK():
    return f"""QPushButton {{ background-color: {T['bg_mid']}; color: {T['text']};
        border: 1px solid {T['border']}; border-radius: 4px; padding: 4px 8px; font-size: 12px; }}
        QPushButton:hover {{ border-color: {T['border_hover']}; background-color: {T['bg_light']}; }}"""

def _BTN_ACTIVE():
    return f"""QPushButton {{ background-color: {T['bg_mid']}; color: {T['text']};
        border: 2px solid {T['accent']}; border-radius: 4px; padding: 4px 8px; font-size: 12px; font-weight: bold; }}
        QPushButton:hover {{ background-color: {T['bg_light']}; }}"""

_COMBO_STYLE = lambda: f"""QComboBox {{ background-color: {T['bg_mid']}; color: {T['text']};
    border: 1px solid {T['border']}; border-radius: 4px; padding: 4px; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{ background-color: {T['bg_mid']}; color: {T['text']};
    selection-background-color: {T['bg_light']}; border: 1px solid {T['border']}; }}"""

_INPUT_STYLE = lambda: f"""QLineEdit {{ background-color: {T['bg_mid']}; color: {T['text']};
    border: 1px solid {T['border']}; border-radius: 4px; padding: 4px 8px; }}
    QLineEdit:focus {{ border-color: {T['text']}; }}"""

_SLIDER_STYLE = lambda: f"""QSlider::groove:horizontal {{ background: {T['slider_groove']}; height: 6px; border-radius: 3px; }}
    QSlider::handle:horizontal {{ background: {T['slider_handle']}; width: 16px; margin: -5px 0; border-radius: 8px; }}
    QSlider::sub-page:horizontal {{ background: {T['slider_fill']}; border-radius: 3px; }}"""


class TS890SWidget(QWidget):
    """Kenwood TS890S Rig-Widget — funktioniert mit jedem CatBase-Backend."""

    _S_LABELS = ["S1","S2","S3","S4","S5","S6","S7","S8","S9","S9+10","S9+20","S9+40","S9+60"]
    _MODES = ["LSB", "USB", "CW", "FM"]
    _DIGI_MODES = ["DATA", "RTTY"]
    _STEPS = ["10","50","100","500","1000","2500","5000","10000","25000","100000"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cat = None
        self._current_mode = ""
        self._current_freq = 0
        self._ptt_active = False
        self._disconnecting = False
        self._smeter_smooth = 0.0
        self._current_preamp = "OFF"
        self._poll_timer = None
        self._poll_count = 0

        # Audio streams (PipeWire)
        self._pw_rx_rec = None
        self._pw_rx_play = None
        self._pw_tx_rec = None
        self._pw_tx_play = None
        self._tx_rms_db = -60.0
        self._RX_GAIN = 5.0

        # PTT Hardware
        self._ptt_method = "CAT"
        self._ptt_port = None
        self._ptt_ser = None
        self._ptt_invert = False

        # VOX
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

        self._build_ui()

        for cls in [QPushButton, QComboBox, QSlider]:
            for w in self.findChildren(cls):
                w.setFocusPolicy(Qt.NoFocus)

        register_refresh(self.refresh_theme)

    # ══════════════════════════════════════════════════════════════════
    # UI BUILD
    # ══════════════════════════════════════════════════════════════════

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(15, 10, 15, 10)
        root.setSpacing(8)

        # ── 1. Frequency Display ─────────────────────────────────────
        self.lbl_freq = QLabel("---.---.--- MHz")
        self.lbl_freq.setAlignment(Qt.AlignCenter)
        self.lbl_freq.setFont(QFont("Roboto", 32, QFont.Bold))
        self.lbl_freq.setStyleSheet(f"color: {T['text']}; font-size: 32px; border: none;")
        root.addWidget(self.lbl_freq)

        # ── 2. Tuning Row ────────────────────────────────────────────
        tune_row = QHBoxLayout()
        tune_row.setSpacing(6)

        self.btn_step_down = QPushButton("STEP <")
        self.btn_step_down.setStyleSheet(_BTN_DARK())
        self.btn_step_down.setMinimumHeight(32)
        self.btn_step_down.clicked.connect(lambda: self._step_freq(-1))
        tune_row.addWidget(self.btn_step_down, stretch=1)

        self.combo_step = QComboBox()
        self.combo_step.addItems(self._STEPS)
        self.combo_step.setCurrentText("100")
        self.combo_step.setMinimumWidth(80)
        self.combo_step.setStyleSheet(_COMBO_STYLE())
        tune_row.addWidget(self.combo_step, stretch=1)

        self.btn_step_up = QPushButton("STEP >")
        self.btn_step_up.setStyleSheet(_BTN_DARK())
        self.btn_step_up.setMinimumHeight(32)
        self.btn_step_up.clicked.connect(lambda: self._step_freq(1))
        tune_row.addWidget(self.btn_step_up, stretch=1)

        tune_row.addStretch(1)

        self.input_freq = QLineEdit()
        self.input_freq.setPlaceholderText("14.200.000")
        self.input_freq.setMinimumWidth(100)
        self.input_freq.setStyleSheet(_INPUT_STYLE())
        self.input_freq.setAlignment(Qt.AlignRight)
        self.input_freq.setFocusPolicy(Qt.ClickFocus)
        self.input_freq.returnPressed.connect(self._set_freq_from_input)
        tune_row.addWidget(self.input_freq, stretch=1)

        self.btn_set_freq = QPushButton("SET")
        self.btn_set_freq.setStyleSheet(f"""QPushButton {{ background-color: {T['bg_mid']}; color: {T['text']};
            border: 2px solid {T['accent']}; border-radius: 4px; padding: 4px 8px; font-weight: bold; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; }}""")
        self.btn_set_freq.setMinimumHeight(32)
        self.btn_set_freq.clicked.connect(self._set_freq_from_input)
        tune_row.addWidget(self.btn_set_freq, stretch=1)

        root.addLayout(tune_row)

        # ── 3. Mode Row ──────────────────────────────────────────────
        self.mode_buttons = {}
        self._digi_modifier = None

        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        for mode in self._MODES:
            btn = QPushButton(mode)
            btn.setMinimumHeight(28)
            btn.setStyleSheet(_BTN_DARK())
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, m=mode: self._set_mode(m))
            mode_row.addWidget(btn, stretch=1)
            self.mode_buttons[mode] = btn

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(2)
        mode_row.addWidget(sep)

        for digi in self._DIGI_MODES:
            btn = QPushButton(digi)
            btn.setMinimumHeight(28)
            btn.setStyleSheet(_BTN_DARK())
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, d=digi: self._toggle_digi_mode(d))
            mode_row.addWidget(btn, stretch=1)
            self.mode_buttons[digi] = btn

        root.addLayout(mode_row)

        # ── 4. DSP Row ───────────────────────────────────────────────
        dsp_row = QHBoxLayout()
        dsp_row.setSpacing(4)

        self.dsp_buttons = {}
        for name in ["ATT", "NB", "DNR", "DNF"]:
            btn = QPushButton(name)
            btn.setMinimumHeight(28)
            btn.setStyleSheet(_BTN_DARK())
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, n=name: self._toggle_dsp(n))
            dsp_row.addWidget(btn, stretch=1)
            self.dsp_buttons[name] = btn

        self.btn_preamp = QPushButton("AMP: OFF")
        self.btn_preamp.setMinimumHeight(32)
        self.btn_preamp.setStyleSheet(_BTN_DARK())
        self.btn_preamp.clicked.connect(self._cycle_preamp)
        dsp_row.addWidget(self.btn_preamp, stretch=1)

        root.addLayout(dsp_row)

        # ── 5. Power Slider ──────────────────────────────────────────
        pwr_row = QHBoxLayout()
        pwr_row.setSpacing(10)

        self.lbl_pwr = QLabel("PWR: 50")
        self.lbl_pwr.setStyleSheet(f"color: {T['text']}; font-size: 11px; border: none;")
        pwr_row.addWidget(self.lbl_pwr)

        self.slider_pwr = QSlider(Qt.Horizontal)
        self.slider_pwr.setRange(0, 100)
        self.slider_pwr.setValue(50)
        self.slider_pwr.setStyleSheet(_SLIDER_STYLE())
        self.slider_pwr.valueChanged.connect(lambda v: self.lbl_pwr.setText(f"PWR: {v}"))
        self.slider_pwr.sliderReleased.connect(self._apply_power)
        pwr_row.addWidget(self.slider_pwr, stretch=1)

        root.addLayout(pwr_row)

        # ── 6. S-Meter ───────────────────────────────────────────────
        self.lbl_smeter_info = QLabel("S-METER: ---")
        self.lbl_smeter_info.setStyleSheet(f"color: {T['text']}; font-size: 13px; border: none;")
        root.addWidget(self.lbl_smeter_info)

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

        self.smeter_bar = QProgressBar()
        self.smeter_bar.setFixedHeight(18)
        self.smeter_bar.setRange(0, 1000)
        self.smeter_bar.setValue(0)
        self.smeter_bar.setTextVisible(False)
        self.smeter_bar.setStyleSheet(f"""
            QProgressBar {{ background-color: {T['bg_dark']}; border: 1px solid {T['border']}; border-radius: 4px; }}
            QProgressBar::chunk {{ background-color: {T['smeter_bar']}; border-radius: 3px; }}""")
        root.addWidget(self.smeter_bar)

        # ── 7. TX Meter ──────────────────────────────────────────────
        self.lbl_tx_info = QLabel("TX: --- dBFS")
        self.lbl_tx_info.setStyleSheet(f"color: {T['text']}; font-size: 13px; border: none;")
        root.addWidget(self.lbl_tx_info)

        self.tx_bar = QProgressBar()
        self.tx_bar.setFixedHeight(18)
        self.tx_bar.setRange(0, 100)
        self.tx_bar.setValue(0)
        self.tx_bar.setTextVisible(False)
        self.tx_bar.setStyleSheet(f"""
            QProgressBar {{ background-color: {T['bg_dark']}; border: 1px solid {T['border']}; border-radius: 4px; }}
            QProgressBar::chunk {{ background-color: {T['tx_bar']}; border-radius: 3px; }}""")
        root.addWidget(self.tx_bar)

        # ── 8. PTT Button ────────────────────────────────────────────
        root.addStretch()

        self.btn_ptt = QPushButton("RX (SPACE)")
        self.btn_ptt.setFixedHeight(50)
        self.btn_ptt.setFont(QFont("Roboto", 20, QFont.Bold))
        self.btn_ptt.setStyleSheet(f"""QPushButton {{ background-color: {T['ptt_rx_bg']}; color: {T['text']};
            border: 2px solid {T['ptt_rx_border']}; border-radius: 8px; }}""")
        self.btn_ptt.pressed.connect(self._ptt_on)
        self.btn_ptt.released.connect(self._ptt_off)
        root.addWidget(self.btn_ptt)

    # ══════════════════════════════════════════════════════════════════
    # CAT ANBINDUNG
    # ══════════════════════════════════════════════════════════════════

    def set_cat_handler(self, cat):
        self._cat = cat
        self._poll_count = 0
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
        self.lbl_freq.setText("---.---.--- MHz")
        self.smeter_bar.setValue(0)
        self.lbl_smeter_info.setText("S-METER: ---")
        self.btn_preamp.setText("AMP: OFF")

    # ══════════════════════════════════════════════════════════════════
    # POLLING
    # ══════════════════════════════════════════════════════════════════

    def _poll(self):
        if not self._cat or not self._cat.connected:
            return

        self._poll_count += 1
        if self._poll_count <= 3:
            self._sync_rig_state()

        # Frequenz
        freq = self._cat.get_frequency()
        if freq is not None and freq != self._current_freq:
            self._current_freq = freq
            mhz_int = freq // 1_000_000
            khz_part = (freq % 1_000_000) // 1_000
            hz_part = freq % 1_000
            self.lbl_freq.setText(f"{mhz_int}.{khz_part:03d}.{hz_part:03d} MHz")

        # S-Meter
        raw = self._cat.get_smeter()
        if raw is not None:
            self._smeter_smooth = 0.8 * raw + 0.2 * self._smeter_smooth
            val = int(self._smeter_smooth)
            # Generische S-Meter Konvertierung (0-255 linear)
            s_val = min(13, val * 13 // 256)
            bar_val = int(val / 255 * 1000)
            self.smeter_bar.setValue(min(1000, bar_val))

            if val <= 128:
                s_str = f"S{min(9, val * 9 // 128)}"
            else:
                db_over = int((val - 128) / 127 * 60)
                s_str = f"S9+{db_over}dB"
            preamp = self._current_preamp or "OFF"
            self.lbl_smeter_info.setText(f"S-METER: {s_str} | {preamp}")
            self._update_s_labels(s_val)

        # TX-Meter + VOX
        self.update_tx_meter(self._tx_rms_db)
        self._vox_tick()

    def _sync_rig_state(self):
        if not self._cat:
            return

        mode = self._cat.get_mode()
        if mode is not None:
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
            elif mode == "AM":
                self._cat.set_mode("USB")
                self._current_mode = "USB"
                self._digi_modifier = None
            else:
                self._current_mode = mode
                self._digi_modifier = None
            self._update_mode_buttons()
            for d in self._DIGI_MODES:
                if d == self._digi_modifier:
                    self.mode_buttons[d].setStyleSheet(_BTN_ACTIVE())
                    self.mode_buttons[d].setChecked(True)
                else:
                    self.mode_buttons[d].setStyleSheet(_BTN_DARK())
                    self.mode_buttons[d].setChecked(False)

        preamp = self._cat.get_preamp()
        if preamp is not None:
            self._current_preamp = preamp
            self.btn_preamp.setText(f"AMP: {preamp}")

        att = self._cat.get_att()
        if att is not None:
            self.dsp_buttons["ATT"].setStyleSheet(_BTN_ACTIVE() if att else _BTN_DARK())

        pwr = self._cat.get_power()
        if pwr is not None:
            self.slider_pwr.blockSignals(True)
            self.slider_pwr.setValue(pwr)
            self.slider_pwr.blockSignals(False)
            self.lbl_pwr.setText(f"PWR: {pwr}")

    def _update_s_labels(self, active_idx):
        for i, lbl in enumerate(self.s_labels):
            if i <= active_idx:
                lbl.setStyleSheet(f"color: {T['smeter_label_active']}; font-size: 10px; font-weight: bold; border: none;")
            else:
                lbl.setStyleSheet(f"color: {T['smeter_label_inactive']}; font-size: 10px; font-weight: bold; border: none;")

    # ══════════════════════════════════════════════════════════════════
    # MODE
    # ══════════════════════════════════════════════════════════════════

    def _set_mode(self, mode):
        if not self._cat or not self._cat.connected:
            return
        if self._digi_modifier:
            combined = {"DATA": {"LSB": "D-L", "USB": "D-U"},
                       "RTTY": {"LSB": "RTTY", "USB": "RTTY-U"}}
            cat_mode = combined.get(self._digi_modifier, {}).get(mode, mode)
            self._cat.set_mode(cat_mode)
        else:
            self._cat.set_mode(mode)
        self._current_mode = mode
        self._update_mode_buttons()

    def _toggle_digi_mode(self, digi):
        if not self._cat or not self._cat.connected:
            return
        if self._digi_modifier == digi:
            self._digi_modifier = None
            self._cat.set_mode(self._current_mode or "USB")
        else:
            self._digi_modifier = digi
            base = self._current_mode or "USB"
            combined = {"DATA": {"LSB": "D-L", "USB": "D-U"},
                       "RTTY": {"LSB": "RTTY", "USB": "RTTY-U"}}
            cat_mode = combined.get(digi, {}).get(base, base)
            self._cat.set_mode(cat_mode)
        for d in self._DIGI_MODES:
            if d == self._digi_modifier:
                self.mode_buttons[d].setStyleSheet(_BTN_ACTIVE())
                self.mode_buttons[d].setChecked(True)
            else:
                self.mode_buttons[d].setStyleSheet(_BTN_DARK())
                self.mode_buttons[d].setChecked(False)
        self._update_mode_buttons()

    def _update_mode_buttons(self):
        for m, btn in self.mode_buttons.items():
            if m in self._DIGI_MODES:
                continue
            btn.setStyleSheet(_BTN_ACTIVE() if m == self._current_mode else _BTN_DARK())
            if self._digi_modifier:
                btn.setEnabled(m in ("LSB", "USB"))
            else:
                btn.setEnabled(True)

    # ══════════════════════════════════════════════════════════════════
    # DSP / PREAMP
    # ══════════════════════════════════════════════════════════════════

    def _toggle_dsp(self, name):
        if not self._cat or not self._cat.connected:
            return
        btn = self.dsp_buttons[name]
        on = btn.isChecked()
        if name == "ATT":
            self._cat.set_att(on)
        elif name == "NB":
            self._cat.set_nb(on)
        elif name == "DNR":
            self._cat.set_dnr(on)
        elif name == "DNF":
            self._cat.set_dnf(on)
        btn.setStyleSheet(_BTN_ACTIVE() if on else _BTN_DARK())

    def _cycle_preamp(self):
        if not self._cat or not self._cat.connected:
            return
        current = self.btn_preamp.text().replace("AMP: ", "")
        cycle = {"OFF": "AMP1", "IPO": "AMP1", "AMP1": "AMP2", "AMP2": "OFF"}
        new_mode = cycle.get(current, "OFF")
        self._cat.set_preamp(new_mode)
        self._current_preamp = new_mode
        self.btn_preamp.setText(f"AMP: {new_mode}")

    def _apply_power(self):
        if self._cat and self._cat.connected:
            self._cat.set_power(self.slider_pwr.value())

    # ══════════════════════════════════════════════════════════════════
    # FREQUENCY
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
            txt = self.input_freq.text().strip().replace(",", ".")
            parts = txt.split(".")
            if len(parts) == 3:
                hz = int(parts[0]) * 1_000_000 + int(parts[1]) * 1_000 + int(parts[2])
            else:
                hz = int(float(txt) * 1_000_000)
            self._cat.set_frequency(hz)
            self.input_freq.clear()
        except ValueError:
            pass
        self.input_freq.clearFocus()

    # ══════════════════════════════════════════════════════════════════
    # PTT
    # ══════════════════════════════════════════════════════════════════

    def _ptt_on(self):
        if self._ptt_active:
            return
        self._ptt_active = True
        self.btn_ptt.setText("TX")
        self.btn_ptt.setStyleSheet(f"""QPushButton {{ background-color: {T['ptt_tx_bg']}; color: {T['text']};
            border: 2px solid {T['ptt_tx_border']}; border-radius: 8px; }}""")
        # PTT Hardware
        if self._ptt_method in ("RTS", "DTR") and self._ptt_ser:
            active = not self._ptt_invert
            if self._ptt_method == "RTS":
                self._ptt_ser.setRTS(active)
            else:
                self._ptt_ser.setDTR(active)
        elif self._cat and self._cat.connected:
            self._cat.ptt_on()

    def _ptt_off(self):
        if not self._ptt_active:
            return
        self._ptt_active = False
        self.btn_ptt.setText("RX (SPACE)")
        self.btn_ptt.setStyleSheet(f"""QPushButton {{ background-color: {T['ptt_rx_bg']}; color: {T['text']};
            border: 2px solid {T['ptt_rx_border']}; border-radius: 8px; }}""")
        # PTT Hardware
        if self._ptt_method in ("RTS", "DTR") and self._ptt_ser:
            safe = self._ptt_invert
            if self._ptt_method == "RTS":
                self._ptt_ser.setRTS(safe)
            else:
                self._ptt_ser.setDTR(safe)
        elif self._cat and self._cat.connected:
            self._cat.ptt_off()

    # ══════════════════════════════════════════════════════════════════
    # TX METER / VOX
    # ══════════════════════════════════════════════════════════════════

    def update_tx_meter(self, db):
        self._tx_rms_db = db
        pct = max(0, min(100, int((db + 60) / 60 * 100)))
        self.tx_bar.setValue(pct)
        self.lbl_tx_info.setText(f"TX: {db:.0f} dBFS")

    def _vox_tick(self):
        if not self._vox_enabled or self._vox_mute:
            return
        import time
        now_ms = int(time.time() * 1000)
        if self._vox_lockout > 0 and now_ms < self._vox_lockout:
            return
        if self._tx_rms_db > self._vox_threshold:
            self._vox_debounce += 1
            if self._vox_debounce >= 2 and not self._vox_active:
                self._vox_active = True
                self._ptt_on()
            self._vox_hold_timer = now_ms + self._vox_hold_ms
        else:
            self._vox_debounce = 0
            if self._vox_active and now_ms > self._vox_hold_timer:
                self._vox_active = False
                self._ptt_off()
                self._vox_lockout = now_ms + self._vox_lockout_ms

    def set_vox_enabled(self, on):
        self._vox_enabled = on
        if not on and self._vox_active:
            self._vox_active = False
            self._ptt_off()

    # ══════════════════════════════════════════════════════════════════
    # AUDIO (PipeWire)
    # ══════════════════════════════════════════════════════════════════

    def _get_pw_node_name(self, device_str):
        """PipeWire node.name aus Config-String lesen."""
        m = re.search(r"\[pw:([^\]]+)\]", device_str)
        if not m:
            return None
        pw_val = m.group(1)
        if not pw_val.isdigit():
            return pw_val
        # Legacy: numerische ID
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

    def start_audio(self, config_path):
        """Audio-Streams starten basierend auf Rig-Config."""
        try:
            subprocess.run(["pkill", "-9", "-f", "pw-cat"],
                         capture_output=True, timeout=3)
            import time; time.sleep(0.5)
        except Exception:
            pass
        self._disconnecting = False
        self._config_path = config_path

        if not config_path or not os.path.exists(config_path):
            return False

        try:
            with open(config_path) as f:
                cfg = json.load(f)
        except Exception:
            return False

        # VOX Config
        vox_cfg = cfg.get("vox", {})
        self._vox_threshold = float(vox_cfg.get("threshold", -25))
        self._vox_hold_ms = int(vox_cfg.get("hold_ms", 700))

        # PTT Config
        ptt_cfg = cfg.get("ptt", {})
        self._ptt_method = ptt_cfg.get("method", "CAT").upper()
        self._ptt_invert = bool(ptt_cfg.get("invert", False))
        ptt_port = ptt_cfg.get("port", "")

        if self._ptt_method in ("RTS", "DTR") and ptt_port:
            try:
                self._ptt_ser = serial.Serial(
                    ptt_port, 38400, timeout=0.5, rtscts=False, dsrdtr=False)
                safe = self._ptt_invert
                self._ptt_ser.setRTS(safe)
                self._ptt_ser.setDTR(safe)
                print(f"PTT Port geöffnet: {ptt_port} ({self._ptt_method}, invert={self._ptt_invert})")
            except Exception as e:
                print(f"PTT Port Fehler: {e}")
                self._ptt_ser = None

        audio = cfg.get("audio")
        if not audio:
            return False

        pc_mic = audio.get("pc_mic", {})
        trx_mic = audio.get("trx_mic", {})
        trx_spk = audio.get("trx_speaker", {})
        pc_spk = audio.get("pc_speaker", {})

        if not any(d.get("device") for d in [pc_mic, trx_mic, trx_spk, pc_spk]):
            print("Audio: Keine Geräte konfiguriert")
            return False

        try:
            if platform.system() == "Linux":
                pw_pc_mic = self._get_pw_node_name(pc_mic.get("device", ""))
                pw_trx_mic = self._get_pw_node_name(trx_mic.get("device", ""))
                pw_trx_spk = self._get_pw_node_name(trx_spk.get("device", ""))
                pw_pc_spk = self._get_pw_node_name(pc_spk.get("device", ""))

                missing = []
                if not pw_pc_mic: missing.append("PC Mic")
                if not pw_trx_mic: missing.append("TRX Mic")
                if not pw_trx_spk: missing.append("TRX Spk")
                if not pw_pc_spk: missing.append("PC Spk")
                if missing:
                    print(f"Audio: PipeWire Nodes fehlen: {', '.join(missing)}")
                    return False

                pc_mic_sr = int(pc_mic.get("rate", 44100))
                trx_mic_sr = int(trx_mic.get("rate", 44100))
                trx_spk_sr = int(trx_spk.get("rate", 44100))
                pc_spk_sr = int(pc_spk.get("rate", 44100))
                pc_mic_ch = int(pc_mic.get("channels", 1))
                trx_mic_ch = int(trx_mic.get("channels", 1))
                trx_spk_ch = int(trx_spk.get("channels", 1))
                pc_spk_ch = int(pc_spk.get("channels", 1))

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

                self._rx_thread = threading.Thread(target=self._rx_routing_loop, daemon=True)
                self._rx_thread.start()
                self._tx_thread = threading.Thread(target=self._tx_routing_loop, daemon=True)
                self._tx_thread.start()

                print(f"Audio gestartet (PipeWire):")
                print(f"  RX: {pw_trx_mic} → {pw_pc_spk}")
                print(f"  TX: {pw_pc_mic} → {pw_trx_spk}")
                return True
        except Exception as e:
            print(f"Audio Fehler: {e}")
            return False

    def _rx_routing_loop(self):
        chunk = 1024 * 2
        silence = b'\x00' * chunk
        while not self._disconnecting:
            try:
                data = self._pw_rx_rec.stdout.read(chunk)
                if not data:
                    break
                if self._pw_rx_play and self._pw_rx_play.stdin:
                    if not self._ptt_active and self._RX_GAIN > 0:
                        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                        samples *= self._RX_GAIN
                        samples = np.clip(samples, -32768, 32767)
                        self._pw_rx_play.stdin.write(samples.astype(np.int16).tobytes())
                    else:
                        self._pw_rx_play.stdin.write(silence)
                    self._pw_rx_play.stdin.flush()
            except Exception:
                break

    def _tx_routing_loop(self):
        chunk = 1024 * 2
        silence = b'\x00' * chunk
        while not self._disconnecting:
            try:
                if self._pw_tx_rec is None:
                    import time; time.sleep(0.05)
                    continue
                data = self._pw_tx_rec.stdout.read(chunk)
                if not data:
                    break
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(samples ** 2))) / 32768.0
                self._tx_rms_db = max(-60.0, 20 * np.log10(max(rms, 1e-7)))
                if self._pw_tx_play and self._pw_tx_play.stdin:
                    if self._ptt_active:
                        self._pw_tx_play.stdin.write(data)
                    else:
                        self._pw_tx_play.stdin.write(silence)
                    self._pw_tx_play.stdin.flush()
            except Exception:
                if self._disconnecting:
                    break

    def stop_audio(self):
        self._disconnecting = True
        for p in ["_pw_rx_rec", "_pw_rx_play", "_pw_tx_rec", "_pw_tx_play"]:
            proc = getattr(self, p, None)
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
                setattr(self, p, None)
        if self._ptt_ser:
            try:
                self._ptt_ser.close()
            except Exception:
                pass
            self._ptt_ser = None

    # ══════════════════════════════════════════════════════════════════
    # THEME
    # ══════════════════════════════════════════════════════════════════

    def refresh_theme(self):
        self.lbl_freq.setStyleSheet(f"color: {T['text']}; font-size: 32px; border: none;")
        self.btn_step_down.setStyleSheet(_BTN_DARK())
        self.btn_step_up.setStyleSheet(_BTN_DARK())
        self.combo_step.setStyleSheet(_COMBO_STYLE())
        self.input_freq.setStyleSheet(_INPUT_STYLE())
        self.slider_pwr.setStyleSheet(_SLIDER_STYLE())
        self._update_mode_buttons()
