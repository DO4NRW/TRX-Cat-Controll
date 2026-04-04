"""
Parametrischer / Grafischer Equalizer für RigLink
===================================================
Implementiert BiQuad-Peaking-Filter, Low-Shelf und High-Shelf
nach Audio-EQ-Cookbook (Robert Bristow-Johnson).

Zwei Anwendungsfälle:
  1. Programmatisch: EQProcessor auf numpy-Arrays anwenden
  2. GUI: EQWidget (PySide6) mit vertikalen Schiebereglern

Verwendung:
    # 10-Band Grafik-EQ
    eq = EQProcessor()
    eq.set_gain(1000.0, +6.0)           # 1 kHz um +6 dB anheben
    out = eq.process(samples, sr=48000) # numpy float32

    # Widget in Layout einbetten
    widget = EQWidget()
    widget.changed.connect(my_slot)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QSlider, QPushButton
)
from PySide6.QtGui import QFont

from core.theme import T


# ── BiQuad-Filter ─────────────────────────────────────────────────────────────

@dataclass
class _BiquadCoeffs:
    """Direkte Form II Koeffizienten (b0, b1, b2, a1, a2) — normiert auf a0=1."""
    b0: float = 1.0
    b1: float = 0.0
    b2: float = 0.0
    a1: float = 0.0
    a2: float = 0.0


class _BiquadFilter:
    """
    Zustandsbehafteter BiQuad-Filter (Direct Form II Transposed).
    Thread-safe: Zustand pro Instanz, kein globaler State.
    """

    def __init__(self, coeffs: _BiquadCoeffs | None = None):
        self._c  = coeffs or _BiquadCoeffs()
        self._z1 = 0.0  # Verzögerungselement 1
        self._z2 = 0.0  # Verzögerungselement 2

    def reset(self):
        """Filterzustand zurücksetzen (bei Samplerate-Wechsel)."""
        self._z1 = self._z2 = 0.0

    def set_coeffs(self, c: _BiquadCoeffs):
        self._c = c
        self.reset()

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Samples filtern. Input/Output: float64-Array."""
        b0, b1, b2 = self._c.b0, self._c.b1, self._c.b2
        a1, a2     = self._c.a1, self._c.a2
        out = np.empty_like(samples)
        z1, z2 = self._z1, self._z2

        for i, x in enumerate(samples):
            y      = b0 * x + z1
            z1     = b1 * x - a1 * y + z2
            z2     = b2 * x - a2 * y
            out[i] = y

        self._z1, self._z2 = z1, z2
        return out


# ── Koeffizienten-Berechnung ──────────────────────────────────────────────────

def _peaking_eq(f0: float, gain_db: float, q: float, fs: float) -> _BiquadCoeffs:
    """
    Peaking-EQ-Filter (Glockenkurve).
    Audio-EQ-Cookbook, Formel für peakingEQ.
    """
    A  = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * f0 / fs
    cw = math.cos(w0)
    sw = math.sin(w0)
    alpha = sw / (2.0 * q)

    b0 =  1.0 + alpha * A
    b1 = -2.0 * cw
    b2 =  1.0 - alpha * A
    a0 =  1.0 + alpha / A
    a1 = -2.0 * cw
    a2 =  1.0 - alpha / A

    return _BiquadCoeffs(b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)


def _low_shelf(f0: float, gain_db: float, fs: float) -> _BiquadCoeffs:
    """Low-Shelf-Filter (Tiefen anheben/absenken)."""
    A  = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * f0 / fs
    cw = math.cos(w0)
    sw = math.sin(w0)
    sqA = math.sqrt(A)
    alpha = sw / 2.0 * math.sqrt((A + 1.0/A) * (1.0/0.707 - 1.0) + 2.0)

    b0 =     A * ((A+1) - (A-1)*cw + 2*sqA*alpha)
    b1 = 2 * A * ((A-1) - (A+1)*cw                )
    b2 =     A * ((A+1) - (A-1)*cw - 2*sqA*alpha)
    a0 =          (A+1) + (A-1)*cw + 2*sqA*alpha
    a1 =    -2 * ((A-1) + (A+1)*cw                )
    a2 =          (A+1) + (A-1)*cw - 2*sqA*alpha

    return _BiquadCoeffs(b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)


