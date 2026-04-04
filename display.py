#!/usr/bin/env python3
"""
RigLink OLED Display — SSD1306 128x64 via I2C (Bus 1, Adresse 0x3C)

Zeigt den Arbeitsstatus von Claude-Screens:
  Zeile 1: Screen-Name (z.B. "riglink-server-skiller")
  Zeile 2: Status    (Working / Thinking / Reading / Idle)
  Zeile 3: Aufgabe   (erste sinnvolle Zeile, gekürzt)
  Zeile 4: Index     (z.B. "Screen 2/4")

Alle 5 Sekunden wird zum nächsten Screen rotiert.
"""

import re
import subprocess
import tempfile
import os
import sys
import time
import signal
import threading
import atexit
import random

from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image, ImageDraw, ImageFont


# ── Konstanten ────────────────────────────────────────────────────────────────

I2C_BUS        = 1
I2C_ADDRESS    = 0x3C
DISPLAY_WIDTH  = 128
DISPLAY_HEIGHT = 64
ROTATE_EVERY   = 5.0      # Sekunden pro Screen
POLL_INTERVAL  = 1.0      # Screen-Inhalt wie oft neu lesen
PID_FILE       = "/tmp/display.pid"
PIXEL_SHIFT_INTERVAL = 60.0   # Pixel-Shift alle 60 Sekunden
DIM_AFTER_SEC  = 600          # Dimmen nach 10 Minuten Idle

# Zeilenpositionen
LINE1_Y =  0
LINE2_Y = 16
LINE3_Y = 32
LINE4_Y = 50

# Schlüsselwörter für Status-Erkennung (Reihenfolge = Priorität)
STATUS_KEYWORDS = [
    ("Working",  ["working", "writing", "editing", "executing", "building",
                  "installing", "running", "creating", "saving"]),
    ("Thinking", ["thinking", "analyzing", "planning", "considering",
                  "let me", "i'll", "i will"]),
    ("Reading",  ["reading", "checking", "looking", "searching", "found",
                  "file", "grep", "glob"]),
]

# Zeilen die als "Aufgabe" unbrauchbar sind
SKIP_PATTERNS = re.compile(
    r"^\s*$"                        # leer
    r"|^\s*[>\$#%]\s*"              # Shell-Prompt
    r"|^bash-|^---+$"               # Trennlinien
    r"|^\s*\d+\s*$"                 # nur Zahlen
    r"|Screen \d+/\d+"              # eigene Status-Zeile
    r"|SSD1306|I2C|luma"            # Display-eigene Ausgaben
)


# ── PID-Lockfile — nur eine Instanz ──────────────────────────────────────────

def _kill_old_instance():
    """Prüft ob eine alte Instanz läuft und beendet sie sauber."""
    if not os.path.exists(PID_FILE):
        return
    try:
        with open(PID_FILE) as f:
            old_pid = int(f.read().strip())
        # Prüfen ob Prozess noch lebt
        os.kill(old_pid, 0)
        # Lebt noch → sauber beenden
        print(f"[Display] Alte Instanz (PID {old_pid}) gefunden — beende sie")
        os.kill(old_pid, signal.SIGTERM)
        # Kurz warten bis beendet
        for _ in range(20):
            try:
                os.kill(old_pid, 0)
                time.sleep(0.1)
            except OSError:
                break
    except (ValueError, OSError):
        pass  # Kein gültiger PID oder Prozess bereits beendet
    # Alte PID-Datei aufräumen
    try:
        os.unlink(PID_FILE)
    except OSError:
        pass


def _write_pid():
    """Schreibt eigene PID in Lockfile."""
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _remove_pid():
    """Entfernt PID-Datei beim Beenden."""
    try:
        os.unlink(PID_FILE)
    except OSError:
        pass


# ── screen-Hilfsfunktionen ────────────────────────────────────────────────────

