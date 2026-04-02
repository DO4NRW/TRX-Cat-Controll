"""
Analog S-Meter Gauge — Portiert von AetherSDR SMeterWidget.
Flacher Bogen, Nadel von unten, Peak-Hold.
"""

import math
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont

from core.theme import T, rgba_parts

# Konstanten (wie AetherSDR)
ARC_START_DEG = 25.0   # rechtes Ende
ARC_END_DEG = 155.0    # linkes Ende
S9_FRAC = 0.6          # S9 bei 60% des Bogens


class SMeterGauge(QWidget):
    """Analog S-Meter mit flachem Bogen und Nadel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0       # 0-1000
        self._peak = 0
        self._peak_decay = 0
        self._s_text = "S0"
        self.setMinimumHeight(70)

    def setValue(self, val):
        self._value = max(0, min(1000, val))
        if val > self._peak:
            self._peak = val
            self._peak_decay = 80
        elif self._peak_decay > 0:
            self._peak_decay -= 1
        else:
            self._peak = max(0, self._peak - 5)
        self.update()

    def value(self):
        return self._value

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        # Hintergrund
        r, g, b, a = rgba_parts(T.get('bg_dark', 'rgba(26,26,26,255)'))
        p.fillRect(0, 0, w, h, QColor(r, g, b, a))

        # Arc Geometrie — flacher Bogen, volle Breite
        cx = w * 0.5
        radius = min(w * 0.48, h * 3.0)  # Begrenzt bei kleiner Höhe
        cy = h + radius * 0.4
        needle_cy = h + 4.0

        arc_start_rad = math.radians(ARC_START_DEG)
        arc_end_rad = math.radians(ARC_END_DEG)
        arc_span_rad = arc_end_rad - arc_start_rad

        def frac_to_angle(frac):
            """0=links, 1=rechts → Winkel in Radians."""
            return arc_end_rad - frac * arc_span_rad

        def arc_point(angle_rad, r):
            return QPointF(cx + r * math.cos(angle_rad), cy - r * math.sin(angle_rad))

        def needle_dir(angle_rad):
            ax = cx + radius * math.cos(angle_rad)
            ay = cy - radius * math.sin(angle_rad)
            dx = ax - cx
            dy = ay - needle_cy
            length = math.sqrt(dx * dx + dy * dy)
            if length < 0.001:
                return 0, -1
            return dx / length, dy / length

        # Farben
        tr, tg, tb, _ = rgba_parts(T.get('text', 'rgba(255,255,255,255)'))
        white_c = QColor(tr, tg, tb, 200)
        er, eg, eb, _ = rgba_parts(T.get('error', 'rgba(255,68,68,255)'))
        red_c = QColor(er, eg, eb)
        ar, ag, ab, _ = rgba_parts(T.get('accent', 'rgba(6,198,164,255)'))
        accent_c = QColor(ar, ag, ab)

        # ── Outer Arc (S-Meter Skala) ────────────────────────────────
        # S0→S9: weiß
        s9_angle = frac_to_angle(S9_FRAC)
        steps = 40
        for i in range(steps):
            f1 = i / steps
            f2 = (i + 1) / steps
            a1 = frac_to_angle(f1)
            a2 = frac_to_angle(f2)
            p1 = arc_point(a1, radius)
            p2 = arc_point(a2, radius)
            color = red_c if f1 >= S9_FRAC else white_c
            p.setPen(QPen(color, 2.5))
            p.drawLine(p1, p2)

        # ── Ticks + Labels ───────────────────────────────────────────
        font_size = max(8, h // 10)
        p.setFont(QFont("Consolas", font_size, QFont.Bold))

        # S-Units: S1, S3, S5, S7, S9
        s_ticks = [(1, "1"), (3, "3"), (5, "5"), (7, "7"), (9, "9")]
        for s_num, label in s_ticks:
            frac = s_num / 13.0
            angle = frac_to_angle(frac)
            ux, uy = needle_dir(angle)
            ax = cx + radius * math.cos(angle)
            ay = cy - radius * math.sin(angle)

            # Tick-Linie (nach außen)
            inner = QPointF(ax + 2 * ux, ay + 2 * uy)
            outer = QPointF(ax + 12 * ux, ay + 12 * uy)
            p.setPen(QPen(white_c, 1.5))
            p.drawLine(inner, outer)

            # Label
            lp = QPointF(ax + 22 * ux, ay + 22 * uy)
            p.setPen(white_c)
            p.drawText(int(lp.x()) - 4, int(lp.y()) + 4, label)

        # S9+ Ticks: +20, +40, +60
        for db_over, label in [(20, "+20"), (40, "+40"), (60, "+60")]:
            frac = (9 + db_over / 60 * 4) / 13.0
            angle = frac_to_angle(frac)
            ux, uy = needle_dir(angle)
            ax = cx + radius * math.cos(angle)
            ay = cy - radius * math.sin(angle)

            inner = QPointF(ax + 2 * ux, ay + 2 * uy)
            outer = QPointF(ax + 12 * ux, ay + 12 * uy)
            p.setPen(QPen(red_c, 1.5))
            p.drawLine(inner, outer)

            lp = QPointF(ax + 22 * ux, ay + 22 * uy)
            p.setPen(red_c)
            p.drawText(int(lp.x()) - 8, int(lp.y()) + 4, label)

        # ── Nadel ────────────────────────────────────────────────────
        frac = self._value / 1000.0
        needle_angle = frac_to_angle(frac)
        ux, uy = needle_dir(needle_angle)
        needle_len = radius * 0.95
        tip = QPointF(cx + needle_len * ux, needle_cy + needle_len * uy)

        # Schatten
        p.setPen(QPen(QColor(0, 0, 0, 60), 2))
        p.drawLine(QPointF(cx + 1, needle_cy + 1), QPointF(tip.x() + 1, tip.y() + 1))

        # Nadel
        p.setPen(QPen(accent_c, 2))
        p.drawLine(QPointF(cx, needle_cy), tip)

        # Nadel-Punkt
        p.setBrush(accent_c)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, needle_cy), 5, 5)

        # ── Peak Hold ────────────────────────────────────────────────
        if self._peak > 10:
            peak_frac = self._peak / 1000.0
            peak_angle = frac_to_angle(peak_frac)
            pp = arc_point(peak_angle, radius - 6)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 160, 0, 150))
            p.drawEllipse(pp, 3, 3)

        # ── S-Wert Text (Mitte oben) ────────────────────────────────
        s_num = min(13, int(frac * 13))
        if s_num <= 9:
            s_text = f"S{s_num}"
        else:
            s_text = f"S9+{(s_num - 9) * 10}"

        p.setFont(QFont("Consolas", font_size + 2, QFont.Bold))
        p.setPen(accent_c)
        tw = p.fontMetrics().horizontalAdvance(s_text)
        p.drawText(int(cx - tw / 2), int(h * 0.25), s_text)

        p.end()
