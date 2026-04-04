"""
RigLink — NetworkCat
TCP-CAT über Hamlib rigctld (Port 4532 Standard).
Implementiert dieselbe CatBase-API wie Serial-Handler.

rigctld starten (Beispiel FT-991A):
    rigctld -m 1035 -r /dev/ttyUSB0 -s 38400

Dann RigLink Remote-Tab: 192.168.1.167:4532
"""

import socket
import threading
import logging

from core.cat import CatBase

log = logging.getLogger(__name__)

_TIMEOUT  = 2.0   # Sekunden pro Kommando
_BUFSIZE  = 4096


class NetworkCat(CatBase):
    """CAT über TCP-Socket — spricht Hamlib rigctld Protokoll."""

    def __init__(self, host: str = "localhost", port: int = 4532, timeout: float = _TIMEOUT, **_):
        # CatBase mit Dummy-Serial-Params, wir nutzen TCP statt Serial
        super().__init__(port=f"tcp:{host}:{port}", baud=0)
        self._host    = host
        self._tcp_port = port
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._lock    = threading.Lock()

    # ── Verbindung ────────────────────────────────────────────────────

    def connect(self) -> bool:
        with self._lock:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(self._timeout)
                s.connect((self._host, self._tcp_port))
                self._sock = s
                self.connected = True
                log.info("NetworkCat verbunden: %s:%d", self._host, self._tcp_port)
                return True
            except Exception as e:
                log.error("NetworkCat connect fehlgeschlagen: %s", e)
                self._sock = None
                self.connected = False
                return False

    def disconnect(self):
        self.connected = False
        with self._lock:
            try:
                if self._sock:
                    self._sock.close()
            except Exception:
                pass
            self._sock = None
        log.info("NetworkCat getrennt")

    # ── Low-level ─────────────────────────────────────────────────────

    def _cmd(self, command: str) -> str | None:
        """Sendet Kommando, liest Antwort bis RPRT-Zeile."""
        with self._lock:
            if not self._sock:
                return None
            try:
                self._sock.sendall((command + "\n").encode())
                data = b""
                while True:
                    chunk = self._sock.recv(_BUFSIZE)
                    if not chunk:
                        break
                    data += chunk
                    if b"RPRT" in data:
                        break
                return data.decode(errors="ignore").strip()
            except Exception as e:
                log.error("NetworkCat Kommando '%s' fehlgeschlagen: %s", command, e)
                return None

    def _parse_value(self, response: str | None) -> str | None:
        """Erste Nicht-RPRT-Zeile aus Antwort extrahieren."""
        if not response:
            return None
        for line in response.splitlines():
            line = line.strip()
            if line.startswith("RPRT"):
                code = line.split()[-1]
                if code != "0":
                    return None  # Fehler
                continue
            if line:
                return line
        return None

    # ── CatBase API ───────────────────────────────────────────────────

    def get_frequency(self) -> int | None:
        val = self._parse_value(self._cmd("f"))
        try:
            return int(val) if val else None
        except (ValueError, TypeError):
            return None

    def set_frequency(self, hz: int):
        self._cmd(f"F {hz}")

    def get_mode(self) -> str | None:
        resp = self._cmd("m")
        if not resp:
            return None
        lines = [l.strip() for l in resp.splitlines()
                 if l.strip() and not l.strip().startswith("RPRT")]
        return lines[0] if lines else None

    def set_mode(self, mode: str):
        self._cmd(f"M {mode} 0")

    def get_smeter(self) -> int | None:
        val = self._parse_value(self._cmd("l STRENGTH"))
        try:
            # rigctld gibt float 0.0–1.0 oder dBm zurück — in S-Einheit umrechnen
            f = float(val) if val else None
            if f is None:
                return None
            # Wert 0–255 (rigctld intern) → S0–S9+
            if f > 9:
                return int(min(f, 60))
            return int(f * 9)
        except (ValueError, TypeError):
            return None

    def ptt_on(self):
        self._cmd("T 1")

    def ptt_off(self):
        self._cmd("T 0")

    def get_preamp(self) -> str | None:
        val = self._parse_value(self._cmd("l PREAMP"))
        return val

    def set_preamp(self, mode: str):
        val = "1" if mode and mode != "IPO" else "0"
        self._cmd(f"L PREAMP {val}")

    def get_att(self) -> bool | None:
        val = self._parse_value(self._cmd("l ATT"))
        try:
            return int(float(val)) > 0 if val else None
        except (ValueError, TypeError):
            return None

    def set_att(self, on: bool):
        self._cmd(f"L ATT {'12' if on else '0'}")
