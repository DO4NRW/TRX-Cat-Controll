import serial
import threading
import logging

log = logging.getLogger(__name__)

# FT-991A Mode codes
MODE_TO_CODE = {
    "LSB":      "1",
    "USB":      "2",
    "CW":       "3",
    "FM":       "4",
    "AM":       "5",
    "RTTY-L":   "6",
    "CW-R":     "7",
    "DATA-L":   "8",
    "RTTY-U":   "9",
    "DATA-FM":  "A",
    "FM-N":     "B",
    "DATA-U":   "C",
}
CODE_TO_MODE = {v: k for k, v in MODE_TO_CODE.items()}


class CatHandler:
    """
    CAT handler for Yaesu FT-991A.
    Serial: /dev/ttyUSB0, 38400 8N1, no flow control.
    All public methods are thread-safe and return None on error.
    """

    def __init__(self, port="/dev/ttyUSB0", baud=38400):
        self._port = port
        self._baud = baud
        self._ser: serial.Serial | None = None
        self._lock = threading.Lock()
        self.connected = False

    # ── Connection ────────────────────────────────────────────────────

    def connect(self) -> bool:
        with self._lock:
            try:
                self._ser = serial.Serial(
                    port=self._port,
                    baudrate=self._baud,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.5,
                    rtscts=False,
                    dsrdtr=False,
                )
                # Turn off Auto-Information to avoid unsolicited data
                self._raw_send("AI0;")
                self.connected = True
                log.info("FT-991A connected on %s", self._port)
                return True
            except Exception as e:
                log.error("FT-991A connect failed: %s", e)
                self._ser = None
                self.connected = False
                return False

    def disconnect(self):
        # Zuerst connected=False OHNE Lock — stoppt laufende Queries
        self.connected = False
        # Dann Serial schließen (Lock nur kurz)
        try:
            if self._ser and self._ser.is_open:
                self._ser.close()
        except Exception:
            pass
        self._ser = None
        log.info("FT-991A disconnected")

    # ── Low-level ─────────────────────────────────────────────────────

    def _raw_send(self, cmd: str):
        """Send command without lock (caller must hold lock)."""
        self._ser.reset_input_buffer()
        self._ser.write(cmd.encode())

    def _query(self, cmd: str) -> str | None:
        """Send command and return response string (without trailing ;)."""
        with self._lock:
            if not self._ser or not self._ser.is_open:
                return None
            try:
                self._raw_send(cmd)
                response = self._ser.read_until(b";").decode(errors="ignore").strip()
                return response.rstrip(";")
            except Exception as e:
                log.error("CAT query '%s' failed: %s", cmd, e)
                return None

    def _send(self, cmd: str):
        """Send command, no response expected."""
        with self._lock:
            if not self._ser or not self._ser.is_open:
                return
            try:
                self._raw_send(cmd)
            except Exception as e:
                log.error("CAT send '%s' failed: %s", cmd, e)

    # ── Frequency ─────────────────────────────────────────────────────

    def get_frequency(self) -> int | None:
        """Return VFO-A frequency in Hz, or None on error."""
        resp = self._query("FA;")
        if resp and resp.startswith("FA") and len(resp) == 11:
            try:
                return int(resp[2:])
            except ValueError:
                pass
        return None

    def set_frequency(self, hz: int):
        """Set VFO-A frequency. Valid range: 30 kHz – 470 MHz."""
        hz = max(30_000, min(470_000_000, int(hz)))
        self._send(f"FA{hz:09d};")

    def step_frequency(self, step_hz: int):
        """Step frequency up (positive) or down (negative)."""
        freq = self.get_frequency()
        if freq is not None:
            self.set_frequency(freq + step_hz)

    # ── Mode ──────────────────────────────────────────────────────────

    def get_mode(self) -> str | None:
        """Return mode string (e.g. 'USB'), or None on error."""
        resp = self._query("MD0;")
        if resp and resp.startswith("MD0") and len(resp) == 4:
            return CODE_TO_MODE.get(resp[3], f"MODE_{resp[3]}")
        return None

    def set_mode(self, mode: str):
        """Set mode by name (e.g. 'USB', 'LSB', 'FM')."""
        code = MODE_TO_CODE.get(mode.upper())
        if code:
            self._send(f"MD0{code};")
        else:
            log.warning("Unknown mode: %s", mode)

    # ── S-Meter ───────────────────────────────────────────────────────

    def get_smeter(self) -> int | None:
        """Return raw S-meter value 0–255, or None on error."""
        resp = self._query("SM0;")
        if resp and resp.startswith("SM0") and len(resp) == 6:
            try:
                return int(resp[3:])
            except ValueError:
                pass
        return None

    def get_smeter_s_units(self) -> float | None:
        """Return S-meter value as S-units (0–9 + dB over S9)."""
        raw = self.get_smeter()
        if raw is None:
            return None
        # FT-991A: 0=S0, 114=S9, 241=S9+60dB (approx linear)
        if raw <= 114:
            return round(raw / 114 * 9, 1)
        else:
            return round(9 + (raw - 114) / (241 - 114) * 60, 1)

    # ── PTT ───────────────────────────────────────────────────────────

    def ptt_on(self):
        """Activate TX via CAT."""
        self._send("TX0;")

    def ptt_off(self):
        """Return to RX via CAT."""
        self._send("RX;")

    # ── RF Power ──────────────────────────────────────────────────────

    def get_power(self) -> int | None:
        """Return RF power 0–100."""
        resp = self._query("PC;")
        if resp and resp.startswith("PC") and len(resp) == 5:
            try:
                return int(resp[2:])
            except ValueError:
                pass
        return None

    def set_power(self, pct: int):
        """Set RF power 5–100%."""
        pct = max(5, min(100, int(pct)))
        self._send(f"PC{pct:03d};")

    # ── Preamp / ATT ──────────────────────────────────────────────────

    def set_preamp(self, mode: str):
        """mode: 'IPO', 'AMP1', 'AMP2'"""
        codes = {"IPO": "0", "AMP1": "1", "AMP2": "2"}
        code = codes.get(mode.upper(), "0")
        self._send(f"PA0{code};")

    def get_preamp(self) -> str | None:
        resp = self._query("PA0;")
        if resp and resp.startswith("PA0") and len(resp) == 4:
            codes = {"0": "IPO", "1": "AMP1", "2": "AMP2"}
            return codes.get(resp[3])
        return None

    def set_att(self, on: bool):
        self._send("RA01;" if on else "RA00;")

    def get_att(self) -> bool | None:
        resp = self._query("RA0;")
        if resp and resp.startswith("RA0") and len(resp) == 5:
            return resp[3:5] == "01"
        return None

    # ── DSP Functions ─────────────────────────────────────────────────

    def set_nb(self, on: bool):
        """Noise Blanker."""
        self._send("NB01;" if on else "NB00;")

    def set_dnr(self, on: bool):
        """Digital Noise Reduction."""
        self._send("NR01;" if on else "NR00;")

    def set_dnr_level(self, level: int):
        """DNR level 1–15."""
        level = max(1, min(15, int(level)))
        self._send(f"RL0{level:02d};")

    def get_dnr_level(self) -> int | None:
        """Read DNR level 1–15."""
        resp = self._query("RL0;")
        if resp and resp.startswith("RL0"):
            try:
                return int(resp[3:])
            except ValueError:
                return None
        return None

    def set_dnf(self, on: bool):
        """Digital Notch Filter."""
        self._send("BC01;" if on else "BC00;")

    # ── Info ──────────────────────────────────────────────────────────

    def get_info(self) -> dict:
        """Return dict with freq, mode, smeter. Useful for UI polling."""
        return {
            "frequency": self.get_frequency(),
            "mode":      self.get_mode(),
            "smeter":    self.get_smeter_s_units(),
            "preamp":    self.get_preamp(),
            "att":       self.get_att(),
        }
