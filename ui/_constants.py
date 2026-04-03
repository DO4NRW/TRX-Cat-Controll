import os

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_ICONS = os.path.join(_PROJECT_DIR, "assets", "icons")
_RIG_DIR = os.path.join(_PROJECT_DIR, "rig")
_THEME_PATH = os.path.join(_PROJECT_DIR, "configs", "theme.json")

# Editierbare Farben mit deutschem Label
_THEME_FIELDS = [
    ("accent",              "Akzentfarbe"),
    ("accent_dark",         "Akzent dunkel"),
    ("error",               "Fehler"),
    ("bg_dark",             "Hintergrund dunkel"),
    ("bg_mid",              "Hintergrund mittel"),
    ("bg_light",            "Hintergrund hell"),
    ("bg_button",           "Button Hintergrund"),
    ("bg_button_hover",     "Button Hover"),
    ("border",              "Rahmen"),
    ("border_hover",        "Rahmen Hover"),
    ("border_active",       "Rahmen aktiv"),
    ("text",                "Text"),
    ("text_secondary",      "Text sekundär"),
    ("text_muted",          "Text gedimmt"),
    ("slider_handle",       "Slider Punkt"),
    ("slider_fill",         "Slider Spur"),
    ("smeter_bar",          "S-Meter Balken"),
    ("smeter_label_active", "S-Meter Label aktiv"),
    ("tx_bar",              "TX-Meter Balken"),
    ("ptt_tx_bg",           "PTT TX Hintergrund"),
    ("ptt_tx_border",       "PTT TX Rahmen"),
    ("vu_green",            "VU Grün"),
    ("vu_yellow",           "VU Gelb"),
    ("vu_red",              "VU Rot"),
    ("wf_color_1",          "Wasserfall 1"),
    ("wf_color_2",          "Wasserfall 2"),
    ("wf_color_3",          "Wasserfall 3"),
    ("wf_color_4",          "Wasserfall 4"),
    ("wf_color_5",          "Wasserfall 5"),
    ("wf_color_6",          "Wasserfall 6"),
    ("wf_color_7",          "Wasserfall 7"),
    ("wf_color_8",          "Wasserfall 8"),
    ("wf_color_9",          "Wasserfall 9"),
    ("smeter_needle",       "S-Meter Nadel"),
    ("smeter_needle_shaft", "S-Meter Nadelschaft"),
    ("smeter_needle_pivot", "S-Meter Drehpunkt"),
    ("smeter_peak",         "S-Meter Peak"),
    ("smeter_arc_normal",   "S-Meter Bogen normal"),
    ("smeter_arc_over",     "S-Meter Bogen S9+"),
    ("smeter_led_green",    "S-Meter LED Grün"),
    ("smeter_led_yellow",   "S-Meter LED Gelb"),
    ("smeter_led_red",      "S-Meter LED Rot"),
    ("smeter_led_off",      "S-Meter LED Aus"),
    ("smeter_digit_color",  "S-Meter Ziffernfarbe"),
]

_SMETER_STYLES = [
    ("segment", "Segmentleiste"),
    ("gauge",   "Analog-Gauge"),
    ("led",     "LED-Punkte"),
    ("digit",   "Kompakt-Zahl"),
    ("vu",      "VU-Meter"),
    ("nixie",   "Nixie-Röhre"),
    ("classic", "Classic Needle"),
    ("dual",    "Dual-Nadel"),
    ("rings",   "Quad-Ringe"),
]