def _high_shelf(f0: float, gain_db: float, fs: float) -> _BiquadCoeffs:
    """High-Shelf-Filter (Höhen anheben/absenken)."""
    A  = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * f0 / fs
    cw = math.cos(w0)
    sw = math.sin(w0)
    sqA = math.sqrt(A)
    alpha = sw / 2.0 * math.sqrt((A + 1.0/A) * (1.0/0.707 - 1.0) + 2.0)

    b0 =      A * ((A+1) + (A-1)*cw + 2*sqA*alpha)
    b1 = -2 * A * ((A-1) + (A+1)*cw                )
    b2 =      A * ((A+1) + (A-1)*cw - 2*sqA*alpha)
    a0 =           (A+1) - (A-1)*cw + 2*sqA*alpha
    a1 =      2 * ((A-1) - (A+1)*cw                )
    a2 =           (A+1) - (A-1)*cw - 2*sqA*alpha

    return _BiquadCoeffs(b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)


# ── 10-Band Grafik-EQ Mittelpunktfrequenzen ───────────────────────────────────

_BANDS_HZ: list[float] = [31.0, 63.0, 125.0, 250.0, 500.0,
                           1000.0, 2000.0, 4000.0, 8000.0, 16000.0]

_BAND_LABELS: list[str] = ["31", "63", "125", "250", "500",
                            "1k", "2k", "4k", "8k", "16k"]

_BAND_Q   = 1.41   # Q für Grafik-EQ (~1 Oktave Bandbreite)
_GAIN_MIN = -12.0  # dB
_GAIN_MAX = +12.0  # dB


# ── EQProcessor ───────────────────────────────────────────────────────────────

class EQProcessor:
    """
    10-Band Grafik-EQ für numpy-Audiosignale.
    Jede Band = ein BiQuad-Peaking-Filter.
    Band 0 (31 Hz): Low-Shelf, Band 9 (16 kHz): High-Shelf.
    """

    def __init__(self, sample_rate: int = 48000):
        self._sr     = sample_rate
        self._gains  = [0.0] * len(_BANDS_HZ)   # Aktuelle Gains in dB
        self._filters: list[_BiquadFilter] = [_BiquadFilter() for _ in _BANDS_HZ]
        self._enabled = True
        self._rebuild_all()

    # ── Öffentliche API ───────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, v: bool):
        self._enabled = v

    def set_gain(self, freq_hz: float, gain_db: float):
        """
        Gain für eine Mittenfrequenz setzen.
        Findet die nächste Band-Frequenz automatisch.
        """
        idx = self._nearest_band(freq_hz)
        self._gains[idx] = float(np.clip(gain_db, _GAIN_MIN, _GAIN_MAX))
        self._rebuild(idx)

    def set_gain_by_index(self, idx: int, gain_db: float):
        """Gain direkt über Band-Index setzen (0–9)."""
        if 0 <= idx < len(_BANDS_HZ):
            self._gains[idx] = float(np.clip(gain_db, _GAIN_MIN, _GAIN_MAX))
            self._rebuild(idx)

    def get_gains(self) -> list[float]:
        """Alle aktuellen Gain-Werte zurückgeben."""
        return list(self._gains)

    def reset_all(self):
        """Alle Gains auf 0 dB zurücksetzen."""
        self._gains = [0.0] * len(_BANDS_HZ)
        self._rebuild_all()

    def set_sample_rate(self, sr: int):
        """Samplerate ändern — Filter neu berechnen."""
        self._sr = sr
        self._rebuild_all()

    def process(self, samples: np.ndarray) -> np.ndarray:
        """
        Audiodaten equalisieren.
        Input/Output: float32 oder float64, mono oder stereo (Nx2).
        """
        if not self._enabled:
            return samples

        data = samples.astype(np.float64)
        mono = data.ndim == 1

        # Stereo: beide Kanäle separat
        if not mono:
            left  = data[:, 0]
            right = data[:, 1]
        else:
            left = data

        # Alle aktiven Filter anwenden
        for i, flt in enumerate(self._filters):
            if abs(self._gains[i]) > 0.01:   # Bypass wenn ~0 dB
                left = flt.process(left)
                if not mono:
                    right = flt.process(right)

        if not mono:
            return np.column_stack([left, right]).astype(samples.dtype)
        return left.astype(samples.dtype)

    def frequency_response(self, freqs: np.ndarray) -> np.ndarray:
        """
        Amplitudengang berechnen (dB) für Anzeige.
        freqs: Array von Frequenzen in Hz.
        """
        response = np.zeros(len(freqs))
        for i, flt in enumerate(self._filters):
            if abs(self._gains[i]) < 0.01:
                continue
            c  = flt._c
            w  = 2.0 * np.pi * freqs / self._sr
            z  = np.exp(1j * w)
            z2 = z * z
            num = c.b0 + c.b1 / z + c.b2 / z2
            den = 1.0  + c.a1 / z + c.a2 / z2
            h   = np.abs(num / den)
            response += 20.0 * np.log10(np.maximum(h, 1e-10))
        return response

    # ── Intern ───────────────────────────────────────────────────────────────

    def _rebuild(self, idx: int):
        """Einen Filter neu berechnen."""
        freq = _BANDS_HZ[idx]
        gain = self._gains[idx]
        if idx == 0:
            coeffs = _low_shelf(freq, gain, self._sr)
        elif idx == len(_BANDS_HZ) - 1:
            coeffs = _high_shelf(freq, gain, self._sr)
        else:
            coeffs = _peaking_eq(freq, gain, _BAND_Q, self._sr)
        self._filters[idx].set_coeffs(coeffs)

    def _rebuild_all(self):
        for i in range(len(_BANDS_HZ)):
            self._rebuild(i)

    def _nearest_band(self, freq: float) -> int:
        return int(np.argmin([abs(f - freq) for f in _BANDS_HZ]))


