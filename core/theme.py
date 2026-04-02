"""
Zentrales Theme-Modul — Mittelsmann für alle UI-Komponenten.
Lädt Farben aus configs/theme.json (RGBA-Format), stellt sie global bereit,
und kann Themes live anwenden.
"""

import os
import json
import copy

_THEME_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "configs", "theme.json")

# ── Globales Theme-Dict — wird von allen UIs gelesen ────────────────
T = {}

# ── Callbacks für Live-Update (Rig-UIs registrieren sich hier) ──────
_refresh_callbacks = []


def register_refresh(callback):
    """Rig-UI oder andere Widgets registrieren hier ihren refresh_theme() Callback."""
    if callback not in _refresh_callbacks:
        _refresh_callbacks.append(callback)


def unregister_refresh(callback):
    """Beim Widget-Destroy abmelden."""
    if callback in _refresh_callbacks:
        _refresh_callbacks.remove(callback)


def load_theme(path=None):
    """Theme aus JSON laden und in globales T dict schreiben.
    Gibt T zurück. Ignoriert _comment Keys.
    WICHTIG: T.clear()+update() statt T={} — damit alle Referenzen gültig bleiben."""
    p = path or _THEME_PATH
    try:
        with open(p) as f:
            raw = json.load(f)
        new_data = {k: v for k, v in raw.items() if not k.startswith("_")}
        T.clear()
        T.update(new_data)
    except Exception as e:
        print(f"Theme laden fehlgeschlagen: {e}")
        T.clear()
        T.update(copy.deepcopy(PRESETS["dark"]))
    return T


def detect_preset():
    """Erkennt welches Preset dem aktuellen Theme entspricht.
    Gibt den Preset-Key zurück oder None wenn keines passt."""
    for name, preset in PRESETS.items():
        if all(T.get(k) == v for k, v in preset.items()):
            return name
    return None


_STATUS_CONF = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "configs", "status_conf.json")


def save_theme(data=None, path=None):
    """Theme in JSON speichern. Behält _comment Keys bei.
    Speichert außerdem den Preset-Namen in status_conf.json."""
    p = path or _THEME_PATH
    try:
        with open(p) as f:
            full = json.load(f)
    except Exception:
        full = {}

    src = data or T
    for k, v in src.items():
        if not k.startswith("_"):
            full[k] = v

    with open(p, "w") as f:
        json.dump(full, f, indent=4)

    # Preset-Name in status_conf.json merken
    _save_last_theme()


def _save_last_theme():
    """Aktuellen Preset-Namen (oder 'custom') in status_conf.json speichern."""
    preset = detect_preset() or "custom"
    try:
        with open(_STATUS_CONF) as f:
            cfg = json.load(f)
        cfg["last_theme"] = preset
        with open(_STATUS_CONF, "w") as f:
            json.dump(cfg, f, indent=4)
    except Exception:
        pass


def get_last_theme():
    """Letzten Theme-Preset aus status_conf.json lesen."""
    try:
        with open(_STATUS_CONF) as f:
            cfg = json.load(f)
        return cfg.get("last_theme", "dark")
    except Exception:
        return "dark"


def apply_theme(main_window=None):
    """Theme live anwenden: T neu laden, MainWindow + alle registrierten Widgets refreshen."""
    load_theme()

    # MainWindow Styles neu setzen
    if main_window and hasattr(main_window, "refresh_theme"):
        main_window.refresh_theme()

    # Alle registrierten Rig-UIs etc. refreshen
    for cb in _refresh_callbacks[:]:
        try:
            cb()
        except Exception as e:
            print(f"Theme refresh callback Fehler: {e}")


def _is_light_theme():
    """Prüft ob das aktuelle Theme hell ist (bg_dark Luminanz > 128)."""
    r, g, b, _ = rgba_parts(T.get("bg_dark", "rgba(26,26,26,255)"))
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return luminance > 128


def themed_icon(svg_path):
    """Icon passend zum Theme laden.
    Helles Theme → assets/icons/light/ (dunkle Icons)
    Dunkles Theme → assets/icons/ (helle Icons, Original)"""
    from PySide6.QtGui import QIcon
    if _is_light_theme():
        # Pfad umbiegen: assets/icons/foo.svg → assets/icons/light/foo.svg
        dir_path = os.path.dirname(svg_path)
        filename = os.path.basename(svg_path)
        light_path = os.path.join(dir_path, "light", filename)
        if os.path.exists(light_path):
            return QIcon(light_path)
    return QIcon(svg_path)


