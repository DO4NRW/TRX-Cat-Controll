"""
Session-Logger — trackt User-Aktionen für Crash-Reports.
Schreibt alle Events in logs/session.log.
Verwaltet clean_exit Flag in logs/session_state.json.
"""

import os
import json
import platform
import logging
from datetime import datetime

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOGS_DIR = os.path.join(_PROJECT_DIR, "logs")
_SESSION_LOG = os.path.join(_LOGS_DIR, "session.log")
_SESSION_STATE = os.path.join(_LOGS_DIR, "session_state.json")

os.makedirs(_LOGS_DIR, exist_ok=True)

# --- State Management ---

def _read_state():
    try:
        with open(_SESSION_STATE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_state(data):
    with open(_SESSION_STATE, "w") as f:
        json.dump(data, f, indent=2)


def had_crash():
    """Prüft ob die letzte Session nicht sauber beendet wurde."""
    state = _read_state()
    # Kein State = erster Start, kein Crash
    if not state:
        return False
    return not state.get("clean_exit", False)


def has_previous_log():
    """Prüft ob ein Session-Log von einer vorherigen Session existiert."""
    return os.path.exists(_SESSION_LOG) and os.path.getsize(_SESSION_LOG) > 0


def get_session_log():
    """Gibt den Inhalt des Session-Logs zurück."""
    try:
        with open(_SESSION_LOG, "r") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def get_system_info():
    """Sammelt System- und Hardware-Informationen für den Report."""
    import sys
    import subprocess
    info = []
    info.append(f"OS: {platform.system()} {platform.release()}")
    info.append(f"Platform: {platform.platform()}")
    info.append(f"Python: {sys.version}")
    try:
        import PySide6
        info.append(f"PySide6: {PySide6.__version__}")
    except Exception:
        pass
    try:
        from core.updater import CURRENT_VERSION
        info.append(f"RigLink: v{CURRENT_VERSION}")
    except Exception:
        pass

    # Hardware
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    info.append(f"CPU: {line.split(':')[1].strip()}")
                    break
        info.append(f"CPU Kerne: {platform.os.cpu_count()}")
    except Exception:
        info.append(f"CPU: {platform.processor() or 'unbekannt'}")

    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    kb = int(line.split()[1])
                    info.append(f"RAM: {kb // 1024} MB ({kb // 1024 // 1024} GB)")
                    break
    except Exception:
        pass

    try:
        result = subprocess.run(["lspci"], capture_output=True, text=True, timeout=3)
        for line in result.stdout.splitlines():
            if "VGA" in line or "3D" in line:
                gpu = line.split(": ", 1)[-1] if ": " in line else line
                info.append(f"GPU: {gpu}")
    except Exception:
        pass

    # Disks
    try:
        result = subprocess.run(["lsblk", "-d", "-o", "NAME,SIZE,MODEL,TYPE"],
                                capture_output=True, text=True, timeout=3)
        for line in result.stdout.splitlines()[1:]:  # Header überspringen
            parts = line.split()
            if len(parts) >= 2 and parts[-1] == "disk":
                name = parts[0]
                size = parts[1]
                model = " ".join(parts[2:-1]) if len(parts) > 3 else "unbekannt"
                info.append(f"Disk: /dev/{name} {size} ({model})")
    except Exception:
        pass

    # Monitore (über xrandr)
    try:
        result = subprocess.run(["xrandr", "--current"], capture_output=True, text=True, timeout=3)
        for line in result.stdout.splitlines():
            if " connected" in line:
                parts = line.split()
                name = parts[0]
                # Auflösung finden (z.B. 1920x1080+0+0)
                res = ""
                for p in parts:
                    if "x" in p and "+" in p:
                        res = p.split("+")[0]
                        break
                info.append(f"Monitor: {name} {res}")
    except Exception:
        pass

    # USB-Geräte (TRX, Soundkarten)
    try:
        result = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=3)
        for line in result.stdout.splitlines():
            low = line.lower()
            if any(k in low for k in ["audio", "serial", "icom", "yaesu", "kenwood",
                                       "elecraft", "burr-brown", "focusrite", "scarlett",
                                       "codec", "sound", "ft-", "ic-", "usb-uart", "cp210",
                                       "ch340", "pl2303", "ftdi"]):
                # Bus/Device Prefix entfernen
                dev = line.split(": ", 1)[-1] if ": " in line else line
                info.append(f"USB: {dev}")
    except Exception:
        pass

    return "\n".join(info)


# --- Logger Setup ---

_logger = logging.getLogger("riglink.session")
_logger.setLevel(logging.DEBUG)
_logger.propagate = False


def start_session():
    """Neue Session starten — altes Log löschen, State auf dirty setzen."""
    # Altes Log nur löschen wenn KEIN Crash vorlag
    state = _read_state()
    if state.get("clean_exit", False):
        # Sauberer Exit → altes Log löschen
        if os.path.exists(_SESSION_LOG):
            os.remove(_SESSION_LOG)

    # State auf "nicht sauber beendet" setzen
    _write_state({"clean_exit": False, "started": datetime.now().isoformat()})

    # File Handler (neu) anhängen
    for h in _logger.handlers[:]:
        _logger.removeHandler(h)

    handler = logging.FileHandler(_SESSION_LOG, mode="a", encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    ))
    _logger.addHandler(handler)

    _logger.info("=== SESSION START ===")
    _logger.info("System: %s %s", platform.system(), platform.release())


def mark_clean_exit():
    """Sauberen Exit markieren — wird in closeEvent aufgerufen."""
    _logger.info("=== SESSION ENDE (sauber) ===")
    state = _read_state()
    state["clean_exit"] = True
    state["ended"] = datetime.now().isoformat()
    _write_state(state)


def clear_old_log():
    """Altes Session-Log löschen (nach erfolgreichem Report oder Abbruch)."""
    if os.path.exists(_SESSION_LOG):
        os.remove(_SESSION_LOG)
    _write_state({})


# --- Logging Shortcuts ---

def log_action(action):
    """User-Aktion loggen (Button-Klick, Menü, etc.)."""
    _logger.info("ACTION: %s", action)


def log_event(event):
    """App-Event loggen (Connect, Disconnect, etc.)."""
    _logger.info("EVENT: %s", event)


def log_error(error):
    """Fehler loggen."""
    _logger.error("ERROR: %s", error)


def log_cat(direction, cmd, response=None):
    """CAT-Kommunikation loggen."""
    if response:
        _logger.debug("CAT %s: %s → %s", direction, cmd, response)
    else:
        _logger.debug("CAT %s: %s", direction, cmd)