# ── EQWidget — PySide6 UI ─────────────────────────────────────────────────────

class EQWidget(QWidget):
    """
    10-Band Grafik-EQ Widget mit vertikalen Schiebereglern.
    Jeder Regler: -12 dB bis +12 dB.

    Signale:
        changed(list[float])  — Neue Gain-Liste bei jeder Änderung
    """

    changed = Signal(list)   # list[float] — alle 10 Gains in dB

    def __init__(self, processor: EQProcessor | None = None, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._proc    = processor or EQProcessor()
        self._sliders: list[QSlider] = []
        self._labels:  list[QLabel]  = []
        self._setup_ui()
        self._apply_theme()

    # ── UI aufbauen ───────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(4)
        root.setContentsMargins(6, 6, 6, 6)

        # Titel + Reset-Button
        top = QHBoxLayout()
        title = QLabel("EQUALIZER")
        f = QFont()
        f.setPointSize(8)
        f.setBold(True)
        title.setFont(f)
        top.addWidget(title)
        top.addStretch()

        self._btn_reset = QPushButton("Reset")
        self._btn_reset.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_reset.setFixedWidth(54)
        self._btn_reset.clicked.connect(self._on_reset)
        top.addWidget(self._btn_reset)

        self._btn_bypass = QPushButton("Bypass")
        self._btn_bypass.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_bypass.setFixedWidth(54)
        self._btn_bypass.setCheckable(True)
        self._btn_bypass.clicked.connect(self._on_bypass)
        top.addWidget(self._btn_bypass)

        root.addLayout(top)

        # Slider-Reihe
        band_row = QHBoxLayout()
        band_row.setSpacing(2)

        for idx, (freq, label) in enumerate(zip(_BANDS_HZ, _BAND_LABELS)):
            col = QVBoxLayout()
            col.setSpacing(2)
            col.setAlignment(Qt.AlignmentFlag.AlignHCenter)

            # dB-Anzeige
            db_lbl = QLabel("0")
            db_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            db_lbl.setFixedWidth(36)
            f2 = QFont("Monospace")
            f2.setPointSize(8)
            db_lbl.setFont(f2)
            col.addWidget(db_lbl)
            self._labels.append(db_lbl)

            # Slider (vertikal, von +12 oben bis -12 unten)
            slider = QSlider(Qt.Orientation.Vertical)
            slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            slider.setRange(int(_GAIN_MIN * 10), int(_GAIN_MAX * 10))
            slider.setValue(0)
            slider.setTickInterval(40)
            slider.setTickPosition(QSlider.TickPosition.TicksBothSides)
            slider.setFixedWidth(28)
            slider.setMinimumHeight(100)
            slider.valueChanged.connect(lambda v, i=idx: self._on_slider(i, v))
            col.addWidget(slider, alignment=Qt.AlignmentFlag.AlignHCenter)
            self._sliders.append(slider)

            # Frequenz-Label
            freq_lbl = QLabel(label)
            freq_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            freq_lbl.setFixedWidth(36)
            col.addWidget(freq_lbl)

            band_row.addLayout(col)

        root.addLayout(band_row)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_slider(self, idx: int, raw_value: int):
        gain = raw_value / 10.0
        self._proc.set_gain_by_index(idx, gain)
        # dB-Label aktualisieren
        sign = '+' if gain > 0 else ''
        self._labels[idx].setText(f"{sign}{gain:.1f}")
        self.changed.emit(self._proc.get_gains())

    def _on_reset(self):
        self._proc.reset_all()
        for s in self._sliders:
            s.blockSignals(True)
            s.setValue(0)
            s.blockSignals(False)
        for lbl in self._labels:
            lbl.setText("0")
        self.changed.emit(self._proc.get_gains())

    def _on_bypass(self, checked: bool):
        self._proc.enabled = not checked

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _apply_theme(self):
        accent    = T.get('accent',           'rgba(6,198,164,255)')
        bg_mid    = T.get('bg_mid',           'rgba(42,42,42,255)')
        bg_btn    = T.get('bg_button',        'rgba(61,61,61,255)')
        bg_hover  = T.get('bg_button_hover',  'rgba(74,74,74,255)')
        border    = T.get('border',           'rgba(85,85,85,255)')
        text      = T.get('text',             'rgba(255,255,255,255)')
        text_mut  = T.get('text_muted',       'rgba(170,170,170,255)')
        sl_groove = T.get('slider_groove',    'rgba(42,42,42,255)')
        sl_handle = T.get('slider_handle',    'rgba(6,198,164,255)')
        sl_fill   = T.get('slider_fill',      'rgba(85,85,85,255)')

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {bg_mid};
                color:            {text};
            }}
            QLabel {{
                color:            {text_mut};
                background:       transparent;
            }}
            QPushButton {{
                background-color: {bg_btn};
                color:            {text};
                border:           1px solid {border};
                border-radius:    3px;
                padding:          2px 6px;
            }}
            QPushButton:hover {{
                background-color: {bg_hover};
            }}
            QPushButton:checked {{
                border:           1px solid {accent};
                color:            {accent};
            }}
            QSlider::groove:vertical {{
                background:       {sl_groove};
                width:            4px;
                border-radius:    2px;
            }}
            QSlider::handle:vertical {{
                background:       {sl_handle};
                border:           1px solid {accent};
                width:            14px;
                height:           14px;
                margin:           -5px -5px;
                border-radius:    7px;
            }}
            QSlider::sub-page:vertical {{
                background:       {sl_fill};
                border-radius:    2px;
            }}
        """)

    # ── Programmatische Steuerung ──────────────────────────────────────────────

    def set_gains(self, gains: list[float]):
        """Alle Gains setzen (z.B. beim Laden einer gespeicherten Konfiguration)."""
        for idx, gain in enumerate(gains[:len(_BANDS_HZ)]):
            clamped = float(np.clip(gain, _GAIN_MIN, _GAIN_MAX))
            self._sliders[idx].blockSignals(True)
            self._sliders[idx].setValue(int(clamped * 10))
            self._sliders[idx].blockSignals(False)
            self._proc.set_gain_by_index(idx, clamped)
            sign = '+' if clamped > 0 else ''
            self._labels[idx].setText(f"{sign}{clamped:.1f}" if clamped != 0 else "0")

    @property
    def processor(self) -> EQProcessor:
        """Zugriff auf den EQProcessor (für Audio-Pipeline)."""
        return self._proc
