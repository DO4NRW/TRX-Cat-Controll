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

        # Wasserfall als QImage (Ring-Buffer)
        self._wf_image = QImage(num_points, self._wf_lines, QImage.Format_RGB32)
        self._wf_image.fill(QColor(10, 10, 20))

        # Display Settings
        self._color_gain = 6.0     # Farbverstärkung
        self._black_level = 5      # Unter diesem Wert = schwarz
        self._spectrum_frac = 0.35  # 35% Spektrum, 65% Wasserfall
        self._fill_alpha = 0.75

        # Farbpalette
        self._palette = self._build_palette()

        self.setMinimumHeight(150)
        self.setAttribute(Qt.WA_OpaquePaintEvent)

    def _build_palette(self):
        """SDR-Style Farbpalette: schwarz → blau → cyan → grün → gelb → rot → weiß."""
        palette = []
        stops = [
            (0.00, (10, 10, 20)),
            (0.05, (0, 0, 60)),
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

    def update_spectrum(self, data):
        """Neue Spektrumdaten (0-160 pro Punkt)."""
        if data is None or len(data) != self._num_points:
            return
        self._spectrum = np.array(data, dtype=np.float32)

        # Wasserfall-Zeile schreiben (Ring-Buffer)
        for col in range(self._num_points):
            idx = self._amp_to_color_idx(int(self._spectrum[col]))
            self._wf_image.setPixel(col, self._wf_write_row, self._palette[idx])
        self._wf_write_row = (self._wf_write_row + 1) % self._wf_lines

        self.update()

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

            # Gefüllte Balken pro Spalte
            fill_color = QColor(accent)
            fill_color.setAlpha(120)
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

        # ── Trennlinie ───────────────────────────────────────────────
        p.setPen(QPen(QColor(6, 198, 164), 1))
        p.drawLine(0, spec_h, w, spec_h)

        # ── Wasserfall (Ring-Buffer) ─────────────────────────────────
        wf_rect = self.rect()
        wf_rect.setTop(spec_h + 1)

        img_h = self._wf_lines
        wr = self._wf_write_row

        # Ring-Buffer: [0..writeRow) = neu, [writeRow..end] = alt
        # Oben = neueste Zeile, unten = älteste
        from PySide6.QtCore import QRect
        top_rows = wr        # Neuere Daten (0..writeRow)
        bot_rows = img_h - wr  # Ältere Daten (writeRow..end)

        if bot_rows >= img_h:
            p.drawImage(wf_rect, self._wf_image)
        else:
            scale = wf_h / img_h if img_h > 0 else 1
            top_h = int(top_rows * scale)
            bot_h = wf_h - top_h

            # Oben: neueste Zeilen (rückwärts von writeRow)
            if top_rows > 0 and top_h > 0:
                p.drawImage(
                    QRect(0, spec_h + 1, w, top_h),
                    self._wf_image,
                    QRect(0, 0, self._num_points, top_rows))
            # Unten: ältere Zeilen
            if bot_rows > 0 and bot_h > 0:
                p.drawImage(
                    QRect(0, spec_h + 1 + top_h, w, bot_h),
                    self._wf_image,
                    QRect(0, wr, self._num_points, bot_rows))

        p.end()
