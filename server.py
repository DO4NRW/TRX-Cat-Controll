#!/usr/bin/env python3
"""
RigLink Server — IC-705 via rigctld + Flask Web-UI auf Port 8080
Startet rigctld automatisch, pollt Frequenz/Mode/S-Meter, steuert PTT.
"""

import os
import sys
import time
import json
import glob as globmod
import socket
import subprocess
import threading
import logging
from typing import Optional

from flask import Flask, jsonify, request, render_template

from audio import AudioStreamer

# Display läuft eigenständig via display.py (liest screen -ls selbst)
DISPLAY_AVAILABLE = False


# ── Datenbank (MariaDB) ─────────────────────────────────────────────────────

DB_CONFIG = {
    "host": "localhost",
    "user": "riglink",
    "password": "riglink2024",
    "database": "riglink",
}


def get_db():
    """Gibt eine MariaDB-Verbindung zurück. Aufrufer muss schließen."""
    try:
        import mysql.connector
        return mysql.connector.connect(**DB_CONFIG)
    except Exception as e:
        log.warning("DB-Verbindung fehlgeschlagen: %s", e)
        return None


# ── Konfiguration ─────────────────────────────────────────────────────────────

RIGCTLD_MODEL   = "3085"          # IC-705
RIGCTLD_DEVICE  = "/dev/ttyACM0"
RIGCTLD_BAUD    = "115200"
RIGCTLD_HOST    = "127.0.0.1"
RIGCTLD_PORT    = 4532
FLASK_PORT      = 80
POLL_INTERVAL   = 0.15            # 150 ms — Frequenz + S-Meter
FULL_SYNC_EVERY = 20              # alle ~3 s vollständiger Sync


# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("riglink")
START_TIME = time.time()


CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config() -> dict:
    """Lädt die gesamte Config aus config.json."""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data: dict) -> bool:
    """Speichert/merged Config in config.json."""
    cfg = load_config()
    cfg.update(data)
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        log.error("Config-Speichern fehlgeschlagen: %s", e)
        return False


def rig_config_get(key: str, default: str = "") -> str:
    """Liest optionale Werte aus der Config-Datei."""
    return str(load_config().get(key, default))


# ── Rig-Zustand ───────────────────────────────────────────────────────────────

class RigState:
    def __init__(self):
        self._lock      = threading.Lock()
        self.connected  = False
        self.frequency  = 0          # Hz
        self.mode       = "---"
        self.ptt        = False
        self.s_meter    = 0          # 0–255 (rigctld roh)
        self.s_value    = 0.0        # S0–S9+ float
        self.s_label    = "S0"
        self.error      = ""

    def get_snapshot(self) -> dict:
        with self._lock:
            return {
                "connected":  self.connected,
                "frequency":  self.frequency,
                "freq_str":   self._format_freq(self.frequency),
                "mode":       self.mode,
                "ptt":        self.ptt,
                "s_meter":    self.s_meter,
                "s_value":    round(self.s_value, 1),
                "s_label":    self.s_label,
                "error":      self.error,
            }

    @staticmethod
    def _format_freq(hz: int) -> str:
        """14205000 → '14.205,000' (Hz, lesbar)"""
        if hz <= 0:
            return "---"
        mhz  = hz // 1_000_000
        khz  = (hz % 1_000_000) // 1_000
        rest = hz % 1_000
        return f"{mhz}.{khz:03d}.{rest:03d}"

    def update(self, **kwargs):
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self, k):
                    setattr(self, k, v)


rig = RigState()


# ── S-Meter Umrechnung ────────────────────────────────────────────────────────

def raw_to_s(raw: int):
    """
    rigctld liefert 0–255.
    S-Wert-Mapping: Icom-typisch linear.
    Rückgabe: (float_value, label_str)
    """
    # Icom: 0=S0, ~114=S9, 255=S9+60
    if raw <= 0:
        return 0.0, "S0"
    if raw <= 114:
        s = raw / 114.0 * 9.0
        label = f"S{int(s)}"
    else:
        # S9+ in 10-dB-Schritten: 114→S9, 171→S9+20, 228→S9+40, 255→S9+60
        over = (raw - 114) / (255 - 114) * 60.0
        s = 9.0 + over / 10.0
        db = int(round(over / 10.0)) * 10
        label = f"S9+{db}" if db > 0 else "S9"
    return round(s, 1), label


