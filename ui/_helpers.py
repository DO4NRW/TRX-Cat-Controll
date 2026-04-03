import os
import subprocess
import re

from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout, QVBoxLayout, QComboBox
from PySide6.QtCore import QSize, Qt

from core.theme import T, themed_icon, with_alpha
from ui._constants import _ICONS, _RIG_DIR


def _scan_rigs():
    """Scanne rig/ Ordner → flat list 'Hersteller Modell' (Kompatibilität)."""
    rig_map = _scan_rigs_map()
    rigs = []
    for maker, models in rig_map.items():
        for model in models:
            rigs.append(f"{maker} {model}")
    return rigs or ["(kein Rig gefunden)"]


def _scan_rigs_map():
    """Scanne rig/ Ordner → Dict: {'Yaesu': ['FT-991A'], 'Icom': ['IC-7300']}."""
    rig_map = {}
    if not os.path.isdir(_RIG_DIR):
        return rig_map
    for maker in sorted(os.listdir(_RIG_DIR)):
        maker_path = os.path.join(_RIG_DIR, maker)
        if not os.path.isdir(maker_path) or maker.startswith(("_", ".")):
            continue
        models = []
        for model in sorted(os.listdir(maker_path)):
            model_path = os.path.join(maker_path, model)
            if not os.path.isdir(model_path) or model.startswith(("_", ".")):
                continue
            if os.path.exists(os.path.join(model_path, "config.json")):
                display = model.upper().replace("FT", "FT-").replace("IC", "IC-").replace("TS", "TS-")
                models.append(display)
        if models:
            rig_map[maker.capitalize()] = models
    return rig_map


def _list_serial_ports():
    """Return only relevant serial ports for the current OS."""
    try:
        from serial.tools import list_ports
        import platform
        all_ports = [p.device for p in list_ports.comports()]
        os_name = platform.system()
        if os_name == "Linux":
            return [p for p in all_ports if "ttyUSB" in p or "ttyACM" in p] or ["(keine gefunden)"]
        elif os_name == "Darwin":
            return [p for p in all_ports if "cu." in p] or ["(keine gefunden)"]
        else:  # Windows
            return all_ports or ["COM1"]
    except Exception:
        return ["(pyserial fehlt)"]


def _section_label(text, icon=None):
    """Section label with optional icon left of the text."""
    row = QWidget()
    row.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 4, 0, 0)
    layout.setSpacing(6)
    if icon:
        ico = QLabel()
        ico.setPixmap(themed_icon(os.path.join(_ICONS, icon)).pixmap(QSize(14, 14)))
        ico.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(ico)
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {T['text_secondary']}; font-size: 12px; font-weight: bold; border: none;")
    layout.addWidget(lbl)
    layout.addStretch()
    return row


def _combo(values, current=""):
    cb = QComboBox()
    cb.addItems(values)
    if current and current in values:
        cb.setCurrentText(current)
    cb.setStyleSheet(f"""
        QComboBox {{
            background-color: {T['bg_mid']};
            color: {T['text_secondary']};
            border: 1px solid {T['border']};
            border-radius: 5px;
            padding: 4px 10px;
            font-size: 13px;
            min-height: 28px;
        }}
        QComboBox::drop-down {{ border: none; width: 24px; }}
        QComboBox QAbstractItemView {{
            background-color: {T['bg_mid']};
            color: {T['text_secondary']};
            selection-background-color: {T['bg_light']};
            border: 1px solid {T['border']};
        }}
    """)
    return cb


_card_counter = 0
def _card(title):
    """Returns (card_widget, inner_layout) — a bordered card with a bold title."""
    global _card_counter
    _card_counter += 1
    card = QWidget()
    obj_name = f"card_{_card_counter}"
    card.setObjectName(obj_name)
    card.setStyleSheet(f"""
        QWidget#{obj_name} {{
            background-color: {with_alpha(T['bg_mid'], 220)};
            border: 1px solid {T['bg_light']};
            border-radius: 8px;
        }}
    """)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 14)
    layout.setSpacing(10)
    hdr = QLabel(title)
    hdr.setStyleSheet(f"color: {T['text']}; font-size: 13px; font-weight: bold; border: none;")
    hdr.setAlignment(Qt.AlignCenter)
    layout.addWidget(hdr)
    return card, layout