def hex_to_rgba(hex_color):
    """'#06c6a4' → 'rgba(6, 198, 164, 255)'"""
    h = hex_color.lstrip("#")
    if len(h) == 8:  # RRGGBBAA
        r, g, b, a = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16)
    elif len(h) == 6:  # RRGGBB
        r, g, b, a = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255
    else:
        return hex_color
    return f"rgba({r}, {g}, {b}, {a})"


def rgba_to_hex(rgba_str):
    """'rgba(6, 198, 164, 255)' → '#06c6a4' (oder '#06c6a4ff' wenn alpha != 255)"""
    try:
        inner = rgba_str.replace("rgba(", "").replace(")", "").strip()
        parts = [int(x.strip()) for x in inner.split(",")]
        r, g, b = parts[0], parts[1], parts[2]
        a = parts[3] if len(parts) > 3 else 255
        if a == 255:
            return f"#{r:02x}{g:02x}{b:02x}"
        return f"#{r:02x}{g:02x}{b:02x}{a:02x}"
    except Exception:
        return rgba_str


def rgba_parts(rgba_str):
    """'rgba(6, 198, 164, 255)' → (6, 198, 164, 255) Tuple"""
    try:
        inner = rgba_str.replace("rgba(", "").replace(")", "").strip()
        parts = [int(x.strip()) for x in inner.split(",")]
        if len(parts) == 3:
            return (parts[0], parts[1], parts[2], 255)
        return tuple(parts[:4])
    except Exception:
        return (0, 0, 0, 255)


def with_alpha(rgba_str, alpha):
    """Theme-Farbe mit neuem Alpha-Wert: with_alpha(T['accent'], 128) → 'rgba(6,198,164,128)'"""
    r, g, b, _ = rgba_parts(rgba_str)
    return f"rgba({r}, {g}, {b}, {alpha})"


# =====================================================================
# PRESET THEMES
# =====================================================================