# ── rigctld Verwaltung ────────────────────────────────────────────────────────

_rigctld_proc: Optional[subprocess.Popen] = None


def start_rigctld() -> bool:
    """rigctld-Prozess starten. True wenn erfolgreich."""
    global _rigctld_proc

    # Prüfen ob Port bereits belegt (evtl. läuft schon)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex((RIGCTLD_HOST, RIGCTLD_PORT)) == 0:
            log.info("rigctld läuft bereits auf Port %d", RIGCTLD_PORT)
            return True

    cmd = [
        "rigctld",
        "-m", RIGCTLD_MODEL,
        "-r", RIGCTLD_DEVICE,
        "-s", RIGCTLD_BAUD,
        "-t", str(RIGCTLD_PORT),
        "-v",
    ]
    log.info("Starte rigctld: %s", " ".join(cmd))
    try:
        _rigctld_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        time.sleep(1.5)  # rigctld braucht kurz zum Starten
        # Verbindungstest
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((RIGCTLD_HOST, RIGCTLD_PORT)) == 0:
                log.info("rigctld gestartet (PID %d)", _rigctld_proc.pid)
                return True
        log.error("rigctld Port nicht erreichbar nach Start")
        return False
    except FileNotFoundError:
        log.error("rigctld nicht gefunden — bitte hamlib installieren")
        return False
    except Exception as e:
        log.error("rigctld Start fehlgeschlagen: %s", e)
        return False


def stop_rigctld():
    global _rigctld_proc
    if _rigctld_proc:
        _rigctld_proc.terminate()
        _rigctld_proc = None
        log.info("rigctld beendet")


# ── CAT-Kommunikation via rigctld TCP ─────────────────────────────────────────

class RigCtlClient:
    """Einfacher TCP-Client für rigctld."""

    def __init__(self, host: str = RIGCTLD_HOST, port: int = RIGCTLD_PORT):
        self.host    = host
        self.port    = port
        self._sock   = None
        self._lock   = threading.Lock()

    def connect(self) -> bool:
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(2.0)
            self._sock.connect((self.host, self.port))
            return True
        except Exception as e:
            log.error("rigctld Verbindung fehlgeschlagen: %s", e)
            self._sock = None
            return False

    def disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _send(self, cmd: str) -> Optional[str]:
        """Befehl senden, Antwort lesen."""
        with self._lock:
            if not self._sock:
                return None
            try:
                self._sock.sendall((cmd + "\n").encode())
                data = b""
                while True:
                    chunk = self._sock.recv(1024)
                    if not chunk:
                        break
                    data += chunk
                    if b"\n" in data:
                        break
                return data.decode(errors="replace").strip()
            except Exception as e:
                log.debug("rigctld Sendefehler: %s", e)
                self._sock = None
                return None

    def get_freq(self) -> Optional[int]:
        r = self._send("f")
        try:
            return int(r.split("\n")[0].strip()) if r else None
        except ValueError:
            return None

    def get_mode(self) -> Optional[str]:
        r = self._send("m")
        if not r:
            return None
        lines = [l for l in r.split("\n") if l.strip()]
        return lines[0].strip() if lines else None

    def get_smeter(self) -> Optional[int]:
        """S-Meter als 0-255 Rohwert."""
        r = self._send("l STRENGTH")
        try:
            val = float(r.split("\n")[0].strip()) if r else None
            # rigctld liefert dBm oder 0-255 je nach Version
            # Werte > 0 = dBm, normieren: -54dBm=S9, -127dBm=S0
            if val is not None:
                if -130 <= val <= 0:
                    # dBm → 0-255
                    raw = int((val + 127) / 73 * 114)
                    return max(0, min(255, raw))
                else:
                    return max(0, min(255, int(val)))
        except (ValueError, TypeError):
            return None

    def set_ptt(self, on: bool) -> bool:
        r = self._send(f"T {1 if on else 0}")
        return r is not None and "RPRT 0" in r

    def get_ptt(self) -> Optional[bool]:
        r = self._send("t")
        try:
            return bool(int(r.split("\n")[0].strip())) if r else None
        except (ValueError, TypeError):
            return None