# ── Audio Helper ────────────────────────────────────────────────────

def _pw_node_info(node_id):
    """Hole nick, bus-type und node.name für eine PipeWire Node-ID."""
    nick = None
    node_name = None
    is_usb = False
    try:
        out = subprocess.run(
            ["pw-cli", "info", str(node_id)],
            capture_output=True, text=True, timeout=2
        ).stdout
        for line in out.splitlines():
            if "node.nick" in line or "device.nick" in line:
                m = re.search(r'"(.+?)"', line)
                if m and nick is None:
                    nick = m.group(1)
            if "node.name" in line and "node.nick" not in line:
                m = re.search(r'"(.+?)"', line)
                if m and node_name is None:
                    node_name = m.group(1)
            if "device.bus" in line and '"usb"' in line:
                is_usb = True
            if "api.alsa.card.name" in line and "usb" in line.lower():
                is_usb = True
    except Exception:
        pass
    return nick, is_usb, node_name


def _list_audio_devices_linux(kind="all", bus="all"):
    """Linux: PipeWire/PulseAudio Geräte via wpctl auslesen.
    bus='pc' → nur interne Geräte, bus='usb' → nur USB-Geräte, bus='all' → alle."""
    result = []

    try:
        out = subprocess.run(["wpctl", "status"], capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return []

    if not out or "Audio" not in out:
        return []

    in_audio = False
    in_sinks = False
    in_sources = False

    for line in out.splitlines():
        if line.strip() == "Audio":
            in_audio = True; continue
        if line.strip() == "Video":
            in_audio = False; continue
        if not in_audio:
            continue

        clean = line.replace("│", "").strip()
        if "Sinks:" in clean and "endpoint" not in clean.lower():
            in_sinks = True; in_sources = False; continue
        elif "Sources:" in clean and "endpoint" not in clean.lower():
            in_sources = True; in_sinks = False; continue
        elif "endpoints:" in clean.lower() or "Streams:" in clean or "Devices:" in clean:
            in_sinks = False; in_sources = False; continue

        if not (in_sinks or in_sources):
            continue

        m = re.search(r"\*?\s*(\d+)\.\s+(.+?)(?:\s+\[vol:.*)?$", clean)
        if not m:
            continue
        dev_id = int(m.group(1))
        dev_name = m.group(2).strip()

        # Bus-Filter: pc = nur interne, usb = nur USB
        _, is_usb, node_name = _pw_node_info(dev_id)
        if bus != "all":
            if bus == "pc" and is_usb:
                continue
            if bus == "usb" and not is_usb:
                continue

        if in_sinks and kind in ("output", "all"):
            result.append((node_name or str(dev_id), dev_name, "out"))
        elif in_sources and kind in ("input", "all"):
            result.append((node_name or str(dev_id), dev_name, "in"))

    # Bei "all": gleiche Namen mit Richtung kennzeichnen
    name_count = {}
    for _, name, _ in result:
        name_count[name] = name_count.get(name, 0) + 1

    formatted = []
    for pw_name, name, direction in result:
        # Anzeige kürzen: "Analoges Stereo", "Digital Stereo" etc. entfernen
        display = re.sub(r"\s*(Analoges|Digital)\s*Stereo\s*", "", name).strip()
        formatted.append((display, f"[pw:{pw_name}] {name}"))

    return formatted


def _list_audio_devices(kind="all", bus="all"):
    """Return device strings, platform-aware.
    Linux: PipeWire/PulseAudio, Windows: WASAPI, macOS: CoreAudio.
    bus='pc' → nur interne, bus='usb' → nur USB, bus='all' → alle."""
    import platform
    os_name = platform.system()

    # ── Linux: PipeWire/PulseAudio bevorzugen ─────────────────────
    if os_name == "Linux":
        pw_devs = _list_audio_devices_linux(kind, bus)
        if pw_devs:
            return pw_devs

    # ── Fallback / Windows / macOS: sounddevice ───────────────────
    try:
        import sounddevice as sd
        devs_raw = sd.query_devices()
        hostapis = sd.query_hostapis()

        preferred = None
        for i, h in enumerate(hostapis):
            name = h["name"].lower()
            if os_name == "Windows" and "wasapi" in name:
                preferred = i; break
            elif os_name == "Darwin" and "core" in name:
                preferred = i; break
            elif os_name == "Linux" and "pulse" in name:
                preferred = i; break
        if preferred is None and os_name == "Linux":
            for i, h in enumerate(hostapis):
                if "alsa" in h["name"].lower():
                    preferred = i; break

        _BLACKLIST = ("midi", "through", "timer", "sequencer")

        # Windows Whitelist
        _MIC_HINTS = ("mikrofon", "microphone", "mic", "input", "capture",
                       "aufnahme", "recording", "line in", "scarlett", "codec",
                       "usb audio", "audio codec")
        _SPK_HINTS = ("lautsprecher", "speaker", "headphone", "kopfhörer",
                       "output", "playback", "wiedergabe", "realtek", "scarlett",
                       "codec", "usb audio", "audio codec", "headset",
                       "hdmi", "displayport", "spdif", "optical", "digital",
                       "monitor", "tv", "receiver")

        result = []
        for i, d in enumerate(devs_raw):
            if preferred is not None and d["hostapi"] != preferred:
                continue
            if kind == "input"  and d["max_input_channels"]  < 1: continue
            if kind == "output" and d["max_output_channels"] < 1: continue
            dname = d["name"].lower()
            if any(bl in dname for bl in _BLACKLIST):
                continue
            result.append((i, d["name"], dname))

        # Windows: zusätzlich Whitelist-Filter
        if os_name == "Windows":
            if kind == "input":
                filtered = [(i, n) for i, n, nl in result
                            if any(h in nl for h in _MIC_HINTS)]
            elif kind == "output":
                filtered = [(i, n) for i, n, nl in result
                            if any(h in nl for h in _SPK_HINTS)]
            else:
                filtered = [(i, n) for i, n, _ in result]
            if not filtered:
                filtered = [(i, n) for i, n, _ in result]
        else:
            filtered = [(i, n) for i, n, _ in result]

        formatted = [f"[{i}] {n}" for i, n in filtered]
        return formatted or ["(keine gefunden)"]
    except Exception:
        return ["(sounddevice fehlt)"]


def _pw_find_id_by_name(node_name):
    """Finde aktuelle PipeWire Node-ID anhand von node.name (stabil über Reboots)."""
    try:
        out = subprocess.run(
            ["pw-cli", "list-objects", "Node"],
            capture_output=True, text=True, timeout=3
        ).stdout
        current_id = None
        for line in out.splitlines():
            id_m = re.search(r"id (\d+),", line)
            if id_m:
                current_id = id_m.group(1)
            if "node.name" in line and "node.nick" not in line:
                m = re.search(r'"(.+?)"', line)
                if m and m.group(1) == node_name and current_id:
                    return current_id
    except Exception:
        pass
    # Fallback: wenn node_name schon numerisch ist (Legacy)
    if node_name and node_name.isdigit():
        return node_name
    return None


def _device_max_channels(device_str: str, kind: str) -> int:
    """Return max channels for a device. Supports [pw:node.name] and [i] formats."""
    try:
        prefix = device_str.split("]")[0].replace("[", "").strip()
        if prefix.startswith("pw:"):
            pw_name = prefix.replace("pw:", "")
            node_id = _pw_find_id_by_name(pw_name)
            if node_id:
                try:
                    out = subprocess.run(
                        ["pw-cli", "info", node_id],
                        capture_output=True, text=True, timeout=2
                    ).stdout
                    for line in out.splitlines():
                        if "audio.channels" in line or "channels" in line.lower():
                            m = re.search(r"(\d+)", line.split("=")[-1] if "=" in line else line.split(":")[-1])
                            if m:
                                return max(1, int(m.group(1)))
                except Exception:
                    pass
            return 2
        else:
            import sounddevice as sd
            idx = int(prefix)
            d = sd.query_devices(idx)
            return int(d["max_input_channels"] if kind == "input" else d["max_output_channels"])
    except Exception:
        return 2