PRESETS = {
    "dark": {
        "accent":              "rgba(6, 198, 164, 255)",
        "accent_dark":         "rgba(4, 138, 115, 255)",
        "success":             "rgba(6, 198, 164, 255)",
        "error":               "rgba(255, 68, 68, 255)",
        "bg_dark":             "rgba(26, 26, 26, 255)",
        "bg_mid":              "rgba(42, 42, 42, 255)",
        "bg_light":            "rgba(58, 58, 58, 255)",
        "bg_button":           "rgba(61, 61, 61, 255)",
        "bg_button_hover":     "rgba(74, 74, 74, 255)",
        "border":              "rgba(85, 85, 85, 255)",
        "border_hover":        "rgba(136, 136, 136, 255)",
        "border_active":       "rgba(6, 198, 164, 255)",
        "border_error":        "rgba(255, 68, 68, 255)",
        "text":                "rgba(255, 255, 255, 255)",
        "text_secondary":      "rgba(204, 204, 204, 255)",
        "text_muted":          "rgba(170, 170, 170, 255)",
        "text_disabled":       "rgba(85, 85, 85, 255)",
        "slider_groove":       "rgba(42, 42, 42, 255)",
        "slider_handle":       "rgba(6, 198, 164, 255)",
        "slider_fill":         "rgba(85, 85, 85, 255)",
        "smeter_bar":          "rgba(6, 198, 164, 255)",
        "smeter_label_active": "rgba(215, 236, 255, 255)",
        "smeter_label_inactive":"rgba(136, 136, 136, 255)",
        "tx_bar":              "rgba(6, 198, 164, 255)",
        "ptt_rx_bg":           "rgba(61, 61, 61, 255)",
        "ptt_rx_border":       "rgba(85, 85, 85, 255)",
        "ptt_tx_bg":           "rgba(211, 47, 47, 255)",
        "ptt_tx_border":       "rgba(255, 102, 89, 255)",
        "vu_green":            "rgba(0, 204, 0, 255)",
        "vu_yellow":           "rgba(204, 204, 0, 255)",
        "vu_red":              "rgba(255, 0, 0, 255)",
        "wf_bg":               "rgba(18, 22, 30, 255)",
        "wf_grid":             "rgba(30, 40, 55, 255)",
        "wf_freq_bar":         "rgba(20, 25, 35, 255)",
        "wf_freq_text":        "rgba(160, 170, 180, 255)",
        "wf_freq_tick":        "rgba(60, 70, 80, 255)",
        "wf_cursor":           "rgba(0, 220, 100, 255)",
        "wf_palette":          "sdr",
    },

    "light": {
        "accent":              "rgba(0, 150, 136, 255)",
        "accent_dark":         "rgba(0, 105, 92, 255)",
        "success":             "rgba(0, 150, 136, 255)",
        "error":               "rgba(211, 47, 47, 255)",
        "bg_dark":             "rgba(245, 245, 245, 255)",
        "bg_mid":              "rgba(255, 255, 255, 255)",
        "bg_light":            "rgba(238, 238, 238, 255)",
        "bg_button":           "rgba(224, 224, 224, 255)",
        "bg_button_hover":     "rgba(200, 200, 200, 255)",
        "border":              "rgba(189, 189, 189, 255)",
        "border_hover":        "rgba(120, 120, 120, 255)",
        "border_active":       "rgba(0, 150, 136, 255)",
        "border_error":        "rgba(211, 47, 47, 255)",
        "text":                "rgba(15, 15, 15, 255)",
        "text_secondary":      "rgba(40, 40, 40, 255)",
        "text_muted":          "rgba(70, 70, 70, 255)",
        "text_disabled":       "rgba(140, 140, 140, 255)",
        "slider_groove":       "rgba(224, 224, 224, 255)",
        "slider_handle":       "rgba(0, 150, 136, 255)",
        "slider_fill":         "rgba(158, 158, 158, 255)",
        "smeter_bar":          "rgba(0, 150, 136, 255)",
        "smeter_label_active": "rgba(0, 77, 64, 255)",
        "smeter_label_inactive":"rgba(100, 100, 100, 255)",
        "tx_bar":              "rgba(0, 150, 136, 255)",
        "ptt_rx_bg":           "rgba(224, 224, 224, 255)",
        "ptt_rx_border":       "rgba(189, 189, 189, 255)",
        "ptt_tx_bg":           "rgba(211, 47, 47, 255)",
        "ptt_tx_border":       "rgba(244, 67, 54, 255)",
        "vu_green":            "rgba(76, 175, 80, 255)",
        "vu_yellow":           "rgba(255, 193, 7, 255)",
        "vu_red":              "rgba(244, 67, 54, 255)",
        "wf_bg":               "rgba(24, 28, 36, 255)",
        "wf_grid":             "rgba(38, 44, 52, 255)",
        "wf_freq_bar":         "rgba(28, 32, 40, 255)",
        "wf_freq_text":        "rgba(140, 150, 165, 255)",
        "wf_freq_tick":        "rgba(55, 62, 72, 255)",
        "wf_cursor":           "rgba(0, 150, 80, 255)",
        "wf_palette":          "sdr",
    },

    "discord": {
        "accent":              "rgba(88, 101, 242, 255)",
        "accent_dark":         "rgba(71, 82, 196, 255)",
        "success":             "rgba(87, 242, 135, 255)",
        "error":               "rgba(237, 66, 69, 255)",
        "bg_dark":             "rgba(30, 31, 34, 255)",
        "bg_mid":              "rgba(43, 45, 49, 255)",
        "bg_light":            "rgba(54, 57, 63, 255)",
        "bg_button":           "rgba(64, 68, 75, 255)",
        "bg_button_hover":     "rgba(74, 78, 86, 255)",
        "border":              "rgba(62, 65, 72, 255)",
        "border_hover":        "rgba(88, 101, 242, 255)",
        "border_active":       "rgba(88, 101, 242, 255)",
        "border_error":        "rgba(237, 66, 69, 255)",
        "text":                "rgba(255, 255, 255, 255)",
        "text_secondary":      "rgba(200, 202, 206, 255)",
        "text_muted":          "rgba(175, 180, 190, 255)",
        "text_disabled":       "rgba(79, 84, 92, 255)",
        "slider_groove":       "rgba(43, 45, 49, 255)",
        "slider_handle":       "rgba(88, 101, 242, 255)",
        "slider_fill":         "rgba(79, 84, 92, 255)",
        "smeter_bar":          "rgba(88, 101, 242, 255)",
        "smeter_label_active": "rgba(222, 224, 252, 255)",
        "smeter_label_inactive":"rgba(148, 155, 164, 255)",
        "tx_bar":              "rgba(88, 101, 242, 255)",
        "ptt_rx_bg":           "rgba(64, 68, 75, 255)",
        "ptt_rx_border":       "rgba(62, 65, 72, 255)",
        "ptt_tx_bg":           "rgba(237, 66, 69, 255)",
        "ptt_tx_border":       "rgba(255, 99, 99, 255)",
        "vu_green":            "rgba(87, 242, 135, 255)",
        "vu_yellow":           "rgba(254, 231, 92, 255)",
        "vu_red":              "rgba(237, 66, 69, 255)",
        "wf_bg":               "rgba(22, 23, 27, 255)",
        "wf_grid":             "rgba(35, 37, 42, 255)",
        "wf_freq_bar":         "rgba(25, 27, 32, 255)",
        "wf_freq_text":        "rgba(150, 155, 165, 255)",
        "wf_freq_tick":        "rgba(55, 58, 65, 255)",
        "wf_cursor":           "rgba(87, 242, 135, 255)",
        "wf_palette":          "sdr",
    },

    "nord": {
        "accent":              "rgba(136, 192, 208, 255)",
        "accent_dark":         "rgba(94, 129, 172, 255)",
        "success":             "rgba(163, 190, 140, 255)",
        "error":               "rgba(191, 97, 106, 255)",
        "bg_dark":             "rgba(46, 52, 64, 255)",
        "bg_mid":              "rgba(59, 66, 82, 255)",
        "bg_light":            "rgba(67, 76, 94, 255)",
        "bg_button":           "rgba(76, 86, 106, 255)",
        "bg_button_hover":     "rgba(86, 95, 114, 255)",
        "border":              "rgba(76, 86, 106, 255)",
        "border_hover":        "rgba(136, 192, 208, 255)",
        "border_active":       "rgba(136, 192, 208, 255)",
        "border_error":        "rgba(191, 97, 106, 255)",
        "text":                "rgba(236, 239, 244, 255)",
        "text_secondary":      "rgba(216, 222, 233, 255)",
        "text_muted":          "rgba(160, 170, 190, 255)",
        "text_disabled":       "rgba(100, 110, 128, 255)",
        "slider_groove":       "rgba(59, 66, 82, 255)",
        "slider_handle":       "rgba(136, 192, 208, 255)",
        "slider_fill":         "rgba(100, 110, 128, 255)",
        "smeter_bar":          "rgba(136, 192, 208, 255)",
        "smeter_label_active": "rgba(236, 239, 244, 255)",
        "smeter_label_inactive":"rgba(120, 130, 150, 255)",
        "tx_bar":              "rgba(136, 192, 208, 255)",
        "ptt_rx_bg":           "rgba(76, 86, 106, 255)",
        "ptt_rx_border":       "rgba(100, 110, 128, 255)",
        "ptt_tx_bg":           "rgba(191, 97, 106, 255)",
        "ptt_tx_border":       "rgba(208, 135, 112, 255)",
        "vu_green":            "rgba(163, 190, 140, 255)",
        "vu_yellow":           "rgba(235, 203, 139, 255)",
        "vu_red":              "rgba(191, 97, 106, 255)",
        "wf_bg":               "rgba(36, 40, 50, 255)",
        "wf_grid":             "rgba(50, 56, 68, 255)",
        "wf_freq_bar":         "rgba(40, 45, 56, 255)",
        "wf_freq_text":        "rgba(160, 170, 190, 255)",
        "wf_freq_tick":        "rgba(65, 72, 88, 255)",
        "wf_cursor":           "rgba(163, 190, 140, 255)",
        "wf_palette":          "sdr",
    },

    "dracula": {
        "accent":              "rgba(189, 147, 249, 255)",
        "accent_dark":         "rgba(139, 97, 199, 255)",
        "success":             "rgba(80, 250, 123, 255)",
        "error":               "rgba(255, 85, 85, 255)",
        "bg_dark":             "rgba(40, 42, 54, 255)",
        "bg_mid":              "rgba(68, 71, 90, 255)",
        "bg_light":            "rgba(55, 58, 75, 255)",
        "bg_button":           "rgba(68, 71, 90, 255)",
        "bg_button_hover":     "rgba(80, 83, 102, 255)",
        "border":              "rgba(98, 114, 164, 255)",
        "border_hover":        "rgba(189, 147, 249, 255)",
        "border_active":       "rgba(189, 147, 249, 255)",
        "border_error":        "rgba(255, 85, 85, 255)",
        "text":                "rgba(248, 248, 242, 255)",
        "text_secondary":      "rgba(220, 220, 210, 255)",
        "text_muted":          "rgba(160, 170, 200, 255)",
        "text_disabled":       "rgba(98, 114, 164, 255)",
        "slider_groove":       "rgba(68, 71, 90, 255)",
        "slider_handle":       "rgba(189, 147, 249, 255)",
        "slider_fill":         "rgba(98, 114, 164, 255)",
        "smeter_bar":          "rgba(80, 250, 123, 255)",
        "smeter_label_active": "rgba(248, 248, 242, 255)",
        "smeter_label_inactive":"rgba(98, 114, 164, 255)",
        "tx_bar":              "rgba(189, 147, 249, 255)",
        "ptt_rx_bg":           "rgba(68, 71, 90, 255)",
        "ptt_rx_border":       "rgba(98, 114, 164, 255)",
        "ptt_tx_bg":           "rgba(255, 85, 85, 255)",
        "ptt_tx_border":       "rgba(255, 121, 198, 255)",
        "vu_green":            "rgba(80, 250, 123, 255)",
        "vu_yellow":           "rgba(241, 250, 140, 255)",
        "vu_red":              "rgba(255, 85, 85, 255)",
        "wf_bg":               "rgba(30, 32, 42, 255)",
        "wf_grid":             "rgba(45, 48, 60, 255)",
        "wf_freq_bar":         "rgba(35, 37, 48, 255)",
        "wf_freq_text":        "rgba(160, 170, 200, 255)",
        "wf_freq_tick":        "rgba(60, 65, 80, 255)",
        "wf_cursor":           "rgba(80, 250, 123, 255)",
        "wf_palette":          "sdr",
    },

    "monokai": {
        "accent":              "rgba(166, 226, 46, 255)",
        "accent_dark":         "rgba(126, 186, 6, 255)",
        "success":             "rgba(166, 226, 46, 255)",
        "error":               "rgba(249, 38, 114, 255)",
        "bg_dark":             "rgba(39, 40, 34, 255)",
        "bg_mid":              "rgba(52, 53, 46, 255)",
        "bg_light":            "rgba(65, 66, 58, 255)",
        "bg_button":           "rgba(65, 66, 58, 255)",
        "bg_button_hover":     "rgba(78, 79, 70, 255)",
        "border":              "rgba(78, 79, 70, 255)",
        "border_hover":        "rgba(166, 226, 46, 255)",
        "border_active":       "rgba(166, 226, 46, 255)",
        "border_error":        "rgba(249, 38, 114, 255)",
        "text":                "rgba(248, 248, 242, 255)",
        "text_secondary":      "rgba(220, 220, 200, 255)",
        "text_muted":          "rgba(175, 172, 155, 255)",
        "text_disabled":       "rgba(78, 79, 70, 255)",
        "slider_groove":       "rgba(52, 53, 46, 255)",
        "slider_handle":       "rgba(166, 226, 46, 255)",
        "slider_fill":         "rgba(117, 113, 94, 255)",
        "smeter_bar":          "rgba(102, 217, 239, 255)",
        "smeter_label_active": "rgba(248, 248, 242, 255)",
        "smeter_label_inactive":"rgba(117, 113, 94, 255)",
        "tx_bar":              "rgba(166, 226, 46, 255)",
        "ptt_rx_bg":           "rgba(65, 66, 58, 255)",
        "ptt_rx_border":       "rgba(78, 79, 70, 255)",
        "ptt_tx_bg":           "rgba(249, 38, 114, 255)",
        "ptt_tx_border":       "rgba(253, 151, 31, 255)",
        "vu_green":            "rgba(166, 226, 46, 255)",
        "vu_yellow":           "rgba(230, 219, 116, 255)",
        "vu_red":              "rgba(249, 38, 114, 255)",
        "wf_bg":               "rgba(30, 31, 26, 255)",
        "wf_grid":             "rgba(45, 46, 40, 255)",
        "wf_freq_bar":         "rgba(35, 36, 30, 255)",
        "wf_freq_text":        "rgba(175, 172, 155, 255)",
        "wf_freq_tick":        "rgba(65, 66, 58, 255)",
        "wf_cursor":           "rgba(166, 226, 46, 255)",
        "wf_palette":          "sdr",
    },

    "colorblind": {
        "accent":              "rgba(0, 114, 178, 255)",
        "accent_dark":         "rgba(0, 80, 130, 255)",
        "success":             "rgba(0, 158, 115, 255)",
        "error":               "rgba(213, 94, 0, 255)",
        "bg_dark":             "rgba(30, 30, 30, 255)",
        "bg_mid":              "rgba(45, 45, 45, 255)",
        "bg_light":            "rgba(60, 60, 60, 255)",
        "bg_button":           "rgba(65, 65, 65, 255)",
        "bg_button_hover":     "rgba(78, 78, 78, 255)",
        "border":              "rgba(90, 90, 90, 255)",
        "border_hover":        "rgba(140, 140, 140, 255)",
        "border_active":       "rgba(0, 114, 178, 255)",
        "border_error":        "rgba(213, 94, 0, 255)",
        "text":                "rgba(255, 255, 255, 255)",
        "text_secondary":      "rgba(200, 200, 200, 255)",
        "text_muted":          "rgba(160, 160, 160, 255)",
        "text_disabled":       "rgba(90, 90, 90, 255)",
        "slider_groove":       "rgba(45, 45, 45, 255)",
        "slider_handle":       "rgba(0, 114, 178, 255)",
        "slider_fill":         "rgba(90, 90, 90, 255)",
        "smeter_bar":          "rgba(0, 114, 178, 255)",
        "smeter_label_active": "rgba(240, 228, 66, 255)",
        "smeter_label_inactive":"rgba(140, 140, 140, 255)",
        "tx_bar":              "rgba(0, 158, 115, 255)",
        "ptt_rx_bg":           "rgba(65, 65, 65, 255)",
        "ptt_rx_border":       "rgba(90, 90, 90, 255)",
        "ptt_tx_bg":           "rgba(213, 94, 0, 255)",
        "ptt_tx_border":       "rgba(230, 159, 0, 255)",
        "vu_green":            "rgba(0, 158, 115, 255)",
        "vu_yellow":           "rgba(240, 228, 66, 255)",
        "vu_red":              "rgba(213, 94, 0, 255)",
        "wf_bg":               "rgba(20, 20, 28, 255)",
        "wf_grid":             "rgba(35, 35, 45, 255)",
        "wf_freq_bar":         "rgba(25, 25, 33, 255)",
        "wf_freq_text":        "rgba(160, 160, 175, 255)",
        "wf_freq_tick":        "rgba(55, 55, 65, 255)",
        "wf_cursor":           "rgba(240, 228, 66, 255)",
        "wf_palette":          "viridis",
    },
}

