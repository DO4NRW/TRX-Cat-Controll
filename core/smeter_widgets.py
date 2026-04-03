"""
S-Meter Widgets — 4 Designs, alle dynamisch aus theme.json konfigurierbar.
Factory: create_smeter(style, parent) erstellt das passende Widget.
"""

import math
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics

from core.theme import T, rgba_parts


_S_LABELS = ["S1","S2","S3","S4","S5","S6","S7","S8","S9","+10","+20","+40","+60"]


def _color(key, fallback="rgba(128,128,128,255)"):
    """Theme-Farbe als QColor."""
    r, g, b, a = rgba_parts(T.get(key, fallback))
    return QColor(r, g, b, a)


def _val_to_s(val):
    """0-1000 → S-String (S0-S9+60dB)."""
    raw = val * 255 // 1000
    if raw <= 128:
        s = min(9, round(raw * 9 / 128))
        return f"S{s}"
    else:
        db_over = round((raw - 128) / 127 * 60)
        return f"S9+{db_over}dB"


def _val_to_label_idx(val):
    """0-1000 → Label-Index (0-12)."""
    raw = val * 255 // 1000
    return min(12, raw * 13 // 256)


# ═══════════════════════════════════════════════════════════════════
# 1. SEGMENT — Horizontale Balkenleiste (QProgressBar + Labels)
# ═══════════════════════════════════════════════════════════════════

class SMeterSegment(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._s_text = "S0"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        self.lbl_info = None  # Kompatibilität

        # Scale Labels
        scale_row = QHBoxLayout()
        scale_row.setSpacing(0)
        self.s_labels = []
        for s in _S_LABELS:
            lbl = QLabel(s)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(f"color: {T['smeter_label_inactive']}; font-size: 10px; font-weight: bold; border: none;")
            scale_row.addWidget(lbl, stretch=1)
            self.s_labels.append(lbl)
        root.addLayout(scale_row)

        # Progress Bar
        self.bar = QProgressBar()
        self.bar.setFixedHeight(18)
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self._apply_bar_style()
        root.addWidget(self.bar)

    def _apply_bar_style(self):
        self.bar.setStyleSheet(f"""
            QProgressBar {{ background-color: {T['bg_dark']}; border: 1px solid {T['border']}; border-radius: 4px; }}
            QProgressBar::chunk {{ background-color: {T['smeter_bar']}; border-radius: 3px; }}""")

    def setValue(self, val):
        self._value = max(0, min(1000, val))
        self.bar.setValue(self._value)
        idx = _val_to_label_idx(self._value)
        for i, lbl in enumerate(self.s_labels):
            if i <= idx:
                lbl.setStyleSheet(f"color: {T['smeter_label_active']}; font-size: 10px; font-weight: bold; border: none;")
            else:
                lbl.setStyleSheet(f"color: {T['smeter_label_inactive']}; font-size: 10px; font-weight: bold; border: none;")

    def setLabel(self, text):
        pass

    def refresh_theme(self):
        self._apply_bar_style()
        for lbl in self.s_labels:
            lbl.setStyleSheet(f"color: {T['smeter_label_inactive']}; font-size: 10px; font-weight: bold; border: none;")


# ═══════════════════════════════════════════════════════════════════
# 2. GAUGE — Analog-Bogen mit Nadel + Peak-Hold
# ═══════════════════════════════════════════════════════════════════

ARC_START_DEG = 25.0
ARC_END_DEG = 155.0
S9_FRAC = 0.6


class SMeterGauge(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._peak = 0
        self._peak_decay = 0
        self._s_text = "S-METER: ---"
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

    def setLabel(self, text):
        self._s_text = text
        self.update()

    def refresh_theme(self):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        # Hintergrund
        # Transparenter Hintergrund — folgt dem GUI-Theme

        cx = w * 0.5
        radius = h * 0.7
        cy = h * 0.95
        needle_cy = h * 0.80

        arc_start_rad = math.radians(ARC_START_DEG)
        arc_end_rad = math.radians(ARC_END_DEG)
        arc_span_rad = arc_end_rad - arc_start_rad

        def frac_to_angle(frac):
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

        # Farben aus Theme
        normal_c = _color('smeter_arc_normal')
        over_c = _color('smeter_arc_over')
        needle_c = _color('smeter_needle')
        shaft_c = _color('smeter_needle_shaft')
        pivot_c = _color('smeter_needle_pivot')
        peak_c = _color('smeter_peak')
        text_c = _color('text')

        # Bogen
        s9_angle = frac_to_angle(S9_FRAC)
        steps = 40
        for i in range(steps):
            f1 = i / steps
            f2 = (i + 1) / steps
            a1 = frac_to_angle(f1)
            a2 = frac_to_angle(f2)
            p1 = arc_point(a1, radius)
            p2 = arc_point(a2, radius)
            color = over_c if f1 >= S9_FRAC else normal_c
            p.setPen(QPen(color, 2.5))
            p.drawLine(p1, p2)

        # Ticks + Labels
        font_size = max(6, h // 12)
        p.setFont(QFont("Consolas", font_size, QFont.Bold))

        s_ticks = [(1, "1"), (3, "3"), (5, "5"), (7, "7"), (9, "9")]
        for s_num, label in s_ticks:
            frac = s_num / 13.0
            angle = frac_to_angle(frac)
            ux, uy = needle_dir(angle)
            ax = cx + radius * math.cos(angle)
            ay = cy - radius * math.sin(angle)
            inner = QPointF(ax + 1 * ux, ay + 1 * uy)
            outer = QPointF(ax + 8 * ux, ay + 8 * uy)
            p.setPen(QPen(normal_c, 1.5))
            p.drawLine(inner, outer)
            lp = QPointF(ax + 14 * ux, ay + 14 * uy)
            p.setPen(normal_c)
            p.drawText(int(lp.x()) - 4, int(lp.y()) + 4, label)

        for db_over, label in [(20, "+20"), (40, "+40"), (60, "+60")]:
            frac = (9 + db_over / 60 * 4) / 13.0
            angle = frac_to_angle(frac)
            ux, uy = needle_dir(angle)
            ax = cx + radius * math.cos(angle)
            ay = cy - radius * math.sin(angle)
            inner = QPointF(ax + 1 * ux, ay + 1 * uy)
            outer = QPointF(ax + 8 * ux, ay + 8 * uy)
            p.setPen(QPen(over_c, 1.5))
            p.drawLine(inner, outer)
            lp = QPointF(ax + 14 * ux, ay + 14 * uy)
            p.setPen(over_c)
            p.drawText(int(lp.x()) - 8, int(lp.y()) + 4, label)

        # Nadel
        frac = self._value / 1000.0
        needle_angle = frac_to_angle(frac)
        ux, uy = needle_dir(needle_angle)
        needle_len = radius * 0.85
        origin = QPointF(cx, needle_cy)
        tip = QPointF(cx + needle_len * ux, needle_cy + needle_len * uy)
        mid = QPointF(cx + needle_len * 0.75 * ux, needle_cy + needle_len * 0.75 * uy)

        p.setPen(QPen(shaft_c, 2))
        p.drawLine(origin, mid)
        p.setPen(QPen(needle_c, 2))
        p.drawLine(mid, tip)

        # Drehpunkt
        p.setBrush(pivot_c)
        p.setPen(QPen(shaft_c, 1))
        p.drawEllipse(origin, 3, 3)

        # Peak Hold
        if self._peak > 10:
            peak_frac = self._peak / 1000.0
            peak_angle = frac_to_angle(peak_frac)
            pp = arc_point(peak_angle, radius - 6)
            p.setPen(Qt.NoPen)
            p.setBrush(peak_c)
            p.drawEllipse(pp, 3, 3)

        p.end()


# ═══════════════════════════════════════════════════════════════════
# 3. LED — Einzelne Rechtecke, Grün→Gelb→Rot
# ═══════════════════════════════════════════════════════════════════

class SMeterLED(QWidget):

    _NUM_LEDS = 13
    # LED 0-6 = Grün (S1-S7), 7-8 = Gelb (S8-S9), 9-12 = Rot (+10 bis +60)
    _GREEN_END = 7
    _YELLOW_END = 9

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._s_text = "S-METER: ---"
        self.setMinimumHeight(50)

    def setValue(self, val):
        self._value = max(0, min(1000, val))
        self.update()

    def setLabel(self, text):
        self._s_text = text
        self.update()

    def refresh_theme(self):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        # Transparenter Hintergrund — folgt dem GUI-Theme

        active_idx = _val_to_label_idx(self._value)

        green_c = _color('smeter_led_green')
        yellow_c = _color('smeter_led_yellow')
        red_c = _color('smeter_led_red')
        off_c = _color('smeter_led_off')
        text_c = _color('text')

        margin = 4
        spacing = 3
        label_h = max(12, h // 4)
        led_area_w = w - 2 * margin
        led_w = (led_area_w - (self._NUM_LEDS - 1) * spacing) / self._NUM_LEDS
        led_h = h - label_h - margin * 2
        y_led = margin
        y_label = margin + led_h + 2

        font_size = max(7, min(10, int(led_w * 0.6)))
        p.setFont(QFont("Consolas", font_size, QFont.Bold))

        led_size = min(led_w, led_h) * 0.55
        led_radius = led_size / 2
        border_c = _color('border')

        for i in range(self._NUM_LEDS):
            cx = margin + i * (led_w + spacing) + led_w / 2
            cy = y_led + led_h / 2

            # Farbe bestimmen (Grün → Gelb → Rot)
            if i < self._GREEN_END:
                fill_c = green_c
            elif i < self._YELLOW_END:
                fill_c = yellow_c
            else:
                fill_c = red_c

            # Aktive LEDs: gefüllt, Inaktive: nur Border + dunkle Füllung
            if i <= active_idx:
                p.setBrush(fill_c)
            else:
                p.setBrush(off_c)
            p.setPen(QPen(border_c, 1.5))
            p.drawEllipse(QPointF(cx, cy), led_radius, led_radius)

            # Label darunter
            label = _S_LABELS[i] if i < len(_S_LABELS) else ""
            p.setPen(text_c if i <= active_idx else off_c)
            fm = QFontMetrics(p.font())
            tw = fm.horizontalAdvance(label)
            p.drawText(int(cx - tw / 2), int(y_label + font_size), label)

        p.end()


# ═══════════════════════════════════════════════════════════════════
# 4. DIGIT — Große Zahl-Anzeige (minimalistisch)
# ═══════════════════════════════════════════════════════════════════

class SMeterDigit(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._s_text = "---"
        self._preamp = ""
        self.setMinimumHeight(40)

    def setValue(self, val):
        self._value = max(0, min(1000, val))
        self.update()

    def setLabel(self, text):
        # Extrahiere S-Wert und Preamp aus "S-METER: S9+20dB | AMP2"
        clean = text.replace("S-METER:", "").strip()
        if "|" in clean:
            parts = clean.split("|")
            self._s_text = parts[0].strip()
            self._preamp = parts[-1].strip()
        elif clean and clean != "---":
            self._s_text = clean
        self.update()

    def refresh_theme(self):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        # Transparenter Hintergrund — folgt dem GUI-Theme

        digit_c = _color('smeter_digit_color')
        text_c = _color('text')

        # Große S-Wert Anzeige
        big_size = max(16, h // 2)
        p.setFont(QFont("Consolas", big_size, QFont.Bold))
        p.setPen(digit_c)
        fm = QFontMetrics(p.font())
        tw = fm.horizontalAdvance(self._s_text)
        p.drawText(int(w / 2 - tw / 2), int(h / 2 + big_size / 3), self._s_text)

        # Balken-Indikator unten (dünner Streifen)
        bar_h = max(3, h // 15)
        bar_w = w - 8
        frac = self._value / 1000.0
        p.setPen(Qt.NoPen)

        # Hintergrund
        p.setBrush(_color('smeter_led_off'))
        p.drawRoundedRect(QRectF(4, h - bar_h - 2, bar_w, bar_h), 2, 2)

        # Gefüllter Teil
        p.setBrush(digit_c)
        p.drawRoundedRect(QRectF(4, h - bar_h - 2, bar_w * frac, bar_h), 2, 2)

        p.end()


# ═══════════════════════════════════════════════════════════════════
# 5. VU-METER — Vertikale Balken gestapelt mit Glow-Effekt
# ═══════════════════════════════════════════════════════════════════

class SMeterVU(QWidget):

    _NUM_BARS = 13

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._s_text = "---"
        self.setMinimumHeight(50)

    def setValue(self, val):
        self._value = max(0, min(1000, val))
        self.update()

    def setLabel(self, text):
        clean = text.replace("S-METER:", "").strip()
        if "|" in clean:
            self._s_text = clean.split("|")[0].strip()
        elif clean and clean != "---":
            self._s_text = clean
        self.update()

    def refresh_theme(self):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        # Transparenter Hintergrund — folgt dem GUI-Theme

        active_idx = _val_to_label_idx(self._value)
        green_c = _color('smeter_led_green')
        yellow_c = _color('smeter_led_yellow')
        red_c = _color('smeter_led_red')
        off_c = _color('smeter_led_off')
        border_c = _color('border')
        text_c = _color('text')

        margin = 4
        spacing = 2
        label_w = 30
        s_label_h = max(14, h // 5)
        bar_area_h = h - 2 * margin - s_label_h
        bar_h = (bar_area_h - (self._NUM_BARS - 1) * spacing) / self._NUM_BARS
        bar_w = w - label_w - margin * 2

        font_size = max(7, min(9, int(bar_h * 0.7)))
        p.setFont(QFont("Consolas", font_size, QFont.Bold))

        for i in range(self._NUM_BARS):
            # Von unten nach oben: Index 0 = unten (S1), Index 12 = oben (+60)
            row = self._NUM_BARS - 1 - i
            y = margin + row * (bar_h + spacing)

            # Farbe
            if i < 7:
                fill_c = green_c
            elif i < 9:
                fill_c = yellow_c
            else:
                fill_c = red_c

            rect = QRectF(label_w + margin, y, bar_w, bar_h)

            if i <= active_idx:
                p.setBrush(fill_c)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(rect, 2, 2)
                # Glow-Effekt
                glow = QColor(fill_c)
                glow.setAlpha(40)
                p.setBrush(glow)
                p.drawRoundedRect(QRectF(rect.x() - 1, rect.y() - 1, rect.width() + 2, rect.height() + 2), 3, 3)
            else:
                p.setBrush(off_c)
                p.setPen(QPen(border_c, 0.5))
                p.drawRoundedRect(rect, 2, 2)

            # Label links
            label = _S_LABELS[i] if i < len(_S_LABELS) else ""
            p.setPen(text_c if i <= active_idx else off_c)
            p.drawText(int(margin), int(y + bar_h * 0.75), label)

        # S-Wert unten groß anzeigen
        s_size = max(10, int(s_label_h * 0.8))
        p.setFont(QFont("Consolas", s_size, QFont.Bold))
        p.setPen(text_c)
        fm = QFontMetrics(p.font())
        tw = fm.horizontalAdvance(self._s_text)
        p.drawText(int(w / 2 - tw / 2), int(h - margin), self._s_text)

        p.end()


# ═══════════════════════════════════════════════════════════════════
# 6. NIXIE — Röhren-Stil mit Scanlines und Glow
# ═══════════════════════════════════════════════════════════════════

class SMeterNixie(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._s_text = "---"
        self.setMinimumHeight(40)

    def setValue(self, val):
        self._value = max(0, min(1000, val))
        self.update()

    def setLabel(self, text):
        clean = text.replace("S-METER:", "").strip()
        if "|" in clean:
            self._s_text = clean.split("|")[0].strip()
        elif clean and clean != "---":
            self._s_text = clean
        self.update()

    def refresh_theme(self):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        # Transparenter Hintergrund — folgt dem GUI-Theme

        # Nixie-Orange Farbe
        nixie_c = QColor(255, 160, 80, 230)
        nixie_glow = QColor(255, 140, 60, 60)
        off_c = _color('smeter_led_off')

        # Glow-Hintergrund
        p.setBrush(nixie_glow)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(4, 4, w - 8, h - 8), 6, 6)

        # Große Nixie-Zahl
        big_size = max(18, h // 2)
        p.setFont(QFont("Consolas", big_size, QFont.Bold))

        # Glow (unscharfer Text dahinter)
        glow_c = QColor(255, 140, 60, 80)
        p.setPen(glow_c)
        fm = QFontMetrics(p.font())
        tw = fm.horizontalAdvance(self._s_text)
        tx = int(w / 2 - tw / 2)
        ty = int(h / 2 + big_size / 3)
        for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1), (0, -2), (0, 2)]:
            p.drawText(tx + dx, ty + dy, self._s_text)

        # Scharfer Text
        p.setPen(nixie_c)
        p.drawText(tx, ty, self._s_text)

        # Scanlines
        p.setPen(QPen(QColor(0, 0, 0, 30), 1))
        for y_line in range(0, h, 3):
            p.drawLine(0, y_line, w, y_line)

        # Fortschrittsbalken unten
        bar_h = max(3, h // 12)
        bar_w = w - 12
        frac = self._value / 1000.0
        p.setPen(Qt.NoPen)
        p.setBrush(off_c)
        p.drawRoundedRect(QRectF(6, h - bar_h - 4, bar_w, bar_h), 2, 2)
        p.setBrush(nixie_c)
        p.drawRoundedRect(QRectF(6, h - bar_h - 4, bar_w * frac, bar_h), 2, 2)

        p.end()


# ═══════════════════════════════════════════════════════════════════
# 7. CLASSIC — Collins-Style Rundskala mit Chromnadel
# ═══════════════════════════════════════════════════════════════════

class SMeterClassic(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._peak = 0
        self._peak_decay = 0
        self.setMinimumHeight(60)

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

    def setLabel(self, text):
        pass

    def refresh_theme(self):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        bg_c = _color('bg_dark')
        p.fillRect(0, 0, w, h, bg_c)

        green_c = _color('smeter_led_green')
        yellow_c = _color('smeter_led_yellow')
        red_c = _color('smeter_led_red')
        needle_c = _color('smeter_needle')
        shaft_c = _color('smeter_needle_shaft')
        pivot_c = _color('smeter_needle_pivot')
        peak_c = _color('smeter_peak')
        text_c = _color('text')
        border_c = _color('border')

        cx = w * 0.5
        radius = h * 0.55
        cy = h * 0.90

        arc_start = math.radians(20.0)
        arc_end = math.radians(160.0)
        arc_span = arc_end - arc_start

        def f2a(frac):
            return arc_end - frac * arc_span

        def arc_pt(angle, r):
            return QPointF(cx + r * math.cos(angle), cy - r * math.sin(angle))

        # Farbzonen als dicke Bögen
        zone_width = 6
        zones = [
            (0.0, 0.46, green_c),    # S1-S6
            (0.46, 0.62, yellow_c),  # S7-S8
            (0.62, 1.0, red_c),      # S9+
        ]
        for f_start, f_end, color in zones:
            steps = 20
            for i in range(steps):
                f1 = f_start + (f_end - f_start) * i / steps
                f2 = f_start + (f_end - f_start) * (i + 1) / steps
                p1 = arc_pt(f2a(f1), radius)
                p2 = arc_pt(f2a(f2), radius)
                p.setPen(QPen(color, zone_width, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(p1, p2)

        # Ticks + Labels
        font_size = max(6, h // 10)
        p.setFont(QFont("Consolas", font_size, QFont.Bold))
        s_ticks = [(1, "1"), (3, "3"), (5, "5"), (7, "7"), (9, "9")]
        for s_num, label in s_ticks:
            frac = s_num / 13.0
            angle = f2a(frac)
            outer = arc_pt(angle, radius + zone_width / 2 + 2)
            tip = arc_pt(angle, radius + zone_width / 2 + 8)
            p.setPen(QPen(text_c, 1))
            p.drawLine(outer, tip)
            lbl_pt = arc_pt(angle, radius + zone_width / 2 + 16)
            p.drawText(int(lbl_pt.x()) - 4, int(lbl_pt.y()) + 4, label)

        for db, label in [(20, "+20"), (40, "+40"), (60, "+60")]:
            frac = (9 + db / 60 * 4) / 13.0
            angle = f2a(frac)
            outer = arc_pt(angle, radius + zone_width / 2 + 2)
            tip = arc_pt(angle, radius + zone_width / 2 + 8)
            p.setPen(QPen(red_c, 1))
            p.drawLine(outer, tip)
            lbl_pt = arc_pt(angle, radius + zone_width / 2 + 14)
            p.drawText(int(lbl_pt.x()) - 8, int(lbl_pt.y()) + 4, label)

        # Nadel (Chrome-Look)
        frac = self._value / 1000.0
        angle = f2a(frac)
        needle_len = radius * 0.95
        dx = math.cos(angle)
        dy = -math.sin(angle)
        origin = QPointF(cx, cy)
        tip = QPointF(cx + needle_len * dx, cy + needle_len * dy)

        p.setPen(QPen(shaft_c, 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(origin, tip)
        p.setPen(QPen(needle_c, 1.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(origin, tip)

        # Pivot
        p.setBrush(pivot_c)
        p.setPen(QPen(border_c, 1.5))
        p.drawEllipse(origin, 5, 5)

        # Peak
        if self._peak > 10:
            peak_angle = f2a(self._peak / 1000.0)
            pp = arc_pt(peak_angle, radius - 4)
            p.setPen(Qt.NoPen)
            p.setBrush(peak_c)
            p.drawEllipse(pp, 3, 3)

        p.end()


# ═══════════════════════════════════════════════════════════════════
# 8. DUAL — Zwei Nadeln (Signal + Peak-Hold als zweite Nadel)
# ═══════════════════════════════════════════════════════════════════

class SMeterDual(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._peak = 0
        self._peak_decay = 0
        self.setMinimumHeight(60)

    def setValue(self, val):
        self._value = max(0, min(1000, val))
        if val > self._peak:
            self._peak = val
            self._peak_decay = 100
        elif self._peak_decay > 0:
            self._peak_decay -= 1
        else:
            self._peak = max(0, self._peak - 3)
        self.update()

    def setLabel(self, text):
        pass

    def refresh_theme(self):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        # Transparenter Hintergrund — folgt dem GUI-Theme

        normal_c = _color('smeter_arc_normal')
        over_c = _color('smeter_arc_over')
        needle_c = _color('smeter_needle')
        peak_c = _color('smeter_peak')
        shaft_c = _color('smeter_needle_shaft')
        pivot_c = _color('smeter_needle_pivot')
        text_c = _color('text')

        cx = w * 0.5
        radius = h * 0.75
        cy = h * 0.95

        arc_start = math.radians(25.0)
        arc_end = math.radians(155.0)
        arc_span = arc_end - arc_start

        def f2a(frac):
            return arc_end - frac * arc_span

        def arc_pt(angle, r):
            return QPointF(cx + r * math.cos(angle), cy - r * math.sin(angle))

        # Bogen
        steps = 40
        for i in range(steps):
            f1 = i / steps
            a1 = f2a(f1)
            a2 = f2a((i + 1) / steps)
            color = over_c if f1 >= 0.6 else normal_c
            p.setPen(QPen(color, 2.5))
            p.drawLine(arc_pt(a1, radius), arc_pt(a2, radius))

        # Ticks
        font_size = max(7, h // 10)
        p.setFont(QFont("Consolas", font_size, QFont.Bold))
        for s_num, label in [(1, "1"), (3, "3"), (5, "5"), (7, "7"), (9, "9")]:
            frac = s_num / 13.0
            angle = f2a(frac)
            ax = cx + radius * math.cos(angle)
            ay = cy - radius * math.sin(angle)
            dx = ax - cx
            dy = ay - cy
            ln = math.sqrt(dx * dx + dy * dy)
            if ln > 0:
                ux, uy = dx / ln, dy / ln
            else:
                ux, uy = 0, -1
            p.setPen(QPen(normal_c, 1.5))
            p.drawLine(QPointF(ax + ux, ay + uy), QPointF(ax + 8 * ux, ay + 8 * uy))
            p.setPen(normal_c)
            p.drawText(int(ax + 14 * ux) - 4, int(ay + 14 * uy) + 4, label)

        # Peak-Nadel (dünn, orange, halbtransparent)
        if self._peak > 10:
            peak_angle = f2a(self._peak / 1000.0)
            peak_dx = math.cos(peak_angle)
            peak_dy = -math.sin(peak_angle)
            peak_tip = QPointF(cx + radius * 0.8 * peak_dx, cy + radius * 0.8 * peak_dy)
            p.setPen(QPen(peak_c, 1.5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx, cy), peak_tip)

        # Signal-Nadel (dick, weiß)
        angle = f2a(self._value / 1000.0)
        ndx = math.cos(angle)
        ndy = -math.sin(angle)
        tip = QPointF(cx + radius * 0.85 * ndx, cy + radius * 0.85 * ndy)
        mid = QPointF(cx + radius * 0.6 * ndx, cy + radius * 0.6 * ndy)

        p.setPen(QPen(shaft_c, 2.5))
        p.drawLine(QPointF(cx, cy), mid)
        p.setPen(QPen(needle_c, 2))
        p.drawLine(mid, tip)

        # Pivot
        p.setBrush(pivot_c)
        p.setPen(QPen(shaft_c, 1))
        p.drawEllipse(QPointF(cx, cy), 4, 4)

        p.end()


# ═══════════════════════════════════════════════════════════════════
# 9. RINGS — Konzentrische Halbringe pro Signalband
# ═══════════════════════════════════════════════════════════════════

class SMeterRings(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._s_text = "---"
        self.setMinimumHeight(50)

    def setValue(self, val):
        self._value = max(0, min(1000, val))
        self.update()

    def setLabel(self, text):
        clean = text.replace("S-METER:", "").strip()
        if "|" in clean:
            self._s_text = clean.split("|")[0].strip()
        elif clean and clean != "---":
            self._s_text = clean
        self.update()

    def refresh_theme(self):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        # Transparenter Hintergrund — folgt dem GUI-Theme

        green_c = _color('smeter_led_green')
        yellow_c = _color('smeter_led_yellow')
        red_c = _color('smeter_led_red')
        off_c = _color('smeter_led_off')
        text_c = _color('text')
        digit_c = _color('smeter_digit_color')

        frac = self._value / 1000.0
        text_h = max(14, h // 5)
        ring_area_h = h - text_h - 4
        cx = w * 0.5
        cy = ring_area_h * 0.95

        # 4 Ringe: S1-S4, S5-S7, S8-S9, S9+
        rings = [
            (ring_area_h * 0.75, 8, 0.0, 4 / 13, green_c),
            (ring_area_h * 0.55, 7, 4 / 13, 7 / 13, green_c),
            (ring_area_h * 0.38, 6, 7 / 13, 9 / 13, yellow_c),
            (ring_area_h * 0.22, 5, 9 / 13, 1.0, red_c),
        ]

        arc_start = math.radians(10.0)
        arc_end = math.radians(170.0)
        arc_span = arc_end - arc_start

        for radius, thickness, f_start, f_end, color in rings:
            steps = 30
            ring_frac = max(0.0, min(1.0, (frac - f_start) / (f_end - f_start))) if frac > f_start else 0.0

            for i in range(steps):
                seg_frac = i / steps
                a1 = arc_end - seg_frac * arc_span
                a2 = arc_end - (seg_frac + 1.0 / steps) * arc_span
                p1 = QPointF(cx + radius * math.cos(a1), cy - radius * math.sin(a1))
                p2 = QPointF(cx + radius * math.cos(a2), cy - radius * math.sin(a2))

                if seg_frac <= ring_frac:
                    p.setPen(QPen(color, thickness, Qt.SolidLine, Qt.RoundCap))
                else:
                    p.setPen(QPen(off_c, thickness * 0.5, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(p1, p2)

        # S-Wert Text zentriert unten
        s_size = max(10, int(text_h * 0.85))
        p.setFont(QFont("Consolas", s_size, QFont.Bold))
        p.setPen(text_c)
        fm = QFontMetrics(p.font())
        tw = fm.horizontalAdvance(self._s_text)
        p.drawText(int(w / 2 - tw / 2), int(h - 4), self._s_text)

        p.end()


# ═══════════════════════════════════════════════════════════════════
# FACTORY
# ═══════════════════════════════════════════════════════════════════

_STYLE_MAP = {
    "segment": SMeterSegment,
    "gauge":   SMeterGauge,
    "led":     SMeterLED,
    "digit":   SMeterDigit,
    "vu":      SMeterVU,
    "nixie":   SMeterNixie,
    "classic": SMeterClassic,
    "dual":    SMeterDual,
    "rings":   SMeterRings,
}


def create_smeter(style=None, parent=None):
    """Factory: Erstellt S-Meter Widget nach Style-Key.
    Fallback auf 'segment' wenn Style unbekannt."""
    if style is None:
        style = T.get("smeter_style", "segment")
    cls = _STYLE_MAP.get(style, SMeterSegment)
    return cls(parent)