# ── Poll-Thread ───────────────────────────────────────────────────────────────

_client = RigCtlClient()
_poll_counter = 0


def _poll_loop():
    global _poll_counter

    # rigctld starten
    if not start_rigctld():
        rig.update(connected=False, error="rigctld Start fehlgeschlagen")
        return

    # Verbindung aufbauen (mit Wiederholversuchen)
    for attempt in range(5):
        if _client.connect():
            break
        log.info("Verbindungsversuch %d/5...", attempt + 1)
        time.sleep(1.0)
    else:
        rig.update(connected=False, error="Verbindung zu rigctld fehlgeschlagen")
        return

    rig.update(connected=True, error="")
    log.info("IC-705 verbunden")

    while True:
        try:
            _poll_counter += 1

            # ── Frequenz (jeder Poll) ──────────────────────────────────────
            freq = _client.get_freq()
            if freq is not None:
                rig.update(frequency=freq)

            # ── S-Meter (jeder Poll) ───────────────────────────────────────
            raw = _client.get_smeter()
            if raw is not None:
                sv, sl = raw_to_s(raw)
                rig.update(s_meter=raw, s_value=sv, s_label=sl)

            # ── Voller Sync alle ~3 s ──────────────────────────────────────
            if _poll_counter % FULL_SYNC_EVERY == 0:
                mode = _client.get_mode()
                if mode:
                    rig.update(mode=mode)
                ptt = _client.get_ptt()
                if ptt is not None:
                    rig.update(ptt=ptt)

            # Verbindungsverlust behandeln
            if _client._sock is None:
                log.warning("rigctld Verbindung verloren — reconnect...")
                rig.update(connected=False, error="Verbindung verloren")
                time.sleep(2.0)
                if _client.connect():
                    rig.update(connected=True, error="")

        except Exception as e:
            log.error("Poll-Fehler: %s", e)

        time.sleep(POLL_INTERVAL)


# ── Flask Web-UI ──────────────────────────────────────────────────────────────

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
app = Flask(__name__, template_folder=TEMPLATE_DIR)

# ── Theme-Presets ────────────────────────────────────────────────────────────

THEMES = {
    "Dark":           {"teal":"#06c6a4","bg":"#0d0d1a","bg_card":"#151528","bg_input":"#1a1a30","border":"#2a2a45","text":"#e0e0e0","dim":"#888888"},
    "Midnight Blue":  {"teal":"#4fc3f7","bg":"#0a0e1a","bg_card":"#0f1628","bg_input":"#141d35","border":"#1e2d50","text":"#e0e8ff","dim":"#6080b0"},
    "Forest Green":   {"teal":"#4caf50","bg":"#0a1a0a","bg_card":"#0f1f0f","bg_input":"#142814","border":"#1e3c1e","text":"#d0e8d0","dim":"#608060"},
    "Solarized Dark": {"teal":"#2aa198","bg":"#002b36","bg_card":"#073642","bg_input":"#073642","border":"#586e75","text":"#839496","dim":"#586e75"},
    "Dracula":        {"teal":"#50fa7b","bg":"#282a36","bg_card":"#383a59","bg_input":"#44475a","border":"#6272a4","text":"#f8f8f2","dim":"#6272a4"},
    "Nord":           {"teal":"#88c0d0","bg":"#2e3440","bg_card":"#3b4252","bg_input":"#434c5e","border":"#4c566a","text":"#eceff4","dim":"#81a1c1"},
    "Monokai":        {"teal":"#a6e22e","bg":"#272822","bg_card":"#383830","bg_input":"#3e3d32","border":"#75715e","text":"#f8f8f2","dim":"#75715e"},
    "Gruvbox Dark":   {"teal":"#b8bb26","bg":"#282828","bg_card":"#3c3836","bg_input":"#504945","border":"#665c54","text":"#ebdbb2","dim":"#928374"},
    "High Contrast":  {"teal":"#ffff00","bg":"#000000","bg_card":"#111111","bg_input":"#1a1a1a","border":"#444444","text":"#ffffff","dim":"#aaaaaa"},
    "Light":          {"teal":"#00897b","bg":"#f5f5f5","bg_card":"#ffffff","bg_input":"#eeeeee","border":"#cccccc","text":"#1a1a1a","dim":"#666666"},
}
app.logger.setLevel(logging.WARNING)