# Preset Display-Namen (deutsch)
PRESET_NAMES = {
    "dark":       "Dunkel (Standard)",
    "light":      "Hell",
    "discord":    "Blurple Night",
    "nord":       "Nord",
    "dracula":    "Dracula",
    "monokai":    "Monokai",
    "colorblind": "Farbenblind",
}

# =====================================================================
# CUSTOM USER THEMES
# =====================================================================

_CUSTOM_THEMES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "configs", "user_themes.json")


def load_user_themes():
    """Alle User-Themes aus configs/user_themes.json laden.
    Gibt dict zurück: {"Mein Theme": {farb-dict}, ...}"""
    try:
        with open(_CUSTOM_THEMES_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_user_theme(name, data):
    """Ein User-Theme speichern (neu oder überschreiben)."""
    themes = load_user_themes()
    themes[name] = copy.deepcopy(data)
    with open(_CUSTOM_THEMES_PATH, "w") as f:
        json.dump(themes, f, indent=4)


def delete_user_theme(name):
    """Ein User-Theme löschen."""
    themes = load_user_themes()
    if name in themes:
        del themes[name]
        with open(_CUSTOM_THEMES_PATH, "w") as f:
            json.dump(themes, f, indent=4)


def is_builtin_preset(name):
    """Prüft ob ein Name ein eingebautes Preset ist (read-only)."""
    return name in PRESET_NAMES.values()


# ── Beim Import direkt laden ────────────────────────────────────────
load_theme()
