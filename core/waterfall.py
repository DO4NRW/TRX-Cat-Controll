"""
Wasserfall/Spektrum-Widget — inspiriert von AetherSDR.
Spektrum oben mit Gradient-Fill, Wasserfall unten als Ring-Buffer.
"""

import numpy as np
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import (QPainter, QColor, QImage, QLinearGradient,
                           QPainterPath, QPen)

from core.theme import T


class WaterfallWidget(QWidget):
    """Spektrum + Wasserfall Display."""

    def __init__(self, parent=None, num_points=475, max_amp=160):
        super().__init__(parent)
        self._num_points = num_points
        self._max_amp = max_amp
        self._spectrum = np.zeros(num_points, dtype=np.float32)
        self._wf_lines = 200
        self._wf_write_row = 0

        # Wasserfall als QImage (Ring-Buffer) — dunkelblauer Hintergrund wie Icom
        self._wf_image = QImage(num_points, self._wf_lines, QImage.Format_RGB32)
        self._wf_image.fill(QColor(8, 12, 35))

        # Display Settings
        self._color_gain = 3.0     # Farbverstärkung (weniger aggressiv)
        self._black_level = 3      # Unter diesem Wert = schwarz
        self._spectrum_frac = 0.35  # 35% Spektrum, 65% Wasserfall
        self._fill_alpha = 0.75

        # Farbpalette
        self._palette = self._build_palette()

        self._last_spectrum = np.zeros(num_points, dtype=np.float32)
        self._display_spectrum = np.zeros(num_points, dtype=np.float32)
        self._scroll_timer = None
        self._center_freq = 0  # Hz
        self._span_hz = 0

        self.setMinimumHeight(150)
        self.setAttribute(Qt.WA_OpaquePaintEvent)

    def _build_palette(self):
        """SDR-Style Farbpalette: schwarz → blau → cyan → grün → gelb → rot → weiß."""
        palette = []
        stops = [
            (0.00, (8, 12, 35)),
            (0.05, (10, 20, 70)),
            (0.15, (0, 40, 160)),
            (0.30, (0, 150, 180)),
            (0.45, (0, 220, 100)),
            (0.60, (180, 220, 0)),
            (0.75, (255, 140, 0)),
            (0.88, (255, 40, 0)),
            (1.00, (255, 255, 255)),
        ]
        for i in range(256):
            frac = i / 255.0
            lo = stops[0]
            hi = stops[-1]
            for j in range(len(stops) - 1):
                if stops[j][0] <= frac <= stops[j + 1][0]:
                    lo = stops[j]
                    hi = stops[j + 1]
                    break
            if hi[0] == lo[0]:
                t = 0
            else:
                t = (frac - lo[0]) / (hi[0] - lo[0])
            r = int(lo[1][0] + t * (hi[1][0] - lo[1][0]))
            g = int(lo[1][1] + t * (hi[1][1] - lo[1][1]))
            b = int(lo[1][2] + t * (hi[1][2] - lo[1][2]))
            palette.append(QColor(r, g, b).rgb())
        return palette

    def _amp_to_color_idx(self, val):
        """Amplitude (0-160) → Farbindex (0-255) mit Gain und Black Level."""
        if val <= self._black_level:
            return 0
        scaled = (val - self._black_level) * self._color_gain
        return min(255, max(0, int(scaled)))

    def start_scroll(self, interval_ms=80):
        """Wasserfall durchgehend scrollen starten."""
        if self._scroll_timer is None:
            from PySide6.QtCore import QTimer
            self._scroll_timer = QTimer(self)
            self._scroll_timer.timeout.connect(self._scroll_tick)
        self._scroll_timer.start(interval_ms)

    def stop_scroll(self):
        if self._scroll_timer:
            self._scroll_timer.stop()

    def _scroll_tick(self):
        """Jeder Tick: langsam zum Ziel blenden und neue Zeile schreiben."""
        # 10% pro Tick Richtung Ziel → ~30 Zwischenzeilen pro Übergang
        self._display_spectrum += 0.10 * (self._last_spectrum - self._display_spectrum)
        self._spectrum = self._display_spectrum.copy()
        self._write_row(self._display_spectrum)
        self.update()

    def set_freq_info(self, center_hz, span_hz):
        """Center-Frequenz und Span für Frequenz-Labels."""
        self._center_freq = center_hz
        self._span_hz = span_hz

    def update_spectrum(self, data):
        """Neues Ziel-Spektrum setzen (Blend passiert im Scroll-Timer)."""
        if data is None or len(data) != self._num_points:
            return
        new = np.array(data, dtype=np.float32)
        # Erstes Update: direkt setzen statt blenden
        if self._last_spectrum.max() == 0:
            self._display_spectrum = new.copy()
            self._spectrum = new.copy()
        self._last_spectrum = new

    def _write_row(self, spectrum):
        """Bild eine Zeile nach unten schieben, neue Zeile oben rein."""
        # Alles eine Zeile runter kopieren
        for y in range(self._wf_lines - 1, 0, -1):
            for x in range(self._num_points):
                self._wf_image.setPixel(x, y, self._wf_image.pixel(x, y - 1))
        # Neue Zeile oben (y=0)
        for col in range(self._num_points):
            idx = self._amp_to_color_idx(int(spectrum[col]))
            self._wf_image.setPixel(col, 0, self._palette[idx])

    def paintEvent(self, event):
        p = QPainter(self)
        w = self.width()
        h = self.height()

        if w <= 0 or h <= 10:
            p.end()
            return

        spec_h = int(h * self._spectrum_frac)
        wf_h = h - spec_h

        # ── Spektrum-Hintergrund (etwas heller für Kontrast) ────────
        bg = QColor(18, 22, 30)
        p.fillRect(0, 0, w, spec_h, bg)

        # ── Grid ─────────────────────────────────────────────────────
        grid_color = QColor(30, 40, 55)
        p.setPen(grid_color)
        for i in range(1, 4):
            y = int(spec_h * i / 4)
            p.drawLine(0, y, w, y)
        for i in range(1, 8):
            x = int(w * i / 8)
            p.drawLine(x, 0, x, spec_h)

        # ── Spektrum (Balken + Linie) ────────────────────────────────
        peak = float(self._spectrum.max())
        if peak > 0:
            accent = QColor(6, 198, 164)  # Teal direkt als RGB
            n = self._num_points
            auto_scale = 0.85 / max(peak, 1)

            # Gefüllte Balken pro Spalte (transparenter)
            fill_color = QColor(accent)
            fill_color.setAlpha(60)
            line_points = []

            for px in range(w):
                idx = int(px * n / w)
                if idx >= n:
                    idx = n - 1
                val = self._spectrum[idx]
                normed = min(1.0, val * auto_scale)
                y = int(spec_h * (1.0 - normed))
                y = max(1, min(spec_h - 1, y))
                bar_h = spec_h - y
                if bar_h > 0:
                    p.fillRect(px, y, 1, bar_h, fill_color)
                line_points.append((px, y))

            # Helle Linie obendrauf
            p.setPen(QPen(accent, 2))
            for i in range(1, len(line_points)):
                p.drawLine(line_points[i-1][0], line_points[i-1][1],
                          line_points[i][0], line_points[i][1])

        # ── Trennlinie (dezent) ──────────────────────────────────────
        p.setPen(QPen(QColor(40, 50, 60), 1))
        p.drawLine(0, spec_h, w, spec_h)

        # ── Wasserfall (Ring-Buffer) ─────────────────────────────────
        wf_rect = self.rect()
        wf_rect.setTop(spec_h + 1)

        img_h = self._wf_lines
        wr = self._wf_write_row

        # Wasserfall: einfach das ganze Bild zeichnen (kein Ring-Buffer mehr)
        from PySide6.QtCore import QRect
        p.drawImage(QRect(0, spec_h + 1, w, wf_h), self._wf_image)

        # ── Center-Marker + Frequenz-Labels ──────────────────────────
        if self._center_freq > 0 and self._span_hz > 0:
            # Center-Marker (vertikale Linie über Spektrum + Wasserfall)
            cx = w // 2
            p.setPen(QPen(QColor(6, 198, 164, 80), 1))
            p.drawLine(cx, 0, cx, h)

            # Frequenz-Labels oben
            p.setFont(QFont("Roboto", 8))
            p.setPen(QColor(150, 160, 170))
            start_freq = self._center_freq - self._span_hz // 2
            end_freq = self._center_freq + self._span_hz // 2

            for i in range(6):
                freq = start_freq + (end_freq - start_freq) * i / 5
                x = int(w * i / 5)
                mhz = freq / 1_000_000
                label = f"{mhz:.3f}"
                if i == 0:
                    p.drawText(x + 2, 10, label)
                elif i == 5:
                    p.drawText(x - 45, 10, label)
                else:
                    p.drawText(x - 20, 10, label)
                p.setPen(QColor(40, 50, 60))
                p.drawLine(x, 0, x, 4)
                p.setPen(QColor(150, 160, 170))

        p.end()