# Audio-Streamer (PCM2901 / USB-Audio)
_audio = AudioStreamer()

_INLINE_HTML_REMOVED = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>RigLink — IC-705</title>
  <style>
    :root {
      --teal:    #06c6a4;
      --bg:      #0d1117;
      --surface: #161b22;
      --border:  #30363d;
      --text:    #e6edf3;
      --muted:   #8b949e;
      --red:     #f85149;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 1.5rem; }
    header { width: 100%; max-width: 700px; display: flex; align-items: center; gap: 1rem; margin-bottom: 1.5rem; }
    header h1 { font-size: 1.4rem; letter-spacing: 0.05em; color: var(--teal); }
    #status-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--muted); flex-shrink: 0; }
    #status-dot.online  { background: var(--teal); box-shadow: 0 0 6px var(--teal); }
    #status-dot.offline { background: var(--red);  box-shadow: 0 0 6px var(--red); }
    .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 1.2rem 1.5rem; width: 100%; max-width: 700px; margin-bottom: 1rem; }
    .card-title { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted); margin-bottom: 0.75rem; }

    /* Frequenz */
    #freq-display { font-size: 2.8rem; font-weight: 700; letter-spacing: 0.04em; color: var(--teal); font-variant-numeric: tabular-nums; line-height: 1; }
    #mode-display { font-size: 1.1rem; color: var(--muted); margin-top: 0.3rem; }

    /* S-Meter */
    .smeter-wrap { display: flex; align-items: center; gap: 0.8rem; }
    #smeter-bar-bg { flex: 1; height: 18px; background: var(--border); border-radius: 4px; overflow: hidden; }
    #smeter-bar { height: 100%; width: 0%; background: linear-gradient(90deg, #06c6a4 0%, #06c6a4 75%, #f0a500 75%, #f0a500 90%, #f85149 90%); border-radius: 4px; transition: width 0.1s ease; }
    #smeter-label { min-width: 4rem; text-align: right; font-weight: 600; font-size: 1rem; color: var(--teal); }

    /* S-Marker */
    .smeter-markers { display: flex; justify-content: space-between; padding: 2px 0; font-size: 0.65rem; color: var(--muted); margin-top: 2px; }

    /* Steuerung */
    .controls { display: flex; gap: 0.75rem; flex-wrap: wrap; margin-top: 0.5rem; }
    button { border: 1px solid var(--border); background: transparent; color: var(--text); border-radius: 6px; padding: 0.5rem 1.2rem; cursor: pointer; font-size: 0.9rem; transition: all 0.15s; }
    button:hover { border-color: var(--teal); color: var(--teal); }
    button.active, button.ptt-on { border-color: var(--teal); color: var(--bg); background: var(--teal); }
    button.ptt-on { background: var(--red); border-color: var(--red); color: #fff; }
    button:disabled { opacity: 0.4; cursor: not-allowed; }

    /* Mode-Buttons */
    #mode-buttons { display: flex; gap: 0.5rem; flex-wrap: wrap; }

    /* Frequenz-Eingabe */
    .freq-input-row { display: flex; gap: 0.5rem; margin-top: 0.75rem; }
    input[type=text] { background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 0.45rem 0.8rem; font-size: 0.9rem; flex: 1; }
    input[type=text]:focus { outline: none; border-color: var(--teal); }

    /* Status-Zeile */
    #status-bar { font-size: 0.75rem; color: var(--muted); margin-top: 0.5rem; }
    footer { margin-top: auto; padding-top: 1.5rem; font-size: 0.7rem; color: var(--muted); }
  </style>
</head>
<body>
  <header>
    <div id="status-dot"></div>
    <h1>RigLink &mdash; IC-705</h1>
    <span id="status-text" style="color:var(--muted);font-size:0.85rem;margin-left:auto"></span>
  </header>

  <!-- Frequenz & Mode -->
  <div class="card">
    <div class="card-title">Frequenz</div>
    <div id="freq-display">---</div>
    <div id="mode-display">---</div>

    <div class="freq-input-row">
      <input type="text" id="freq-input" placeholder="MHz eingeben z.B. 14.205" />
      <button onclick="setFreq()">Setzen</button>
    </div>
  </div>

  <!-- S-Meter -->
  <div class="card">
    <div class="card-title">S-Meter</div>
    <div class="smeter-wrap">
      <div id="smeter-bar-bg"><div id="smeter-bar"></div></div>
      <div id="smeter-label">S0</div>
    </div>
    <div class="smeter-markers">
      <span>S1</span><span>S3</span><span>S5</span><span>S7</span><span>S9</span><span>+20</span><span>+40</span>
    </div>
  </div>

  <!-- Steuerung -->
  <div class="card">
    <div class="card-title">Steuerung</div>
    <div class="controls">
      <button id="ptt-btn" onclick="togglePTT()">PTT</button>
    </div>

    <div class="card-title" style="margin-top:1rem">Mode</div>
    <div id="mode-buttons">
      <button onclick="setMode('USB')">USB</button>
      <button onclick="setMode('LSB')">LSB</button>
      <button onclick="setMode('FM')">FM</button>
      <button onclick="setMode('AM')">AM</button>
      <button onclick="setMode('CW')">CW</button>
      <button onclick="setMode('PKTUSB')">FT8/JS8</button>
      <button onclick="setMode('PKTLSB')">PSK/WSPR</button>
    </div>
  </div>

  <div id="status-bar">Verbinde...</div>
  <footer>RigLink &copy; DO4NRW &mdash; Hamlib {{ hamlib_ver }}</footer>

<script>
  let pttActive = false;

  async function poll() {
    try {
      const r = await fetch('/api/state');
      const d = await r.json();

      // Status-Dot
      const dot = document.getElementById('status-dot');
      dot.className = d.connected ? 'online' : 'offline';
      document.getElementById('status-text').textContent = d.connected ? 'Verbunden' : 'Getrennt';

      // Frequenz
      document.getElementById('freq-display').textContent = d.freq_str || '---';
      document.getElementById('mode-display').textContent = d.mode || '---';

      // S-Meter: 0-12 → 0-100%
      const pct = Math.min(100, (d.s_value / 12) * 100);
      document.getElementById('smeter-bar').style.width = pct + '%';
      document.getElementById('smeter-label').textContent = d.s_label || 'S0';

      // PTT
      pttActive = d.ptt;
      const btn = document.getElementById('ptt-btn');
      btn.className = d.ptt ? 'ptt-on' : '';
      btn.textContent = d.ptt ? 'TX AKTIV' : 'PTT';

      document.getElementById('status-bar').textContent =
        d.error ? '⚠ ' + d.error : 'Aktualisiert ' + new Date().toLocaleTimeString('de-DE');
    } catch(e) {
      document.getElementById('status-dot').className = 'offline';
      document.getElementById('status-bar').textContent = 'Verbindung zum Server unterbrochen';
    }
  }

  async function togglePTT() {
    await fetch('/api/ptt', { method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ ptt: !pttActive }) });
  }

  async function setMode(mode) {
    await fetch('/api/mode', { method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ mode }) });
  }

  async function setFreq() {
    const val = document.getElementById('freq-input').value.trim();
    if (!val) return;
    // MHz-Eingabe → Hz
    const hz = Math.round(parseFloat(val.replace(',', '.')) * 1e6);
    if (isNaN(hz) || hz <= 0) return alert('Ungültige Frequenz');
    await fetch('/api/frequency', { method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ frequency: hz }) });
    document.getElementById('freq-input').value = '';
  }

  // Frequenz-Eingabe mit Enter
  document.getElementById('freq-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') setFreq();
  });

  // PTT: Leertaste (nur wenn kein Input fokussiert)
  document.addEventListener('keydown', e => {
    if (e.code === 'Space' && document.activeElement.tagName !== 'INPUT') {
      e.preventDefault();
      fetch('/api/ptt', { method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ ptt: true }) });
    }
  });
  document.addEventListener('keyup', e => {
    if (e.code === 'Space' && document.activeElement.tagName !== 'INPUT') {
      fetch('/api/ptt', { method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ ptt: false }) });
    }
  });

