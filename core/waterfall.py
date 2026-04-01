"""
Wasserfall/Spektrum-Widget — inspiriert von AetherSDR.
Spektrum oben mit Gradient-Fill, Wasserfall unten als Ring-Buffer.
"""

import numpy as np
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import (QPainter, QColor, QImage, QLinearGradient,
                           QPainterPath, QPen, QFont)

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
        self._filter_width = 2700  # Default SSB Bandbreite in Hz

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

    def set_freq_info(self, center_hz, span_hz, filter_width=None):
        """Center-Frequenz, Span und Filter-Bandbreite."""
        self._center_freq = center_hz
        self._span_hz = span_hz
        if filter_width is not None:
            self._filter_width = filter_width

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
        """Ring-Buffer: neue Zeile schreiben, Pointer weiter."""
        for col in range(self._num_points):
            idx = self._amp_to_color_idx(int(spectrum[col]))
            self._wf_image.setPixel(col, self._wf_write_row, self._palette[idx])
        self._wf_write_row = (self._wf_write_row + 1) % self._wf_lines

    def paintEvent(self, event):
        p = QPainter(self)
        w = self.width()
        h = self.height()

        if w <= 0 or h <= 10:
            p.end()
            return

        freq_bar_h = 18  # Frequenz-Leiste Höhe
        spec_h = int((h - freq_bar_h) * self._spectrum_frac)
        wf_h = max(10, h - spec_h - freq_bar_h)

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

        # ── Frequenz-Leiste (zwischen Spektrum und Wasserfall) ────────
        freq_y = spec_h
        p.fillRect(0, freq_y, w, freq_bar_h, QColor(20, 25, 35))
        # Obere + untere Linie
        p.setPen(QPen(QColor(40, 50, 60), 1))
        p.drawLine(0, freq_y, w, freq_y)
        p.drawLine(0, freq_y + freq_bar_h, w, freq_y + freq_bar_h)

        if self._center_freq > 0 and self._span_hz > 0:
            start_freq = self._center_freq - self._span_hz // 2
            end_freq = self._center_freq + self._span_hz // 2

            p.setFont(QFont("Roboto", 8))
            p.setPen(QColor(160, 170, 180))
            for i in range(6):
                freq = start_freq + (end_freq - start_freq) * i / 5
                x = int(w * i / 5)
                mhz = freq / 1_000_000
                label = f"{mhz:.3f}"
                if i == 0:
                    p.drawText(x + 3, freq_y + 13, label)
                elif i == 5:
                    p.drawText(x - 48, freq_y + 13, label)
                else:
                    p.drawText(x - 22, freq_y + 13, label)
                # Tick-Linie
                p.setPen(QColor(60, 70, 80))
                p.drawLine(x, freq_y, x, freq_y + 4)
                p.setPen(QColor(160, 170, 180))

        # ── Wasserfall (Ring-Buffer: neueste oben) ────────────────────
        from PySide6.QtCore import QRect
        wf_y = freq_y + freq_bar_h
        wr = self._wf_write_row
        img_h = self._wf_lines

        # Teil 1: [wr..end] = ältere (unten)
        # Teil 2: [0..wr) = neuere (oben)
        # Neueste oben → erst [0..wr) dann [wr..end]
        if wr == 0:
            p.drawImage(QRect(0, wf_y, w, wf_h), self._wf_image)
        else:
            scale = wf_h / img_h
            new_h = max(1, int(wr * scale))
            old_h = wf_h - new_h
            # Oben: neuere [wr-1 → 0] (umgekehrt gezeichnet = neueste ganz oben)
            p.drawImage(QRect(0, wf_y, w, new_h),
                       self._wf_image, QRect(0, 0, self._num_points, wr))
            # Unten: ältere [end → wr]
            if old_h > 0:
                p.drawImage(QRect(0, wf_y + new_h, w, old_h),
                           self._wf_image, QRect(0, wr, self._num_points, img_h - wr))

        # ── Center-Marker (nur im Wasserfall) ────────────────────────
        if self._center_freq > 0:
            cx = w // 2
            p.setPen(QPen(QColor(6, 198, 164, 60), 1))
            p.drawLine(cx, wf_y, cx, h)

            # ── Bandbreiten-Anzeige (Passband) ───────────────────────
            if self._span_hz > 0 and self._filter_width > 0:
                bw_pixels = int(self._filter_width / self._span_hz * w)
                bx = cx - bw_pixels // 2
                # Halbtransparentes Rechteck im Wasserfall
                p.fillRect(bx, wf_y, bw_pixels, wf_h, QColor(6, 198, 164, 25))
                # Ränder
                p.setPen(QPen(QColor(6, 198, 164, 80), 1))
                p.drawLine(bx, wf_y, bx, h)
                p.drawLine(bx + bw_pixels, wf_y, bx + bw_pixels, h)

        p.end()