def list_screens() -> list[tuple[str, str]]:
    """
    Gibt Liste von (pid_name, screen_name) zurück.
    Beispiel: [("12345.riglink-server-skiller", "riglink-server-skiller")]
    """
    try:
        out = subprocess.check_output(
            ["screen", "-ls"], text=True, stderr=subprocess.DEVNULL
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    screens = []
    for line in out.splitlines():
        # Typisches Format: "\t12345.riglink-server-skiller\t(Attached)"
        m = re.match(r"\s+(\d+\.([\w\-\.]+))", line)
        if m:
            screens.append((m.group(1), m.group(2)))
    return screens


def hardcopy_screen(pid_name: str) -> list[str]:
    """
    Liest den aktuellen Inhalt eines Screen-Fensters via hardcopy.
    Gibt Zeilen als Liste zurück (leer bei Fehler).
    """
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
        tmpfile = tf.name
    try:
        subprocess.run(
            ["screen", "-S", pid_name, "-X", "hardcopy", "-h", tmpfile],
            timeout=2, stderr=subprocess.DEVNULL, check=False
        )
        time.sleep(0.1)  # Screen braucht kurz
        with open(tmpfile, "r", errors="replace") as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines if l.strip()]
    except Exception:
        return []
    finally:
        try:
            os.unlink(tmpfile)
        except OSError:
            pass


def detect_status(lines: list[str]) -> str:
    """
    Erkennt aktuellen Arbeitsstatus anhand der letzten Zeilen des Screen-Inhalts.
    Schaut nur auf die letzten 20 Zeilen (aktuellster Output).
    """
    recent = " ".join(lines[-20:]).lower()
    for label, keywords in STATUS_KEYWORDS:
        for kw in keywords:
            if kw in recent:
                return label
    return "Idle"


def extract_task(lines: list[str]) -> str:
    """
    Extrahiert die erste sinnvolle Aufgaben-Zeile aus dem Screen-Inhalt.
    Sucht von hinten nach einer lesbaren, nicht-trivialen Zeile.
    """
    for line in reversed(lines[-40:]):
        stripped = line.strip()
        if len(stripped) < 5:
            continue
        if SKIP_PATTERNS.search(stripped):
            continue
        # Steuerzeichen entfernen
        clean = re.sub(r"\x1b\[[0-9;]*m", "", stripped)
        clean = re.sub(r"[^\x20-\x7e\xc0-\xff]", "", clean).strip()
        if len(clean) >= 5:
            return clean[:32]
    return "---"


# ── Fonts laden ───────────────────────────────────────────────────────────────

def _load_fonts():
    try:
        bold   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
        normal = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        small  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
    except OSError:
        bold = normal = small = ImageFont.load_default()
    return bold, normal, small


# ── Frame rendern ─────────────────────────────────────────────────────────────

_STATUS_ICONS = {
    "Working":  ">",
    "Thinking": "~",
    "Reading":  "?",
    "Idle":     "-",
}

def _render(screen_name: str, status: str, task: str,
            idx: int, total: int, fonts) -> Image.Image:
    bold, normal, small = fonts

    img  = Image.new("1", (DISPLAY_WIDTH, DISPLAY_HEIGHT), 0)
    draw = ImageDraw.Draw(img)

    # ── Zeile 1: Screen-Name (invertierter Header) ─────────────────────────
    draw.rectangle([0, LINE1_Y, DISPLAY_WIDTH - 1, LINE1_Y + 13], fill=1)
    name = screen_name[:22]
    draw.text((2, LINE1_Y), name, font=bold, fill=0)

    # ── Zeile 2: Status mit Icon ───────────────────────────────────────────
    icon = _STATUS_ICONS.get(status, "-")
    draw.text((2, LINE2_Y), f"{icon} {status}", font=normal, fill=1)

    # ── Zeile 3: Aufgabe (gekürzt, scrollt nicht) ──────────────────────────
    draw.text((2, LINE3_Y), task[:22], font=small, fill=1)

    # ── Zeile 4: Screen-Index ──────────────────────────────────────────────
    counter = f"Screen {idx}/{total}"
    draw.text((2, LINE4_Y), counter, font=small, fill=1)
    # Kleiner Fortschrittsbalken rechts
    bar_x = 75
    bar_w = DISPLAY_WIDTH - bar_x - 2
    draw.rectangle([bar_x, LINE4_Y + 2, bar_x + bar_w, LINE4_Y + 9], outline=1)
    if total > 0:
        filled = int((idx / total) * bar_w)
        if filled > 0:
            draw.rectangle([bar_x + 1, LINE4_Y + 3, bar_x + filled, LINE4_Y + 8], fill=1)

    return img