"""  # Ende des entfernten Inline-HTML-Blocks


@app.route("/")
def index():
    try:
        ver = subprocess.check_output(["rigctld", "--version"],
                                       stderr=subprocess.STDOUT, text=True).split()[2]
    except Exception:
        ver = "?"
    return render_template("index.html", hamlib_ver=ver)


@app.route("/api/audio")
def api_audio():
    return jsonify(_audio.status())


@app.route("/api/audio/rx/start", methods=["POST"])
def api_audio_rx_start():
    ok = _audio.start_rx()
    return jsonify({"ok": ok})


@app.route("/api/audio/rx/stop", methods=["POST"])
def api_audio_rx_stop():
    _audio.stop_rx()
    return jsonify({"ok": True})


@app.route("/api/audio/tx/start", methods=["POST"])
def api_audio_tx_start():
    data = request.get_json(silent=True) or {}
    path = data.get("file", "/tmp/riglink_tx.wav")
    ok = _audio.start_tx(path)
    return jsonify({"ok": ok})


@app.route("/api/audio/tx/stop", methods=["POST"])
def api_audio_tx_stop():
    _audio.stop_tx()
    return jsonify({"ok": True})


## Alter /api/status wurde durch api_status_extended ersetzt (siehe unten)


@app.route("/api/state")
def api_state():
    return jsonify(rig.get_snapshot())


@app.route("/api/ptt", methods=["POST"])
def api_ptt():
    data = request.get_json(silent=True) or {}
    on   = bool(data.get("ptt", False))
    ok   = _client.set_ptt(on)
    if ok:
        rig.update(ptt=on)
    return jsonify({"ok": ok, "ptt": on})


@app.route("/api/mode", methods=["POST"])
def api_mode():
    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode", "")).upper()
    if not mode:
        return jsonify({"ok": False, "error": "Kein Mode angegeben"}), 400
    # rigctld: M <mode> <passband>  (0 = Standard-Passband)
    r = _client._send(f"M {mode} 0")
    ok = r is not None and "RPRT 0" in r
    if ok:
        rig.update(mode=mode)
    return jsonify({"ok": ok, "mode": mode})


@app.route("/api/frequency", methods=["POST"])
def api_frequency():
    data = request.get_json(silent=True) or {}
    try:
        hz = int(data["frequency"])
    except (KeyError, ValueError, TypeError):
        return jsonify({"ok": False, "error": "Ungültige Frequenz"}), 400
    r = _client._send(f"F {hz}")
    ok = r is not None and "RPRT 0" in r
    if ok:
        rig.update(frequency=hz)
    return jsonify({"ok": ok, "frequency": hz})


# ── Neue Config-APIs ─────────────────────────────────────────────────────────

@app.route("/api/ports")
def api_ports():
    """Verfügbare Serial-Ports auflisten."""
    ports = sorted(
        globmod.glob("/dev/ttyACM*") + globmod.glob("/dev/ttyUSB*")
    )
    return jsonify({"ports": ports})


@app.route("/api/config")
def api_config():
    """Aktuelle Config als JSON zurückgeben."""
    return jsonify(load_config())


@app.route("/api/config/save", methods=["POST"])
def api_config_save():
    """Config-Werte speichern (merge)."""
    data = request.get_json(silent=True) or {}
    ok = save_config(data)
    return jsonify({"ok": ok})


@app.route("/api/cat/test", methods=["POST"])
def api_cat_test():
    """CAT-Verbindung testen — Frequenz abfragen."""
    freq = _client.get_freq()
    if freq is not None:
        return jsonify({
            "ok": True,
            "frequency": RigState._format_freq(freq),
        })
    return jsonify({"ok": False, "error": "Keine Antwort vom TRX"})


@app.route("/api/ptt/test", methods=["POST"])
def api_ptt_test():
    """PTT kurz testen (1s TX)."""
    ok_on = _client.set_ptt(True)
    if not ok_on:
        return jsonify({"ok": False, "error": "PTT konnte nicht aktiviert werden"})
    time.sleep(1.0)
    _client.set_ptt(False)
    return jsonify({"ok": True})


@app.route("/api/audio/nodes")
def api_audio_nodes():
    """PipeWire-Nodes auflisten (Quellen und Senken)."""
    sources = []
    sinks = []
    try:
        out = subprocess.check_output(
            ["pw-cli", "list-objects"], text=True, timeout=5
        )
        # Einfaches Parsing: Node-Name + Beschreibung extrahieren
        current = {}
        for line in out.split("\n"):
            line = line.strip()
            if line.startswith("id "):
                if current.get("name"):
                    if current.get("media_class") == "Audio/Source":
                        sources.append({"name": current["name"],
                                        "description": current.get("desc", current["name"])})
                    elif current.get("media_class") == "Audio/Sink":
                        sinks.append({"name": current["name"],
                                      "description": current.get("desc", current["name"])})
                current = {}
            elif "node.name" in line and "=" in line:
                current["name"] = line.split("=", 1)[1].strip().strip('"')
            elif "node.description" in line and "=" in line:
                current["desc"] = line.split("=", 1)[1].strip().strip('"')
            elif "media.class" in line and "=" in line:
                current["media_class"] = line.split("=", 1)[1].strip().strip('"')
        # Letzten Eintrag verarbeiten
        if current.get("name"):
            if current.get("media_class") == "Audio/Source":
                sources.append({"name": current["name"],
                                "description": current.get("desc", current["name"])})
            elif current.get("media_class") == "Audio/Sink":
                sinks.append({"name": current["name"],
                              "description": current.get("desc", current["name"])})
    except Exception as e:
        log.warning("PipeWire-Nodes konnten nicht gelesen werden: %s", e)

    return jsonify({"sources": sources, "sinks": sinks})


@app.route("/api/status")
def api_status_extended():
    """Erweiterter Systemstatus — rigctld, Uptime, Audio, Host, USB-Geräte."""
    # rigctld-Port prüfen
    rigctld_ok = False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        rigctld_ok = (s.connect_ex((RIGCTLD_HOST, RIGCTLD_PORT)) == 0)

    # Host-IP ermitteln
    try:
        host_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        host_ip = "127.0.0.1"

    # USB-Geräte
    usb_devices = []
    try:
        out = subprocess.check_output(
            ["lsusb"], text=True, timeout=5
        )
        for line in out.strip().split("\n"):
            if line.strip():
                usb_devices.append(line.strip())
    except Exception:
        pass

    return jsonify({
        "rigctld_running": rigctld_ok,
        "uptime_sec":      round(time.time() - START_TIME, 0),
        "host":            host_ip,
        "audio":           _audio.status(),
        "usb_devices":     usb_devices,
    })


@app.route("/api/themes")
def get_themes():
    """Liste aller verfügbaren Theme-Preset-Namen."""
    return jsonify(list(THEMES.keys()))


@app.route("/api/theme")
def get_theme():
    """Aktives Theme als JSON — Farben des gewählten Presets."""
    cfg = load_config()
    preset = cfg.get("theme_preset", "Dark")
    colors = THEMES.get(preset, THEMES["Dark"])
    return jsonify({**colors, "preset": preset})


@app.route("/api/theme/save", methods=["POST"])
def save_theme():
    """Theme-Preset speichern."""
    data = request.get_json(force=True)
    preset = data.get("preset", "Dark")
    save_config({"theme_preset": preset})
    colors = THEMES.get(preset, THEMES["Dark"])
    return jsonify({"ok": True, "preset": preset, **colors})


@app.route("/api/db/test")
def api_db_test():
    """DB-Verbindung testen."""
    conn = get_db()
    if conn is None:
        return jsonify({"ok": False, "error": "DB nicht erreichbar"})
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        count = cur.fetchone()[0]
        return jsonify({"ok": True, "user_count": count})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    finally:
        conn.close()


# ── Start ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("RigLink Server startet — IC-705 auf %s", RIGCTLD_DEVICE)

    # Poll-Thread
    poll_thread = threading.Thread(target=_poll_loop, daemon=True, name="poller")
    poll_thread.start()

    try:
        log.info("Web-UI: http://0.0.0.0:%d", FLASK_PORT)
        app.run(host="0.0.0.0", port=FLASK_PORT, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        log.info("Beendet.")
    finally:
        _audio.stop_all()
        stop_rigctld()
