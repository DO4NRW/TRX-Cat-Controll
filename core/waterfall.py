"""
Wasserfall/Spektrum-Widget — inspiriert von AetherSDR.
Spektrum oben mit Gradient-Fill, Wasserfall unten fließt von oben nach unten.
"""

import numpy as np
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import (QPainter, QColor, QImage, QLinearGradient,
                           QPainterPath, QPen, QFont, QCursor)

from core.theme import T


class WaterfallWidget(QWidget):
    """Spektrum + Wasserfall Display.

    Signals:
        frequency_clicked(int) — User hat auf eine Frequenz geklickt (Hz)
        frequency_scrolled(int) — User hat mit Mausrad gescrollt (Step in Hz, +/-)
    """
    frequency_clicked = Signal(int)   # Frequenz in Hz
    frequency_scrolled = Signal(int)  # Richtung * Step in Hz
    filter_changed = Signal(int)      # Neue Filter-Bandbreite in Hz

    def __init__(self, parent=None, num_points=475, max_amp=160):
        super().__init__(parent)
        self._num_points = num_points
        self._max_amp = max_amp
        self._spectrum = np.zeros(num_points, dtype=np.float32)
        self._wf_lines = 200

        # Wasserfall als numpy Array (RGB) — fließt von oben nach unten
        self._wf_data = np.zeros((self._wf_lines, num_points, 3), dtype=np.uint8)
        # Dunkelblauer Hintergrund
        self._wf_data[:, :, 0] = 8   # R
        self._wf_data[:, :, 1] = 12  # G
        self._wf_data[:, :, 2] = 35  # B

        # Display Settings
        self._color_gain = 3.0
        self._black_level = 3
        self._spectrum_frac = 0.35
        self._fill_alpha = 0.75

        # Farbpalette als numpy Array (256 x 3)
        self._palette = self._build_palette()

        self._last_spectrum = np.zeros(num_points, dtype=np.float32)
        self._display_spectrum = np.zeros(num_points, dtype=np.float32)
        self._scroll_timer = None
        self._center_freq = 0
        self._span_hz = 0
        self._filter_width = 2700
        self._filter_side = "upper"
        self._step_hz = 100
        self._scroll_accum = 0
        self._hover_x = -1
        self._dragging_filter = False  # Filter-Kante wird gezogen
        self._drag_edge = None         # "left" oder "right"

        self.setMinimumHeight(150)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setCursor(QCursor(Qt.CrossCursor))

    def _build_palette(self):
        """SDR-Style Farbpalette: schwarz → blau → cyan → grün → gelb → rot → weiß."""
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
        palette = np.zeros((256, 3), dtype=np.uint8)
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
            palette[i, 0] = int(lo[1][0] + t * (hi[1][0] - lo[1][0]))
            palette[i, 1] = int(lo[1][1] + t * (hi[1][1] - lo[1][1]))
            palette[i, 2] = int(lo[1][2] + t * (hi[1][2] - lo[1][2]))
        return palette

    def _amp_to_color_idx(self, spectrum):
        """Amplitude Array → Farbindex Array (vektorisiert)."""
        scaled = (spectrum - self._black_level) * self._color_gain
        scaled = np.clip(scaled, 0, 255).astype(np.uint8)
        scaled[spectrum <= self._black_level] = 0
        return scaled

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
        """Jeder Tick: blenden, neue Zeile oben rein, alles rutscht nach unten."""
        self._display_spectrum += 0.10 * (self._last_spectrum - self._display_spectrum)
        self._spectrum = self._display_spectrum.copy()

        # Alle Zeilen um eins nach unten schieben
        self._wf_data[1:] = self._wf_data[:-1]

        # Neue Zeile oben (Zeile 0) schreiben
        indices = self._amp_to_color_idx(self._display_spectrum)
        self._wf_data[0] = self._palette[indices]

        self.update()

    def set_freq_info(self, center_hz, span_hz, filter_width=None, filter_side=None):
        """Center-Frequenz, Span, Filter-Bandbreite und Seite."""
        self._center_freq = center_hz
        self._span_hz = span_hz
        if filter_width is not None:
            self._filter_width = filter_width
        if filter_side is not None:
            self._filter_side = filter_side

    def update_spectrum(self, data):
        """Neues Ziel-Spektrum setzen (Blend passiert im Scroll-Timer)."""
        if data is None or len(data) != self._num_points:
            return
        new = np.array(data, dtype=np.float32)
        if self._last_spectrum.max() == 0:
            self._display_spectrum = new.copy()
            self._spectrum = new.copy()
        self._last_spectrum = new

    def set_step_hz(self, step):
        """Tuning-Schrittweite für Mausrad setzen."""
        self._step_hz = max(1, int(step))

    def _x_to_freq(self, x):
        """Pixel X-Position → Frequenz in Hz."""
        if self._span_hz <= 0 or self._center_freq <= 0 or self.width() <= 0:
            return 0
        frac = x / self.width()
        start_freq = self._center_freq - self._span_hz // 2
        return int(start_freq + frac * self._span_hz)

    def _passband_edges_px(self):
        """Gibt (left_px, right_px) der Passband-Kanten zurück."""
        if self._span_hz <= 0 or self._filter_width <= 0:
            return None, None
        w = self.width()
        cx = w // 2
        bw_px = int(self._filter_width / self._span_hz * w)
        if self._filter_side == "upper":
            return cx, cx + bw_px
        elif self._filter_side == "lower":
            return cx - bw_px, cx
        else:
            return cx - bw_px // 2, cx + bw_px // 2

    def mousePressEvent(self, event):
        """Klick → Frequenz setzen oder Filter-Kante greifen."""
        if event.button() == Qt.LeftButton and self._span_hz > 0:
            x = int(event.position().x())
            left, right = self._passband_edges_px()

            # Prüfe ob nahe an einer Filter-Kante (±5px)
            if left is not None:
                if abs(x - left) < 6:
                    self._dragging_filter = True
                    self._drag_edge = "left"
                    event.accept()
                    return
                elif abs(x - right) < 6:
                    self._dragging_filter = True
                    self._drag_edge = "right"
                    event.accept()
                    return

            # Normaler Click-to-Tune
            if self._center_freq > 0:
                freq = self._x_to_freq(x)
                if freq > 0:
                    freq = round(freq / self._step_hz) * self._step_hz
                    self.frequency_clicked.emit(freq)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging_filter:
            self._dragging_filter = False
            self._drag_edge = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        """Hover, Filter-Drag oder Click-to-Tune Drag."""
        self._hover_x = int(event.position().x())
        x = self._hover_x
        w = self.width()

        # Filter-Kante ziehen
        if self._dragging_filter and self._span_hz > 0:
            cx = w // 2
            dx_hz = abs(x - cx) / w * self._span_hz
            new_bw = max(100, int(dx_hz))  # Min 100 Hz
            if new_bw != self._filter_width:
                self._filter_width = new_bw
                self.filter_changed.emit(new_bw)
            self.update()
            event.accept()
            return

        # Cursor anpassen: Resize-Cursor nahe Filter-Kanten
        left, right = self._passband_edges_px()
        if left is not None and (abs(x - left) < 6 or abs(x - right) < 6):
            self.setCursor(QCursor(Qt.SizeHorCursor))
        else:
            self.setCursor(QCursor(Qt.CrossCursor))

        # Click-to-Tune Drag
        if event.buttons() & Qt.LeftButton and not self._dragging_filter:
            if self._span_hz > 0 and self._center_freq > 0:
                freq = self._x_to_freq(x)
                if freq > 0:
                    freq = round(freq / self._step_hz) * self._step_hz
                    self.frequency_clicked.emit(freq)

        self.update()
        event.accept()

    def leaveEvent(self, event):
        """Maus verlässt Widget → Cursor-Linie ausblenden."""
        self._hover_x = -1
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event):
        """Mausrad → Frequenz hoch/runter um Step-Size."""
        delta = event.angleDelta().y()
        self._scroll_accum += delta
        steps = self._scroll_accum // 120
        self._scroll_accum -= steps * 120
        if steps != 0:
            self.frequency_scrolled.emit(int(steps * self._step_hz))
        event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        w = self.width()
        h = self.height()

        if w <= 0 or h <= 10:
            p.end()
            return

        freq_bar_h = 18
        spec_h = int((h - freq_bar_h) * self._spectrum_frac)
        wf_h = max(10, h - spec_h - freq_bar_h)

        # ── Spektrum-Hintergrund ─────────────────────────────────────
        from core.theme import T, rgba_parts
        bg = QColor(*rgba_parts(T.get('wf_bg', 'rgba(18,22,30,255)')))
        p.fillRect(0, 0, w, spec_h, bg)

        # ── Grid ─────────────────────────────────────────────────────
        grid_color = QColor(*rgba_parts(T.get('wf_grid', 'rgba(30,40,55,255)')))
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
            accent = QColor(*rgba_parts(T.get('accent', 'rgba(6,198,164,255)')))
            n = self._num_points
            auto_scale = 0.85 / max(peak, 1)

            fill_color = QColor(accent)
            fill_color.setAlpha(30)
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

            p.setPen(QPen(accent, 1))
            for i in range(1, len(line_points)):
                p.drawLine(line_points[i-1][0], line_points[i-1][1],
                          line_points[i][0], line_points[i][1])

        # ── Frequenz-Leiste ──────────────────────────────────────────
        freq_y = spec_h
        freq_bar_bg = QColor(*rgba_parts(T.get('wf_freq_bar', 'rgba(20,25,35,255)')))
        freq_text_c = QColor(*rgba_parts(T.get('wf_freq_text', 'rgba(160,170,180,255)')))
        freq_tick_c = QColor(*rgba_parts(T.get('wf_freq_tick', 'rgba(60,70,80,255)')))
        p.fillRect(0, freq_y, w, freq_bar_h, freq_bar_bg)
        p.setPen(QPen(freq_tick_c, 1))
        p.drawLine(0, freq_y, w, freq_y)
        p.drawLine(0, freq_y + freq_bar_h, w, freq_y + freq_bar_h)

        if self._center_freq > 0 and self._span_hz > 0:
            start_freq = self._center_freq - self._span_hz // 2
            end_freq = self._center_freq + self._span_hz // 2

            p.setFont(QFont("Roboto", 8))
            p.setPen(freq_text_c)
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
                p.setPen(freq_tick_c)
                p.drawLine(x, freq_y, x, freq_y + 4)
                p.setPen(freq_text_c)

        # ── Wasserfall (numpy → QImage, fließt von oben nach unten) ──
        wf_y = freq_y + freq_bar_h

        # numpy RGB Array → QImage
        rgb = np.ascontiguousarray(self._wf_data)
        # RGBX Format braucht 4 Bytes pro Pixel
        h_img, w_img, _ = rgb.shape
        rgbx = np.zeros((h_img, w_img, 4), dtype=np.uint8)
        rgbx[:, :, 0] = rgb[:, :, 2]  # B
        rgbx[:, :, 1] = rgb[:, :, 1]  # G
        rgbx[:, :, 2] = rgb[:, :, 0]  # R
        rgbx[:, :, 3] = 255           # A

        img = QImage(rgbx.data, w_img, h_img, w_img * 4, QImage.Format_RGB32)
        p.drawImage(QRect(0, wf_y, w, wf_h), img)

        # ── Center-Marker + Passband (über Spektrum UND Wasserfall) ──
        if self._center_freq > 0:
            ar, ag, ab, _ = rgba_parts(T.get('accent', 'rgba(6,198,164,255)'))
            cx = w // 2
            # Center-Linie (über gesamte Höhe)
            p.setPen(QPen(QColor(ar, ag, ab, 100), 1))
            p.drawLine(cx, 0, cx, h)

            # Bandbreiten-Anzeige (Passband)
            if self._span_hz > 0 and self._filter_width > 0:
                bw_pixels = int(self._filter_width / self._span_hz * w)
                if self._filter_side == "upper":
                    bx = cx
                elif self._filter_side == "lower":
                    bx = cx - bw_pixels
                else:
                    bx = cx - bw_pixels // 2
                # Halbtransparente Füllung über gesamte Höhe
                p.fillRect(bx, 0, bw_pixels, h, QColor(ar, ag, ab, 40))
                # Ränder
                p.setPen(QPen(QColor(ar, ag, ab, 140), 1))
                p.drawLine(bx, 0, bx, h)
                p.drawLine(bx + bw_pixels, 0, bx + bw_pixels, h)

        # ── Maus-Cursor mit Frequenz-Label ───────────────────────────
        if self._hover_x >= 0 and self._span_hz > 0:
            cr, cg, cb, _ = rgba_parts(T.get('wf_cursor', 'rgba(0,220,100,255)'))
            hx = self._hover_x
            # Cursor-Linie
            p.setPen(QPen(QColor(cr, cg, cb, 100), 1, Qt.DashLine))
            p.drawLine(hx, 0, hx, h)

            # Frequenz-Label am Cursor
            hover_freq = self._x_to_freq(hx)
            if hover_freq > 0:
                hover_freq = round(hover_freq / self._step_hz) * self._step_hz
                khz = (hover_freq % 1_000_000) // 1_000
                hz = hover_freq % 1_000
                label = f"{hover_freq // 1_000_000}.{khz:03d}.{hz:03d}"
                p.setFont(QFont("Consolas", 9, QFont.Bold))
                fm = p.fontMetrics()
                tw = fm.horizontalAdvance(label) + 8
                th = fm.height() + 4
                lx = min(hx + 5, w - tw - 2)
                ly = 4
                p.fillRect(lx, ly, tw, th, QColor(0, 0, 0, 180))
                p.setPen(QColor(cr, cg, cb))
                p.drawText(lx + 4, ly + fm.ascent() + 2, label)

        p.end()