def _render_no_screens(fonts) -> Image.Image:
    """Anzeige wenn keine Screens aktiv."""
    bold, normal, small = fonts
    img  = Image.new("1", (DISPLAY_WIDTH, DISPLAY_HEIGHT), 0)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, DISPLAY_WIDTH - 1, 13], fill=1)
    draw.text((2, 0), "RigLink Watcher", font=bold, fill=0)
    draw.text((2, 18), "Idle", font=normal, fill=1)
    draw.text((2, 32), "Keine Screens aktiv", font=small, fill=1)
    return img


# ── Haupt-Loop ────────────────────────────────────────────────────────────────

def run_display() -> None:
    # Einzelinstanz: alte Instanz killen, eigene PID schreiben
    _kill_old_instance()
    _write_pid()
    atexit.register(_remove_pid)

    serial_if = i2c(port=I2C_BUS, address=I2C_ADDRESS)
    device = ssd1306(serial_if, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT)
    fonts  = _load_fonts()

    print(f"[Display] Gestartet (PID {os.getpid()}) — SSD1306 I2C Bus {I2C_BUS} Adresse 0x{I2C_ADDRESS:02X}")

    current_idx  = 0       # aktuell angezeigter Screen (Index in Liste)
    last_rotate  = time.time()
    last_content = {}      # cache: pid_name → (status, task, timestamp)
    last_active  = time.time()  # Zeitpunkt des letzten "nicht-Idle" Status
    last_shift   = time.time()  # Zeitpunkt des letzten Pixel-Shifts
    shift_x      = 0            # Aktueller Pixel-Shift X-Offset
    shift_y      = 0            # Aktueller Pixel-Shift Y-Offset
    dimmed       = False        # Display aktuell gedimmt?

    def _shutdown(signum, frame):
        """Sauberes Beenden bei SIGTERM."""
        print(f"\n[Display] Signal {signum} empfangen — beende.")
        _remove_pid()
        device.clear()
        device.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while True:
            screens = list_screens()
            now     = time.time()

            if not screens:
                device.display(_render_no_screens(fonts))
                time.sleep(POLL_INTERVAL)
                continue

            # Index korrekt halten
            current_idx = current_idx % len(screens)

            # Rotation nach ROTATE_EVERY Sekunden
            if now - last_rotate >= ROTATE_EVERY:
                current_idx = (current_idx + 1) % len(screens)
                last_rotate = now

            pid_name, screen_name = screens[current_idx]

            # Content nur alle POLL_INTERVAL Sekunden neu lesen
            cached = last_content.get(pid_name)
            if cached is None or (now - cached[2]) >= POLL_INTERVAL:
                lines  = hardcopy_screen(pid_name)
                status = detect_status(lines)
                task   = extract_task(lines)
                last_content[pid_name] = (status, task, now)
            else:
                status, task, _ = cached

            # Burn-in Schutz: Aktivität tracken
            if status != "Idle":
                last_active = now

            # Burn-in Schutz: Dimmen nach DIM_AFTER_SEC Idle
            idle_sec = now - last_active
            should_dim = idle_sec >= DIM_AFTER_SEC
            if should_dim != dimmed:
                device.contrast(16 if should_dim else 255)
                dimmed = should_dim
                if should_dim:
                    print(f"[Display] Burn-in Schutz: Dimmen nach {DIM_AFTER_SEC}s Idle")
                else:
                    print("[Display] Aktivität erkannt — volle Helligkeit")

            # Burn-in Schutz: Pixel-Shift alle PIXEL_SHIFT_INTERVAL Sekunden
            if now - last_shift >= PIXEL_SHIFT_INTERVAL:
                shift_x = random.randint(0, 2)
                shift_y = random.randint(0, 2)
                last_shift = now

            img = _render(
                screen_name = screen_name,
                status      = status,
                task        = task,
                idx         = current_idx + 1,
                total       = len(screens),
                fonts       = fonts,
            )

            # Pixel-Shift anwenden: Bild leicht verschieben
            if shift_x > 0 or shift_y > 0:
                shifted = Image.new("1", (DISPLAY_WIDTH, DISPLAY_HEIGHT), 0)
                shifted.paste(img, (shift_x, shift_y))
                img = shifted

            device.display(img)

            print(f"[Display] {screen_name:30s}  {status:8s}  {task}")
            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n[Display] Beendet.")
    finally:
        _remove_pid()
        device.clear()
        device.cleanup()


if __name__ == "__main__":
    run_display()
