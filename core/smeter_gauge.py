"""
Analog S-Meter Gauge — inspiriert von AetherSDR/FlexRadio.
Bogen mit Nadel, S-Stufen, Peak-Hold.
"""

import math
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QConicalGradient

from core.theme import T, rgba_parts


class SMeterGauge(QWidget):
    """Analog S-Meter mit Bogen-Skala und Nadel."""

    _S_LABELS = ["S1", "S3", "S5", "S7", "S9", "+20", "+40", "+60"]
    _S_FRACTIONS = [1/13, 3/13, 5/13, 7/13, 9/13, 11/13, 12/13, 1.0]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0       # 0-1000
        self._peak = 0        # Peak-Hold
        self._peak_decay = 0  # Decay-Counter
        self.setMinimumHeight(80)
        self.setMinimumWidth(200)

    def setValue(self, val):
        """Wert setzen (0-1000)."""
        self._value = max(0, min(1000, val))
        # Peak-Hold
        if val > self._peak:
            self._peak = val
            self._peak_decay = 60  # ~3 Sekunden bei 20fps
        elif self._peak_decay > 0:
            self._peak_decay -= 1
        else:
            self._peak = max(0, self._peak - 8)  # Langsam abfallen
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

        # Arc Geometrie
        cx = w * 0.5
        radius = w * 0.42
        cy = h * 0.85  # Bogen-Zentrum unten

        arc_start = 200  # Grad (links)
        arc_end = 340    # Grad (rechts)
        arc_span = arc_end - arc_start

        def frac_to_angle(frac):
            """Fraction 0-1 → Winkel in Grad."""
            return arc_start + frac * arc_span

        def angle_to_point(angle_deg, r):
            """Winkel → Punkt auf dem Bogen."""
            rad = math.radians(angle_deg)
            return QPointF(cx + r * math.cos(rad), cy - r * math.sin(rad))

        # ── Bogen zeichnen ───────────────────────────────────────────
        ar, ag, ab, _ = rgba_parts(T.get('text', 'rgba(255,255,255,255)'))
        s9_frac = 9 / 13  # S9 Position

        # S0-S9: weiß
        pen_white = QPen(QColor(ar, ag, ab), 2)
        p.setPen(pen_white)
        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        p.drawArc(rect, int(frac_to_angle(0) * 16), int((s9_frac * arc_span) * 16))

        # S9+: rot/accent
        acr, acg, acb, _ = rgba_parts(T.get('error', 'rgba(255,68,68,255)'))
        pen_red = QPen(QColor(acr, acg, acb), 2)
        p.setPen(pen_red)
        start_angle = frac_to_angle(s9_frac)
        span_angle = (1.0 - s9_frac) * arc_span
        p.drawArc(rect, int(start_angle * 16), int(span_angle * 16))

        # ── Tick-Marks + Labels ──────────────────────────────────────
        p.setFont(QFont("Consolas", 7))
        tr, tg, tb, _ = rgba_parts(T.get('text_secondary', 'rgba(204,204,204,255)'))

        for i, (label, frac) in enumerate(zip(self._S_LABELS, self._S_FRACTIONS)):
            angle = frac_to_angle(frac)
            # Tick
            p1 = angle_to_point(angle, radius - 4)
            p2 = angle_to_point(angle, radius + 4)
            color = QColor(acr, acg, acb) if frac > s9_frac else QColor(ar, ag, ab)
            p.setPen(QPen(color, 1))
            p.drawLine(p1, p2)
            # Label
            lp = angle_to_point(angle, radius + 14)
            p.setPen(QColor(tr, tg, tb))
            p.drawText(int(lp.x()) - 8, int(lp.y()) + 3, label)

        # ── Nadel ────────────────────────────────────────────────────
        frac = self._value / 1000.0
        needle_angle = frac_to_angle(frac)
        needle_tip = angle_to_point(needle_angle, radius - 8)

        # Nadel-Schatten
        p.setPen(QPen(QColor(0, 0, 0, 80), 3))
        p.drawLine(QPointF(cx + 1, cy + 1), QPointF(needle_tip.x() + 1, needle_tip.y() + 1))

        # Nadel
        accent_r, accent_g, accent_b, _ = rgba_parts(T.get('accent', 'rgba(6,198,164,255)'))
        p.setPen(QPen(QColor(accent_r, accent_g, accent_b), 2))
        p.drawLine(QPointF(cx, cy), needle_tip)

        # Nadel-Punkt (Zentrum)
        p.setBrush(QColor(accent_r, accent_g, accent_b))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), 4, 4)

        # ── Peak-Hold Marker ─────────────────────────────────────────
        if self._peak > 0:
            peak_frac = self._peak / 1000.0
            peak_angle = frac_to_angle(peak_frac)
            peak_p = angle_to_point(peak_angle, radius - 2)
            p.setPen(QPen(QColor(255, 160, 0, 180), 2))
            p.setBrush(QColor(255, 160, 0, 180))
            p.drawEllipse(peak_p, 3, 3)

        # ── Wert-Text ────────────────────────────────────────────────
        p.setFont(QFont("Consolas", 10, QFont.Bold))
        p.setPen(QColor(accent_r, accent_g, accent_b))
        # S-Stufe berechnen
        s_num = min(9, int(frac * 13))
        if s_num <= 9:
            s_text = f"S{s_num}"
        else:
            s_text = f"S9+{(s_num - 9) * 10}"
        p.drawText(int(cx) - 15, int(cy) - 8, s_text)

        p.end()
