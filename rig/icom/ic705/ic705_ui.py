"""
Icom IC705 Rig-Widget — funktioniert mit jedem CAT-Backend.
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
from core.session_logger import log_action, log_event, log_error

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


class _SegmentedMeter(QWidget):
    """S-Meter als segmentierte Blöcke mit Tick-Marks oben."""
    def __init__(self, segments, parent=None):
        super().__init__(parent)
        self._segments = segments
        self._value = 0  # 0-1000
        from PySide6.QtGui import QPainter, QColor, QPen

    def setValue(self, val):
        self._value = val
        self.update()

    def value(self):
        return self._value

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QColor, QPen
        from PySide6.QtCore import QRect
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        n = self._segments
        gap = 2
        tick_h = 4

        # Tick-Marks oben (vertikale Striche)
        r, g, b, _ = __import__('core.theme', fromlist=['rgba_parts']).rgba_parts(
            T.get('smeter_label_inactive', 'rgba(136,136,136,255)'))
        tick_color = QColor(r, g, b)
        p.setPen(QPen(tick_color, 1))
        for i in range(n):
            cx = int((i + 0.5) * w / n)
            p.drawLine(cx, 0, cx, tick_h)

        # Segmente
        bar_y = tick_h + 1
        bar_h = h - bar_y
        seg_w = w / n
        fill_frac = self._value / 1000.0
        fill_segments = fill_frac * n

        # Hintergrund
        bg_r, bg_g, bg_b, _ = __import__('core.theme', fromlist=['rgba_parts']).rgba_parts(
            T.get('bg_dark', 'rgba(26,26,26,255)'))
        border_r, border_g, border_b, _ = __import__('core.theme', fromlist=['rgba_parts']).rgba_parts(
            T.get('border', 'rgba(85,85,85,255)'))
        bar_r, bar_g, bar_b, _ = __import__('core.theme', fromlist=['rgba_parts']).rgba_parts(
            T.get('smeter_bar', 'rgba(6,198,164,255)'))

        for i in range(n):
            x = int(i * seg_w) + gap // 2
            sw = int(seg_w) - gap
            rect = QRect(x, bar_y, sw, bar_h)

            if i < int(fill_segments):
                # Voller Block
                p.fillRect(rect, QColor(bar_r, bar_g, bar_b))
            elif i < fill_segments:
                # Teilweise gefüllt (letzter Block)
                p.fillRect(rect, QColor(bg_r, bg_g, bg_b))
                part_w = int(sw * (fill_segments - int(fill_segments)))
                p.fillRect(QRect(x, bar_y, part_w, bar_h), QColor(bar_r, bar_g, bar_b))
            else:
                # Leer
                p.fillRect(rect, QColor(bg_r, bg_g, bg_b))

            # Border
            p.setPen(QPen(QColor(border_r, border_g, border_b), 1))
            p.drawRect(rect)

        p.end()


class IC705Widget(QWidget):
    """Icom IC705 Rig-Widget — funktioniert mit jedem CatBase-Backend."""

    _S_LABELS = ["S1","S2","S3","S4","S5","S6","S7","S8","S9","S9+10","S9+20","S9+40","S9+60"]
    _MODES = ["LSB", "USB", "CW", "CW-R", "FM", "RTTY", "RTTY-R"]
    _DIGI_MODES = ["DATA"]
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
        self._demo_recording = False
        self._demo_frames = []
        self._demo_start = 0

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

        # ── 0. Waterfall / Spectrum ───────────────────────────────────
        from core.waterfall import WaterfallWidget

        # Span-Slider
        span_row = QHBoxLayout()
        span_row.setSpacing(6)
        self.lbl_span = QLabel("SPAN: TRX")
        self.lbl_span.setStyleSheet(f"color: {T['text_secondary']}; font-size: 10px; border: none;")
        span_row.addWidget(self.lbl_span)
        self.slider_span = QSlider(Qt.Horizontal)
        self.slider_span.setRange(0, 6)
        self.slider_span.setValue(3)
        self.slider_span.setStyleSheet(_SLIDER_STYLE())
        self.slider_span.valueChanged.connect(self._update_span_label)
        self.slider_span.sliderReleased.connect(self._apply_span)
        span_row.addWidget(self.slider_span, stretch=1)
        root.addLayout(span_row)

        self._SPAN_VALUES = [
            (2500, "2.5 kHz"), (5000, "5 kHz"), (10000, "10 kHz"),
            (50000, "50 kHz"), (100000, "100 kHz"), (250000, "250 kHz"),
            (500000, "500 kHz"),
        ]

        self.waterfall = WaterfallWidget(self, num_points=475, max_amp=160)
        self.waterfall.setMinimumHeight(180)
        self.waterfall.frequency_clicked.connect(self._on_waterfall_click)
        self.waterfall.frequency_scrolled.connect(self._on_waterfall_scroll)
        self.waterfall.filter_changed.connect(self._on_filter_changed)
        self.waterfall.installEventFilter(self)

        # Wasserfall + Contrast-Slider in HLayout
        wf_row = QHBoxLayout()
        wf_row.setSpacing(4)
        wf_row.addWidget(self.waterfall, stretch=1)

        # Wasserfall-Regler (vertikal, rechts neben Wasserfall)
        slider_col = QVBoxLayout()
        slider_col.setSpacing(2)

        _vslider_style = f"""
            QSlider::groove:vertical {{ background: {T['slider_groove']}; width: 4px; border-radius: 2px; }}
            QSlider::handle:vertical {{ background: {T['slider_handle']}; height: 12px; margin: 0 -4px; border-radius: 6px; }}
            QSlider::sub-page:vertical {{ background: {T['slider_fill']}; border-radius: 2px; }}"""

        lbl_sig = QLabel("SIG")
        lbl_sig.setStyleSheet(f"color: {T['text_muted']}; font-size: 8px; border: none;")
        lbl_sig.setAlignment(Qt.AlignCenter)
        slider_col.addWidget(lbl_sig)
        self.slider_signal = QSlider(Qt.Vertical)
        self.slider_signal.setRange(10, 60)  # color_gain * 10 (1.0 - 6.0)
        self.slider_signal.setValue(30)       # Default 3.0
        self.slider_signal.setFixedWidth(16)
        self.slider_signal.setToolTip("Signal Kontrast")
        self.slider_signal.setFocusPolicy(Qt.NoFocus)
        self.slider_signal.setStyleSheet(_vslider_style)
        self.slider_signal.valueChanged.connect(self._apply_signal_gain)
        slider_col.addWidget(self.slider_signal, stretch=1)

        lbl_nf = QLabel("NF")
        lbl_nf.setStyleSheet(f"color: {T['text_muted']}; font-size: 8px; border: none;")
        lbl_nf.setAlignment(Qt.AlignCenter)
        slider_col.addWidget(lbl_nf)
        self.slider_noise = QSlider(Qt.Vertical)
        self.slider_noise.setRange(0, 30)  # black_level 0-30
        self.slider_noise.setValue(3)      # Default 3
        self.slider_noise.setFixedWidth(16)
        self.slider_noise.setToolTip("Rausch-Filter (Black Level)")
        self.slider_noise.setFocusPolicy(Qt.NoFocus)
        self.slider_noise.setStyleSheet(_vslider_style)
        self.slider_noise.valueChanged.connect(self._apply_noise_floor)
        slider_col.addWidget(self.slider_noise, stretch=1)

        wf_row.addLayout(slider_col)

        root.addLayout(wf_row, stretch=1)

        # ── 1. Frequency Display (versteckt — Freq-Leiste im Wasserfall zeigt es)
        self.lbl_freq = QLabel("")
        self.lbl_freq.setFixedHeight(0)
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
        self.combo_step.currentTextChanged.connect(
            lambda t: self.waterfall.set_step_hz(int(t)) if t.isdigit() else None)
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

        # ── 4. DSP Row (IC-705 spezifisch) ──────────────────────────
        dsp_row = QHBoxLayout()
        dsp_row.setSpacing(4)

        self.dsp_buttons = {}
        for name in ["ATT", "NB", "NR", "NOTCH", "COMP"]:
            btn = QPushButton(name)
            btn.setMinimumHeight(28)
            btn.setStyleSheet(_BTN_DARK())
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, n=name: self._toggle_dsp(n))
            dsp_row.addWidget(btn, stretch=1)
            self.dsp_buttons[name] = btn

        self.btn_preamp = QPushButton("P.AMP: OFF")
        self.btn_preamp.setMinimumHeight(32)
        self.btn_preamp.setStyleSheet(_BTN_DARK())
        self.btn_preamp.clicked.connect(self._cycle_preamp)
        dsp_row.addWidget(self.btn_preamp, stretch=1)

        # AGC Button (SLOW/MID/FAST)
        self.btn_agc = QPushButton("AGC: SLOW")
        self.btn_agc.setMinimumHeight(32)
        self.btn_agc.setStyleSheet(_BTN_DARK())
        self.btn_agc.clicked.connect(self._cycle_agc)
        dsp_row.addWidget(self.btn_agc, stretch=1)

        root.addLayout(dsp_row)

        # ── 5. Power Slider ──────────────────────────────────────────
        pwr_row = QHBoxLayout()
        pwr_row.setSpacing(6)

        self.lbl_pwr = QLabel("PWR: 50")
        self.lbl_pwr.setStyleSheet(f"color: {T['text']}; font-size: 11px; border: none;")
        pwr_row.addWidget(self.lbl_pwr)

        self.slider_pwr = QSlider(Qt.Horizontal)
        self.slider_pwr.setRange(0, 255)
        self.slider_pwr.setValue(128)
        self.slider_pwr.setStyleSheet(_SLIDER_STYLE())
        self.slider_pwr.valueChanged.connect(lambda v: self.lbl_pwr.setText(f"PWR: {v * 10 / 255:.1f}W"))
        self.slider_pwr.sliderReleased.connect(self._apply_power)
        pwr_row.addWidget(self.slider_pwr, stretch=1)

        root.addLayout(pwr_row)

        # ── 5b. PBT Slider (BW + SFT wie IC-705 Twin PBT) ───────
        pbt_row = QHBoxLayout()
        pbt_row.setSpacing(6)

        self.lbl_bw = QLabel("BW: 0")
        self.lbl_bw.setStyleSheet(f"color: {T['text']}; font-size: 11px; border: none;")
        self.lbl_bw.setFixedWidth(55)
        pbt_row.addWidget(self.lbl_bw)

        self.slider_pbt_inner = QSlider(Qt.Horizontal)
        self.slider_pbt_inner.setRange(0, 255)
        self.slider_pbt_inner.setValue(128)
        self.slider_pbt_inner.setStyleSheet(_SLIDER_STYLE())
        self.slider_pbt_inner.setToolTip("PBT Inner (Bandbreite)")
        self.slider_pbt_inner.valueChanged.connect(self._update_pbt_labels)
        self.slider_pbt_inner.sliderReleased.connect(self._apply_pbt)
        pbt_row.addWidget(self.slider_pbt_inner, stretch=1)

        self.lbl_sft = QLabel("SFT: 0")
        self.lbl_sft.setStyleSheet(f"color: {T['text']}; font-size: 11px; border: none;")
        self.lbl_sft.setFixedWidth(50)
        pbt_row.addWidget(self.lbl_sft)

        self.slider_pbt_outer = QSlider(Qt.Horizontal)
        self.slider_pbt_outer.setRange(0, 255)
        self.slider_pbt_outer.setValue(128)
        self.slider_pbt_outer.setStyleSheet(_SLIDER_STYLE())
        self.slider_pbt_outer.setToolTip("PBT Outer (Shift)")
        self.slider_pbt_outer.valueChanged.connect(self._update_pbt_labels)
        self.slider_pbt_outer.sliderReleased.connect(self._apply_pbt)
        pbt_row.addWidget(self.slider_pbt_outer, stretch=1)

        root.addLayout(pbt_row)

        # ── 6. S-Meter ───────────────────────────────────────────────
        self.lbl_smeter_info = QLabel("S-METER: ---")
        self.lbl_smeter_info.setStyleSheet(f"color: {T['text']}; font-size: 13px; border: none;")
        root.addWidget(self.lbl_smeter_info)

        # S-Meter Labels
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

        # S-Meter Segmented Bar (Custom Widget)
        self.smeter_bar = _SegmentedMeter(len(self._S_LABELS), self)
        self.smeter_bar.setFixedHeight(20)
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

        # ── 9. PTT Button ────────────────────────────────────────────

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
        # Scope aktivieren (IC-705 CI-V)
        if hasattr(cat, 'scope_enable'):
            cat.scope_enable(True)
        # Wasserfall Scroll starten
        if hasattr(self, 'waterfall'):
            self.waterfall.start_scroll(60)
        # Schneller Timer (50ms = ~20fps), Queries nur jeden 3. Tick
        if self._poll_timer is None:
            self._poll_timer = QTimer(self)
            self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(40)  # 25fps poll

    def stop_polling(self):
        if hasattr(self, 'waterfall'):
            self.waterfall.stop_scroll()
        if self._poll_timer:
            self._poll_timer.stop()
        if self._cat and hasattr(self._cat, 'scope_enable'):
            try:
                self._cat.scope_enable(False)
            except Exception:
                pass
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

        # Mode/Preamp/Power Sync in den ersten Ticks (OHNE DSP — das passiert einmal in set_cat_handler)
        if self._poll_count <= 5:
            self._sync_rig_basics()

        # Scope-Daten lesen: bei Query-Ticks aus dem Buffer, sonst direkt vom Port
        if self._poll_count % 5 != 0 and hasattr(self._cat, '_flush_scope_from_serial'):
            self._cat._flush_scope_from_serial()
        if hasattr(self._cat, 'scope_read') and hasattr(self, 'waterfall'):
            spectrum = self._cat.scope_read()
            if spectrum:
                self.waterfall.update_spectrum(spectrum)
                if self._poll_count % 30 == 0:
                    print(f"SCOPE: {sum(1 for v in spectrum if v>0)}/475 max={max(spectrum)}")
                # Demo-Recorder: Scope + aktuelle Werte mitschneiden
                if self._demo_recording:
                    import time
                    frame = {'sp': spectrum[:], 't': round(time.time() - self._demo_start, 2)}
                    frame['f'] = self._current_freq
                    frame['s'] = int(self._smeter_smooth)
                    frame['m'] = self._current_mode
                    sc = getattr(self._cat, '_scope_center_hz', 0)
                    ss = getattr(self._cat, '_scope_span_hz', 0)
                    if sc > 0: frame['sc'] = sc
                    if ss > 0: frame['ss'] = ss
                    self._demo_frames.append(frame)
                # Freq+Span+Passband an Wasserfall (bei jedem Scope-Update)
                scope_center = getattr(self._cat, '_scope_center_hz', 0) or self._current_freq
                if scope_center > 0 and hasattr(self._cat, '_scope_span_hz'):
                    bw = {"USB": 2700, "LSB": 2700, "CW": 500, "CW-R": 500,
                          "FM": 15000, "RTTY": 500, "RTTY-R": 500, "AM": 6000}
                    side = {"USB": "upper", "LSB": "lower", "CW": "upper", "CW-R": "lower",
                            "FM": "both", "RTTY": "lower", "RTTY-R": "upper", "AM": "both"}
                    fw = bw.get(self._current_mode, 2700)
                    fs = side.get(self._current_mode, "upper")
                    self.waterfall.set_freq_info(scope_center, self._cat._scope_span_hz, fw, fs)
                if hasattr(self._cat, '_scope_span_hz') and not self.slider_span.isSliderDown():
                    span_hz = self._cat._scope_span_hz
                    if span_hz > 0:
                        for i, (hz, _) in enumerate(self._SPAN_VALUES):
                            if hz == span_hz:
                                self.slider_span.blockSignals(True)
                                self.slider_span.setValue(i)
                                self.lbl_span.setText(f"SPAN: {self._SPAN_VALUES[i][1]}")
                                self.slider_span.blockSignals(False)
                                break

        # Frequenz: erste 10 Ticks normal, danach nur alle 50 Ticks (~5 Sek)
        if self._poll_count <= 10 or self._poll_count % 50 == 0:
            freq = self._cat.get_frequency()
            if freq is not None and freq != self._current_freq:
                self._current_freq = freq
                mhz_int = freq // 1_000_000
                khz_part = (freq % 1_000_000) // 1_000
                hz_part = freq % 1_000
                self.lbl_freq.setText(f"{mhz_int}.{khz_part:03d}.{hz_part:03d} MHz")
                # Freq + Bandbreite an Wasserfall
                if hasattr(self, 'waterfall') and hasattr(self._cat, '_scope_span_hz'):
                    bw = {"USB": 2700, "LSB": 2700, "CW": 500, "CW-R": 500,
                          "FM": 15000, "RTTY": 500, "RTTY-R": 500, "AM": 6000}
                    side = {"USB": "upper", "LSB": "lower", "CW": "upper", "CW-R": "lower",
                            "FM": "both", "RTTY": "lower", "RTTY-R": "upper", "AM": "both"}
                    fw = bw.get(self._current_mode, 2700)
                    fs = side.get(self._current_mode, "upper")
                    self.waterfall.set_freq_info(freq, self._cat._scope_span_hz, fw, fs)

        # S-Meter nur jeden 3. Tick — Rest der Zeit geht Bandbreite an Scope
        raw = self._cat.get_smeter() if self._poll_count % 5 == 0 else None
        if raw is not None:
            self._smeter_smooth = 0.8 * raw + 0.2 * self._smeter_smooth
            val = int(self._smeter_smooth)
            # S-Meter aus Config lesen (Fallback: Icom Standard)
            s9_raw = getattr(self, '_s9_raw', 120)
            max_raw = getattr(self, '_max_raw', 241)
            s9_steps = getattr(self, '_s9_steps', ["S9+20", "S9+40", "S9+60"])

            if val <= s9_raw:
                s_num = val * 9 / max(s9_raw, 1)
                s_str = f"S{min(9, round(s_num))}"
                frac = s_num / 13
            else:
                db_over = (val - s9_raw) / max(max_raw - s9_raw, 1) * 60
                n_steps = len(s9_steps)
                step_size = 60 / max(n_steps, 1)
                s_str = "S9"
                for i, label in enumerate(s9_steps):
                    if db_over >= (i + 0.5) * step_size:
                        s_str = label
                frac = (9 + db_over / 60 * 4) / 13
            s_val = min(12, int(frac * 13))
            bar_val = int(frac * 1000)
            self.smeter_bar.setValue(min(1000, bar_val))
            preamp = self._current_preamp or "OFF"
            self.lbl_smeter_info.setText(f"S-METER: {s_str} | {preamp}")
            self._update_s_labels(s_val)

        # TX-Meter + VOX
        self.update_tx_meter(self._tx_rms_db)
        self._vox_tick()

        # Scope-Daten werden oben im Poll gelesen

    def _sync_rig_basics(self):
        """Mode, Preamp, Power, PBT syncen (sicher mit Scope)."""
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
                self._current_mode = "AM"
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

        # P.AMP auslesen (IC-705: OFF/P1/P2)
        preamp = self._cat.get_preamp()
        if preamp is not None:
            pamp_map = {"OFF": "OFF", "AMP1": "P1", "AMP2": "P2"}
            state = pamp_map.get(preamp, "OFF")
            self._current_preamp = state
            self.btn_preamp.setText(f"P.AMP: {state}")

        # ATT auslesen
        att = self._cat.get_att()
        if att is not None and "ATT" in self.dsp_buttons:
            self.dsp_buttons["ATT"].setChecked(att)
            self.dsp_buttons["ATT"].setStyleSheet(_BTN_ACTIVE() if att else _BTN_DARK())

        # Power auslesen (IC-705: 0-255 raw = 0-10W)
        raw = self._cat.get_power_raw()
        if raw is not None:
            self.slider_pwr.blockSignals(True)
            self.slider_pwr.setValue(raw)
            self.slider_pwr.blockSignals(False)
            self.lbl_pwr.setText(f"PWR: {raw * 10 / 255:.1f}W")

        # PBT Inner/Outer auslesen
        for sub, slider in [(0x07, self.slider_pbt_inner), (0x08, self.slider_pbt_outer)]:
            result = self._cat._civ_query(0x14, sub=sub)
            if result:
                _, data = result
                if len(data) >= 3 and data[0] == sub:
                    val = self._cat._bcd_to_int_msb(data[1:3])
                    slider.blockSignals(True)
                    slider.setValue(val)
                    slider.blockSignals(False)
        self._update_pbt_labels()

    def _sync_rig_state(self):
        """Einmal bei Connect: DSP-States vom TRX lesen (Scope wird pausiert)."""
        if not self._cat:
            return
        # Basics zuerst (Mode, Preamp, Power, PBT)
        self._sync_rig_basics()

        # DSP-States: Scope pausieren für saubere CI-V Queries
        if hasattr(self._cat, 'scope_enable'):
            self._cat.scope_enable(False)
        import time; time.sleep(0.15)

        dsp_queries = {
            "NB":    (0x16, 0x22),
            "NR":    (0x16, 0x40),
            "NOTCH": (0x16, 0x41),
            "COMP":  (0x16, 0x44),
        }
        for name, (cmd, sub) in dsp_queries.items():
            if name not in self.dsp_buttons:
                continue
            result = self._cat._civ_query(cmd, sub=sub)
            if result:
                _, data = result
                on = len(data) >= 2 and data[0] == sub and data[1] > 0
                self.dsp_buttons[name].setChecked(on)
                self.dsp_buttons[name].setStyleSheet(_BTN_ACTIVE() if on else _BTN_DARK())
            time.sleep(0.05)

        att = self._cat.get_att()
        if att is not None and "ATT" in self.dsp_buttons:
            self.dsp_buttons["ATT"].setChecked(att)
            self.dsp_buttons["ATT"].setStyleSheet(_BTN_ACTIVE() if att else _BTN_DARK())

        agc = self._cat.get_agc()
        if agc and hasattr(self, 'btn_agc'):
            self.btn_agc.setText(f"AGC: {agc}")

        # Scope wieder einschalten
        if hasattr(self._cat, 'scope_enable'):
            self._cat.scope_enable(True)

        # States speichern
        self._save_dsp_state()

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
        # Passband im Wasserfall sofort updaten
        if hasattr(self, 'waterfall') and hasattr(self._cat, '_scope_span_hz'):
            bw = {"USB": 2700, "LSB": 2700, "CW": 500, "CW-R": 500,
                  "FM": 15000, "RTTY": 500, "RTTY-R": 500, "AM": 6000}
            side = {"USB": "upper", "LSB": "lower", "CW": "upper", "CW-R": "lower",
                    "FM": "both", "RTTY": "lower", "RTTY-R": "upper", "AM": "both"}
            sc = getattr(self._cat, '_scope_center_hz', 0) or self._current_freq
            self.waterfall.set_freq_info(sc, self._cat._scope_span_hz,
                                         bw.get(mode, 2700), side.get(mode, "upper"))

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
                btn.setStyleSheet(_BTN_ACTIVE() if self._digi_modifier == m else _BTN_DARK())
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
        elif name == "NR":
            self._cat.set_dnr(on)
        elif name == "NOTCH":
            self._cat.set_dnf(on)
        elif name == "COMP":
            self._cat.set_comp(on)
        btn.setStyleSheet(_BTN_ACTIVE() if on else _BTN_DARK())
        # DSP-State speichern
        self._save_dsp_state()

    def _cycle_preamp(self):
        if not self._cat or not self._cat.connected:
            return
        current = self.btn_preamp.text().replace("P.AMP: ", "")
        cycle = {"OFF": "AMP1", "AMP1": "OFF"}
        new_mode = cycle.get(current, "OFF")
        self._cat.set_preamp(new_mode)
        self._current_preamp = new_mode
        pamp_map = {"OFF": "OFF", "AMP1": "P1", "AMP2": "P2"}
        self.btn_preamp.setText(f"P.AMP: {pamp_map.get(new_mode, new_mode)}")

    def _update_span_label(self, idx):
        """Nur Label updaten beim Slider-Bewegen."""
        if idx < len(self._SPAN_VALUES):
            self.lbl_span.setText(f"SPAN: {self._SPAN_VALUES[idx][1]}")

    def _apply_span(self):
        """Span am TRX setzen wenn Slider losgelassen wird."""
        idx = self.slider_span.value()
        if idx >= len(self._SPAN_VALUES):
            return
        span_hz = self._SPAN_VALUES[idx][0]
        if not self._cat or not self._cat.connected:
            return
        import time
        # Scope Output pausieren
        self._cat._civ_send(0x27, sub=0x11, data=bytes([0x00]))
        time.sleep(0.1)
        # Span setzen: Receiver(0x00) + 3 Bytes BCD
        val = span_hz
        bcd = []
        for _ in range(3):
            lo = val % 10; val //= 10
            hi = val % 10; val //= 10
            bcd.append((hi << 4) | lo)
        self._cat._civ_send(0x27, sub=0x15, data=bytes([0x00] + bcd))
        time.sleep(0.2)
        # Scope Output wieder an
        self._cat._civ_send(0x27, sub=0x11, data=bytes([0x01]))
        # Wasserfall leeren (alte Span-Daten passen nicht mehr)
        if hasattr(self, 'waterfall'):
            self.waterfall._wf_image.fill(QColor(8, 12, 35))
            self.waterfall._display_spectrum[:] = 0
            self.waterfall._last_spectrum[:] = 0

    def _cycle_agc(self):
        if not self._cat or not self._cat.connected:
            return
        current = self.btn_agc.text().replace("AGC: ", "")
        cycle = {"SLOW": "MID", "MID": "FAST", "FAST": "SLOW"}
        new_mode = cycle.get(current, "SLOW")
        self._cat.set_agc(new_mode)
        self.btn_agc.setText(f"AGC: {new_mode}")
        self._save_dsp_state()

    def _apply_power(self):
        if self._cat and self._cat.connected:
            self._cat.set_power_raw(self.slider_pwr.value())
            QTimer.singleShot(200, self._readback_power)

    def _readback_power(self):
        """Power vom Rig zurücklesen und Slider aktualisieren."""
        if not self._cat or not self._cat.connected:
            return
        raw = self._cat.get_power_raw()
        if raw is not None:
            self.slider_pwr.blockSignals(True)
            self.slider_pwr.setValue(raw)
            self.slider_pwr.blockSignals(False)
            self.lbl_pwr.setText(f"PWR: {raw * 10 / 255:.1f}W")

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

    def eventFilter(self, obj, event):
        """EventFilter auf Wasserfall — fängt Mouse-Events ab."""
        from PySide6.QtCore import QEvent
        if obj is self.waterfall:
            if event.type() == QEvent.Type.MouseButtonPress:
                x = int(event.position().x())
                freq = self.waterfall._x_to_freq(x)
                if freq > 0:
                    step = self.waterfall._step_hz
                    freq = round(freq / step) * step
                    self._on_waterfall_click(freq)
                return True
            elif event.type() == QEvent.Type.MouseMove:
                if event.buttons() & Qt.LeftButton:
                    x = int(event.position().x())
                    freq = self.waterfall._x_to_freq(x)
                    if freq > 0:
                        step = self.waterfall._step_hz
                        freq = round(freq / step) * step
                        self._on_waterfall_click(freq)
                    return True
            elif event.type() == QEvent.Type.Wheel:
                delta = event.angleDelta().y()
                self.waterfall._scroll_accum += delta
                steps = self.waterfall._scroll_accum // 120
                self.waterfall._scroll_accum -= steps * 120
                if steps != 0:
                    self._on_waterfall_scroll(int(steps * self.waterfall._step_hz))
                return True
        return super().eventFilter(obj, event)

    def _update_pbt_labels(self):
        inner = self.slider_pbt_inner.value()
        outer = self.slider_pbt_outer.value()
        # BW = Differenz der beiden (wie am IC-705)
        bw = abs(outer - inner)
        sft = ((inner + outer) / 2 - 128)
        self.lbl_bw.setText(f"BW: {bw}")
        self.lbl_sft.setText(f"SFT: {int(sft)}")

    def _apply_pbt(self):
        if not self._cat or not self._cat.connected:
            return
        inner = self.slider_pbt_inner.value()
        outer = self.slider_pbt_outer.value()
        # CI-V: 0x14 0x07 = PBT Inner, 0x14 0x08 = PBT Outer
        self._cat._civ_send(0x14, sub=0x07,
            data=self._cat._int_to_bcd_msb(inner, 2))
        self._cat._civ_send(0x14, sub=0x08,
            data=self._cat._int_to_bcd_msb(outer, 2))

    def _status_conf_path(self):
        """Pfad zu status_conf.json."""
        return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))), "configs", "status_conf.json")

    def _save_dsp_state(self):
        """DSP Button-States in status_conf.json speichern."""
        try:
            path = self._status_conf_path()
            cfg = {}
            if os.path.exists(path):
                with open(path) as f:
                    cfg = json.load(f)
            dsp = {}
            for name, btn in self.dsp_buttons.items():
                dsp[name] = btn.isChecked()
            if hasattr(self, 'btn_agc'):
                dsp["AGC"] = self.btn_agc.text().replace("AGC: ", "")
            cfg["dsp_state"] = dsp
            with open(path, "w") as f:
                json.dump(cfg, f, indent=4)
            print(f"DSP gespeichert: {dsp}")
        except Exception as e:
            print(f"DSP speichern fehlgeschlagen: {e}")

    def _load_dsp_state(self):
        """DSP Button-States aus status_conf.json laden."""
        try:
            path = self._status_conf_path()
            with open(path) as f:
                dsp = json.load(f).get("dsp_state", {})
            if not dsp:
                print("Keine gespeicherten DSP-States")
                return
            print(f"DSP laden: {dsp}")
            for name, on in dsp.items():
                if name == "AGC":
                    if hasattr(self, 'btn_agc'):
                        self.btn_agc.setText(f"AGC: {on}")
                    continue
                if name in self.dsp_buttons:
                    self.dsp_buttons[name].setChecked(on)
                    self.dsp_buttons[name].setStyleSheet(_BTN_ACTIVE() if on else _BTN_DARK())
        except Exception as e:
            print(f"DSP laden fehlgeschlagen: {e}")

    def _apply_signal_gain(self, val):
        """Signal-Kontrast (color_gain)."""
        self.waterfall._color_gain = val / 10.0

    def _apply_noise_floor(self, val):
        """Rausch-Filter (black_level)."""
        self.waterfall._black_level = val

    # ══════════════════════════════════════════════════════════════════
    # DEMO RECORDER (F9 Start/Stop)
    # ══════════════════════════════════════════════════════════════════

    def start_demo_recording(self):
        import time, subprocess, os
        self._demo_frames = []
        self._demo_start = time.time()
        self._demo_recording = True
        self._demo_audio_proc = None

        # RX-Audio parallel aufnehmen (TRX USB Audio → WAV)
        docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))), "docs")
        audio_path = os.path.join(docs_dir, "demo_audio.wav")

        # TRX Audio-Device aus Config lesen
        trx_mic = ""
        if self._config_path:
            try:
                with open(self._config_path) as f:
                    cfg = json.load(f)
                dev = cfg.get("audio", {}).get("trx_mic", {}).get("device", "")
                # node.name aus "[pw:node.name] ..." extrahieren
                if "[pw:" in dev:
                    trx_mic = dev.split("[pw:")[1].split("]")[0]
            except Exception:
                pass

        if trx_mic:
            try:
                self._demo_audio_proc = subprocess.Popen(
                    ["pw-record", "--target", trx_mic, "--rate", "44100",
                     "--channels", "1", "--format", "s16", audio_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                print(f"🎙️ Audio-Aufnahme: {trx_mic}")
            except Exception as e:
                print(f"Audio-Aufnahme fehlgeschlagen: {e}")

        log_event("Demo-Aufnahme gestartet")
        print("🔴 DEMO RECORDING GESTARTET")

    def stop_demo_recording(self):
        self._demo_recording = False

        # Audio stoppen
        if self._demo_audio_proc:
            self._demo_audio_proc.terminate()
            self._demo_audio_proc.wait(timeout=3)
            self._demo_audio_proc = None
            print("🎙️ Audio-Aufnahme gestoppt")

        log_event(f"Demo-Aufnahme gestoppt: {len(self._demo_frames)} Frames")
        print(f"⬜ DEMO RECORDING GESTOPPT — {len(self._demo_frames)} Frames")

        if not self._demo_frames:
            return

        import os
        output = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))), "docs", "demo_data.json")
        with open(output, 'w') as f:
            json.dump(self._demo_frames, f, separators=(',', ':'))
        size = os.path.getsize(output) / 1024
        print(f"💾 Gespeichert: {output} ({size:.0f} KB, {len(self._demo_frames)} Frames)")

    def keyPressEvent(self, event):
        from PySide6.QtCore import Qt
        if event.key() == Qt.Key_F9:
            if self._demo_recording:
                self.stop_demo_recording()
            else:
                self.start_demo_recording()
            event.accept()
        else:
            super().keyPressEvent(event)

    # ══════════════════════════════════════════════════════════════════
    # WATERFALL CLICK / SCROLL
    # ══════════════════════════════════════════════════════════════════

    def _on_waterfall_click(self, freq_hz):
        """Klick im Wasserfall → Frequenz direkt setzen."""
        if not self._cat or not self._cat.connected:
            return
        log_action(f"Wasserfall Klick → {freq_hz} Hz")
        self._cat.set_frequency(freq_hz)

    def _on_filter_changed(self, bw_hz):
        """Filter-Bandbreite geändert durch Drag im Wasserfall."""
        if self._cat and self._cat.connected:
            log_action(f"Filter → {bw_hz} Hz")
            self._cat.set_filter(bw_hz)

    def _on_waterfall_scroll(self, delta_hz):
        """Mausrad im Wasserfall → Frequenz um delta_hz ändern."""
        if not self._cat or not self._cat.connected:
            return
        self._cat.step_frequency(delta_hz)

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

        # S-Meter Kalibrierung aus Config
        sm_cfg = cfg.get("smeter", {})
        self._s9_raw = int(sm_cfg.get("s9_raw", 120))
        self._max_raw = int(sm_cfg.get("max_raw", 241))
        self._s9_steps = sm_cfg.get("steps_over_s9", ["S9+20", "S9+40", "S9+60"])

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
        # Frequenz + Tuning
        self.lbl_freq.setStyleSheet(f"color: {T['text']}; font-size: 32px; border: none;")
        self.btn_step_down.setStyleSheet(_BTN_DARK())
        self.btn_step_up.setStyleSheet(_BTN_DARK())
        self.combo_step.setStyleSheet(_COMBO_STYLE())
        self.input_freq.setStyleSheet(_INPUT_STYLE())
        self.btn_set_freq.setStyleSheet(f"""QPushButton {{ background-color: {T['bg_mid']}; color: {T['text']};
            border: 2px solid {T['accent']}; border-radius: 4px; padding: 4px 12px; font-size: 13px; font-weight: bold; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; }}""")

        # Mode + Digi Buttons
        self._update_mode_buttons()

        # DSP Buttons
        for name, btn in self.dsp_buttons.items():
            btn.setStyleSheet(_BTN_ACTIVE() if btn.isChecked() else _BTN_DARK())
        self.btn_preamp.setStyleSheet(_BTN_DARK())
        self.btn_agc.setStyleSheet(_BTN_DARK())

        # Power + PBT
        self.lbl_pwr.setStyleSheet(f"color: {T['text']}; font-size: 11px; border: none;")
        self.slider_pwr.setStyleSheet(_SLIDER_STYLE())
        self.lbl_bw.setStyleSheet(f"color: {T['text']}; font-size: 11px; border: none;")
        self.lbl_sft.setStyleSheet(f"color: {T['text']}; font-size: 11px; border: none;")
        self.slider_pbt_inner.setStyleSheet(_SLIDER_STYLE())
        self.slider_pbt_outer.setStyleSheet(_SLIDER_STYLE())

        # Span/Ref Slider + Contrast
        self.lbl_span.setStyleSheet(f"color: {T['text_secondary']}; font-size: 10px; border: none;")
        self.slider_span.setStyleSheet(_SLIDER_STYLE())
        _vs = f"""QSlider::groove:vertical {{ background: {T['slider_groove']}; width: 4px; border-radius: 2px; }}
            QSlider::handle:vertical {{ background: {T['slider_handle']}; height: 12px; margin: 0 -4px; border-radius: 6px; }}
            QSlider::sub-page:vertical {{ background: {T['slider_fill']}; border-radius: 2px; }}"""
        self.slider_signal.setStyleSheet(_vs)
        self.slider_noise.setStyleSheet(_vs)

        # S-Meter
        self.lbl_smeter_info.setStyleSheet(f"color: {T['text']}; font-size: 13px; border: none;")
        self.smeter_bar.update()  # Custom Widget repaint
        for lbl in self.s_labels:
            lbl.setStyleSheet(f"color: {T['smeter_label_inactive']}; font-size: 10px; font-weight: bold; border: none;")

        # TX Meter
        self.lbl_tx_info.setStyleSheet(f"color: {T['text']}; font-size: 13px; border: none;")
        self.tx_bar.setStyleSheet(f"""
            QProgressBar {{ background-color: {T['bg_dark']}; border: 1px solid {T['border']}; border-radius: 4px; }}
            QProgressBar::chunk {{ background-color: {T['tx_bar']}; border-radius: 3px; }}""")

        # PTT Button
        if not self._ptt_active:
            self.btn_ptt.setStyleSheet(f"""QPushButton {{ background-color: {T['ptt_rx_bg']}; color: {T['text']};
                border: 2px solid {T['ptt_rx_border']}; border-radius: 8px; }}""")
